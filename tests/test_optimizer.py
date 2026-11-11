"""Unit tests for meshscout.core.optimizer Greedy Weighted Minimum Set-Cover Repeater Optimizer."""

from __future__ import annotations

import time
from typing import List, Sequence
import pytest

from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    SiteCandidate,
    SiteType,
)
from meshscout.core.optimizer import (
    estimate_site_deployment_cost,
    solve_minimum_set_cover,
)
from meshscout.core.viewshed import TargetCoveragePoint, ViewshedResult


def _build_viewshed(
    site_id: str,
    name: str,
    covered_ids: Sequence[str],
    all_target_ids: Sequence[str],
    elevation_m: float = 500.0,
    access: AccessDifficulty = AccessDifficulty.MODERATE,
    has_grid: bool = False,
) -> ViewshedResult:
    site = SiteCandidate(
        site_id=site_id,
        name=name,
        location=Coordinate(lat=44.50, lon=-72.90, elevation_m=elevation_m),
        site_type=SiteType.COMMUNICATIONS_TOWER if has_grid else SiteType.MOUNTAIN_PEAK,
        mast_height_m=8.0,
        has_grid_power=has_grid,
        access_difficulty=access,
    )
    covered_set = set(covered_ids)
    shadowed = [tid for tid in all_target_ids if tid not in covered_set]
    cov_frac = len(covered_set) / len(all_target_ids) if all_target_ids else 0.0

    target_results = [
        TargetCoveragePoint(
            target_id=tid,
            coordinate=Coordinate(lat=44.48, lon=-73.05, elevation_m=110.0),
            distance_km=12.0,
            has_line_of_sight=(tid in covered_set),
            fresnel_clearance_ratio=1.1 if (tid in covered_set) else -0.4,
            estimated_rx_dbm=-105.0 if (tid in covered_set) else -142.0,
            link_margin_db=30.0 if (tid in covered_set) else -7.0,
            is_covered=(tid in covered_set),
        )
        for tid in all_target_ids
    ]

    return ViewshedResult(
        repeater=site,
        total_targets=len(all_target_ids),
        covered_targets=len(covered_set),
        coverage_fraction=round(cov_frac, 4),
        weighted_coverage_fraction=round(cov_frac, 4),
        target_results=target_results,
        covered_target_ids=list(covered_ids),
        shadowed_target_ids=shadowed,
    )


def test_benchmark_25_candidates_100_targets_under_500ms() -> None:
    """Verify 25-candidate, 100-target valley set-cover solves in <500ms and reaches >=90% coverage."""
    all_targets = [f"T-{i:03d}" for i in range(100)]
    viewsheds: List[ViewshedResult] = []

    # 3 primary high-ridgeline repeaters that together cover 94% of the valley basin:
    # R-00 covers 0..34 (35 targets)
    # R-01 covers 30..64 (35 targets, 30 new -> 65 cumulative)
    # R-02 covers 60..93 (34 targets, 29 new -> 94 cumulative >= 90%)
    viewsheds.append(
        _build_viewshed(
            "VT-PRIMARY-01",
            "Mount Mansfield Ridge",
            [f"T-{i:03d}" for i in range(0, 35)],
            all_targets,
            elevation_m=1339.0,
            access=AccessDifficulty.DRIVE_UP,
            has_grid=True,
        )
    )
    viewsheds.append(
        _build_viewshed(
            "VT-PRIMARY-02",
            "Bolton Valley Crest",
            [f"T-{i:03d}" for i in range(30, 65)],
            all_targets,
            elevation_m=1010.0,
            access=AccessDifficulty.MODERATE,
            has_grid=True,
        )
    )
    viewsheds.append(
        _build_viewshed(
            "VT-PRIMARY-03",
            "Saxon Hill Water Tower",
            [f"T-{i:03d}" for i in range(60, 94)],
            all_targets,
            elevation_m=295.0,
            access=AccessDifficulty.DRIVE_UP,
            has_grid=True,
        )
    )

    # Add 22 smaller overlapping foothills/rooftop repeaters (each covering 8-12 targets)
    for idx in range(22):
        start = (idx * 4) % 90
        subset = [f"T-{i:03d}" for i in range(start, min(100, start + 10))]
        viewsheds.append(
            _build_viewshed(
                f"VT-FOOTHILL-{idx:02d}",
                f"Foothill Candidate {idx:02d}",
                subset,
                all_targets,
                elevation_m=220.0 + idx * 5.0,
                access=AccessDifficulty.HIKE_IN,
                has_grid=False,
            )
        )

    assert len(viewsheds) == 25

    t0 = time.perf_counter()
    res = solve_minimum_set_cover(viewsheds, target_coverage_fraction=0.90)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert res.ok is True
    assert res.value is not None
    assert elapsed_ms < 500.0, f"Optimizer took {elapsed_ms:.2f}ms, exceeding 500ms budget"

    opt = res.value
    assert opt.threshold_met is True
    assert opt.achieved_coverage_fraction >= 0.90
    assert len(opt.selected_sites) == 3
    selected_ids = [s.site_id for s in opt.selected_sites]
    assert set(selected_ids) == {"VT-PRIMARY-01", "VT-PRIMARY-02", "VT-PRIMARY-03"}
    assert selected_ids == ["VT-PRIMARY-01", "VT-PRIMARY-03", "VT-PRIMARY-02"]
    assert opt.total_targets == 100
    assert len(opt.covered_target_ids) == 94
    assert len(opt.uncovered_target_ids) == 6


