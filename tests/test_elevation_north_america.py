"""Hermetic unit tests for MeshScout Terrain Provenance Tagging & DEM Tile Planner (TASK-1132).

Verifies:
1. SRTM HGT tile planner calculation (get_required_hgt_tiles_for_bounds).
2. Terrain provenance source tagging ('synthetic' inside Vermont box, 'synthetic_out_of_domain' outside).
3. Deduplicated synthetic elevation function and zero numeric drift across domain boundaries.
4. SRTMHgtReader and HGTElevationTileReader interface parity.
"""

from __future__ import annotations

import math
from pathlib import Path
import pytest

from meshscout.adapters.elevation import (
    HGTElevationTileReader,
    SRTMHgtReader,
    USGS3DEPElevationAdapter,
    VERMONT_MODEL_BOX_MAX_LAT,
    VERMONT_MODEL_BOX_MAX_LON,
    VERMONT_MODEL_BOX_MIN_LAT,
    VERMONT_MODEL_BOX_MIN_LON,
    _synthetic_vermont_elevation_fn as adapter_elevation_fn,
    get_required_hgt_tiles_for_bounds,
    is_in_vermont_model_box,
)
from meshscout.core.composite_viewshed import (
    _synthetic_vermont_elevation_fn as viewshed_elevation_fn,
)
from meshscout.core.contracts import Coordinate, RegionalBounds


def test_vermont_model_box_boundary_predicates():
    """Verify Vermont high-precision model box boundary definitions and predicate helper."""
    assert VERMONT_MODEL_BOX_MIN_LAT == 42.5
    assert VERMONT_MODEL_BOX_MAX_LAT == 45.5
    assert VERMONT_MODEL_BOX_MIN_LON == -74.5
    assert VERMONT_MODEL_BOX_MAX_LON == -71.0

    # Interior points
    assert is_in_vermont_model_box(44.5, -73.2) is True
    assert is_in_vermont_model_box(43.0, -72.0) is True

    # Exact boundary points (inclusive)
    assert is_in_vermont_model_box(42.5, -74.5) is True
    assert is_in_vermont_model_box(45.5, -71.0) is True
    assert is_in_vermont_model_box(42.5, -71.0) is True
    assert is_in_vermont_model_box(45.5, -74.5) is True

    # Exterior points
    assert is_in_vermont_model_box(45.501, -73.0) is False  # North (Quebec)
    assert is_in_vermont_model_box(42.499, -73.0) is False  # South (Mass)
    assert is_in_vermont_model_box(44.0, -70.999) is False  # East (Maine/NH)
    assert is_in_vermont_model_box(44.0, -74.501) is False  # West (Adirondacks)


def test_required_hgt_tiles_integer_box_six_tiles():
    """Verify 2x3 degree integer-aligned box (lat 43-45, lon -74 to -71) returns exactly 6 tiles."""
    box = RegionalBounds(
        name="Integer_2x3_Box",
        min_lat=43.0,
        max_lat=45.0,
        min_lon=-74.0,
        max_lon=-71.0,
    )

    expected_tiles = [
        "N43W072.hgt",
        "N43W073.hgt",
        "N43W074.hgt",
        "N44W072.hgt",
        "N44W073.hgt",
        "N44W074.hgt",
    ]

    # Test standalone function
    tiles = get_required_hgt_tiles_for_bounds(box)
    assert len(tiles) == 6
    assert tiles == expected_tiles

    # Test SRTMHgtReader instance method
    reader = SRTMHgtReader()
    try:
        assert reader.get_required_hgt_tiles_for_bounds(box) == expected_tiles
    finally:
        reader.close()

    # Test class-level staticmethod
    assert SRTMHgtReader.get_required_hgt_tiles_for_bounds(box) == expected_tiles
    assert HGTElevationTileReader.get_required_hgt_tiles_for_bounds(box) == expected_tiles


def test_required_hgt_tiles_fractional_subregions():
    """Verify tile calculations for fractional county bounds and single point bounds."""
    # Chittenden county fractional box: lat 44.25-44.60, lon -73.35 to -72.80
    chittenden = RegionalBounds(
        name="Chittenden_County",
        min_lat=44.25,
        max_lat=44.60,
        min_lon=-73.35,
        max_lon=-72.80,
    )
    tiles = get_required_hgt_tiles_for_bounds(chittenden)
    assert tiles == ["N44W073.hgt", "N44W074.hgt"]

    # Local small bounds around Burlington
    burlington_bounds = RegionalBounds(
        name="Burlington_City",
        min_lat=44.47,
        max_lat=44.48,
        min_lon=-73.22,
        max_lon=-73.20,
    )
    point_tiles = get_required_hgt_tiles_for_bounds(burlington_bounds)
    assert point_tiles == ["N44W074.hgt"]

    # Southern / Eastern hemisphere region
    australia_bounds = RegionalBounds(
        name="Sydney_Basin",
        min_lat=-34.0,
        max_lat=-33.0,
        min_lon=150.0,
        max_lon=151.0,
    )
    aus_tiles = get_required_hgt_tiles_for_bounds(australia_bounds)
    assert aus_tiles == ["S34E150.hgt"]


