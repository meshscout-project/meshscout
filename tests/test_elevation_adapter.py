"""Hermetic unit tests for USGS 3DEP Elevation Adapter and offline interpolation."""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
import struct
import time
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from meshscout.adapters.base import (
    BaseRegionalAdapter,
    RateLimitBackoff,
    RateLimitConfig,
)
from meshscout.adapters.elevation import (
    ElevationGrid,
    HGTElevationTileReader,
    HGT_1ARCSEC_SIZE,
    HGT_3ARCSEC_SIZE,
    HGT_VOID_VALUE,
    USGS3DEPElevationAdapter,
    _synthetic_vermont_elevation_fn,
    haversine_distance_km,
)
from meshscout.core.contracts import (
    Coordinate,
    ElevationProfile,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)


@pytest.fixture
def chittenden_bounds() -> RegionalBounds:
    """Fixture defining Chittenden County regional bounding box."""
    return RegionalBounds(
        name="Vermont_Chittenden_County",
        min_lat=44.25,
        max_lat=44.60,
        min_lon=-73.35,
        max_lon=-72.80,
    )


@pytest.fixture
def synthetic_elevation_grid(chittenden_bounds: RegionalBounds) -> ElevationGrid:
    """Fixture creating a synthetic offline elevation grid modeling Mount Mansfield."""
    rows, cols = 200, 200

    def terrain_fn(lat: float, lon: float) -> float:
        # Summit at Mount Mansfield (44.5437, -72.8143), elevation 1339m, base at 100m
        dlat = (lat - 44.5437) / 0.06
        dlon = (lon - -72.8143) / 0.06
        return 100.0 + 1239.0 * math.exp(-(dlat**2 + dlon**2))

    return ElevationGrid.from_fn(chittenden_bounds, rows=rows, cols=cols, fn=terrain_fn)


def test_protocol_conformance(chittenden_bounds: RegionalBounds):
    """Verify USGS3DEPElevationAdapter implements the BaseRegionalAdapter protocol."""
    adapter = USGS3DEPElevationAdapter(bounds=chittenden_bounds, offline_mode=True)
    assert isinstance(adapter, BaseRegionalAdapter)
    assert adapter.adapter_name == "usgs_3dep_elevation"
    assert adapter.bounds == chittenden_bounds
    assert adapter.health_check().ok is True


def test_rate_limiter_backoff_and_retry():
    """Verify rate limiter exponential backoff and retry behavior."""
    cfg = RateLimitConfig(
        min_delay=0.1,
        max_delay=0.2,
        max_retries=3,
        backoff_factor=2.0,
        disabled=True,
    )
    limiter = RateLimitBackoff(config=cfg)

    # In disabled mode, wait() is zero
    assert limiter.wait() == 0.0

    call_count = 0

    def failing_action():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("Transient error")
        return "success"

    retries_recorded = []

    def on_retry(att, exc, delay):
        retries_recorded.append((att, str(exc), delay))

    res = limiter.execute(
        failing_action,
        retryable_exceptions=(ValueError,),
        on_retry=on_retry,
    )

    assert res == "success"
    assert call_count == 3
    assert len(retries_recorded) == 2


def test_rate_limiter_exceeds_max_retries():
    """Verify rate limiter propagates exception when max retries are exceeded."""
    cfg = RateLimitConfig(max_retries=2, disabled=True)
    limiter = RateLimitBackoff(config=cfg)

    def always_fails():
        raise RuntimeError("Persistent network fault")

    with pytest.raises(RuntimeError) as exc_info:
        limiter.execute(always_fails, retryable_exceptions=(RuntimeError,))
    assert "Persistent network fault" in str(exc_info.value)


