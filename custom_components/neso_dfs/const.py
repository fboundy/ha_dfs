"""Constants for the NESO DFS integration."""

from datetime import timedelta

DOMAIN = "neso_dfs"

CONF_POSTCODE = "postcode"
CONF_ZONE = "zone"
CONF_LIVE_ONLY = "live_only"
CONF_PARTICIPANT = "participant"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=15)

# How far back to fetch so the calendar can show recent events, without pulling the
# whole season on every poll.
EVENT_HISTORY_DAYS = 14
BID_HISTORY_DAYS = 7

ATTR_EVENT_ID = "event_id"
ATTR_EVENT_TYPE = "event_type"
ATTR_EVENT_TAG = "event_tag"
ATTR_SERVICE_TYPE = "service_type"
ATTR_DELIVERY_DATE = "delivery_date"
ATTR_START = "start"
ATTR_END = "end"
ATTR_START_LOCAL = "start_local"
ATTR_END_LOCAL = "end_local"
ATTR_REQUIREMENT_MW = "requirement_mw"
ATTR_ZONE_CAP_MW = "zone_cap_mw"
ATTR_ZONES_IN_SCOPE = "zones_in_scope"
ATTR_BIDS_CLOSE = "bids_close"
ATTR_PARTICIPANTS = "participants"
ATTR_ZONE = "zone"

STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_NO_BID = "no_bid"
STATUS_PENDING = "pending"
PARTICIPANT_STATUSES = [STATUS_ACCEPTED, STATUS_REJECTED, STATUS_NO_BID, STATUS_PENDING]


def as_participant_list(value) -> list[str]:
    """Read the participant option, which older entries stored as a single string."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [name for name in value if name]
