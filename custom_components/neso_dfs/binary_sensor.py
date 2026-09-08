"""Binary sensors for DFS event state."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DfsConfigEntry
from .const import ATTR_ZONE, STATUS_ACCEPTED
from .entity import DfsEntity, event_attributes


async def async_setup_entry(
    hass: HomeAssistant, entry: DfsConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([DfsActiveBinarySensor(coordinator), DfsEventTodayBinarySensor(coordinator)])

    if coordinator.participant:
        async_add_entities([DfsParticipantAcceptedBinarySensor(coordinator)])


class DfsParticipantAcceptedBinarySensor(DfsEntity, BinarySensorEntity):
    """On only when the tracked bidder is confirmed accepted for the current or next event.

    Unknown while the auction is unsettled, so a pending bid never reads as a rejection.
    """

    _attr_translation_key = "participant_accepted"
    _attr_icon = "mdi:gavel"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "participant_accepted")

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.results_published:
            return None
        return self.coordinator.participant_status == STATUS_ACCEPTED

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_ZONE: self.zone,
            "participant": self.coordinator.participant,
            "status": self.coordinator.participant_status,
            "results_published": self.coordinator.results_published,
            "accepted_mw": self.coordinator.participant_accepted_mw,
        }


class DfsActiveBinarySensor(DfsEntity, BinarySensorEntity):
    """On while a DFS delivery window covering this zone is running."""

    _attr_translation_key = "event_active"
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "event_active")

    @property
    def is_on(self) -> bool:
        return self.coordinator.active_event is not None

    @property
    def extra_state_attributes(self) -> dict:
        event = self.coordinator.active_event
        attributes = {ATTR_ZONE: self.zone}
        attributes.update(event_attributes(event, self.zone))
        if event is not None:
            window = next(
                (w for w in event.windows_for_zone(self.zone) if w.start <= datetime.now(timezone.utc) < w.end),
                None,
            )
            if window is not None:
                attributes["current_window_mw"] = window.requirement_mw
        return attributes


class DfsEventTodayBinarySensor(DfsEntity, BinarySensorEntity):
    """On when a DFS event covering this zone is scheduled for today."""

    _attr_translation_key = "event_today"
    _attr_icon = "mdi:calendar-alert"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "event_today")

    @property
    def is_on(self) -> bool:
        today = dt_util.now().date()
        return any(event.delivery_date == today for event in self.coordinator.events)

    @property
    def extra_state_attributes(self) -> dict:
        today = dt_util.now().date()
        events = [event for event in self.coordinator.events if event.delivery_date == today]
        return {
            ATTR_ZONE: self.zone,
            "event_count": len(events),
            "windows": [
                {"start": event.start_local, "end": event.end_local, "type": event.event_type} for event in events
            ],
        }