def test_offline_interpolation_exact_nodes(chittenden_bounds: RegionalBounds):
    """Verify offline interpolation returns exact elevation values at grid vertices."""
    rows, cols = 5, 5
    grid = ElevationGrid.from_fn(
        chittenden_bounds,
        rows=rows,
        cols=cols,
        fn=lambda lat, lon: 500.0 + (lat - 44.25) * 100.0 + (lon + 73.35) * 50.0,
    )

    lat_step = (chittenden_bounds.max_lat - chittenden_bounds.min_lat) / (rows - 1)
    lon_step = (chittenden_bounds.max_lon - chittenden_bounds.min_lon) / (cols - 1)

    for r in range(rows):
        lat = chittenden_bounds.min_lat + r * lat_step
        for c in range(cols):
            lon = chittenden_bounds.min_lon + c * lon_step
            expected = grid.elevations[r][c]
            interpolated = grid.interpolate(lat, lon)
            assert interpolated is not None
            assert math.isclose(interpolated, expected, abs_tol=1e-6)


def test_offline_interpolation_planar_slope_within_half_meter(
    chittenden_bounds: RegionalBounds,
):
    """Verify bilinear interpolation on a tilted planar surface has < 0.001m error (strictly <= 0.5m)."""
    grid = ElevationGrid.from_fn(
        chittenden_bounds,
        rows=10,
        cols=10,
        fn=lambda lat, lon: 200.0 + 80.0 * (lat - 44.25) - 40.0 * (lon + 73.35),
    )

    adapter = USGS3DEPElevationAdapter(
        bounds=chittenden_bounds, offline_grid=grid, offline_mode=True
    )

    # Test several interior arbitrary test coordinates
    test_coords = [
        (44.3333, -73.1234),
        (44.4567, -72.9876),
        (44.2891, -73.2501),
        (44.5789, -72.8543),
    ]

    for lat, lon in test_coords:
        true_elev = 200.0 + 80.0 * (lat - 44.25) - 40.0 * (lon + 73.35)
        res = adapter.get_elevation_at(lat, lon)
        assert res.ok is True
        assert res.value is not None
        diff = abs(res.value - true_elev)
        assert (
            diff <= 0.5
        ), f"Planar interpolation error {diff:.6f}m exceeds 0.5m threshold"
        assert diff < 0.001


def test_offline_interpolation_curved_terrain_within_half_meter(
    chittenden_bounds: RegionalBounds,
    synthetic_elevation_grid: ElevationGrid,
):
    """Verify offline bilinear interpolation on realistic mountainous terrain is within 0.5m."""
    adapter = USGS3DEPElevationAdapter(
        bounds=chittenden_bounds,
        offline_grid=synthetic_elevation_grid,
        offline_mode=True,
    )

    def ground_truth(lat: float, lon: float) -> float:
        dlat = (lat - 44.5437) / 0.06
        dlon = (lon - -72.8143) / 0.06
        return 100.0 + 1239.0 * math.exp(-(dlat**2 + dlon**2))

    # Evaluate 40 points across the domain
    max_error = 0.0
    for i in range(40):
        t = (i + 0.5) / 40.0
        test_lat = chittenden_bounds.min_lat + t * (
            chittenden_bounds.max_lat - chittenden_bounds.min_lat
        )
        test_lon = chittenden_bounds.min_lon + (1.0 - t) * (
            chittenden_bounds.max_lon - chittenden_bounds.min_lon
        )

        true_val = ground_truth(test_lat, test_lon)
        res = adapter.get_elevation_at(test_lat, test_lon)

        assert res.ok is True
        assert res.value is not None
        err = abs(res.value - true_val)
        if err > max_error:
            max_error = err
        assert (
            err <= 0.5
        ), f"Interpolation error {err:.4f}m at ({test_lat}, {test_lon}) exceeded 0.5m"

    # Confirm worst-case error across all samples is strictly within 0.5m
    assert max_error <= 0.5, f"Max error {max_error:.4f}m exceeds 0.5m requirement"


