"""DFS events as calendars, at two grains.

An event is a scheduled time range, which a calendar models directly. It also sidesteps the
awkward part of the entity model: events run for a varying number of half-hour slots, so no
fixed set of entities can represent the schedule. A calendar holds as many entries as there are.

Two are published because the useful grain differs by task: the event calendar answers "when am
I being asked to shift load", the slot calendar answers "what is each half hour actually worth".
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
from .vendor_lib.bids import BidWindow


async def async_setup_entry(
    hass: HomeAssistant, entry: DfsConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([DfsEventCalendar(coordinator), DfsSlotCalendar(coordinator)])


class _DfsCalendarBase(DfsEntity, CalendarEntity):
    """Shared current/next selection and range query over generated entries."""

    def _entries(self) -> list[CalendarEvent]:
        raise NotImplementedError

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.utcnow()
        entries = self._entries()
        current = next((e for e in entries if e.start <= now < e.end), None)
        if current:
            return current
        upcoming = [e for e in entries if e.start > now]
        return min(upcoming, key=lambda e: e.start) if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [e for e in self._entries() if e.end > start_date and e.start < end_date]

    def _event_header(self, event: DfsEvent) -> list[str]:
        cap = event.zonal_caps.get(self.zone)
        lines = [f"Event {event.event_id} · {event.service_type} · {event.event_tag}".strip(" ·")]
        if event.peak_requirement_mw is not None:
            lines.append(f"Requirement {event.peak_requirement_mw:g} MW")
        if cap is not None:
            lines.append(f"Zone {self.zone} cap {cap:g} MW")
        if event.submission_time:
            lines.append(f"Bids close {event.submission_time}")
        return lines


class DfsEventCalendar(_DfsCalendarBase):
    """One entry per DFS event, with the auction result broken down in the description."""

    _attr_translation_key = "events"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: DfsCoordinator) -> None:
        super().__init__(coordinator, "calendar")

    def _entries(self) -> list[CalendarEvent]:
        return [self._to_entry(event) for event in self.coordinator.all_events]

    def _to_entry(self, event: DfsEvent) -> CalendarEvent:
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
        lines = self._event_header(event)
        windows = self.coordinator.bid_windows_for_event(event)
        if windows:
            lines.append("")
            lines.append(f"Auction result by slot ({len(windows)} slots):")
            for window in windows:
                price = f"£{window.clearing_price:g}/MWh" if window.clearing_price is not None else "—"
                lines.append(
                    f"  {window.start_local}-{window.end_local}  {window.accepted_mw:g} MW  {price}"
                )
        elif event.start > dt_util.utcnow():
            # Only claim this for events still ahead; for older ones we simply have no
            # bid data loaded, which is not the same as the auction being unsettled.
            lines.append("")
            lines.append("Auction not settled yet.")
        return "\n".join(lines)


class DfsSlotCalendar(_DfsCalendarBase):
    """One entry per half-hour delivery slot, priced once the auction settles."""

    _attr_translation_key = "slots"
    _attr_icon = "mdi:calendar-clock-outline"

    def __init__(self, coordinator: DfsCoordinator) -> None:
        super().__init__(coordinator, "slot_calendar")

    def _entries(self) -> list[CalendarEvent]:
        entries = []
        for event in self.coordinator.all_events:
            settled = {window.start: window for window in self.coordinator.bid_windows_for_event(event)}
            for slot in event.windows:
                entries.append(self._to_entry(event, slot, settled.get(slot.start)))
        return entries

    def _to_entry(self, event: DfsEvent, slot, window: BidWindow | None) -> CalendarEvent:
        if window is not None and window.clearing_price is not None:
            summary = f"{window.accepted_mw:g} MW · £{window.clearing_price:g}/MWh"
        elif slot.requirement_mw is not None:
            summary = f"DFS {event.event_type} · {slot.requirement_mw:g} MW sought"
        else:
            summary = f"DFS {event.event_type}"

        return CalendarEvent(
            summary=summary,
            start=slot.start,
            end=slot.end,
            description=self._describe(event, window),
            uid=f"{DOMAIN}-z{self.zone}-slot-{event.event_id}-{slot.start.isoformat()}",
        )

    def _describe(self, event: DfsEvent, window: BidWindow | None) -> str:
        lines = self._event_header(event)
        if window is None:
            if event.start > dt_util.utcnow():
                lines.append("")
                lines.append("Auction not settled yet.")
            return "\n".join(lines)

        lines.append("")
        lines.append(f"Accepted {window.accepted_mw:g} MW, rejected {window.rejected_mw:g} MW")
        for bid in sorted(window.accepted_bids, key=lambda b: (b.price is None, b.price)):
            lines.append(f"  ✓ £{bid.price:g}/MWh  {bid.mw:g} MW  {bid.participant}")
        for bid in sorted(window.rejected_bids, key=lambda b: (b.price is None, b.price)):
            lines.append(f"  ✗ £{bid.price:g}/MWh  {bid.mw:g} MW  {bid.participant}")
        return "\n".join(lines)
