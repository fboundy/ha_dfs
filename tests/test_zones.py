import pytest

from neso_dfs.api import NesoError
from neso_dfs.zones import ZoneMap, resolve_location

SQUARE = [[[0.0, 0.0], [0.0, 2.0], [2.0, 2.0], [2.0, 0.0], [0.0, 0.0]]]
HOLE = [[0.8, 0.8], [0.8, 1.2], [1.2, 1.2], [1.2, 0.8], [0.8, 0.8]]


def zone_map(*features):
    return ZoneMap({"type": "FeatureCollection", "features": list(features)})


def feature(number, geometry):
    return {"type": "Feature", "properties": {"Region": number}, "geometry": geometry}


def test_point_inside_polygon():
    zones = zone_map(feature(4, {"type": "Polygon", "coordinates": SQUARE}))
    assert zones.zone_for_point(1.0, 0.5).number == 4
    assert zones.zone_for_point(5.0, 5.0) is None


def test_hole_is_excluded():
    zones = zone_map(feature(7, {"type": "Polygon", "coordinates": [SQUARE[0], HOLE]}))
    assert zones.zone_for_point(0.5, 0.5).number == 7
    assert zones.zone_for_point(1.0, 1.0) is None


def test_multipolygon_parts_both_match():
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [SQUARE, [[[10.0, 10.0], [10.0, 11.0], [11.0, 11.0], [11.0, 10.0], [10.0, 10.0]]]],
    }
    zones = zone_map(feature(2, geometry))
    assert zones.zone_for_point(0.5, 0.5).number == 2
    assert zones.zone_for_point(10.5, 10.5).number == 2


def test_zone_code_formatting():
    zones = zone_map(feature(11, {"type": "Polygon", "coordinates": SQUARE}))
    assert zones.zone_for_point(1.0, 1.0).code == "Z11"


def test_empty_boundary_data_is_rejected():
    with pytest.raises(NesoError):
        zone_map()


def test_resolve_location_requires_input():
    with pytest.raises(NesoError):
        resolve_location()
    with pytest.raises(NesoError):
        resolve_location(latitude=51.5)


def test_resolve_location_from_coordinates():
    location = resolve_location(latitude=51.5, longitude=-0.1)
    assert (location.latitude, location.longitude) == (51.5, -0.1)
    assert location.postcode is None