def test_offline_interpolation_out_of_bounds(chittenden_bounds: RegionalBounds):
    """Verify coordinates outside the regional bounds fail with OUT_OF_BOUNDS error."""
    grid = ElevationGrid.from_fn(
        chittenden_bounds, rows=5, cols=5, fn=lambda lat, lon: 100.0
    )
    adapter = USGS3DEPElevationAdapter(
        bounds=chittenden_bounds, offline_grid=grid, offline_mode=True
    )

    outside_north = adapter.get_elevation_at(45.0, -73.0)
    assert outside_north.ok is False
    assert outside_north.error is not None
    assert outside_north.error.code == "OUT_OF_BOUNDS"

    outside_west = adapter.get_elevation_at(44.4, -74.0)
    assert outside_west.ok is False
    assert outside_west.error.code == "OUT_OF_BOUNDS"


def test_elevation_profile_transect(
    chittenden_bounds: RegionalBounds,
    synthetic_elevation_grid: ElevationGrid,
):
    """Verify elevation profile sampling along great circle transect between two sites."""
    adapter = USGS3DEPElevationAdapter(
        bounds=chittenden_bounds,
        offline_grid=synthetic_elevation_grid,
        offline_mode=True,
    )

    site_a = SiteCandidate(
        site_id="VT-PEAK-01",
        name="Mount Mansfield Summit",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=10.0,
    )

    site_b = SiteCandidate(
        site_id="VT-TWR-02",
        name="Essex Junction Mast",
        location=Coordinate(lat=44.4900, lon=-73.1100, elevation_m=105.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=15.0,
    )

    num_samples = 30
    profile_res = adapter.get_elevation_profile(site_a, site_b, num_samples=num_samples)
    assert profile_res.ok is True
    profile = profile_res.value
    assert isinstance(profile, ElevationProfile)
    assert len(profile.points) == num_samples

    expected_dist_km = haversine_distance_km(site_a.location, site_b.location)
    assert math.isclose(profile.distance_km, expected_dist_km, abs_tol=0.01)

    # Verify boundary points
    assert profile.points[0].distance_m == 0.0
    assert math.isclose(profile.points[0].elevation_m, 1339.0, abs_tol=0.5)

    last_pt = profile.points[-1]
    assert math.isclose(last_pt.distance_m, expected_dist_km * 1000.0, abs_tol=0.1)
    assert math.isclose(last_pt.elevation_m, 105.0, abs_tol=0.5)

    # Verify monotonic increasing distance along transect
    for i in range(1, len(profile.points)):
        prev_pt = profile.points[i - 1]
        curr_pt = profile.points[i]
        assert curr_pt.distance_m > prev_pt.distance_m
        assert curr_pt.coordinate.elevation_m == curr_pt.elevation_m


def test_online_epqs_query_mock_success():
    """Verify online USGS EPQS endpoint response parsing with mock HTTP client."""
    rate_cfg = RateLimitConfig(disabled=True)
    adapter = USGS3DEPElevationAdapter(
        rate_limiter=RateLimitBackoff(rate_cfg), offline_mode=False
    )

    mock_resp_data = {
        "location": {"x": -72.8143, "y": 44.5437},
        "elevation": 1339.0,
        "unit": "Meters",
    }
    mock_bytes = json.dumps(mock_resp_data).encode("utf-8")

    mock_response = MagicMock()
    mock_response.read.return_value = mock_bytes
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
        res = adapter.get_elevation_at(44.5437, -72.8143)
        assert res.ok is True
        assert res.value == 1339.0
        assert mock_open.called


def test_online_epqs_fallback_to_offline_grid(
    chittenden_bounds: RegionalBounds,
    synthetic_elevation_grid: ElevationGrid,
):
    """Verify online network failure seamlessly falls back to offline grid interpolation."""
    rate_cfg = RateLimitConfig(max_retries=1, disabled=True)
    adapter = USGS3DEPElevationAdapter(
        bounds=chittenden_bounds,
        offline_grid=synthetic_elevation_grid,
        offline_mode=False,
        rate_limiter=RateLimitBackoff(rate_cfg),
    )

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("DNS resolution failed"),
    ):
        res = adapter.get_elevation_at(44.5437, -72.8143)
        assert res.ok is True
        assert res.value is not None
        # Mount Mansfield peak elevation from synthetic grid
        assert math.isclose(res.value, 1339.0, abs_tol=0.5)


