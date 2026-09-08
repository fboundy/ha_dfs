"""Tools for NESO's Demand Flexibility Service (DFS): zone lookup and event data."""

from .api import NesoError
from .events import DfsEvent, ServiceWindow, fetch_events, fetch_service_windows, parse_zonal_caps
from .zones import Location, Zone, ZoneMap, find_zone, resolve_location

__all__ = [
    "DfsEvent",
    "Location",
    "NesoError",
    "ServiceWindow",
    "Zone",
    "ZoneMap",
    "fetch_events",
    "fetch_service_windows",
    "find_zone",
    "parse_zonal_caps",
    "resolve_location",
]

__version__ = "0.1.0"
