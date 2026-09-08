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

## Who won the bidding?

NESO publishes every bid shortly after the auction closes — usually hours before delivery starts —
so the accepted volume and clearing price for your zone are known in advance of the event.

```console
$ neso-dfs bids --zone 6
DFS zone: Z6

date        window          accepted  rejected   clearing
2026-09-08  17:00-17:30          1.8       0.0     175.00
2026-09-08  18:00-18:30         17.4       0.0     185.00
2026-09-08  18:30-19:00         15.4       0.0     203.00

Accepted providers in the 21:30-22:00 window:
     1.30 MW  INFINIS LIMITED
     0.20 MW  HILDEBRAND TECHNOLOGY LIMITED
```

`clearing` is the highest accepted price in that window — what the marginal accepted bid was paid.

## Home Assistant integration

`custom_components/neso_dfs/` is a config-flow integration built on the same library. Install it
through HACS as a custom repository (category *Integration*), or run `./scripts/deploy.sh` to copy
it to a Home Assistant host over SSH.

Leave the postcode blank during setup and it uses the coordinates Home Assistant already holds for
your home.

| Entity | Description |
| --- | --- |
| `sensor.dfs_zone` | Your DFS zone (1–12) |
| `binary_sensor.dfs_event_active` | On while a window covering your zone is being delivered |
| `binary_sensor.dfs_event_today` | On when an event is scheduled today |
| `sensor.next_dfs_event_start` / `_end` | Timestamps for the next event |
| `sensor.next_dfs_event_requirement` | Peak MW requirement |
| `sensor.upcoming_dfs_events` | Count, with every upcoming event in its attributes |
| `sensor.dfs_accepted_volume` | MW accepted in your zone for the current or next window |
| `sensor.dfs_clearing_price` | Highest accepted price, £/MWh |

### Tracking a bidder

The options flow lets you pick a registered DFS participant — your own aggregator, for instance —
and adds three more entities. **Confirmed results and historical likelihood are kept separate**, so
a bid that has not settled yet never reads as a rejection:

| Entity | Description |
| --- | --- |
| `sensor.dfs_bidder` | The participant being tracked |
| `binary_sensor.dfs_bidder_accepted` | Confirmed accepted for the current/next event. `unknown` until the auction settles |
| `sensor.dfs_bidder_status` | `accepted`, `rejected`, `no_bid`, or `pending` while unsettled |
| `sensor.dfs_bidder_accepted_volume` | Confirmed MW accepted |
| `sensor.dfs_bidder_accept_rate` | Share of this bidder's past bids accepted in your zone — the prior, only meaningful while a bid is `pending` |

Use `dfs_bidder_status` to drive automations: act on `accepted`, and treat `pending` as "not known
yet" rather than a no.

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
| Bids | NESO Data Portal, [DFS Utilisation Report](https://www.neso.energy/data-portal/demand-flexibility/dfs_utilisation_report) (CKAN resource `3ebf77d7-05df-466e-a023-dc45a90efeea`) |
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

## Support

[![ko-fi](https://img.shields.io/badge/Ko--fi-Support-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/fboundy)

If you would like to support this work financially, the Ko-fi link supports
[Penrith Mountain Rescue Team](https://penrithmrt.org.uk).