def test_get_elevation_coordinate_contract(chittenden_bounds: RegionalBounds):
    """Verify get_elevation updates a Coordinate contract properly."""
    grid = ElevationGrid.from_fn(
        chittenden_bounds, rows=5, cols=5, fn=lambda lat, lon: 350.0
    )
    adapter = USGS3DEPElevationAdapter(
        bounds=chittenden_bounds, offline_grid=grid, offline_mode=True
    )

    coord_input = Coordinate(lat=44.40, lon=-73.00, elevation_m=0.0)
    res = adapter.get_elevation(coord_input)
    assert res.ok is True
    assert res.value is not None
    assert res.value.lat == 44.40
    assert res.value.lon == -73.00
    assert math.isclose(res.value.elevation_m, 350.0, abs_tol=0.5)


def _create_synthetic_1201_hgt(
    tile_path: Path,
    values: Optional[dict[tuple[int, int], int]] = None,
    default_val: int = 0,
) -> Path:
    """Helper to create a hermetic 1201x1201 (3-arc-second) SRTM HGT tile."""
    # 1201 x 1201 signed 16-bit big-endian integers = 2,884,802 bytes
    data = bytearray(struct.pack(">h", default_val) * (1201 * 1201))
    stride = 1201 * 2
    if values:
        for (r, c), val in values.items():
            offset = r * stride + c * 2
            struct.pack_into(">h", data, offset, val)
    tile_path.write_bytes(data)
    return tile_path


def test_hgt_coordinate_filename_mapping():
    """Verify coordinate bounds mapping to standard SRTM HGT tile filenames."""
    # Northern / Western (e.g. Vermont, USA)
    assert HGTElevationTileReader.get_tile_filename(44.5, -72.8) == "N44W073.hgt"
    assert HGTElevationTileReader.get_tile_filename(44.0, -73.0) == "N44W073.hgt"
    assert HGTElevationTileReader.get_tile_filename(44.25, -73.35) == "N44W074.hgt"

    # Southern / Eastern hemispheres
    assert HGTElevationTileReader.get_tile_filename(-12.34, 15.67) == "S13E015.hgt"
    assert HGTElevationTileReader.get_tile_filename(-33.86, 151.21) == "S34E151.hgt"

    # Equator & Prime Meridian edge cases
    assert HGTElevationTileReader.get_tile_filename(0.5, 0.5) == "N00E000.hgt"
    assert HGTElevationTileReader.get_tile_filename(-0.5, -0.5) == "S01W001.hgt"
    assert HGTElevationTileReader.get_tile_filename(0.0, 0.0) == "N00E000.hgt"
    assert HGTElevationTileReader.get_tile_filename(-0.0001, -0.0001) == "S01W001.hgt"
    assert HGTElevationTileReader.get_tile_filename(51.5, -0.1) == "N51W001.hgt"


def test_hgt_reader_synthetic_tile_corners_and_center(tmp_path: Path):
    """Verify HGTElevationTileReader on synthetic 1201x1201 tile with known corners and center."""
    tile_file = tmp_path / "N44W073.hgt"
    # Set known posts: NW, NE, SW, SE, and Center (600, 600)
    corner_values = {
        (0, 0): 150,        # NW corner
        (0, 1200): 250,     # NE corner
        (1200, 0): 350,     # SW corner
        (1200, 1200): 450,  # SE corner
        (600, 600): 550,    # Center
    }
    _create_synthetic_1201_hgt(tile_file, values=corner_values, default_val=100)

    reader = HGTElevationTileReader(dem_dir=tmp_path)
    try:
        # Tile existence detection
        assert reader.has_tile(44.5, -72.5) is True
        assert reader.has_tile(45.5, -72.5) is False

        # Center lookup (exact post at row 600, col 600)
        center_elev = reader.get_elevation(44.5, -72.5)
        assert center_elev is not None
        assert math.isclose(center_elev, 550.0, abs_tol=1e-4)

        # SW corner (row 1200, col 0) at (44.0, -73.0)
        sw_elev = reader.get_elevation(44.0, -73.0)
        assert sw_elev is not None
        assert math.isclose(sw_elev, 350.0, abs_tol=1e-4)

        # Boundary checks near corners
        nw_elev = reader.get_elevation(44.999999, -73.0)
        assert nw_elev is not None
        assert math.isclose(nw_elev, 150.0, abs_tol=0.5)

        ne_elev = reader.get_elevation(44.999999, -72.000001)
        assert ne_elev is not None
        assert math.isclose(ne_elev, 250.0, abs_tol=0.5)

        se_elev = reader.get_elevation(44.0, -72.000001)
        assert se_elev is not None
        assert math.isclose(se_elev, 450.0, abs_tol=0.5)
    finally:
        reader.close()