def test_terrain_provenance_tagging_inside_vermont_box():
    """Verify terrain_source is 'synthetic' when sampling inside the Vermont precision domain."""
    adapter = USGS3DEPElevationAdapter(offline_mode=True)
    try:
        # Sample well within domain (Mount Mansfield area)
        res = adapter.get_elevation_at(44.5437, -72.8143)
        assert res.ok is True
        assert adapter.last_terrain_source == "synthetic"
        assert res.terrain_source == "synthetic"
        assert res.details == {"terrain_source": "synthetic"}

        # Coordinate contract query
        coord = Coordinate(lat=44.5, lon=-73.2, elevation_m=0.0)
        res_coord = adapter.get_elevation(coord)
        assert res_coord.ok is True
        assert res_coord.terrain_source == "synthetic"
        assert res_coord.details == {"terrain_source": "synthetic"}

        # Exactly on bounding edges
        res_edge = adapter.get_elevation_at(42.5, -74.5)
        assert res_edge.ok is True
        assert res_edge.terrain_source == "synthetic"
    finally:
        adapter.close()


def test_terrain_provenance_tagging_outside_vermont_box():
    """Verify terrain_source is 'synthetic_out_of_domain' when sampling outside the Vermont box."""
    adapter = USGS3DEPElevationAdapter(offline_mode=True)
    try:
        # North of VT box (Montreal / Quebec: 46.0, -73.0)
        res_north = adapter.get_elevation_at(46.0, -73.0)
        assert res_north.ok is True
        assert adapter.last_terrain_source == "synthetic_out_of_domain"
        assert res_north.terrain_source == "synthetic_out_of_domain"
        assert res_north.details == {"terrain_source": "synthetic_out_of_domain"}

        # South of VT box (Connecticut / Mass: 41.5, -73.0)
        res_south = adapter.get_elevation_at(41.5, -73.0)
        assert res_south.ok is True
        assert adapter.last_terrain_source == "synthetic_out_of_domain"
        assert res_south.terrain_source == "synthetic_out_of_domain"
        assert res_south.details == {"terrain_source": "synthetic_out_of_domain"}

        # East of VT box (Maine: 44.0, -70.0)
        res_east = adapter.get_elevation_at(44.0, -70.0)
        assert res_east.ok is True
        assert adapter.last_terrain_source == "synthetic_out_of_domain"
        assert res_east.terrain_source == "synthetic_out_of_domain"
        assert res_east.details == {"terrain_source": "synthetic_out_of_domain"}

        # West of VT box (Central NY / Adirondacks: 44.0, -75.5)
        res_west = adapter.get_elevation_at(44.0, -75.5)
        assert res_west.ok is True
        assert adapter.last_terrain_source == "synthetic_out_of_domain"
        assert res_west.terrain_source == "synthetic_out_of_domain"
        assert res_west.details == {"terrain_source": "synthetic_out_of_domain"}

        # Coordinate contract query outside box
        coord = Coordinate(lat=46.0, lon=-73.0, elevation_m=0.0)
        res_coord = adapter.get_elevation(coord)
        assert res_coord.ok is True
        assert res_coord.terrain_source == "synthetic_out_of_domain"
        assert res_coord.details == {"terrain_source": "synthetic_out_of_domain"}
    finally:
        adapter.close()


def test_zero_numeric_drift_and_deduplication():
    """Verify zero numerical drift between adapter and composite_viewshed elevation functions."""
    test_coordinates = [
        (44.5, -73.2),
        (44.5437, -72.8143),
        (44.25, -73.35),
        (42.5, -74.5),
        (45.5, -71.0),
        (46.0, -73.0),
        (43.0, -70.0),
    ]

    adapter = USGS3DEPElevationAdapter(offline_mode=True)
    try:
        for lat, lon in test_coordinates:
            val_adapter_fn = adapter_elevation_fn(lat, lon)
            val_viewshed_fn = viewshed_elevation_fn(lat, lon)
            res_adapter = adapter.get_elevation_at(lat, lon)

            # Mathematical equivalence
            assert val_adapter_fn == val_viewshed_fn
            assert res_adapter.ok is True
            assert math.isclose(res_adapter.value, val_adapter_fn, abs_tol=1e-9)
    finally:
        adapter.close()
