# NESO Demand Flexibility Service for Home Assistant

[![Validate](https://github.com/fboundy/ha_dfs/actions/workflows/validate.yml/badge.svg)](https://github.com/fboundy/ha_dfs/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)

A Home Assistant integration for NESO's
[Demand Flexibility Service](https://www.neso.energy/industry-information/balancing-services/demand-flexibility-service-dfs)
(DFS) — the scheme that pays you to shift electricity use away from peak periods.

It tells you three things:

- **Which DFS zone you are in**, worked out from the location Home Assistant already knows.
- **When events are running**, and whether your zone is actually being procured for them.
- **How the bidding went** — accepted volume, clearing price, and whether your own provider won.

Since April 2026 DFS is procured **zonally** across 12 zones, so a national event is no longer the
same as an event where you can earn. This integration keys everything off your zone.

## Installation

### HACS (recommended)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/fboundy/ha_dfs` with category **Integration**.
3. Install **NESO Demand Flexibility Service**, then restart Home Assistant.

### Manually

Copy `custom_components/neso_dfs/` into your Home Assistant `config/custom_components/` directory
and restart. If you have SSH access to the host, `./scripts/deploy.sh user@host` does this for you.

## Setup

Go to **Settings → Devices & Services → Add Integration** and choose **NESO Demand Flexibility
Service**.

- **Postcode** — leave blank to use the coordinates Home Assistant already holds for your home.
  Enter one only if you want a different location.
- **Participant** — optionally pick a registered DFS participant to follow, chosen from those that
  actually bid into your zone. Skip it if you just want event data; you can set it later through
  the **Configure** button.

Northern Ireland is not covered by DFS, so a location outside Great Britain is rejected with a
clear error rather than guessing a zone.

## Entities

Entities are grouped under a device named for your zone, and their IDs carry that prefix — the
zone sensor for a zone 6 setup is `sensor.neso_dfs_zone_6_dfs_zone`.

| Name | Description |
| --- | --- |
| DFS zone | Your zone, 1–12 |
| DFS event active | On while a window covering your zone is being delivered |
| DFS event today | On when an event is scheduled today |
| Next DFS event start / end | Timestamps for the next event |
| Next DFS event requirement | Peak MW requirement published for it |
| Upcoming DFS events | Count, with every upcoming event in its attributes |
| DFS accepted volume | MW accepted in your zone for the current or next window, with every bid listed in its attributes |
| DFS clearing price | Highest accepted price in your zone, £/MWh |

Every event entity carries the full detail in its attributes: event ID, direction (Upwards or
Downwards), live or test, the bid deadline, your zone's MW cap and which zones are in scope.

An event publishes a per-zone MW cap. **A cap of `0`, or a zone missing from the list, means that
zone is not being procured** — the event is running, but not where you are.

The accepted volume sensor carries the full auction result for the window in `accepted_bids` and
`rejected_bids`, each a list of `{participant, unit_id, mw, price}` ordered by price. NESO publishes
one bid per participant per zone, so this is a handful of rows, not thousands. Reading the two lists
together shows the merit order directly — every rejected bid sits above the clearing price:

```yaml
accepted_bids:
  - {participant: Shuffle Energy Limited, unit_id: SHUF-06-Z6, mw: 0.1, price: 175.0}
  - {participant: INFINIS LIMITED,        unit_id: INFI-06-Z6, mw: 2.4, price: 177.0}
  - {participant: EQUIWATT LIMITED,       unit_id: EQUI-06-Z6, mw: 1.2, price: 203.0}   # marginal
rejected_bids:
  - {participant: AXLE ENERGY LIMITED,    unit_id: AXLE-01-Z6, mw: 2.7, price: 319.3}
```

### Tracking a participant

Setting a participant adds five more entities. **Confirmed results and historical likelihood are
kept deliberately separate**, so a bid that has not settled yet never reads as a rejection:

| Name | Description |
| --- | --- |
| Participant | The participant being tracked |
| Participant accepted | Confirmed accepted for the current or next event. `unknown` until the auction settles |
| Participant status | `accepted`, `rejected`, `no_bid`, or `pending` while unsettled |
| Participant accepted volume | Confirmed MW accepted |
| Participant accept rate | Share of this participant's past bids accepted in your zone |

Accept rate is a **prior, not a prediction** — it only tells you anything while a bid is still
`pending`. Once the auction settles, the status sensor is fact and the rate is irrelevant to that
event.

NESO publishes bids shortly after the auction closes, usually hours before delivery starts, so you
generally know the outcome well in advance.

### Example automation

```yaml
automation:
  - alias: Preheat when my provider wins a DFS slot
    triggers:
      - trigger: state
        entity_id: sensor.neso_dfs_zone_6_participant_status
        to: accepted
    actions:
      - action: notify.persistent_notification
        data:
          message: >-
            DFS accepted for
            {{ state_attr('sensor.neso_dfs_zone_6_participant_status', 'event_window_local') }},
            {{ states('sensor.neso_dfs_zone_6_participant_accepted_volume') }} MW at
            {{ states('sensor.neso_dfs_zone_6_dfs_clearing_price') }} £/MWh.
```

Trigger on `accepted` rather than off `pending` — pending means "not known yet", not "no".

## Data sources

| What | Source |
| --- | --- |
| Zone boundaries | NESO ["DFS 12 Zones GeoJson Map"](https://www.neso.energy/document/376656/download) |
| Events | NESO Data Portal, [DFS Service Requirement](https://www.neso.energy/data-portal/demand-flexibility/dfs_service_requirement) (CKAN `3635fd80-49d7-4d02-964d-cc8c08d50302`) |
| Bids | NESO Data Portal, [DFS Utilisation Report](https://www.neso.energy/data-portal/demand-flexibility/dfs_utilisation_report) (CKAN `3ebf77d7-05df-466e-a023-dc45a90efeea`) |
| Postcode geocoding | [postcodes.io](https://postcodes.io) |

Everything is public open data — no account, token or API key. Data is polled every 15 minutes, and
the zone boundaries are cached locally for 30 days.

The integration has **no third-party Python dependencies**; it bundles its own copy of the library
below, so `manifest.json` requires nothing at install time.

## Appendix: command line tool

The same logic ships as a standalone, dependency-free CLI, useful for checking things without
Home Assistant.

```bash
pip install -e .
```

Find your zone:

```console
$ neso-dfs zone --postcode "SW1A 1AA"
SW1A 1AA | Westminster, London | 51.50101, -0.14156
DFS zone: Z12 (zone 12 of 12)
```

List upcoming events:

```console
$ neso-dfs events --postcode "SW1A 1AA"
Tue 08 Sep 2026  17:00-22:00 local  [Downwards / Live / Energy]
  Event ID          115
  Requirement       500 MW (peak half-hour)
  Bids close        08/09/2026 12:00
  Zones in scope    Z4, Z5, Z6, Z7, Z8, Z9, Z10, Z11, Z12
  Your zone         Z12 cap 500 MW
```

Inspect the bidding:

```console
$ neso-dfs bids --zone 6
date        window          accepted  rejected   clearing
2026-09-08  18:00-18:30         17.4       0.0     185.00
2026-09-08  18:30-19:00         15.4       0.0     203.00
```

All three commands accept `-p/--postcode`, `--lat`/`--lon` or `-z/--zone`, plus `--json` for
machine-readable output. `events` also takes `--only-my-zone`, `--live-only` and `--all`.

### Python API

```python
from neso_dfs import fetch_events, find_zone

zone, location = find_zone(postcode="SW1A 1AA")

for event in fetch_events(zone=zone.number, include_test=False):
    print(event.delivery_date, event.start, event.end, event.peak_requirement_mw)
```

`fetch_events()` returns `DfsEvent` objects grouping the half-hour windows NESO publishes under one
event ID. Times are timezone-aware UTC, with NESO's local clock strings kept alongside.

### Development

```bash
pytest
python scripts/sync_vendor.py   # after changing anything under neso_dfs/
```

`neso_dfs/` is the source of truth; `scripts/sync_vendor.py` copies it into the integration's
`vendor_lib/` so HACS can install the component self-contained, and a test fails if the two drift.

Tests run fully offline. `pytest-homeassistant-custom-component` imports `homeassistant`, which
needs `fcntl` and cannot load on Windows, so `pyproject.toml` disables that plugin; drop
`-p no:homeassistant` and use Linux or WSL if you add tests covering the Home Assistant layer.

## Support

[![ko-fi](https://img.shields.io/badge/Ko--fi-Support-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/fboundy)

If you would like to support this work financially, the Ko-fi link supports
[Penrith Mountain Rescue Team](https://penrithmrt.org.uk).
