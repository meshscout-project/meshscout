"""Unit and spatial integrity tests for Vermont cartographic geodata adapter."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

import pytest

from meshscout.adapters.geodata import (
    CONNECTICUT_RIVER_NH,
    LAKE_CHAMPLAIN_POLYGON,
    LAKE_GEORGE,
    LAKE_WINNIPESAUKEE,
    NEW_HAMPSHIRE_STATE_BORDER,
    NEW_HAMPSHIRE_SUMMITS,
    NEW_YORK_CHAMPLAIN_RIM_BORDER,
    NEW_YORK_SUMMITS,
    QUEBEC_STATE_BORDER,
    QUEBEC_SUMMITS,
    RICHELIEU_RIVER,
    ST_LAWRENCE_RIVER,
    VERMONT_COUNTY_BORDERS,
    VERMONT_HIGHWAYS,
    VERMONT_LAKES,
    VERMONT_REFERENCE_TOWNS,
    VERMONT_RIVERS,
    VERMONT_STATE_BORDER,
    VERMONT_SUMMITS,
    get_cartographic_layers,
)
from meshscout.core.contracts import RegionalBounds

# Strict geographic bounding box encompassing Vermont and Lake Champlain
VT_GEO_MIN_LAT = 42.5
VT_GEO_MAX_LAT = 45.2
VT_GEO_MIN_LON = -73.6
VT_GEO_MAX_LON = -71.3

ALL_14_COUNTIES = {
    "Addison",
    "Bennington",
    "Caledonia",
    "Chittenden",
    "Essex",
    "Franklin",
    "Grand Isle",
    "Lamoille",
    "Orange",
    "Orleans",
    "Rutland",
    "Washington",
    "Windham",
    "Windsor",
}


def test_lake_champlain_span_and_islands() -> None:
    """Verify Lake Champlain spans lat ~43.55 to 45.02 and includes major islands."""
    coords = LAKE_CHAMPLAIN_POLYGON["coordinates"]
    lats = [pt[1] for pt in coords]
    lons = [pt[0] for pt in coords]

    # Must span all the way from South Bay / Whitehall (lat 43.55) to Canadian border (lat 45.02)
    assert min(lats) <= 43.55, f"Lake Champlain southern limit {min(lats)} exceeds 43.55"
    assert max(lats) >= 45.02, f"Lake Champlain northern limit {max(lats)} below 45.02"

    # Must fall within global bounding limits
    assert all(VT_GEO_MIN_LAT <= lat <= VT_GEO_MAX_LAT for lat in lats)
    assert all(VT_GEO_MIN_LON <= lon <= VT_GEO_MAX_LON for lon in lons)

    # Lake polygon must be closed
    assert coords[0] == coords[-1], "Lake Champlain exterior boundary is not closed"

    # GeoJSON geometry checks
    geom = LAKE_CHAMPLAIN_POLYGON["geometry"]
    assert geom["type"] == "Polygon"
    assert len(geom["coordinates"]) >= 5  # exterior ring + 4 island holes

    # Verify major island cutouts/polygons exist
    islands = LAKE_CHAMPLAIN_POLYGON["islands"]
    expected_islands = ["Grand Isle", "South Hero", "North Hero", "Isle La Motte"]
    for island_name in expected_islands:
        assert island_name in islands
        isl = islands[island_name]
        assert isl["coordinates"][0] == isl["coordinates"][-1]
        isl_lats = [pt[1] for pt in isl["coordinates"]]
        isl_lons = [pt[0] for pt in isl["coordinates"]]
        assert all(VT_GEO_MIN_LAT <= lat <= VT_GEO_MAX_LAT for lat in isl_lats)
        assert all(VT_GEO_MIN_LON <= lon <= VT_GEO_MAX_LON for lon in isl_lons)


def test_vermont_state_border_polygon() -> None:
    """Verify Vermont state border polygon is closed and encompasses standard bounds."""
    coords = VERMONT_STATE_BORDER["coordinates"]
    assert len(coords) >= 40, f"Expected 40-50 coordinate pairs, found {len(coords)}"
    assert coords[0] == coords[-1], "Vermont state border polygon is not closed"

    lats = [pt[1] for pt in coords]
    lons = [pt[0] for pt in coords]

    # Verify bounds encompass the authentic State of Vermont
    assert min(lats) <= 42.73, f"VT southern border {min(lats)} expected <= 42.73"
    assert max(lats) >= 45.01, f"VT northern border {max(lats)} expected >= 45.01"
    assert min(lons) <= -73.35, f"VT western border {min(lons)} expected <= -73.35"
    assert max(lons) >= -71.51, f"VT eastern border {max(lons)} expected >= -71.51"

    assert all(VT_GEO_MIN_LAT <= lat <= VT_GEO_MAX_LAT for lat in lats)
    assert all(VT_GEO_MIN_LON <= lon <= VT_GEO_MAX_LON for lon in lons)


def test_vermont_inland_lakes_integrity() -> None:
    """Verify major inland water bodies exist with valid closed polygons."""
    expected_lakes = [
        "Lake Memphremagog",
        "Lake Bomoseen",
        "Lake Dunmore",
        "Waterbury Reservoir",
        "Somerset Reservoir",
        "Harriman Reservoir",
        "Lake Willoughby",
    ]
    for lake_name in expected_lakes:
        assert lake_name in VERMONT_LAKES
        lake = VERMONT_LAKES[lake_name]
        coords = lake["coordinates"]
        assert coords[0] == coords[-1], f"Lake {lake_name} polygon must be closed"
        lats = [pt[1] for pt in coords]
        lons = [pt[0] for pt in coords]
        assert all(VT_GEO_MIN_LAT <= lat <= VT_GEO_MAX_LAT for lat in lats)
        assert all(VT_GEO_MIN_LON <= lon <= VT_GEO_MAX_LON for lon in lons)
        assert lake["elevation_m"] > 0


def test_vermont_rivers_integrity() -> None:
    """Verify key river LoRa propagation corridors and coordinate bounds."""
    expected_rivers = [
        "Winooski River",
        "Lamoille River",
        "Missisquoi River",
        "Otter Creek",
        "White River",
        "Connecticut River",
    ]
    for river_name in expected_rivers:
        assert river_name in VERMONT_RIVERS
        river = VERMONT_RIVERS[river_name]
        coords = river["coordinates"]
        assert len(coords) >= 6, f"River {river_name} needs sufficient waypoints"
        lats = [pt[1] for pt in coords]
        lons = [pt[0] for pt in coords]
        assert all(VT_GEO_MIN_LAT <= lat <= VT_GEO_MAX_LAT for lat in lats)
        assert all(VT_GEO_MIN_LON <= lon <= VT_GEO_MAX_LON for lon in lons)

    # Connecticut river spans entire eastern border
    ct_river_lats = [pt[1] for pt in VERMONT_RIVERS["Connecticut River"]["coordinates"]]
    assert min(ct_river_lats) <= 42.73
    assert max(ct_river_lats) >= 45.01


def test_vermont_highways_integrity() -> None:
    """Verify primary travel corridors have high-fidelity line geometries."""
    expected_highways = [
        "Interstate 89",
        "Interstate 91",
        "US Route 7",
        "US Route 2",
        "US Route 4",
        "VT Route 100",
        "VT Route 15",
    ]
    for hwy_name in expected_highways:
        assert hwy_name in VERMONT_HIGHWAYS
        hwy = VERMONT_HIGHWAYS[hwy_name]
        coords = hwy["coordinates"]
        assert len(coords) >= 8, f"Highway {hwy_name} needs sufficient waypoints"
        lats = [pt[1] for pt in coords]
        lons = [pt[0] for pt in coords]
        assert all(VT_GEO_MIN_LAT <= lat <= VT_GEO_MAX_LAT for lat in lats)
        assert all(VT_GEO_MIN_LON <= lon <= VT_GEO_MAX_LON for lon in lons)


def test_vermont_county_borders_representation() -> None:
    """Verify county dividing segments represent all 14 counties."""
    counties_represented = set()
    for segment in VERMONT_COUNTY_BORDERS.values():
        coords = segment["coordinates"]
        assert len(coords) >= 2
        for county in segment["counties"]:
            counties_represented.add(county)
        lats = [pt[1] for pt in coords]
        lons = [pt[0] for pt in coords]
        assert all(VT_GEO_MIN_LAT <= lat <= VT_GEO_MAX_LAT for lat in lats)
        assert all(VT_GEO_MIN_LON <= lon <= VT_GEO_MAX_LON for lon in lons)

    assert counties_represented == ALL_14_COUNTIES


def test_vermont_summits_and_passes() -> None:
    """Verify summits and mountain passes with elevations, prominences, and coordinates."""
    assert len(VERMONT_SUMMITS) >= 20
    assert "Mount Mansfield" in VERMONT_SUMMITS
    assert "Killington Peak" in VERMONT_SUMMITS
    assert "Camel's Hump" in VERMONT_SUMMITS

    mansfield = VERMONT_SUMMITS["Mount Mansfield"]
    assert mansfield["elevation_m"] == 1339.0
    assert mansfield["prominence_m"] == 1107.0

    for name, summit in VERMONT_SUMMITS.items():
        assert VT_GEO_MIN_LAT <= summit["lat"] <= VT_GEO_MAX_LAT
        assert VT_GEO_MIN_LON <= summit["lon"] <= VT_GEO_MAX_LON
        assert summit["elevation_m"] > 0
        assert "county" in summit


def test_vermont_reference_towns_all_14_counties() -> None:
    """Verify 40+ key towns exist across all 14 Vermont counties."""
    assert len(VERMONT_REFERENCE_TOWNS) >= 40
    counties_found = set()
    for name, town in VERMONT_REFERENCE_TOWNS.items():
        assert VT_GEO_MIN_LAT <= town["lat"] <= VT_GEO_MAX_LAT
        assert VT_GEO_MIN_LON <= town["lon"] <= VT_GEO_MAX_LON
        counties_found.add(town["county"])

    assert counties_found == ALL_14_COUNTIES, f"Missing counties: {ALL_14_COUNTIES - counties_found}"


def test_get_cartographic_layers_performance_and_serializability() -> None:
    """Verify layers serialization in JSON and execution under 15ms."""
    t0 = time.perf_counter()
    layers = get_cartographic_layers()
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.015, f"get_cartographic_layers took {elapsed * 1000:.2f}ms, expected < 15ms"

    # Must be valid, pure JSON serializable dict
    serialized = json.dumps(layers)
    assert len(serialized) > 1000
    deserialized = json.loads(serialized)
    assert "lake_champlain" in deserialized
    assert "state_border" in deserialized
    assert "lakes" in deserialized
    assert "rivers" in deserialized
    assert "highways" in deserialized
    assert "county_borders" in deserialized
    assert "summits" in deserialized
    assert "reference_towns" in deserialized


def test_get_cartographic_layers_regional_filtering() -> None:
    """Verify spatial bounding box filtering with RegionalBounds."""
    chittenden_bounds = RegionalBounds(
        name="Chittenden_Box",
        min_lat=44.25,
        max_lat=44.65,
        min_lon=-73.35,
        max_lon=-72.75,
    )
    t0 = time.perf_counter()
    filtered = get_cartographic_layers(chittenden_bounds)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.015

    # Chittenden towns should be included, Southern/Eastern towns excluded
    assert "Burlington" in filtered["reference_towns"]
    assert "Essex Junction" in filtered["reference_towns"]
    assert "Brattleboro" not in filtered["reference_towns"]
    assert "Bennington" not in filtered["reference_towns"]

    # Winooski River traverses Chittenden, White River does not
    assert "Winooski River" in filtered["rivers"]
    assert "White River" not in filtered["rivers"]

    # I-89 traverses Chittenden, I-91 does not
    assert "Interstate 89" in filtered["highways"]
    assert "Interstate 91" not in filtered["highways"]


def test_get_cartographic_layers_quebec() -> None:
    """Verify get_cartographic_layers(state_code='CA_QC') returns Quebec border and St. Lawrence/Richelieu rivers."""
    layers = get_cartographic_layers(state_code="CA_QC")
    assert layers["state_border"] is not None
    assert layers["state_border"] == QUEBEC_STATE_BORDER
    assert layers["state_border"]["properties"]["abbreviation"] == "QC"
    assert layers["state_border"]["coordinates"][0] == layers["state_border"]["coordinates"][-1]

    # St. Lawrence and Richelieu rivers must be present
    assert "St. Lawrence River" in layers["rivers"]
    assert "Richelieu River" in layers["rivers"]
    assert "St. Lawrence River" in layers["waterways"]
    assert "Richelieu River" in layers["waterways"]

    # Monteregian Hills summits
    assert "Mont Royal" in layers["summits"]
    assert "Mont Saint-Hilaire" in layers["summits"]
    assert "Mont Orford" in layers["summits"]
    assert "Mont Sutton" in layers["summits"]
    assert "Mont Mégantic" in layers["summits"]
    assert layers["summits"]["Mont Royal"]["elevation_m"] == 233.0
    assert layers["summits"]["Mont Saint-Hilaire"]["elevation_m"] == 414.0
    assert layers["summits"]["Mont Orford"]["elevation_m"] == 853.0
    assert layers["summits"]["Mont Sutton"]["elevation_m"] == 968.0
    assert layers["summits"]["Mont Mégantic"]["elevation_m"] == 1105.0


def test_get_cartographic_layers_new_hampshire() -> None:
    """Verify get_cartographic_layers(state_code='NH') returns NH border and Lake Winnipesaukee."""
    layers = get_cartographic_layers(state_code="NH")
    assert layers["state_border"] is not None
    assert layers["state_border"] == NEW_HAMPSHIRE_STATE_BORDER
    assert layers["state_border"]["properties"]["abbreviation"] == "NH"
    assert layers["state_border"]["coordinates"][0] == layers["state_border"]["coordinates"][-1]

    # Lake Winnipesaukee and Connecticut River
    assert "Lake Winnipesaukee" in layers["lakes"]
    assert "Lake Winnipesaukee" in layers["waterways"]
    assert "Connecticut River" in layers["rivers"]
    assert "Connecticut River" in layers["waterways"]
    assert layers["lakes"]["Lake Winnipesaukee"]["coordinates"][0] == layers["lakes"]["Lake Winnipesaukee"]["coordinates"][-1]

    # White Mountains summits
    assert "Mount Washington" in layers["summits"]
    assert "Cannon Mountain" in layers["summits"]
    assert "Mount Monadnock" in layers["summits"]
    assert layers["summits"]["Mount Washington"]["elevation_m"] == 1917.0
    assert layers["summits"]["Cannon Mountain"]["elevation_m"] == 1243.0
    assert layers["summits"]["Mount Monadnock"]["elevation_m"] == 965.0


def test_get_cartographic_layers_new_york() -> None:
    """Verify get_cartographic_layers(state_code='NY') returns Adirondack/Lake Champlain rim border."""
    layers = get_cartographic_layers(state_code="NY")
    assert layers["state_border"] is not None
    assert layers["state_border"] == NEW_YORK_CHAMPLAIN_RIM_BORDER
    assert layers["state_border"]["properties"]["abbreviation"] == "NY"
    assert layers["state_border"]["coordinates"][0] == layers["state_border"]["coordinates"][-1]

    # Lake George and Lake Champlain
    assert "Lake George" in layers["lakes"]
    assert "Lake George" in layers["waterways"]
    assert layers["lakes"]["Lake George"]["coordinates"][0] == layers["lakes"]["Lake George"]["coordinates"][-1]

    # Adirondacks summits
    assert "Whiteface Mountain" in layers["summits"]
    assert "Lyon Mountain" in layers["summits"]
    assert "Poke-O-Moonshine" in layers["summits"]
    assert layers["summits"]["Whiteface Mountain"]["elevation_m"] == 1483.0
    assert layers["summits"]["Lyon Mountain"]["elevation_m"] == 1167.0
    assert layers["summits"]["Poke-O-Moonshine"]["elevation_m"] == 664.0


def test_get_cartographic_layers_cross_border_bounds() -> None:
    """Verify cross-border bounds box retrieves intersecting adjacent regional features."""
    # Bounding box spanning northern VT and southern Quebec (includes Mont Sutton and Richelieu)
    border_bounds = RegionalBounds(
        name="Border_Corridor",
        min_lat=44.90,
        max_lat=45.30,
        min_lon=-73.40,
        max_lon=-72.40,
    )
    layers = get_cartographic_layers(bounds=border_bounds, state_code="VT")
    assert layers["state_border"] is not None
    # Cross-border summits and waterways included
    assert "Mont Sutton" in layers["summits"]
    assert "Richelieu River" in layers["rivers"] or "Richelieu River" in layers["waterways"]

