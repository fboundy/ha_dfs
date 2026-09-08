"""Upcoming DFS events from NESO's published service requirements."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from .api import NesoError, datastore_sql

SERVICE_REQUIREMENT_RESOURCE = "3635fd80-49d7-4d02-964d-cc8c08d50302"
SERVICE_REQUIREMENT_ARCHIVE_RESOURCE = "f5605e2b-b677-424c-8df7-d0ce4ee03cef"

_ZONE_CAP_PATTERN = re.compile(r"Z(\d+)\s*:\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class ServiceWindow:
    """One half-hour DFS delivery window."""

    event_id: str
    delivery_date: date
    start: datetime
    end: datetime
    start_local: str
    end_local: str
    requirement_mw: float | None
    event_type: str
    event_tag: str
    service_type: str
    dispatch_type: str
    guaranteed_price: float | None
    submission_time: str
    participants: tuple[str, ...]
    zonal_caps: dict[int, float]

    @property
    def is_test(self) -> bool:
        return self.service_type.strip().lower() == "test"

    def cap_for_zone(self, zone: int) -> float | None:
        """MW cap for a zone, or None when the event publishes no zonal split."""
        if not self.zonal_caps:
            return None
        return self.zonal_caps.get(zone, 0.0)

    def covers_zone(self, zone: int) -> bool:
        cap = self.cap_for_zone(zone)
        return True if cap is None else cap > 0


@dataclass
class DfsEvent:
    """Contiguous service windows published under one event ID."""

    event_id: str
    delivery_date: date
    event_type: str
    service_type: str
    windows: list[ServiceWindow] = field(default_factory=list)

    @property
    def start(self) -> datetime:
        return min(window.start for window in self.windows)

    @property
    def end(self) -> datetime:
        return max(window.end for window in self.windows)

    @property
    def start_local(self) -> str:
        return min(self.windows, key=lambda window: window.start).start_local

    @property
    def end_local(self) -> str:
        return max(self.windows, key=lambda window: window.end).end_local

    @property
    def is_test(self) -> bool:
        return self.windows[0].is_test

    @property
    def event_tag(self) -> str:
        return self.windows[0].event_tag

    @property
    def submission_time(self) -> str:
        return self.windows[0].submission_time

    @property
    def dispatch_type(self) -> str:
        return self.windows[0].dispatch_type

    @property
    def participants(self) -> tuple[str, ...]:
        return self.windows[0].participants

    @property
    def peak_requirement_mw(self) -> float | None:
        values = [w.requirement_mw for w in self.windows if w.requirement_mw is not None]
        return max(values) if values else None

    @property
    def zonal_caps(self) -> dict[int, float]:
        merged: dict[int, float] = {}
        for window in self.windows:
            for zone, cap in window.zonal_caps.items():
                merged[zone] = max(merged.get(zone, 0.0), cap)
        return merged

    @property
    def zones_in_scope(self) -> list[int]:
        return sorted(zone for zone, cap in self.zonal_caps.items() if cap > 0)

    def covers_zone(self, zone: int) -> bool:
        return any(window.covers_zone(zone) for window in self.windows)

    def windows_for_zone(self, zone: int) -> list[ServiceWindow]:
        return [window for window in self.windows if window.covers_zone(zone)]

    def is_upcoming(self, now: datetime | None = None) -> bool:
        return self.end > (now or datetime.now(timezone.utc))


def parse_zonal_caps(value: str | None) -> dict[int, float]:
    """Parse NESO's ``Z1:0,Z2:500`` zonal cap string."""
    if not value:
        return {}
    return {int(zone): float(cap) for zone, cap in _ZONE_CAP_PATTERN.findall(value)}


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    text = str(value).strip()
    return datetime.fromisoformat(text.replace("Z", "+00:00").split("T")[0].split(" ")[0]).date()