def test_hgt_reader_bilinear_interpolation_accuracy(tmp_path: Path):
    """Verify bilinear interpolation between 4 bounding posts matches exact theoretical values."""
    tile_file = tmp_path / "N44W073.hgt"
    # Four bounding posts around (600, 600)
    grid_posts = {
        (600, 600): 100,  # r0, c0
        (600, 601): 200,  # r0, c1
        (601, 600): 300,  # r1, c0
        (601, 601): 400,  # r1, c1
    }
    _create_synthetic_1201_hgt(tile_file, values=grid_posts, default_val=0)

    reader = HGTElevationTileReader(dem_dir=tmp_path)
    try:
        # Sample at u = 0.25 (row 600.25), v = 0.50 (col 600.50)
        # Expected = (1-0.25)*(1-0.5)*100 + (1-0.25)*0.5*200 + 0.25*(1-0.5)*300 + 0.25*0.5*400
        #          = 0.375*100 + 0.375*200 + 0.125*300 + 0.125*400 = 37.5 + 75.0 + 37.5 + 50.0 = 200.0
        lat_sample1 = 44.0 + (1.0 - (600.25 / 1200.0))
        lon_sample1 = -73.0 + (600.50 / 1200.0)

        val1 = reader.get_elevation(lat_sample1, lon_sample1)
        assert val1 is not None
        assert math.isclose(val1, 200.0, abs_tol=1e-3)

        # Sample at u = 0.50 (row 600.50), v = 0.25 (col 600.25)
        # Expected = 0.5*0.75*100 + 0.5*0.25*200 + 0.5*0.75*300 + 0.5*0.25*400
        #          = 37.5 + 25.0 + 112.5 + 50.0 = 225.0
        lat_sample2 = 44.0 + (1.0 - (600.50 / 1200.0))
        lon_sample2 = -73.0 + (600.25 / 1200.0)

        val2 = reader.get_elevation(lat_sample2, lon_sample2)
        assert val2 is not None
        assert math.isclose(val2, 225.0, abs_tol=1e-3)
    finally:
        reader.close()


def test_hgt_reader_void_value_handling(tmp_path: Path):
    """Verify SRTM void value (-32768) is gracefully handled and filtered during interpolation."""
    tile_file = tmp_path / "N44W073.hgt"
    posts = {
        # Cell 1: 1 valid post, 3 void posts
        (600, 600): 280,
        (600, 601): HGT_VOID_VALUE,
        (601, 600): HGT_VOID_VALUE,
        (601, 601): HGT_VOID_VALUE,

        # Cell 2: 2 valid posts, 2 void posts
        (610, 610): 100,
        (610, 611): 200,
        (611, 610): HGT_VOID_VALUE,
        (611, 611): HGT_VOID_VALUE,

        # Cell 3: All 4 posts void
        (700, 700): HGT_VOID_VALUE,
        (700, 701): HGT_VOID_VALUE,
        (701, 700): HGT_VOID_VALUE,
        (701, 701): HGT_VOID_VALUE,
    }
    _create_synthetic_1201_hgt(tile_file, values=posts, default_val=0)

    reader = HGTElevationTileReader(dem_dir=tmp_path)
    try:
        # Cell 1: midway (u=0.5, v=0.5) -> Only (600, 600) is valid, normalized elevation is 280.0
        lat1 = 44.0 + (1.0 - (600.5 / 1200.0))
        lon1 = -73.0 + (600.5 / 1200.0)
        elev1 = reader.get_elevation(lat1, lon1)
        assert elev1 is not None
        assert math.isclose(elev1, 280.0, abs_tol=1e-3)

        # Cell 2: midway (u=0.5, v=0.5) -> Valid posts are 100 and 200 with equal weights -> 150.0
        lat2 = 44.0 + (1.0 - (610.5 / 1200.0))
        lon2 = -73.0 + (610.5 / 1200.0)
        elev2 = reader.get_elevation(lat2, lon2)
        assert elev2 is not None
        assert math.isclose(elev2, 150.0, abs_tol=1e-3)

        # Cell 3: All posts void -> returns None
        lat3 = 44.0 + (1.0 - (700.5 / 1200.0))
        lon3 = -73.0 + (700.5 / 1200.0)
        elev3 = reader.get_elevation(lat3, lon3)
        assert elev3 is None
    finally:
        reader.close()


