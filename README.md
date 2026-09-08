# neso-dfs

A small Python tool for NESO's [Demand Flexibility Service](https://www.neso.energy/industry-information/balancing-services/demand-flexibility-service-dfs) (DFS):

1. **Find which DFS zone you are in** from a postcode or coordinates.
2. **Look up upcoming DFS events**, including whether your zone is actually being procured.

No third-party dependencies — standard library only.

## Install

```bash
pip install -e .
```

Or run it straight from the source tree with `python -m neso_dfs`.

## Which zone am I in?

Since April 2026 DFS is procured zonally across **12 zones** covering Great Britain.

```console
$ neso-dfs zone --postcode "SW1A 1AA"
SW1A 1AA | Westminster, London | 51.50101, -0.14156
DFS zone: Z12 (zone 12 of 12)

$ neso-dfs zone --lat 55.95033 --lon -3.19302
55.95033, -3.19302
DFS zone: Z3 (zone 3 of 12)
```

Zones run roughly north to south: Z1 is the Scottish Highlands, Z12 is London and the South East.
Northern Ireland is not covered by DFS, and the lookup returns no zone for locations outside GB.

Add `--json` for machine-readable output, and `--refresh` to re-download the boundaries.

## What events are coming up?

```console
$ neso-dfs events --postcode "SW1A 1AA"
SW1A 1AA | Westminster, London | 51.50101, -0.14156
DFS zone: Z12

Tue 08 Sep 2026  17:00-22:00 local  [Downwards / Live / Energy]
  Event ID          115
  UTC window        2026-09-08 16:00-21:00Z
  Requirement       500 MW (peak half-hour)
  Bids close        08/09/2026 12:00
  Dispatch          All Participants
  Zones in scope    Z4, Z5, Z6, Z7, Z8, Z9, Z10, Z11, Z12
  Your zone         Z12 cap 500 MW
```

An event publishes a per-zone MW cap. A cap of `0` means that zone is not being procured for that
event, which is what `Your zone` and `--only-my-zone` key off.

| Option | Effect |
| --- | --- |
| `-p/--postcode`, `--lat`/`--lon`, `-z/--zone` | Pick the zone to report against |
| `--only-my-zone` | Hide events that do not procure in your zone |
| `--live-only` | Exclude test events |
| `--all` | Include events that have already finished |
| `--json` | Machine-readable output |

Events are published shortly before the day of delivery, so an empty list is normal — outside a
tight system margin there simply are no DFS events scheduled.

## Python API

```python
from neso_dfs import fetch_events, find_zone

zone, location = find_zone(postcode="SW1A 1AA")

for event in fetch_events(zone=zone.number, include_test=False):
    print(event.delivery_date, event.start, event.end, event.peak_requirement_mw)
    print(event.zonal_caps[zone.number], "MW cap in your zone")
```

`fetch_events()` returns `DfsEvent` objects, each grouping the half-hour `ServiceWindow` rows that
NESO publishes under one event ID. Times are timezone-aware UTC (`event.start` / `event.end`), with
NESO's local clock strings kept alongside as `start_local` / `end_local`.

## Data sources

| What | Source |
| --- | --- |
| Zone boundaries | NESO ["DFS 12 Zones GeoJson Map"](https://www.neso.energy/document/376656/download) |
| Events | NESO Data Portal, [DFS Service Requirement](https://www.neso.energy/data-portal/demand-flexibility/dfs_service_requirement) (CKAN resource `3635fd80-49d7-4d02-964d-cc8c08d50302`) |
| Postcode geocoding | [postcodes.io](https://postcodes.io) |

Zone boundaries are cached for 30 days under `~/.cache/neso_dfs` (`%LOCALAPPDATA%\neso_dfs` on
Windows); set `NESO_DFS_CACHE` to override the location.

## Tests

```bash
pytest
```

The tests are offline — no network access needed.

`pytest-homeassistant-custom-component` pulls in `homeassistant`, which imports `fcntl` and so
cannot load on Windows. `pyproject.toml` disables that plugin with `-p no:homeassistant`; drop the
flag if you add tests exercising the Home Assistant layer, and run those under Linux or WSL.