def _parse_time(value: Any) -> time:
    hour, minute = str(value).strip().split(":")[:2]
    return time(int(hour), int(minute))


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _window_bounds(delivery_date: date, start_utc: time, end_utc: time, start_local: time) -> tuple[datetime, datetime]:
    """Pair the UTC clock times with the delivery date, allowing for midnight wrap."""
    start = datetime.combine(delivery_date, start_utc, tzinfo=timezone.utc)
    # The delivery date is local; under BST an early-hours local window sits on the
    # previous UTC date (00:30 BST == 23:30 UTC).
    if start_utc.hour - start_local.hour > 12:
        start -= timedelta(days=1)
    end = datetime.combine(start.date(), end_utc, tzinfo=timezone.utc)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def parse_service_window(record: dict[str, Any]) -> ServiceWindow:
    delivery_date = _parse_date(record["Delivery Date"])
    start_local = _parse_time(record["From_Local"])
    start, end = _window_bounds(
        delivery_date,
        _parse_time(record["From_UTC"]),
        _parse_time(record["To_UTC"]),
        start_local,
    )
    participants = tuple(
        name.strip() for name in str(record.get("Participant Bids Eligible") or "").split(",") if name.strip()
    )
    return ServiceWindow(
        event_id=str(record.get("Event ID") or "").strip(),
        delivery_date=delivery_date,
        start=start,
        end=end,
        start_local=str(record["From_Local"]).strip(),
        end_local=str(record["To_Local"]).strip(),
        requirement_mw=_parse_float(record.get("Service Requirement MW")),
        event_type=str(record.get("Event Type") or "").strip(),
        event_tag=str(record.get("Event Tag") or "").strip(),
        service_type=str(record.get("Service Requirement Type") or "").strip(),
        dispatch_type=str(record.get("Dispatch Type") or "").strip(),
        guaranteed_price=_parse_float(record.get("Guaranteed Acceptance Price GBP per MWh")),
        submission_time=str(record.get("DFS Submission Time_Local") or "").strip(),
        participants=participants,
        zonal_caps=parse_zonal_caps(record.get("Zonal Cap")),
    )


def group_windows(windows: Iterable[ServiceWindow]) -> list[DfsEvent]:
    events: dict[tuple[str, date, str], DfsEvent] = {}
    for window in windows:
        key = (window.event_id, window.delivery_date, window.event_type)
        event = events.get(key)
        if event is None:
            event = DfsEvent(
                event_id=window.event_id,
                delivery_date=window.delivery_date,
                event_type=window.event_type,
                service_type=window.service_type,
            )
            events[key] = event
        event.windows.append(window)
    ordered = sorted(events.values(), key=lambda event: (event.start, event.event_id))
    for event in ordered:
        event.windows.sort(key=lambda window: window.start)
    return ordered


def fetch_service_windows(since: date | None = None, archive: bool = False) -> list[ServiceWindow]:
    """Fetch raw service windows from the NESO data portal."""
    resource = SERVICE_REQUIREMENT_ARCHIVE_RESOURCE if archive else SERVICE_REQUIREMENT_RESOURCE
    sql = f'SELECT * FROM "{resource}"'
    if since is not None:
        sql += f" WHERE \"Delivery Date\" >= '{since.isoformat()}'"
    records = datastore_sql(sql)
    windows = []
    for record in records:
        try:
            windows.append(parse_service_window(record))
        except (KeyError, ValueError) as exc:
            raise NesoError(f"unexpected record format from NESO: {exc}") from exc
    return windows


def fetch_events(
    zone: int | None = None,
    include_test: bool = True,
    upcoming_only: bool = True,
    since: date | None = None,
    archive: bool = False,
    now: datetime | None = None,
) -> list[DfsEvent]:
    """Fetch DFS events, optionally narrowed to one zone."""
    now = now or datetime.now(timezone.utc)
    if since is None and upcoming_only:
        since = (now - timedelta(days=1)).date()

    events = group_windows(fetch_service_windows(since=since, archive=archive))
    if upcoming_only:
        events = [event for event in events if event.is_upcoming(now)]
    if not include_test:
        events = [event for event in events if not event.is_test]
    if zone is not None:
        events = [event for event in events if event.covers_zone(zone)]
    return events