def test_cost_weighted_tie_breaking_drive_up_vs_helicopter() -> None:
    """Verify optimizer selects lower-cost DRIVE_UP grid site over HELICOPTER off-grid site with equal coverage."""
    all_targets = [f"T-{i:02d}" for i in range(20)]

    heli_site = _build_viewshed(
        "VT-HELI-01",
        "Remote Peak Helicopter Site",
        all_targets[:18],
        all_targets,
        elevation_m=1200.0,
        access=AccessDifficulty.HELICOPTER,
        has_grid=False,
    )
    drive_site = _build_viewshed(
        "VT-DRIVE-01",
        "Accessible Tower Site",
        all_targets[:18],
        all_targets,
        elevation_m=600.0,
        access=AccessDifficulty.DRIVE_UP,
        has_grid=True,
    )

    cost_heli = estimate_site_deployment_cost(heli_site.repeater)
    cost_drive = estimate_site_deployment_cost(drive_site.repeater)
    assert cost_drive < cost_heli

    res = solve_minimum_set_cover([heli_site, drive_site], target_coverage_fraction=0.90)
    assert res.ok is True
    assert res.value is not None
    assert len(res.value.selected_sites) == 1
    assert res.value.selected_sites[0].site_id == "VT-DRIVE-01"
    assert res.value.threshold_met is True


def test_max_repeaters_budget_cap() -> None:
    """Verify max_repeaters stops selection even before target_coverage_fraction is reached."""
    all_targets = [f"T-{i:02d}" for i in range(30)]
    vs1 = _build_viewshed("VT-R1", "Repeater 1", all_targets[0:10], all_targets)
    vs2 = _build_viewshed("VT-R2", "Repeater 2", all_targets[10:20], all_targets)
    vs3 = _build_viewshed("VT-R3", "Repeater 3", all_targets[20:30], all_targets)

    res = solve_minimum_set_cover(
        [vs1, vs2, vs3],
        target_coverage_fraction=0.90,
        max_repeaters=2,
    )
    assert res.ok is True
    assert res.value is not None

    opt = res.value
    assert len(opt.selected_sites) == 2
    assert opt.threshold_met is False
    assert pytest.approx(opt.achieved_coverage_fraction, rel=1e-3) == 20 / 30


