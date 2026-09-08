"""HTTP access to NESO's open data (CKAN) API and the postcodes.io geocoder."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "neso-dfs/0.1"
CKAN_SQL_URL = "https://api.neso.energy/api/3/action/datastore_search_sql"
CKAN_SEARCH_URL = "https://api.neso.energy/api/3/action/datastore_search"
POSTCODES_URL = "https://api.postcodes.io/postcodes/"

DEFAULT_TIMEOUT = 30


class NesoError(RuntimeError):
    """Any failure talking to an upstream service."""


def http_get(url: str, params: dict[str, str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise NesoError(f"HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        raise NesoError(f"could not reach {url}: {exc.reason}") from exc


def get_json(url: str, params: dict[str, str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> Any:
    raw = http_get(url, params, timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NesoError(f"{url} did not return JSON") from exc


def datastore_sql(sql: str, timeout: int = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    """Run a read-only SQL query against a CKAN datastore resource."""
    payload = get_json(CKAN_SQL_URL, {"sql": sql}, timeout)
    if not payload.get("success"):
        error = payload.get("error", {})
        raise NesoError(f"NESO API rejected the query: {error}")
    return payload["result"]["records"]


def geocode_postcode(postcode: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Resolve a UK postcode to coordinates via postcodes.io."""
    cleaned = postcode.strip().upper()
    if not cleaned:
        raise NesoError("postcode is empty")
    url = POSTCODES_URL + urllib.parse.quote(cleaned)
    try:
        payload = get_json(url, timeout=timeout)
    except NesoError as exc:
        if "HTTP 404" in str(exc):
            raise NesoError(f"postcode {cleaned!r} not found") from exc
        raise
    result = payload.get("result") or {}
    if result.get("latitude") is None or result.get("longitude") is None:
        raise NesoError(f"postcode {cleaned!r} has no coordinates (it may be a non-geographic postcode)")
    return result
