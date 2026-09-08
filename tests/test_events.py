from datetime import date, datetime, timezone

import pytest

from neso_dfs.events import group_windows, parse_service_window, parse_zonal_caps


def record(**overrides):
    base = {
        "Event ID": "115",
        "Delivery Date": "2026-09-08",
        "From_Local": "17:00",
        "To_Local": "17:30",
        "From_UTC": "16:00",
        "To_UTC": "16:30",
        "Service Requirement MW": 500,
        "Event Type": "Downwards",
        "Event Tag": "Energy",
        "Service Requirement Type": "Live",
        "Dispatch Type": "All Participants",
        "Guaranteed Acceptance Price GBP per MWh": "0",
        "DFS Submission Time_Local": "08/09/2026 12:00",
        "Participant Bids Eligible": "CUB (UK) LTD,OCTOPUS ENERGY LIMITED",
        "Zonal Cap": "Z1:0,Z2:0,Z3:0,Z4:500,Z5:500,Z6:500",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Z1:100, Z2: 500", {1: 100.0, 2: 500.0}),
        ("Z1:0,Z10:250.5", {1: 0.0, 10: 250.5}),
        ("", {}),
        (None, {}),
    ],
)
def test_parse_zonal_caps(raw, expected):
    assert parse_zonal_caps(raw) == expected


def test_parse_service_window():
    window = parse_service_window(record())
    assert window.delivery_date == date(2026, 9, 8)
    assert window.start == datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc)
    assert window.end == datetime(2026, 9, 8, 16, 30, tzinfo=timezone.utc)
    assert window.requirement_mw == 500
    assert window.participants == ("CUB (UK) LTD", "OCTOPUS ENERGY LIMITED")
    assert not window.is_test


def test_early_hours_bst_window_falls_on_previous_utc_date():
    window = parse_service_window(
        record(From_Local="00:30", To_Local="01:00", From_UTC="23:30", To_UTC="00:00")
    )
    assert window.start == datetime(2026, 9, 7, 23, 30, tzinfo=timezone.utc)
    assert window.end == datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)


def test_window_crossing_midnight_utc():
    window = parse_service_window(
        record(From_Local="23:30", To_Local="00:00", From_UTC="22:30", To_UTC="23:00")
    )
    assert window.end > window.start


def test_zone_scope_follows_cap():
    window = parse_service_window(record())
    assert window.covers_zone(4)
    assert not window.covers_zone(1)
    assert not window.covers_zone(12)  # absent from the cap list


def test_national_event_covers_every_zone():
    window = parse_service_window(record(**{"Zonal Cap": ""}))
    assert window.cap_for_zone(3) is None
    assert window.covers_zone(3)


def test_group_windows_merges_by_event():
    windows = [
        parse_service_window(record()),
        parse_service_window(record(From_Local="17:30", To_Local="18:00", From_UTC="16:30", To_UTC="17:00")),
        parse_service_window(record(**{"Event ID": "116", "Delivery Date": "2026-09-09"})),
    ]
    events = group_windows(windows)
    assert [event.event_id for event in events] == ["115", "116"]
    first = events[0]
    assert len(first.windows) == 2
    assert first.start_local == "17:00"
    assert first.end_local == "18:00"
    assert first.peak_requirement_mw == 500
    assert first.zones_in_scope == [4, 5, 6]


def test_is_upcoming():
    event = group_windows([parse_service_window(record())])[0]
    assert event.is_upcoming(datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc))
    assert not event.is_upcoming(datetime(2026, 9, 8, 17, 0, tzinfo=timezone.utc))
