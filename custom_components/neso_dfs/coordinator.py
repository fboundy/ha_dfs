"""Polls NESO for DFS events relevant to the configured zone."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .vendor_lib import DfsEvent, NesoError, fetch_events

_LOGGER = logging.getLogger(__name__)


class DfsCoordinator(DataUpdateCoordinator[list[DfsEvent]]):
    """Keeps the list of upcoming DFS events for one zone up to date."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone: int, live_only: bool) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} Z{zone}",
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.zone = zone
        self.live_only = live_only

    async def _async_update_data(self) -> list[DfsEvent]:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except NesoError as err:
            raise UpdateFailed(f"Could not fetch DFS events: {err}") from err

    def _fetch(self) -> list[DfsEvent]:
        return fetch_events(zone=self.zone, include_test=not self.live_only, upcoming_only=True)

    @property
    def active_event(self) -> DfsEvent | None:
        """The event currently being delivered, if any."""
        now = datetime.now(timezone.utc)
        for event in self.data or []:
            if event.start <= now < event.end:
                return event
        return None

    @property
    def next_event(self) -> DfsEvent | None:
        """The soonest event that has not finished yet."""
        now = datetime.now(timezone.utc)
        upcoming = [event for event in (self.data or []) if event.end > now]
        return min(upcoming, key=lambda event: event.start) if upcoming else None
