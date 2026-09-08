"""Polls NESO for DFS events and bid results relevant to the configured zone."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    STATUS_ACCEPTED,
    STATUS_NO_BID,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from .vendor_lib import DfsEvent, NesoError, fetch_events
from .vendor_lib.bids import (
    BidWindow,
    ParticipantHistory,
    current_or_next_window,
    fetch_bid_windows,
    fetch_participant_history,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class DfsData:
    """Everything the entities need for one zone."""

    events: list[DfsEvent] = field(default_factory=list)
    bid_windows: list[BidWindow] = field(default_factory=list)
    participant_history: ParticipantHistory | None = None


class DfsCoordinator(DataUpdateCoordinator[DfsData]):
    """Keeps DFS events and bid results for one zone up to date."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        zone: int,
        live_only: bool,
        participant: str | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} Z{zone}",
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.zone = zone
        self.live_only = live_only
        self.participant = participant or None

    async def _async_update_data(self) -> DfsData:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except NesoError as err:
            raise UpdateFailed(f"Could not fetch DFS data: {err}") from err

    def _fetch(self) -> DfsData:
        events = fetch_events(zone=self.zone, include_test=not self.live_only, upcoming_only=True)
        history = fetch_participant_history(self.zone, self.participant) if self.participant else None
        return DfsData(
            events=events,
            bid_windows=fetch_bid_windows(self.zone),
            participant_history=history,
        )

    @property
    def events(self) -> list[DfsEvent]:
        return self.data.events if self.data else []

    @property
    def active_event(self) -> DfsEvent | None:
        """The event currently being delivered, if any."""
        now = datetime.now(timezone.utc)
        return next((event for event in self.events if event.start <= now < event.end), None)

    @property
    def next_event(self) -> DfsEvent | None:
        """The soonest event that has not finished yet."""
        now = datetime.now(timezone.utc)
        upcoming = [event for event in self.events if event.end > now]
        return min(upcoming, key=lambda event: event.start) if upcoming else None

    @property
    def bid_window(self) -> BidWindow | None:
        """Bids for the window being delivered now, else the next one published."""
        return current_or_next_window(self.data.bid_windows) if self.data else None

    @property
    def tracked_event(self) -> DfsEvent | None:
        """The event the participant entities describe: the live one, else the next."""
        return self.active_event or self.next_event

    @property
    def tracked_event_windows(self) -> list[BidWindow]:
        """Published bid results for the tracked event, empty if the auction has not settled."""
        event = self.tracked_event
        if event is None or not self.data:
            return []
        return [window for window in self.data.bid_windows if window.event_id == event.event_id]

    @property
    def results_published(self) -> bool:
        return bool(self.tracked_event_windows)

    @property
    def participant_status(self) -> str | None:
        """Confirmed outcome for the tracked participant, or PENDING while the auction is unsettled.

        Kept separate from the historical accept rate: this is fact, that is a prior.
        """
        if not self.participant or self.tracked_event is None:
            return None
        windows = self.tracked_event_windows
        if not windows:
            return STATUS_PENDING
        if any(window.participant_accepted(self.participant) for window in windows):
            return STATUS_ACCEPTED
        if any(window.participant_bids(self.participant) for window in windows):
            return STATUS_REJECTED
        return STATUS_NO_BID

    @property
    def participant_accepted_mw(self) -> float | None:
        """Confirmed accepted volume for the tracked participant, peak across the event's windows."""
        if not self.participant or not self.results_published:
            return None
        volumes = [window.participant_accepted_mw(self.participant) for window in self.tracked_event_windows]
        return max(volumes) if volumes else 0.0
