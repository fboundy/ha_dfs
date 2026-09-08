from datetime import date, datetime, timezone

import pytest

from neso_dfs.api import NesoError
from neso_dfs.bids import ParticipantHistory, _sql_literal, current_or_next_window, group_bids


def row(**overrides):
    base = {
        "Event ID": "115",
        "Event Type": "Downwards",
        "Event Tag": "Energy",
        "Delivery Date": "2026-09-08",
        "From_Local": "17:00",
        "To_Local": "17:30",
        "From_UTC": "16:00",
        "To_UTC": "16:30",
        "Registered DFS Participant": "AXLE ENERGY LIMITED",
        "DFS Unit ID": "AXLE-01-Z6",
        "Zone": "6",
        "DFS Procured MW": "3.5",
        "Service Requirement Type": "Live",
        "Utilisation Price GBP per MWh": "175",
        "Status": "Accepted",
    }
    base.update(overrides)
    return base


def test_single_window_aggregates():
    windows = group_bids(
        [
            row(),
            row(**{"Registered DFS Participant": "INFINIS LIMITED", "DFS Procured MW": "9.7",
                   "Utilisation Price GBP per MWh": "203"}),
            row(**{"Registered DFS Participant": "OCTOPUS ENERGY LIMITED", "DFS Procured MW": "2.0",
                   "Utilisation Price GBP per MWh": "2000", "Status": "Rejected"}),
        ]
    )
    assert len(windows) == 1
    window = windows[0]
    assert window.zone == 6
    assert window.delivery_date == date(2026, 9, 8)
    assert window.accepted_mw == 13.2
    assert window.rejected_mw == 2.0
    assert window.clearing_price == 203.0
    assert window.lowest_accepted_price == 175.0


def test_accepted_and_rejected_partition_the_window():
    window = group_bids(
        [
            row(**{"Utilisation Price GBP per MWh": "175"}),
            row(**{"Registered DFS Participant": "INFINIS LIMITED", "DFS Unit ID": "INFI-06-Z6",
                   "Utilisation Price GBP per MWh": "203"}),
            row(**{"Registered DFS Participant": "OCTOPUS ENERGY LIMITED", "DFS Unit ID": "OCTO-06-Z6",
                   "Utilisation Price GBP per MWh": "319.3", "Status": "Rejected"}),
        ]
    )[0]
    assert len(window.accepted_bids) == 2
    assert len(window.rejected_bids) == 1
    assert len(window.accepted_bids) + len(window.rejected_bids) == len(window.bids)
    assert window.rejected_bids[0].participant == "OCTOPUS ENERGY LIMITED"
    # The marginal accepted bid sets the clearing price; rejections sit above it.
    assert window.clearing_price == 203.0
    assert window.rejected_bids[0].price > window.clearing_price


def test_accepted_by_participant_is_sorted_by_volume():
    windows = group_bids(
        [
            row(**{"DFS Procured MW": "1.0"}),
            row(**{"Registered DFS Participant": "INFINIS LIMITED", "DFS Procured MW": "9.7"}),
        ]
    )
    assert list(windows[0].accepted_by_participant) == ["INFINIS LIMITED", "AXLE ENERGY LIMITED"]


def test_rejected_bids_excluded_from_accepted_totals():
    windows = group_bids([row(**{"Status": "Rejected"})])
    window = windows[0]
    assert window.accepted_mw == 0
    assert window.clearing_price is None
    assert not window.participant_accepted("AXLE")


@pytest.mark.parametrize("needle,expected", [("AXLE", True), ("axle energy", True), ("OCTOPUS", False)])
def test_participant_accepted_matches_case_insensitively(needle, expected):
    window = group_bids([row()])[0]
    assert window.participant_accepted(needle) is expected


def test_windows_split_by_event_and_time():
    windows = group_bids(
        [
            row(),
            row(From_Local="17:30", To_Local="18:00", From_UTC="16:30", To_UTC="17:00"),
            row(**{"Event ID": "116"}),
        ]
    )
    assert len(windows) == 3


def test_participant_volume_and_price():
    window = group_bids(
        [
            row(**{"DFS Procured MW": "2.0", "Utilisation Price GBP per MWh": "180"}),
            row(**{"DFS Unit ID": "AXLE-02-Z6", "DFS Procured MW": "1.5",
                   "Utilisation Price GBP per MWh": "190"}),
            row(**{"Registered DFS Participant": "INFINIS LIMITED", "DFS Procured MW": "9.0"}),
        ]
    )[0]
    assert window.participant_accepted_mw("AXLE") == 3.5
    assert window.participant_price("AXLE") == 190.0
    assert window.participant_accepted_mw("OCTOPUS") == 0


@pytest.mark.parametrize(
    "value,expected",
    [
        ("AXLE ENERGY LIMITED", "'AXLE ENERGY LIMITED'"),
        ("O'Brien Power", "'O''Brien Power'"),
        ("6", "'6'"),
    ],
)
def test_sql_literal_escapes_quotes(value, expected):
    assert _sql_literal(value) == expected


def test_sql_literal_rejects_control_characters():
    with pytest.raises(NesoError):
        _sql_literal("bad\nvalue")


@pytest.mark.parametrize(
    "total,accepted,expected",
    [(36, 12, 33.3), (0, 0, None), (4, 4, 100.0)],
)
def test_accept_rate(total, accepted, expected):
    history = ParticipantHistory(
        participant="AXLE ENERGY LIMITED",
        zone=6,
        total_bids=total,
        accepted_bids=accepted,
        accepted_mw=30.2,
        average_accepted_price=257.52,
        since=date(2025, 1, 1),
    )
    assert history.accept_rate == expected


def test_current_or_next_window_prefers_the_live_one():
    windows = group_bids(
        [
            row(),
            row(From_Local="17:30", To_Local="18:00", From_UTC="16:30", To_UTC="17:00"),
        ]
    )
    during = datetime(2026, 9, 8, 16, 15, tzinfo=timezone.utc)
    assert current_or_next_window(windows, during).start_local == "17:00"

    before = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    assert current_or_next_window(windows, before).start_local == "17:00"

    after = datetime(2026, 9, 8, 23, 0, tzinfo=timezone.utc)
    assert current_or_next_window(windows, after) is None
