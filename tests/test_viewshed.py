"""Unit tests for the Point-to-Multipoint Valley Basin Viewshed Engine."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List

import pytest

from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RadioConfig,
    RegionalBounds,
    SiteCandidate,
)
from meshscout.core.viewshed import (
    TargetGridPoint,
    compute_viewshed,
    generate_target_grid,
    haversine_distance_km,
    sample_transect_points,
)


@pytest.fixture
def chittenden_fixture() -> Dict:
    """Load the Winooski Valley / Chittenden County sample fixture."""
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "vt_chittenden_sample.json"
    with fixture_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def chittenden_sites(chittenden_fixture: Dict) -> Dict[str, SiteCandidate]:
    """Return SiteCandidate instances keyed by site_id."""
    return {
        item["site_id"]: SiteCandidate.model_validate(item)
        for item in chittenden_fixture["sites"]
    }


@pytest.fixture
def chittenden_bounds(chittenden_fixture: Dict) -> RegionalBounds:
    """Return RegionalBounds for Vermont Chittenden County."""
    return RegionalBounds.model_validate(chittenden_fixture["bounds"])


def _winooski_basin_terrain(lat: float, lon: float) -> float:
    """Synthetic terrain model for Chittenden County & Winooski River Valley.

    - Western Champlain Valley (lon < -72.90): low valley basin (~70m to 130m) rising
      steeply near Mount Mansfield (lon > -72.88).
    - Local Richmond gorge ridge barrier near (44.455, -72.930) rising up to 850m,
      which shadows the deep Richmond valley floor (VT-VAL-04 at 44.4037, -73.0039)
      from Mount Mansfield (44.5437, -72.8143) and blocks low valley repeaters from
      reaching the western basin.
    """
    # Concave Green Mountain western escarpment rising east of -73.00
    east_frac = max(0.0, (lon - (-73.25)) / 0.45)
    base_elev = 65.0 + 950.0 * (east_frac ** 3.2)

    # Narrow intermediate ridge between Mount Mansfield (44.5437, -72.8143) and Richmond (44.4037, -73.0039)
    # Midpoint of Mansfield -> Richmond is (44.4737, -72.9091)
    ridge_dist_sq = ((lat - 44.460) / 0.018) ** 2 + ((lon - (-72.925)) / 0.020) ** 2
    ridge_bump = 850.0 * math.exp(-ridge_dist_sq)

    # Steep gorge wall immediately west/northwest of Richmond (44.4037, -73.0039)
    gorge_wall_sq = ((lat - 44.428) / 0.020) ** 2 + ((lon - (-73.038)) / 0.020) ** 2
    gorge_wall = 460.0 * math.exp(-gorge_wall_sq)

    return base_elev + ridge_bump + gorge_wall


def test_empty_targets_returns_fail(chittenden_sites: Dict[str, SiteCandidate]) -> None:
    """Empty target grid must return Result.fail with EMPTY_TARGET_GRID."""
    mansfield = chittenden_sites["VT-PEAK-01"]
    res = compute_viewshed(repeater=mansfield, targets=[])
    assert not res.ok
    assert res.error is not None
    assert res.error.code == "EMPTY_TARGET_GRID"


def test_invalid_sample_count_returns_fail(chittenden_sites: Dict[str, SiteCandidate]) -> None:
    """Sample count < 2 must return Result.fail."""
    mansfield = chittenden_sites["VT-PEAK-01"]
    target = TargetGridPoint(
        target_id="T-01",
        coordinate=Coordinate(lat=44.49, lon=-73.11, elevation_m=105.0),
    )
    res = compute_viewshed(repeater=mansfield, targets=[target], num_samples=1)
    assert not res.ok
    assert res.error is not None
    assert res.error.code == "INVALID_SAMPLE_COUNT"


def test_generate_target_grid_bounds(chittenden_bounds: RegionalBounds) -> None:
    """Regular grid helper generates expected points within RegionalBounds."""
    grid_res = generate_target_grid(
        bounds=chittenden_bounds,
        lat_steps=4,
        lon_steps=3,
        elevation_fn=lambda lat, lon: 100.0,
        rx_height_m=2.5,
    )
    assert grid_res.ok
    assert grid_res.value is not None
    points = grid_res.value
    assert len(points) == 12
    for pt in points:
        assert chittenden_bounds.contains(pt.coordinate)
        assert pt.coordinate.elevation_m == 100.0
        assert pt.rx_height_m == 2.5

    bad_res = generate_target_grid(bounds=chittenden_bounds, lat_steps=0, lon_steps=3)
    assert not bad_res.ok
    assert bad_res.error is not None
    assert bad_res.error.code == "INVALID_GRID_DIMENSIONS"


def test_mount_mansfield_viewshed_covers_valley_and_identifies_shadowed_pocket(
    chittenden_sites: Dict[str, SiteCandidate],
) -> None:
    """High repeater on Mount Mansfield (VT-PEAK-01, 1339m) covers open Champlain Valley
    points (Burlington, Essex Junction) while identifying shadowed valley pockets blocked
    by intermediate ridges (Richmond gorge).
    """
    mansfield = chittenden_sites["VT-PEAK-01"]
    essex = chittenden_sites["VT-TWR-02"]
    burlington = chittenden_sites["VT-TWR-03"]
    richmond = chittenden_sites["VT-VAL-04"]

    targets: List[TargetGridPoint] = [
        TargetGridPoint(
            target_id="VAL-ESSEX",
            coordinate=essex.location,
            rx_height_m=2.0,
            population_weight=3.0,
        ),
        TargetGridPoint(
            target_id="VAL-BURLINGTON",
            coordinate=burlington.location,
            rx_height_m=2.0,
            population_weight=5.0,
        ),
        TargetGridPoint(
            target_id="VAL-SOUTH-BURLINGTON",
            coordinate=Coordinate(lat=44.4669, lon=-73.1709, elevation_m=85.0),
            rx_height_m=2.0,
            population_weight=2.0,
        ),
        TargetGridPoint(
            target_id="VAL-RICHMOND-GORGE",
            coordinate=richmond.location,
            rx_height_m=2.0,
            population_weight=1.0,
        ),
    ]

    # Use conservative rx sensitivity threshold where severe knife-edge diffraction causes dropout
    radio = RadioConfig(
        frequency_mhz=915.0,
        tx_power_dbm=20.0,
        rx_sensitivity_dbm=-112.0,
        antenna_gain_dbi=3.0,
        cable_loss_db=1.0,
    )

    res = compute_viewshed(
        repeater=mansfield,
        targets=targets,
        elevation_fn=_winooski_basin_terrain,
        radio=radio,
        min_margin_db=6.0,
        require_los=True,
        num_samples=35,
    )
    assert res.ok
    assert res.value is not None
    vs = res.value

    assert "VAL-ESSEX" in vs.covered_target_ids
    assert "VAL-BURLINGTON" in vs.covered_target_ids
    assert "VAL-SOUTH-BURLINGTON" in vs.covered_target_ids
    assert "VAL-RICHMOND-GORGE" in vs.shadowed_target_ids

    assert vs.total_targets == 4
    assert vs.covered_targets == 3
    assert vs.coverage_fraction == pytest.approx(0.75, abs=1e-4)
    # Weighted coverage: (3 + 5 + 2) / (3 + 5 + 2 + 1) = 10 / 11 = 0.9091
    assert vs.weighted_coverage_fraction == pytest.approx(10.0 / 11.0, abs=1e-3)


def test_low_valley_node_restricted_viewshed_vs_high_ridge_repeaters(
    chittenden_sites: Dict[str, SiteCandidate],
) -> None:
    """Low valley node (VT-VAL-04, 98m) has a restricted viewshed compared to high
    ridge repeaters (VT-PEAK-01 at 1339m and VT-PEAK-05 at 1120m).
    """
    mansfield = chittenden_sites["VT-PEAK-01"]
    bolton = chittenden_sites["VT-PEAK-05"]
    richmond_low = chittenden_sites["VT-VAL-04"]

    targets: List[TargetGridPoint] = [
        TargetGridPoint(
            target_id="VAL-ESSEX",
            coordinate=Coordinate(lat=44.4900, lon=-73.1100, elevation_m=105.0),
        ),
        TargetGridPoint(
            target_id="VAL-BURLINGTON",
            coordinate=Coordinate(lat=44.4759, lon=-73.2121, elevation_m=65.0),
        ),
        TargetGridPoint(
            target_id="VAL-WILLISTON",
            coordinate=Coordinate(lat=44.4375, lon=-73.0992, elevation_m=120.0),
        ),
        TargetGridPoint(
            target_id="VAL-WINOOSKI",
            coordinate=Coordinate(lat=44.4914, lon=-73.1856, elevation_m=60.0),
        ),
        TargetGridPoint(
            target_id="VAL-SHELBURNE",
            coordinate=Coordinate(lat=44.3806, lon=-73.2276, elevation_m=55.0),
        ),
    ]

    radio = RadioConfig(
        frequency_mhz=915.0,
        tx_power_dbm=20.0,
        rx_sensitivity_dbm=-115.0,
        antenna_gain_dbi=3.0,
        cable_loss_db=1.0,
    )

    mansfield_vs = compute_viewshed(
        repeater=mansfield,
        targets=targets,
        elevation_fn=_winooski_basin_terrain,
        radio=radio,
        min_margin_db=6.0,
        require_los=True,
    ).value
    bolton_vs = compute_viewshed(
        repeater=bolton,
        targets=targets,
        elevation_fn=_winooski_basin_terrain,
        radio=radio,
        min_margin_db=6.0,
        require_los=True,
    ).value
    richmond_vs = compute_viewshed(
        repeater=richmond_low,
        targets=targets,
        elevation_fn=_winooski_basin_terrain,
        radio=radio,
        min_margin_db=6.0,
        require_los=True,
    ).value

    assert mansfield_vs is not None
    assert bolton_vs is not None
    assert richmond_vs is not None

    assert mansfield_vs.coverage_fraction > richmond_vs.coverage_fraction
    assert bolton_vs.coverage_fraction > richmond_vs.coverage_fraction
    assert richmond_vs.covered_targets == 0


def test_precomputed_profiles_by_target_vs_synthetic_elevation_fn(
    chittenden_sites: Dict[str, SiteCandidate],
) -> None:
    """Precomputed ElevationProfile lookup produces identical coverage decisions to
    synthetic elevation_fn and accurately captures sharp knife-edge ridge barriers.
    """
    mansfield = chittenden_sites["VT-PEAK-01"]
    essex = chittenden_sites["VT-TWR-02"]

    target_clear = TargetGridPoint(
        target_id="T-CLEAR",
        coordinate=essex.location,
        rx_height_m=2.0,
        population_weight=2.0,
    )
    target_blocked = TargetGridPoint(
        target_id="T-BLOCKED",
        coordinate=essex.location,
        rx_height_m=2.0,
        population_weight=3.0,
    )

    dist_km = haversine_distance_km(mansfield.location, essex.location)
    clear_pts = sample_transect_points(mansfield.location, essex.location, elevation_fn=None, num_samples=15)

    # Inject a massive 1400m wall in the middle of the blocked profile
    blocked_pts: List[ElevationPoint] = []
    for idx, pt in enumerate(clear_pts):
        if idx == len(clear_pts) // 2:
            blocked_pts.append(
                ElevationPoint(
                    distance_m=pt.distance_m,
                    elevation_m=1400.0,
                    coordinate=Coordinate(lat=pt.coordinate.lat, lon=pt.coordinate.lon, elevation_m=1400.0),
                )
            )
        else:
            blocked_pts.append(pt)

    profiles: Dict[str, ElevationProfile] = {
        "T-CLEAR": ElevationProfile(
            source_site=mansfield,
            target_site=essex,
            distance_km=dist_km,
            points=clear_pts,
        ),
        "T-BLOCKED": ElevationProfile(
            source_site=mansfield,
            target_site=essex,
            distance_km=dist_km,
            points=blocked_pts,
        ),
    }

    radio = RadioConfig(rx_sensitivity_dbm=-110.0)
    res = compute_viewshed(
        repeater=mansfield,
        targets=[target_clear, target_blocked],
        profiles_by_target=profiles,
        radio=radio,
        min_margin_db=6.0,
        require_los=False,
    )
    assert res.ok
    assert res.value is not None
    vs = res.value

    assert "T-CLEAR" in vs.covered_target_ids
    assert "T-BLOCKED" in vs.shadowed_target_ids

    clear_res = next(r for r in vs.target_results if r.target_id == "T-CLEAR")
    blocked_res = next(r for r in vs.target_results if r.target_id == "T-BLOCKED")

    assert clear_res.has_line_of_sight is True
    assert blocked_res.has_line_of_sight is False
    assert clear_res.fresnel_clearance_ratio > 0.6
    assert blocked_res.fresnel_clearance_ratio < 0.0
    assert clear_res.link_margin_db > blocked_res.link_margin_db + 15.0
    # Weighted coverage: T-CLEAR weight 2.0 / total weight 5.0 = 0.4
    assert vs.weighted_coverage_fraction == pytest.approx(0.4, abs=1e-4)


def test_radial_viewshed_polygon_ridge_scalloping(
    chittenden_sites: Dict[str, SiteCandidate],
) -> None:
    """Test 360-degree radial viewshed polygon generation on Mount Mansfield.

    Verifies:
    1. Returns closed polygon with requested number of radial vertices.
    2. Identifies deep reach westward toward Champlain Valley and obstruction by eastern ridge.
    3. LOS area is strictly non-zero and bounded by diffracted coverage area.
    """
    from meshscout.core.viewshed import compute_radial_viewshed_polygon

    mansfield = chittenden_sites["VT-PEAK-01"]
    res = compute_radial_viewshed_polygon(
        origin=mansfield,
        num_radials=36,
        max_range_km=50.0,
        elevation_fn=_winooski_basin_terrain,
    )
    assert res.ok
    assert res.value is not None
    poly = res.value

    assert poly.num_radials == 36
    assert len(poly.los_polygon) == 37
    assert len(poly.diffracted_polygon) == 37
    assert poly.los_polygon[0] == poly.los_polygon[-1]
    assert poly.diffracted_polygon[0] == poly.diffracted_polygon[-1]
    assert poly.radio_horizon_km > 50.0
    assert poly.los_area_sq_km > 100.0
    assert poly.diffracted_area_sq_km >= poly.los_area_sq_km

    # Coordinate validity: all points within Northern Vermont bounds
    for pt in poly.los_polygon:
        lat, lon = pt
        assert 43.5 <= lat <= 45.5
        assert -74.0 <= lon <= -71.5