def test_unreachable_coverage_threshold_reporting() -> None:
    """Verify threshold_met=False when the union of all candidates covers <90% of targets."""
    all_targets = [f"T-{i:02d}" for i in range(20)]
    # Union covers only 12/20 = 60%
    vs1 = _build_viewshed("VT-R1", "Repeater 1", all_targets[0:8], all_targets)
    vs2 = _build_viewshed("VT-R2", "Repeater 2", all_targets[6:12], all_targets)

    res = solve_minimum_set_cover([vs1, vs2], target_coverage_fraction=0.90)
    assert res.ok is True
    assert res.value is not None

    opt = res.value
    assert opt.threshold_met is False
    assert opt.achieved_coverage_fraction == 0.60
    assert len(opt.covered_target_ids) == 12
    assert len(opt.uncovered_target_ids) == 8


def test_invalid_and_empty_inputs() -> None:
    """Verify Result.fail is returned on empty candidate list or invalid thresholds."""
    res_empty = solve_minimum_set_cover([])
    assert res_empty.ok is False
    assert res_empty.error is not None
    assert res_empty.error.code == "EMPTY_VIEWSHED_CANDIDATES"

    all_targets = ["T-01", "T-02"]
    vs = _build_viewshed("VT-R1", "Repeater 1", ["T-01"], all_targets)

    res_bad_thresh = solve_minimum_set_cover([vs], target_coverage_fraction=1.5)
    assert res_bad_thresh.ok is False
    assert res_bad_thresh.error is not None
    assert res_bad_thresh.error.code == "INVALID_COVERAGE_THRESHOLD"

    res_bad_max = solve_minimum_set_cover([vs], max_repeaters=0)
    assert res_bad_max.ok is False
    assert res_bad_max.error is not None
    assert res_bad_max.error.code == "INVALID_MAX_REPEATERS"


def test_find_optimal_mesh_route_2hop_bridge() -> None:
    """Verify obstructed valley nodes bridge via high mountain summit repeater in 2 hops."""
    from meshscout.core.optimizer import find_optimal_mesh_route

    # West valley node (Burlington, 61m)
    burlington = SiteCandidate(
        site_id="VT-BURL-01",
        name="Burlington Waterfront",
        location=Coordinate(lat=44.4759, lon=-73.2121, elevation_m=61.0),
        site_type=SiteType.BUILDING_ROOFTOP,
        mast_height_m=8.0,
    )
    # East valley node (Stowe, 220m)
    stowe = SiteCandidate(
        site_id="VT-STOW-01",
        name="Stowe Village",
        location=Coordinate(lat=44.4654, lon=-72.6874, elevation_m=220.0),
        site_type=SiteType.BUILDING_ROOFTOP,
        mast_height_m=8.0,
    )
    # Intermediate summit repeater (Mount Mansfield Summit Ridge, 1339m)
    mansfield = SiteCandidate(
        site_id="VT-PEAK-01",
        name="Mount Mansfield Summit",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=15.0,
    )

    def blocking_ridge_elevation(lat: float, lon: float) -> float:
        # Central Green Mountain ridge blocks direct valley-to-valley line of sight
        if -72.95 < lon < -72.75:
            return 1100.0
        return 100.0

    res = find_optimal_mesh_route(
        origin=burlington,
        destination=stowe,
        candidate_repeaters=[mansfield],
        elevation_fn=blocking_ridge_elevation,
        max_hops=3,
        min_link_margin_db=0.0,
    )
    assert res.ok is True
    assert res.value is not None
    route = res.value
    assert route.route_found is True
    assert route.total_hops == 2
    assert route.intermediate_node_ids == ["VT-PEAK-01"]
    assert len(route.legs) == 2
    assert route.legs[0].source_site_id == "VT-BURL-01"
    assert route.legs[0].target_site_id == "VT-PEAK-01"
    assert route.legs[1].source_site_id == "VT-PEAK-01"
    assert route.legs[1].target_site_id == "VT-STOW-01"
    assert route.bottleneck_margin_db > 0.0
    assert route.hop_limit_exceeded is False