def test_usgs_adapter_dem_source_integration(tmp_path: Path):
    """Verify USGS3DEPElevationAdapter prioritizes DEM tile when present and falls back to synthetic when absent."""
    tile_file = tmp_path / "N44W073.hgt"
    # Create N44W073 tile with known center elevation 725m
    _create_synthetic_1201_hgt(tile_file, values={(600, 600): 725}, default_val=100)

    adapter = USGS3DEPElevationAdapter(dem_dir=tmp_path, offline_mode=True)
    try:
        # Coordinate inside N44W073 -> resolved from local DEM tile
        res_dem = adapter.get_elevation_at(44.5, -72.5)
        assert res_dem.ok is True
        assert math.isclose(res_dem.value, 725.0, abs_tol=1e-3)
        assert adapter.last_terrain_source == "dem"
        assert res_dem.details["terrain_source"] == "dem"

        # Coordinate inside N44W074 (tile absent) -> resolved from synthetic fallback
        res_synthetic = adapter.get_elevation_at(44.5, -73.2)
        assert res_synthetic.ok is True
        assert adapter.last_terrain_source == "synthetic"
        assert res_synthetic.details["terrain_source"] == "synthetic"
        expected_elev = _synthetic_vermont_elevation_fn(44.5, -73.2)
        assert math.isclose(res_synthetic.value, expected_elev, abs_tol=1e-3)

        # Coordinate contract query
        coord = Coordinate(lat=44.5, lon=-72.5, elevation_m=0.0)
        res_coord = adapter.get_elevation(coord)
        assert res_coord.ok is True
        assert math.isclose(res_coord.value.elevation_m, 725.0, abs_tol=1e-3)
        assert res_coord.details["terrain_source"] == "dem"
    finally:
        adapter.close()


def test_dem_point_lookup_benchmark(tmp_path: Path):
    """Benchmark HGTElevationTileReader point lookup speed (< 0.1ms per query)."""
    tile_file = tmp_path / "N44W073.hgt"
    _create_synthetic_1201_hgt(tile_file, values={(600, 600): 500}, default_val=200)

    reader = HGTElevationTileReader(dem_dir=tmp_path)
    try:
        # Warm-up phase
        for i in range(50):
            _ = reader.get_elevation(44.5, -72.5)

        num_queries = 10000
        t0 = time.perf_counter()
        for i in range(num_queries):
            test_lat = 44.1 + (i % 800) * 0.001
            test_lon = -72.9 + ((i * 7) % 800) * 0.001
            _ = reader.get_elevation(test_lat, test_lon)
        t1 = time.perf_counter()

        elapsed = t1 - t0
        avg_sec_per_query = elapsed / num_queries
        avg_ms_per_query = avg_sec_per_query * 1000.0

        # Assert speed threshold < 0.1ms (100 microseconds)
        assert (
            avg_sec_per_query < 0.0001
        ), f"Point lookup {avg_ms_per_query:.4f}ms exceeds 0.1ms threshold"
    finally:
        reader.close()
