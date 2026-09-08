"""Shared entity base and event attribute helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_BIDS_CLOSE,
    ATTR_DELIVERY_DATE,
    ATTR_END,
    ATTR_END_LOCAL,
    ATTR_EVENT_ID,
    ATTR_EVENT_TAG,
    ATTR_EVENT_TYPE,
    ATTR_PARTICIPANTS,
    ATTR_REQUIREMENT_MW,
    ATTR_SERVICE_TYPE,
    ATTR_START,
    ATTR_START_LOCAL,
    ATTR_ZONE_CAP_MW,
    ATTR_ZONES_IN_SCOPE,
    DOMAIN,
)
from .coordinator import DfsCoordinator
from .vendor_lib import DfsEvent


def event_attributes(event: DfsEvent | None, zone: int) -> dict:
    """Flatten an event into state attributes for the dashboard."""
    if event is None:
        return {}
    return {
        ATTR_EVENT_ID: event.event_id,
        ATTR_DELIVERY_DATE: event.delivery_date.isoformat(),
        ATTR_EVENT_TYPE: event.event_type,
        ATTR_EVENT_TAG: event.event_tag,
        ATTR_SERVICE_TYPE: event.service_type,
        ATTR_START: event.start,
        ATTR_END: event.end,
        ATTR_START_LOCAL: event.start_local,
        ATTR_END_LOCAL: event.end_local,
        ATTR_REQUIREMENT_MW: event.peak_requirement_mw,
        ATTR_ZONE_CAP_MW: event.zonal_caps.get(zone),
        ATTR_ZONES_IN_SCOPE: event.zones_in_scope,
        ATTR_BIDS_CLOSE: event.submission_time,
        ATTR_PARTICIPANTS: list(event.participants),
    }


class DfsEntity(CoordinatorEntity[DfsCoordinator]):
    """Base entity tied to the configured DFS zone."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DfsCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_zone{coordinator.zone}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"zone_{coordinator.zone}")},
            name=f"NESO DFS Zone {coordinator.zone}",
            manufacturer="National Energy System Operator",
            model="Demand Flexibility Service",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def zone(self) -> int:
        return self.coordinator.zone
