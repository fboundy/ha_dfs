"""DFS events as a calendar.

An event is a scheduled time range, which a calendar models directly. It also sidesteps the
awkward part of the entity model: events run for a varying number of half-hour slots, so no
fixed set of entities can represent the schedule. A calendar holds as many entries as there are.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DfsConfigEntry
from .const import DOMAIN
from .coordinator import DfsCoordinator
from .entity import DfsEntity
from .vendor_lib import DfsEvent


async def async_setup_entry(
    hass: HomeAssistant, entry: DfsConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([DfsEventCalendar(entry.runtime_data)])


class DfsEventCalendar(DfsEntity, CalendarEntity):
    """Every DFS event that procures in this zone, one entry per event."""

    _attr_translation_key = "events"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: DfsCoordinator) -> None:
        super().__init__(coordinator, "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        """The event running now, else the next one."""
        now = dt_util.utcnow()
        current = next(
            (e for e in self.coordinator.all_events if e.start <= now < e.end),
            None,
        )
        if current:
            return self._to_calendar_event(current)
        upcoming = [e for e in self.coordinator.all_events if e.start > now]
        if not upcoming:
            return None
        return self._to_calendar_event(min(upcoming, key=lambda e: e.start))

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            self._to_calendar_event(event)
            for event in self.coordinator.all_events
            if event.end > start_date and event.start < end_date
        ]

    def _to_calendar_event(self, event: DfsEvent) -> CalendarEvent:
        label = f"DFS {event.event_type}".strip()
        if event.is_test:
            label += " (test)"
        return CalendarEvent(
            summary=f"{label} — Z{self.zone}",
            start=event.start,
            end=event.end,
            description=self._describe(event),
            uid=f"{DOMAIN}-z{self.zone}-{event.delivery_date.isoformat()}-{event.event_id}",
        )

    def _describe(self, event: DfsEvent) -> str:
        cap = event.zonal_caps.get(self.zone)
        lines = [f"Event {event.event_id} · {event.service_type} · {event.event_tag}".strip(" ·")]
        if event.peak_requirement_mw is not None:
            lines.append(f"Requirement {event.peak_requirement_mw:g} MW")
        if cap is not None:
            lines.append(f"Zone {self.zone} cap {cap:g} MW")
        if event.submission_time:
            lines.append(f"Bids close {event.submission_time}")

        windows = self.coordinator.bid_windows_for_event(event)
        if windows:
            lines.append("")
            lines.append(f"Auction result by slot ({len(windows)} slots):")
            for window in windows:
                price = f"£{window.clearing_price:g}/MWh" if window.clearing_price is not None else "—"
                lines.append(
                    f"  {window.start_local}-{window.end_local}  "
                    f"{window.accepted_mw:g} MW  {price}"
                )
        elif event.start > dt_util.utcnow():
            # Only claim this for events still ahead; for older ones we simply have no
            # bid data loaded, which is not the same as the auction being unsettled.
            lines.append("")
            lines.append("Auction not settled yet.")
        return "\n".join(lines)
