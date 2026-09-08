"""Accepted and rejected DFS bids, aggregated per zone and delivery window.

NESO publishes every bid in the DFS Utilisation Report shortly after the auction closes -
typically well before delivery starts - so the accepted volume and clearing price for your
zone are known in advance of the event itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from .api import NesoError, datastore_sql
from .events import _parse_date, _parse_float, _parse_time, _window_bounds

UTILISATION_RESOURCE = "3ebf77d7-05df-466e-a023-dc45a90efeea"

ACCEPTED = "Accepted"


@dataclass
class Bid:
    """One participant's bid for one delivery window."""

    event_id: str
    zone: int
    participant: str
    unit_id: str
    mw: float
    price: float | None
    status: str

    @property
    def accepted(self) -> bool:
        return self.status.strip().lower() == ACCEPTED.lower()


@dataclass
class BidWindow:
    """Every bid submitted for one zone in one delivery window."""

    event_id: str
    zone: int
    delivery_date: date
    start: datetime
    end: datetime
    start_local: str
    end_local: str
    bids: list[Bid] = field(default_factory=list)

    @property
    def accepted_bids(self) -> list[Bid]:
        return [bid for bid in self.bids if bid.accepted]

    @property
    def accepted_mw(self) -> float:
        return round(sum(bid.mw for bid in self.accepted_bids), 3)

    @property
    def rejected_mw(self) -> float:
        return round(sum(bid.mw for bid in self.bids if not bid.accepted), 3)

    @property
    def clearing_price(self) -> float | None:
        """Highest accepted price - what the marginal accepted bid was paid."""
        prices = [bid.price for bid in self.accepted_bids if bid.price is not None]
        return max(prices) if prices else None

    @property
    def lowest_accepted_price(self) -> float | None:
        prices = [bid.price for bid in self.accepted_bids if bid.price is not None]
        return min(prices) if prices else None

    @property
    def accepted_by_participant(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for bid in self.accepted_bids:
            totals[bid.participant] = round(totals.get(bid.participant, 0.0) + bid.mw, 3)
        return dict(sorted(totals.items(), key=lambda item: -item[1]))

    def participant_bids(self, participant: str) -> list[Bid]:
        needle = participant.strip().lower()
        return [bid for bid in self.bids if needle in bid.participant.lower()]

    def participant_accepted(self, participant: str) -> bool:
        needle = participant.strip().lower()
        return any(needle in bid.participant.lower() for bid in self.accepted_bids)

    def participant_accepted_mw(self, participant: str) -> float:
        return round(sum(bid.mw for bid in self.participant_bids(participant) if bid.accepted), 3)

    def participant_price(self, participant: str) -> float | None:
        """The price this participant bid in this window, if they bid at all."""
        prices = [bid.price for bid in self.participant_bids(participant) if bid.price is not None]
        return max(prices) if prices else None

    def is_current(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return self.start <= now < self.end


def _parse_bid_row(record: dict[str, Any]) -> tuple[BidWindow, Bid]:
    delivery_date = _parse_date(record["Delivery Date"])
    start, end = _window_bounds(
        delivery_date,
        _parse_time(record["From_UTC"]),
        _parse_time(record["To_UTC"]),
        _parse_time(record["From_Local"]),
    )
    zone = int(float(record["Zone"]))
    event_id = str(record.get("Event ID") or "").strip()
    window = BidWindow(
        event_id=event_id,
        zone=zone,
        delivery_date=delivery_date,
        start=start,
        end=end,
        start_local=str(record["From_Local"]).strip(),
        end_local=str(record["To_Local"]).strip(),
    )
    bid = Bid(
        event_id=event_id,
        zone=zone,
        participant=str(record.get("Registered DFS Participant") or "").strip(),
        unit_id=str(record.get("DFS Unit ID") or "").strip(),
        mw=_parse_float(record.get("DFS Procured MW")) or 0.0,
        price=_parse_float(record.get("Utilisation Price GBP per MWh")),
        status=str(record.get("Status") or "").strip(),
    )
    return window, bid


def group_bids(records: Iterable[dict[str, Any]]) -> list[BidWindow]:
    windows: dict[tuple[str, int, datetime], BidWindow] = {}
    for record in records:
        window, bid = _parse_bid_row(record)
        key = (window.event_id, window.zone, window.start)
        existing = windows.setdefault(key, window)
        existing.bids.append(bid)
    return sorted(windows.values(), key=lambda window: (window.start, window.event_id))


def fetch_bid_windows(zone: int, since: date | None = None, days_back: int = 1) -> list[BidWindow]:
    """Fetch bid windows for one zone, from ``since`` (default: yesterday) onwards."""
    zone = int(zone)
    if since is None:
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).date()
    sql = (
        f'SELECT * FROM "{UTILISATION_RESOURCE}" '
        f"WHERE \"Zone\" = '{zone}' AND \"Delivery Date\" >= '{since.isoformat()}'"
    )
    return group_bids(datastore_sql(sql))


def _sql_literal(value: str) -> str:
    """Quote a string for a PostgreSQL literal, rejecting anything unprintable."""
    if any(character < " " or character == "\x7f" for character in value):
        raise NesoError("value contains control characters")
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


@dataclass
class ParticipantHistory:
    """How one participant has fared bidding into a zone."""

    participant: str
    zone: int
    total_bids: int
    accepted_bids: int
    accepted_mw: float
    average_accepted_price: float | None
    since: date

    @property
    def accept_rate(self) -> float | None:
        """Percentage of this participant's bids that were accepted."""
        if not self.total_bids:
            return None
        return round(100 * self.accepted_bids / self.total_bids, 1)


def fetch_participants(zone: int) -> list[str]:
    """Every participant that has bid into this zone, sorted alphabetically.

    Sorted in Python rather than SQL so the ordering ignores case - NESO mixes
    "OCTOPUS ENERGY LIMITED" with "Shuffle Energy Limited".
    """
    sql = (
        f'SELECT DISTINCT "Registered DFS Participant" AS participant '
        f'FROM "{UTILISATION_RESOURCE}" WHERE "Zone" = {_sql_literal(str(int(zone)))}'
    )
    records = datastore_sql(sql)
    names = {str(record["participant"]).strip() for record in records if record.get("participant")}
    return sorted(names, key=str.casefold)


def fetch_participant_history(
    zone: int, participant: str, since: date | None = None
) -> ParticipantHistory:
    """Aggregate a participant's bidding record in a zone, computed server-side."""
    zone = int(zone)
    if since is None:
        since = date(date.today().year - 1, 1, 1)
    sql = (
        f'SELECT COUNT(*) AS total, '
        f"SUM(CASE WHEN \"Status\" = '{ACCEPTED}' THEN 1 ELSE 0 END) AS accepted, "
        f"SUM(CASE WHEN \"Status\" = '{ACCEPTED}' THEN \"DFS Procured MW\"::numeric ELSE 0 END) AS accepted_mw, "
        f"AVG(CASE WHEN \"Status\" = '{ACCEPTED}' "
        f'THEN "Utilisation Price GBP per MWh"::numeric END) AS average_price '
        f'FROM "{UTILISATION_RESOURCE}" '
        f'WHERE "Zone" = {_sql_literal(str(zone))} '
        f'AND "Registered DFS Participant" = {_sql_literal(participant)} '
        f'AND "Delivery Date" >= {_sql_literal(since.isoformat())}'
    )
    record = datastore_sql(sql)[0]
    average = _parse_float(record.get("average_price"))
    return ParticipantHistory(
        participant=participant,
        zone=zone,
        total_bids=int(record.get("total") or 0),
        accepted_bids=int(record.get("accepted") or 0),
        accepted_mw=round(float(record.get("accepted_mw") or 0), 3),
        average_accepted_price=round(average, 2) if average is not None else None,
        since=since,
    )


def current_or_next_window(windows: list[BidWindow], now: datetime | None = None) -> BidWindow | None:
    """The window being delivered now, else the soonest one still to come."""
    now = now or datetime.now(timezone.utc)
    for window in windows:
        if window.is_current(now):
            return window
    upcoming = [window for window in windows if window.start > now]
    return min(upcoming, key=lambda window: window.start) if upcoming else None
