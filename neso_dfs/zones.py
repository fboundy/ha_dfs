"""Work out which of NESO's 12 DFS zones a location sits in.

Boundaries come from NESO's published "DFS 12 Zones GeoJson Map", which is served
as a zip archive containing a single GeoJSON file (WGS84 lon/lat).
"""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .api import NesoError, geocode_postcode, http_get

ZONES_URL = "https://www.neso.energy/document/376656/download"
CACHE_MAX_AGE_SECONDS = 30 * 24 * 3600

Ring = Sequence[Sequence[float]]


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    postcode: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Zone:
    number: int

    @property
    def code(self) -> str:
        return f"Z{self.number}"


def cache_dir(override: str | Path | None = None) -> Path:
    """Where the zone boundaries are cached.

    Callers can pass a directory explicitly; Home Assistant does, because a container's
    home directory does not survive a restart and the boundaries would be re-downloaded
    every time.
    """
    if override:
        return Path(override)
    override = os.environ.get("NESO_DFS_CACHE")
    if override:
        return Path(override)
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    else:
        root = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(root) / "neso_dfs"


def _cache_path(override: str | Path | None = None) -> Path:
    return cache_dir(override) / "dfs_12_zones.geojson"


def _download_zones() -> dict[str, Any]:
    raw = http_get(ZONES_URL, timeout=120)
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".geojson")]
            if not names:
                raise NesoError("zone download contained no .geojson file")
            raw = archive.read(names[0])
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NesoError("zone boundary download was not valid GeoJSON") from exc


def load_zone_geojson(refresh: bool = False, cache: str | Path | None = None) -> dict[str, Any]:
    """Return the zone FeatureCollection, downloading it if the cache is stale."""
    path = _cache_path(cache)
    if not refresh and path.exists():
        age = time.time() - path.stat().st_mtime
        if age < CACHE_MAX_AGE_SECONDS:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

    data = _download_zones()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return data


def _point_in_ring(lon: float, lat: float, ring: Ring) -> bool:
    """Ray-casting test for a point against a single closed ring."""
    inside = False
    count = len(ring)
    previous = count - 1
    for current in range(count):
        x_i, y_i = ring[current][0], ring[current][1]
        x_j, y_j = ring[previous][0], ring[previous][1]
        if (y_i > lat) != (y_j > lat):
            crossing = (x_j - x_i) * (lat - y_i) / (y_j - y_i) + x_i
            if lon < crossing:
                inside = not inside
        previous = current
    return inside


def _point_in_polygon(lon: float, lat: float, polygon: Sequence[Ring]) -> bool:
    if not polygon or not _point_in_ring(lon, lat, polygon[0]):
        return False
    return not any(_point_in_ring(lon, lat, hole) for hole in polygon[1:])


def _polygons(geometry: dict[str, Any]) -> Iterable[Sequence[Ring]]:
    kind = geometry.get("type")
    if kind == "Polygon":
        yield geometry["coordinates"]
    elif kind == "MultiPolygon":
        yield from geometry["coordinates"]


def _bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    min_lon = min_lat = float("inf")
    max_lon = max_lat = float("-inf")
    for polygon in _polygons(geometry):
        for lon, lat in polygon[0]:
            min_lon = min(min_lon, lon)
            max_lon = max(max_lon, lon)
            min_lat = min(min_lat, lat)
            max_lat = max(max_lat, lat)
    return min_lon, min_lat, max_lon, max_lat


class ZoneMap:
    """The 12 DFS zone boundaries, ready for point lookups."""

    def __init__(self, geojson: dict[str, Any]):
        self._zones: list[tuple[int, tuple[float, float, float, float], dict[str, Any]]] = []
        for feature in geojson.get("features", []):
            properties = feature.get("properties") or {}
            number = properties.get("Region") or properties.get("Zone")
            geometry = feature.get("geometry")
            if number is None or not geometry:
                continue
            self._zones.append((int(number), _bounds(geometry), geometry))
        if not self._zones:
            raise NesoError("zone boundary data contained no usable zones")
        self._zones.sort(key=lambda item: item[0])

    @classmethod
    def load(cls, refresh: bool = False, cache: str | Path | None = None) -> "ZoneMap":
        return cls(load_zone_geojson(refresh=refresh, cache=cache))

    @property
    def zone_numbers(self) -> list[int]:
        return [number for number, _, _ in self._zones]

    def zone_for_point(self, latitude: float, longitude: float) -> Zone | None:
        for number, (min_lon, min_lat, max_lon, max_lat), geometry in self._zones:
            if not (min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat):
                continue
            if any(_point_in_polygon(longitude, latitude, polygon) for polygon in _polygons(geometry)):
                return Zone(number)
        return None


def resolve_location(
    postcode: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> Location:
    """Turn either a postcode or a coordinate pair into a Location."""
    if postcode:
        result = geocode_postcode(postcode)
        parts = [result.get("admin_district"), result.get("region") or result.get("country")]
        return Location(
            latitude=result["latitude"],
            longitude=result["longitude"],
            postcode=result.get("postcode", postcode),
            description=", ".join(part for part in parts if part),
        )
    if latitude is None or longitude is None:
        raise NesoError("provide either a postcode or both latitude and longitude")
    return Location(latitude=latitude, longitude=longitude)


def find_zone(
    postcode: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    refresh: bool = False,
    cache: str | Path | None = None,
) -> tuple[Zone | None, Location]:
    """Look up the DFS zone for a postcode or coordinate pair."""
    location = resolve_location(postcode, latitude, longitude)
    zone_map = ZoneMap.load(refresh=refresh, cache=cache)
    return zone_map.zone_for_point(location.latitude, location.longitude), location
