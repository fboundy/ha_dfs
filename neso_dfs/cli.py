"""Command line interface for the NESO DFS tool."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone

from .api import NesoError
from .events import DfsEvent, fetch_events
from .zones import Location, Zone, find_zone


def _add_location_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--postcode", help="UK postcode, e.g. 'SW1A 1AA'")
    parser.add_argument("--lat", type=float, help="latitude in decimal degrees (WGS84)")
    parser.add_argument("--lon", type=float, help="longitude in decimal degrees (WGS84)")
    parser.add_argument(
        "--refresh", action="store_true", help="re-download the zone boundaries instead of using the cache"
    )


def _describe_location(location: Location) -> str:
    parts = [part for part in (location.postcode, location.description) if part]
    parts.append(f"{location.latitude:.5f}, {location.longitude:.5f}")
    return " | ".join(parts)


def _resolve_zone(args: argparse.Namespace) -> tuple[Zone | None, Location | None]:
    if getattr(args, "zone", None) is not None:
        return Zone(args.zone), None
    if not (args.postcode or (args.lat is not None and args.lon is not None)):
        return None, None
    return find_zone(args.postcode, args.lat, args.lon, refresh=args.refresh)


def _event_to_dict(event: DfsEvent, zone: int | None) -> dict:
    payload = {
        "event_id": event.event_id,
        "delivery_date": event.delivery_date.isoformat(),
        "event_type": event.event_type,
        "event_tag": event.event_tag,
        "service_type": event.service_type,
        "start_utc": event.start.isoformat(),
        "end_utc": event.end.isoformat(),
        "start_local": event.start_local,
        "end_local": event.end_local,
        "bid_submission_deadline_local": event.submission_time,
        "peak_requirement_mw": event.peak_requirement_mw,
        "dispatch_type": event.dispatch_type,
        "zonal_caps_mw": event.zonal_caps,
        "zones_in_scope": event.zones_in_scope,
        "participants": list(event.participants),
        "windows": [
            {
                **{
                    key: value
                    for key, value in asdict(window).items()
                    if key not in {"start", "end", "delivery_date", "participants", "zonal_caps"}
                },
                "start_utc": window.start.isoformat(),
                "end_utc": window.end.isoformat(),
            }
            for window in event.windows
        ],
    }
    if zone is not None:
        payload["zone"] = zone
        payload["zone_cap_mw"] = event.zonal_caps.get(zone)
        payload["in_your_zone"] = event.covers_zone(zone)
    return payload


def _print_event(event: DfsEvent, zone: int | None) -> None:
    labels = [event.event_type or "?", event.service_type or "?"]
    if event.event_tag:
        labels.append(event.event_tag)
    print(f"{event.delivery_date:%a %d %b %Y}  {event.start_local}-{event.end_local} local  [{' / '.join(labels)}]")
    print(f"  Event ID          {event.event_id}")
    print(f"  UTC window        {event.start:%Y-%m-%d %H:%M}-{event.end:%H:%M}Z")
    if event.peak_requirement_mw is not None:
        print(f"  Requirement       {event.peak_requirement_mw:g} MW (peak half-hour)")
    if event.submission_time:
        print(f"  Bids close        {event.submission_time}")
    if event.dispatch_type:
        print(f"  Dispatch          {event.dispatch_type}")

    caps = event.zonal_caps
    if caps:
        in_scope = event.zones_in_scope
        print(f"  Zones in scope    {', '.join(f'Z{number}' for number in in_scope) if in_scope else 'none'}")
        if zone is not None:
            cap = caps.get(zone, 0.0)
            verdict = f"Z{zone} cap {cap:g} MW" if cap > 0 else f"Z{zone} not procured for this event"
            print(f"  Your zone         {verdict}")
    else:
        print("  Zones in scope    national (no zonal split published)")
    print()


def command_zone(args: argparse.Namespace) -> int:
    zone, location = find_zone(args.postcode, args.lat, args.lon, refresh=args.refresh)
    if args.json:
        print(
            json.dumps(
                {
                    "zone": zone.number if zone else None,
                    "zone_code": zone.code if zone else None,
                    "location": asdict(location),
                },
                indent=2,
            )
        )
        return 0 if zone else 1

    print(_describe_location(location))
    if zone is None:
        print("No DFS zone found - the location is outside the GB zone boundaries.")
        return 1
    print(f"DFS zone: {zone.code} (zone {zone.number} of 12)")
    return 0


def command_events(args: argparse.Namespace) -> int:
    zone, location = _resolve_zone(args)
    zone_number = zone.number if zone else None

    events = fetch_events(
        zone=zone_number if args.only_my_zone else None,
        include_test=not args.live_only,
        upcoming_only=not args.all,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "zone": zone_number,
                    "location": asdict(location) if location else None,
                    "events": [_event_to_dict(event, zone_number) for event in events],
                },
                indent=2,
            )
        )
        return 0

    if location is not None:
        print(_describe_location(location))
    if zone_number is not None:
        print(f"DFS zone: Z{zone_number}\n")
    elif args.only_my_zone:
        print("Note: --only-my-zone needs a postcode, coordinates or --zone.\n")

    if not events:
        scope = "" if args.all else "upcoming "
        print(f"No {scope}DFS events published.")
        return 0

    for event in events:
        _print_event(event, zone_number)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neso-dfs",
        description="Find your NESO Demand Flexibility Service zone and upcoming DFS events.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    zone_parser = subparsers.add_parser("zone", help="find the DFS zone for a location")
    _add_location_arguments(zone_parser)
    zone_parser.add_argument("--json", action="store_true", help="output JSON")
    zone_parser.set_defaults(func=command_zone)

    events_parser = subparsers.add_parser("events", help="list DFS events")
    _add_location_arguments(events_parser)
    events_parser.add_argument("-z", "--zone", type=int, help="DFS zone number (1-12), instead of a location")
    events_parser.add_argument(
        "--only-my-zone", action="store_true", help="hide events that do not procure in your zone"
    )
    events_parser.add_argument("--live-only", action="store_true", help="exclude test events")
    events_parser.add_argument("--all", action="store_true", help="include events that have already finished")
    events_parser.add_argument("--json", action="store_true", help="output JSON")
    events_parser.set_defaults(func=command_events)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except NesoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
