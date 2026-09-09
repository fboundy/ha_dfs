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
    participant_history: dict[str, ParticipantHistory] = field(default_factory=dict)


class DfsCoordinator(DataUpdateCoordinator[DfsData]):
    """Keeps DFS events and bid results for one zone up to date."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        zone: int,
        live_only: bool,
        participants: list[str] | None = None,
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
        self.participants = list(participants or [])

    async def _async_update_data(self) -> DfsData:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except NesoError as err:
            raise UpdateFailed(f"Could not fetch DFS data: {err}") from err

    def _fetch(self) -> DfsData:
        events = fetch_events(zone=self.zone, include_test=not self.live_only, upcoming_only=True)
        return DfsData(
            events=events,
            bid_windows=fetch_bid_windows(self.zone),
            participant_history={
                name: fetch_participant_history(self.zone, name) for name in self.participants
            },
        )

    def history_for(self, participant: str) -> ParticipantHistory | None:
        return self.data.participant_history.get(participant) if self.data else None

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
    def bid_window_profile(self) -> list[BidWindow]:
        """Every published half-hour window of the event the current bid window belongs to.

        Events run for hours but are auctioned per half-hour slot, and both volume and
        clearing price move between slots, so the whole shape is worth carrying.
        """
        window = self.bid_window
        if window is None or not self.data:
            return []
        return sorted(
            (
                other
                for other in self.data.bid_windows
                if other.event_id == window.event_id and other.delivery_date == window.delivery_date
            ),
            key=lambda other: other.start,
        )

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

    def participant_status(self, participant: str) -> str | None:
        """Confirmed outcome for one participant, or PENDING while the auction is unsettled.

        Kept separate from the historical accept rate: this is fact, that is a prior.
        Scoped to this coordinator's zone, so it never reports another zone's result.
        """
        if self.tracked_event is None:
            return None
        windows = self.tracked_event_windows
        if not windows:
            return STATUS_PENDING
        if any(window.participant_accepted(participant) for window in windows):
            return STATUS_ACCEPTED
        if any(window.participant_bids(participant) for window in windows):
            return STATUS_REJECTED
        return STATUS_NO_BID

    def participant_accepted_mw(self, participant: str) -> float | None:
        """Confirmed accepted volume for one participant, peak across the event's windows."""
        if not self.results_published:
            return None
        volumes = [window.participant_accepted_mw(participant) for window in self.tracked_event_windows]
        return max(volumes) if volumes else 0.0
