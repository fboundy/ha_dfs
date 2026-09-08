"""Sensors describing the configured zone and the next DFS event."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DfsConfigEntry
from .const import ATTR_ZONE, CONF_POSTCODE, PARTICIPANT_STATUSES
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
            DfsAcceptedVolumeSensor(coordinator),
            DfsClearingPriceSensor(coordinator),
        ]
    )

    if coordinator.participant:
        async_add_entities(
            [
                DfsParticipantSensor(coordinator),
                DfsParticipantStatusSensor(coordinator),
                DfsParticipantAcceptedVolumeSensor(coordinator),
                DfsParticipantAcceptRateSensor(coordinator),
            ]
        )


def _bid_rows(bids) -> list[dict]:
    """One row per bid: NESO publishes a single bid per participant per window."""
    return [
        {
            "participant": bid.participant,
            "unit_id": bid.unit_id,
            "mw": bid.mw,
            "price": bid.price,
        }
        for bid in sorted(bids, key=lambda b: (b.price is None, b.price))
    ]


def _bid_window_attributes(window, zone: int) -> dict:
    if window is None:
        return {ATTR_ZONE: zone}
    return {
        ATTR_ZONE: zone,
        "event_id": window.event_id,
        "delivery_date": window.delivery_date.isoformat(),
        "window_start": window.start,
        "window_end": window.end,
        "window_start_local": window.start_local,
        "window_end_local": window.end_local,
        "accepted_mw": window.accepted_mw,
        "rejected_mw": window.rejected_mw,
        "clearing_price": window.clearing_price,
        "lowest_accepted_price": window.lowest_accepted_price,
        "accepted_by_participant": window.accepted_by_participant,
    }


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


class DfsAcceptedVolumeSensor(DfsEntity, SensorEntity):
    """Flexibility accepted in this zone for the current or next delivery window."""

    _attr_translation_key = "accepted_volume"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.MEGA_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "accepted_volume")

    @property
    def native_value(self) -> float | None:
        window = self.coordinator.bid_window
        return window.accepted_mw if window else None

    @property
    def extra_state_attributes(self) -> dict:
        window = self.coordinator.bid_window
        attributes = _bid_window_attributes(window, self.zone)
        if window is not None:
            attributes["accepted_bids"] = _bid_rows(window.accepted_bids)
            attributes["rejected_bids"] = _bid_rows(window.rejected_bids)
        return attributes


class DfsClearingPriceSensor(DfsEntity, SensorEntity):
    """Highest accepted bid price in this zone - what the marginal bid was paid."""

    _attr_translation_key = "clearing_price"
    _attr_native_unit_of_measurement = "GBP/MWh"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "clearing_price")

    @property
    def native_value(self) -> float | None:
        window = self.coordinator.bid_window
        return window.clearing_price if window else None

    @property
    def extra_state_attributes(self) -> dict:
        return _bid_window_attributes(self.coordinator.bid_window, self.zone)


class DfsParticipantSensor(DfsEntity, SensorEntity):
    """Names the registered DFS participant the other entities here report on."""

    _attr_translation_key = "participant"
    _attr_icon = "mdi:account-hard-hat"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "participant")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.participant

    @property
    def extra_state_attributes(self) -> dict:
        return {ATTR_ZONE: self.zone}


class DfsParticipantStatusSensor(DfsEntity, SensorEntity):
    """Confirmed auction outcome for the tracked participant on the current or next event.

    ``pending`` means the auction has not settled yet - use the accept rate sensor for
    the historical likelihood until this resolves.
    """

    _attr_translation_key = "participant_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PARTICIPANT_STATUSES

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "participant_status")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.participant_status

    @property
    def extra_state_attributes(self) -> dict:
        event = self.coordinator.tracked_event
        return {
            ATTR_ZONE: self.zone,
            "participant": self.coordinator.participant,
            "results_published": self.coordinator.results_published,
            "event_id": event.event_id if event else None,
            "delivery_date": event.delivery_date.isoformat() if event else None,
            "event_window_local": f"{event.start_local}-{event.end_local}" if event else None,
        }


class DfsParticipantAcceptedVolumeSensor(DfsEntity, SensorEntity):
    """Volume the tracked participant has confirmed accepted for the current or next event."""

    _attr_translation_key = "participant_accepted_volume"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.MEGA_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "participant_accepted_volume")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.participant_accepted_mw

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_ZONE: self.zone,
            "participant": self.coordinator.participant,
            "results_published": self.coordinator.results_published,
        }


class DfsParticipantAcceptRateSensor(DfsEntity, SensorEntity):
    """How often the tracked participant has been accepted in this zone historically.

    This is the prior for bids that have not settled; it says nothing about a
    result that is already confirmed.
    """

    _attr_translation_key = "participant_accept_rate"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-line"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "participant_accept_rate")

    @property
    def native_value(self) -> float | None:
        history = self.coordinator.data.participant_history if self.coordinator.data else None
        return history.accept_rate if history else None

    @property
    def extra_state_attributes(self) -> dict:
        history = self.coordinator.data.participant_history if self.coordinator.data else None
        if history is None:
            return {ATTR_ZONE: self.zone, "participant": self.coordinator.participant}
        return {
            ATTR_ZONE: self.zone,
            "participant": history.participant,
            "total_bids": history.total_bids,
            "accepted_bids": history.accepted_bids,
            "accepted_mw": history.accepted_mw,
            "average_accepted_price": history.average_accepted_price,
            "history_since": history.since.isoformat(),
        }


class DfsUpcomingEventCountSensor(DfsEntity, SensorEntity):
    """How many DFS events covering this zone are still to come."""

    _attr_translation_key = "upcoming_events"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "upcoming_events")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.events)

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
                for event in self.coordinator.events
            ],
        }
