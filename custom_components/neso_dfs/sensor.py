"""Sensors describing the configured zone and the next DFS event."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DfsConfigEntry
from .const import ATTR_ZONE, CONF_POSTCODE
from .entity import DfsEntity, event_attributes


async def async_setup_entry(
    hass: HomeAssistant, entry: DfsConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            DfsZoneSensor(coordinator, entry.data.get(CONF_POSTCODE)),
            DfsNextEventStartSensor(coordinator),
            DfsNextEventEndSensor(coordinator),
            DfsNextEventRequirementSensor(coordinator),
            DfsUpcomingEventCountSensor(coordinator),
        ]
    )


class DfsZoneSensor(DfsEntity, SensorEntity):
    """The DFS zone this Home Assistant instance sits in."""

    _attr_translation_key = "zone"
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator, postcode: str | None) -> None:
        super().__init__(coordinator, "zone")
        self._postcode = postcode

    @property
    def native_value(self) -> int:
        return self.zone

    @property
    def extra_state_attributes(self) -> dict:
        return {"zone_code": f"Z{self.zone}", CONF_POSTCODE: self._postcode}


class DfsNextEventStartSensor(DfsEntity, SensorEntity):
    """When the next DFS event in this zone starts."""

    _attr_translation_key = "next_event_start"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "next_event_start")

    @property
    def native_value(self) -> datetime | None:
        event = self.coordinator.next_event
        return event.start if event else None

    @property
    def extra_state_attributes(self) -> dict:
        attributes = {ATTR_ZONE: self.zone}
        attributes.update(event_attributes(self.coordinator.next_event, self.zone))
        return attributes


class DfsNextEventEndSensor(DfsEntity, SensorEntity):
    """When the next DFS event in this zone ends."""

    _attr_translation_key = "next_event_end"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "next_event_end")

    @property
    def native_value(self) -> datetime | None:
        event = self.coordinator.next_event
        return event.end if event else None


class DfsNextEventRequirementSensor(DfsEntity, SensorEntity):
    """Peak MW requirement published for the next event."""

    _attr_translation_key = "next_event_requirement"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.MEGA_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "next_event_requirement")

    @property
    def native_value(self) -> float | None:
        event = self.coordinator.next_event
        return event.peak_requirement_mw if event else None

    @property
    def extra_state_attributes(self) -> dict:
        event = self.coordinator.next_event
        return {ATTR_ZONE: self.zone, "zone_cap_mw": event.zonal_caps.get(self.zone) if event else None}


class DfsUpcomingEventCountSensor(DfsEntity, SensorEntity):
    """How many DFS events covering this zone are still to come."""

    _attr_translation_key = "upcoming_events"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "upcoming_events")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_ZONE: self.zone,
            "events": [
                {
                    "event_id": event.event_id,
                    "date": event.delivery_date.isoformat(),
                    "start_local": event.start_local,
                    "end_local": event.end_local,
                    "type": event.event_type,
                    "service_type": event.service_type,
                    "requirement_mw": event.peak_requirement_mw,
                    "zone_cap_mw": event.zonal_caps.get(self.zone),
                }
                for event in self.coordinator.data or []
            ],
        }
