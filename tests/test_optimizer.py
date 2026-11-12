"""Unit tests for meshscout.core.optimizer Greedy Weighted Minimum Set-Cover Repeater Optimizer."""

from __future__ import annotations

import time
from typing import List, Sequence
import pytest

from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    ReachabilityState,
    SiteCandidate,
    SiteType,
)
from meshscout.core.optimizer import (
    estimate_site_deployment_cost,
    find_optimal_mesh_route,
    solve_minimum_set_cover,
)
from meshscout.core.presets import (
    CLIENT_ENVIRONMENT_PROFILES,
    build_radio_config,
    resolve_site_radio_profile,
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
    for leg in route.legs:
        assert leg.forward_margin_db is None
        assert leg.reverse_margin_db is None
        assert leg.reachability_state is None


def test_find_optimal_mesh_route_client_origin_vehicle_cabin_3hop() -> None:
    """Verify SENSECAP_T1000E + VEHICLE_CABIN client routes across 3-hop backhaul without leaking cabin loss to repeater backhaul."""
    origin = SiteCandidate(
        site_id="VT-CLIENT-CABIN",
        name="Mobile Vehicle Tracker (Burlington)",
        location=Coordinate(lat=44.4000, lon=-73.2500, elevation_m=65.0),
        site_type=SiteType.CUSTOM,
        mast_height_m=1.5,
    )
    rep1 = SiteCandidate(
        site_id="VT-WEST-RELAY",
        name="West Foothill Solar Relay",
        location=Coordinate(lat=44.5200, lon=-73.1200, elevation_m=500.0),
        site_type=SiteType.FIRE_LOOKOUT,
        mast_height_m=10.0,
    )
    rep2 = SiteCandidate(
        site_id="VT-EAST-RELAY",
        name="East Ridge Solar Relay",
        location=Coordinate(lat=44.5200, lon=-72.9000, elevation_m=520.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=12.0,
    )
    destination = SiteCandidate(
        site_id="VT-MONTPELIER-GW",
        name="Montpelier Civic Gateway",
        location=Coordinate(lat=44.4000, lon=-72.7600, elevation_m=160.0),
        site_type=SiteType.BUILDING_ROOFTOP,
        mast_height_m=10.0,
    )

    def two_basin_terrain(lat: float, lon: float) -> float:
        # Central massif blocks direct origin->dest, origin->rep2, and rep1->dest,
        # while west flank (origin->rep1), north crest (rep1->rep2), and east flank (rep2->dest) are clear.
        if lat < 44.5050 and -73.1100 < lon < -72.9100:
            return 2500.0
        return 90.0

    t1000e_radio = build_radio_config("SENSECAP_T1000E", "MESHTASTIC_LONGFAST", "SUMMER_LEAF_ON").value
    solar_radio = build_radio_config("RAK4631_SOLAR", "MESHTASTIC_LONGFAST", "SUMMER_LEAF_ON").value
    assert t1000e_radio is not None and solar_radio is not None
    cabin_loss_db = CLIENT_ENVIRONMENT_PROFILES["VEHICLE_CABIN"].clutter_loss_db

    res_cabin = find_optimal_mesh_route(
        origin=origin,
        destination=destination,
        candidate_repeaters=[rep1, rep2],
        radio=solar_radio,
        elevation_fn=two_basin_terrain,
        max_hops=3,
        min_link_margin_db=3.0,
        origin_client_radio=t1000e_radio,
        client_env_loss_db=cabin_loss_db,
    )
    assert res_cabin.ok is True
    assert res_cabin.value is not None
    route = res_cabin.value
    assert route.route_found is True
    assert route.total_hops == 3
    assert route.intermediate_node_ids == ["VT-WEST-RELAY", "VT-EAST-RELAY"]
    assert len(route.legs) == 3

    for leg in route.legs:
        assert leg.forward_margin_db is not None
        assert leg.reverse_margin_db is not None
        assert leg.reachability_state == ReachabilityState.TWO_WAY
        assert leg.link_margin_db == round(min(leg.forward_margin_db, leg.reverse_margin_db), 1)
        assert min(leg.forward_margin_db, leg.reverse_margin_db) >= 3.0

    # Re-run with client_env_loss_db=0.0 to prove VEHICLE_CABIN (6.0 dB) applies ONLY to leg 0 (client leg)
    # and NOT to leg 1 (pure repeater-to-repeater backhaul) or leg 2 (repeater-to-fixed-gateway)!
    res_outdoor = find_optimal_mesh_route(
        origin=origin,
        destination=destination,
        candidate_repeaters=[rep1, rep2],
        radio=solar_radio,
        elevation_fn=two_basin_terrain,
        max_hops=3,
        min_link_margin_db=3.0,
        origin_client_radio=t1000e_radio,
        client_env_loss_db=0.0,
    )
    assert res_outdoor.ok is True and res_outdoor.value is not None
    outdoor_route = res_outdoor.value
    assert outdoor_route.total_hops == 3

    # Leg 0 (origin -> rep1) loses exactly 6.0 dB in both directions inside vehicle cabin:
    assert outdoor_route.legs[0].forward_margin_db - route.legs[0].forward_margin_db == pytest.approx(
        cabin_loss_db, abs=0.05
    )
    assert outdoor_route.legs[0].reverse_margin_db - route.legs[0].reverse_margin_db == pytest.approx(
        cabin_loss_db, abs=0.05
    )
    # Leg 1 (rep1 -> rep2) and Leg 2 (rep2 -> fixed destination) suffer 0.0 dB vehicle cabin loss:
    assert route.legs[1].forward_margin_db == outdoor_route.legs[1].forward_margin_db
    assert route.legs[1].reverse_margin_db == outdoor_route.legs[1].reverse_margin_db
    assert route.legs[2].forward_margin_db == outdoor_route.legs[2].forward_margin_db
    assert route.legs[2].reverse_margin_db == outdoor_route.legs[2].reverse_margin_db


def test_find_optimal_mesh_route_rejects_alligator_summit_for_civic_relay() -> None:
    """Verify alligator 28 dBm high-noise commercial tower (downlink passes, client uplink fails) is rejected for civic relay."""
    origin = SiteCandidate(
        site_id="VT-CLIENT-01",
        name="Valley Pocket Tracker in Vehicle",
        location=Coordinate(lat=44.4759, lon=-73.2121, elevation_m=70.0),
        site_type=SiteType.CUSTOM,
        mast_height_m=1.5,
    )
    destination = SiteCandidate(
        site_id="VT-DEST-01",
        name="East Valley Emergency Ops",
        location=Coordinate(lat=44.4759, lon=-72.9621, elevation_m=80.0),
        site_type=SiteType.BUILDING_ROOFTOP,
        mast_height_m=8.0,
    )
    alligator_tower = SiteCandidate(
        site_id="VT-ALLIGATOR-01",
        name="Noisy Commercial Summit Tower",
        location=Coordinate(lat=44.5659, lon=-73.0871, elevation_m=900.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=20.0,
    )
    civic_relay = SiteCandidate(
        site_id="VT-CIVIC-01",
        name="Municipal South Ridge Water Tower",
        location=Coordinate(lat=44.3859, lon=-73.0871, elevation_m=300.0),
        site_type=SiteType.WATER_TOWER,
        mast_height_m=15.0,
    )

    def valley_and_spur_terrain(lat: float, lon: float) -> float:
        # 1. Central valley massif blocks direct origin <-> destination (lat == 44.4759)
        if 44.468 < lat < 44.484 and -73.18 < lon < -73.00:
            return 2500.0
        # 2. Northern foothill spur (~20 dB diffraction) on origin -> alligator_tower:
        #    28 dBm tower downlink passes (+20.6 dB >= 3.0 dB), while 20 dBm cabin client uplink
        #    into 12 dB co-site commercial broadcast noise fails (+0.6 dB < 3.0 dB)!
        if 44.518 < lat < 44.524 and lon < -73.12:
            return 547.0
        # 3. Slightly stronger southern knoll (~22.5 dB diffraction) gives civic_relay slightly higher path loss
        #    than alligator_tower (so naive symmetric routing picks alligator_tower), yet quiet 1 dB noise floor
        #    allows civic_relay to close TWO_WAY (+7.6 dB >= 3.0 dB)!
        if 44.428 < lat < 44.434 and lon < -73.12:
            return 262.5
        return 90.0

    g2_prof = resolve_site_radio_profile(
        site_type=alligator_tower.site_type,
        hardware_id="STATION_G2_BACKBONE",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="SUMMER_FOLIAGE",
        noise_override_db=12.0,
    ).value
    civic_prof = resolve_site_radio_profile(
        site_type=civic_relay.site_type,
        hardware_id="RAK4631_SOLAR",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="SUMMER_FOLIAGE",
    ).value
    t1000e_radio = build_radio_config("SENSECAP_T1000E", "MESHTASTIC_LONGFAST", "SUMMER_LEAF_ON").value
    assert g2_prof is not None and civic_prof is not None and t1000e_radio is not None
    cabin_loss_db = CLIENT_ENVIRONMENT_PROFILES["VEHICLE_CABIN"].clutter_loss_db

    # 1. Legacy symmetric routing (assuming uniform 28 dBm G2 radios everywhere) falls for the alligator summit:
    sym_res = find_optimal_mesh_route(
        origin=origin,
        destination=destination,
        candidate_repeaters=[alligator_tower, civic_relay],
        radio=g2_prof.radio,
        elevation_fn=valley_and_spur_terrain,
        max_hops=3,
        min_link_margin_db=3.0,
    )
    assert sym_res.ok is True and sym_res.value is not None
    assert sym_res.value.route_found is True
    assert sym_res.value.intermediate_node_ids == ["VT-ALLIGATOR-01"]

    # 2. Verify alligator_tower alone fails asymmetric two-way routing (tower downlink passes, client uplink fails):
    alligator_only_res = find_optimal_mesh_route(
        origin=origin,
        destination=destination,
        candidate_repeaters=[alligator_tower],
        radio=civic_prof.radio,
        elevation_fn=valley_and_spur_terrain,
        max_hops=3,
        min_link_margin_db=3.0,
        origin_client_radio=t1000e_radio,
        client_env_loss_db=cabin_loss_db,
        site_profiles={alligator_tower.site_id: g2_prof},
    )
    assert alligator_only_res.ok is True and alligator_only_res.value is not None
    assert alligator_only_res.value.route_found is False

    # Confirm via direct 1-hop route from alligator_tower -> origin that downlink passes >= 3.0 dB while uplink < 3.0 dB:
    probe_res = find_optimal_mesh_route(
        origin=alligator_tower,
        destination=origin,
        candidate_repeaters=[],
        max_hops=1,
        min_link_margin_db=3.0,
        destination_client_radio=t1000e_radio,
        client_env_loss_db=cabin_loss_db,
        site_profiles={alligator_tower.site_id: g2_prof},
        elevation_fn=valley_and_spur_terrain,
    )
    assert probe_res.ok is True and probe_res.value is not None
    assert probe_res.value.route_found is False
    # Bottleneck margin is the failed client uplink (< 3.0 dB), whereas 20 dB stronger tower downlink passes (>= 3.0 dB)
    assert probe_res.value.bottleneck_margin_db < 3.0
    assert probe_res.value.bottleneck_margin_db + 20.0 >= 3.0

    # 3. With both repeaters available, asymmetric routing deterministically rejects alligator_tower and selects civic_relay:
    asym_res = find_optimal_mesh_route(
        origin=origin,
        destination=destination,
        candidate_repeaters=[alligator_tower, civic_relay],
        radio=civic_prof.radio,
        elevation_fn=valley_and_spur_terrain,
        max_hops=3,
        min_link_margin_db=3.0,
        origin_client_radio=t1000e_radio,
        client_env_loss_db=cabin_loss_db,
        site_profiles={
            alligator_tower.site_id: g2_prof,
            civic_relay.site_id: civic_prof,
        },
    )
    assert asym_res.ok is True and asym_res.value is not None
    asym_route = asym_res.value
    assert asym_route.route_found is True
    assert asym_route.total_hops == 2
    assert asym_route.intermediate_node_ids == ["VT-CIVIC-01"]
    assert len(asym_route.legs) == 2
    for leg in asym_route.legs:
        assert leg.reachability_state == ReachabilityState.TWO_WAY
        assert leg.forward_margin_db is not None and leg.reverse_margin_db is not None
        assert min(leg.forward_margin_db, leg.reverse_margin_db) >= 3.0


def test_find_optimal_mesh_route_destination_client_and_negative_loss_guard() -> None:
    """Verify destination_client_radio uses 0 dB noise penalty and negative client_env_loss_db returns Result.fail."""
    hub = SiteCandidate(
        site_id="VT-HUB-01",
        name="Summit Hub Repeater",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=800.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=20.0,
    )
    dest_client = SiteCandidate(
        site_id="VT-HIKER-01",
        name="Trailhead Pocket Tracker",
        location=Coordinate(lat=44.5000, lon=-72.8500, elevation_m=250.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,  # even if mislabeled noisy, client radio overrides noise to 0.0 dB
        mast_height_m=1.5,
    )

    g2_prof = resolve_site_radio_profile(
        site_type=hub.site_type,
        hardware_id="STATION_G2_BACKBONE",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="WINTER_DORMANT",
    ).value
    t1000e_radio = build_radio_config("SENSECAP_T1000E", "MESHTASTIC_LONGFAST", "WINTER_LEAF_OFF").value
    assert g2_prof is not None and t1000e_radio is not None

    bad_res = find_optimal_mesh_route(
        origin=hub,
        destination=dest_client,
        candidate_repeaters=[],
        destination_client_radio=t1000e_radio,
        client_env_loss_db=-2.0,
    )
    assert bad_res.ok is False
    assert bad_res.error is not None
    assert bad_res.error.code == "INVALID_LOSS_PENALTY"

    ok_res = find_optimal_mesh_route(
        origin=hub,
        destination=dest_client,
        candidate_repeaters=[],
        elevation_fn=lambda lat, lon: 150.0,
        destination_client_radio=t1000e_radio,
        client_env_loss_db=4.0,
        site_profiles={hub.site_id: g2_prof},
    )
    assert ok_res.ok is True and ok_res.value is not None
    assert ok_res.value.route_found is True
    assert ok_res.value.total_hops == 1
    leg = ok_res.value.legs[0]
    assert leg.forward_margin_db is not None and leg.reverse_margin_db is not None
    assert leg.reachability_state == ReachabilityState.TWO_WAY
    # Hub (28 dBm, 6 dB noise) -> Client (20 dBm, 0 dB noise): forward - reverse == (28 - 20) + (6 - 0) == +14.0 dB
    assert leg.forward_margin_db - leg.reverse_margin_db == pytest.approx(14.0, abs=0.05)
