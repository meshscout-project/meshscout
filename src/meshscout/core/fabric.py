"""Two-tier infill-to-trunk RF fabric, multi-interface bridge routing, and co-site desense engine.

Implements pure Layer-1 computation with zero file or network I/O, importing only
from core contracts, ITM, viewshed, traffic, optimizer, and Python stdlib.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple
from pydantic import BaseModel, Field

from meshscout.core.contracts import (
    AntennaPattern,
    InterfaceTier,
    MultiInterfaceSiteProfile,
    RadiationClass,
    RadioConfig,
    RadioInterfaceSpec,
    ReachabilityState,
    Result,
    SiteCandidate,
)
from meshscout.core.itm import evaluate_point_to_point_link, forward_azimuth_deg
from meshscout.core.optimizer import (
    _build_leg_profile,
    is_active_candidate,
    solve_minimum_set_cover,
)
from meshscout.core.traffic import compute_antenna_isolation_db
from meshscout.core.viewshed import ViewshedResult


class CoSiteDesensePair(BaseModel):
    """Pairwise co-site transmitter-to-receiver desense assessment on a shared mast."""

    site_id: str
    aggressor_interface_id: str
    victim_interface_id: str
    freq_offset_mhz: float
    vertical_sep_m: float
    spatial_isolation_db: float
    filter_rejection_db: float
    coupled_tx_dbm: float
    desense_db: float
    blocking_risk: bool
    mitigation: str


class FabricHopLeg(BaseModel):
    """Single hop or intra-site bridge transition in a multi-interface fabric route."""

    source_site_id: str
    source_interface_id: str
    target_site_id: str
    target_interface_id: str
    leg_kind: str
    distance_km: float
    link_margin_db: float
    azimuth_deg: float


class FabricRouteResult(BaseModel):
    """Multi-interface end-to-end route spanning access, bridge, and backhaul tiers."""

    origin_id: str
    destination_id: str
    route_found: bool
    rf_hops: int
    bridge_transitions: int
    bottleneck_margin_db: float
    legs: List[FabricHopLeg] = Field(default_factory=list)


class DirectedAntennaAssignment(BaseModel):
    """Recommended boresight azimuth and downtilt angle for a directed site interface."""

    site_id: str
    interface_id: str
    peer_site_id: str
    azimuth_deg: float
    downtilt_deg: float
    link_margin_db: float


class TwoTierFabricPlan(BaseModel):
    """Integrated two-tier trunk backhaul and backhaul-viable valley infill plan."""

    trunk_site_ids: List[str]
    infill_site_ids: List[str]
    unconnected_infill_ids: List[str]
    covered_target_ids: List[str]
    achieved_weighted_coverage_fraction: float
    trunk_connected: bool
    antenna_assignments: List[DirectedAntennaAssignment]
    cosite_desense_pairs: List[CoSiteDesensePair]
    cosite_blocking_count: int


def evaluate_cosite_desense(
    site: SiteCandidate,
    profile: MultiInterfaceSiteProfile,
    horizontal_sep_m: float = 0.5,
) -> List[CoSiteDesensePair]:
    """Evaluate co-site broadband noise desense and RX compression risk across interfaces."""
    pairs: List[CoSiteDesensePair] = []
    rx_floor_dbm = -114.0 + profile.noise_penalty_db

    for tx_if in profile.interfaces:
        tx_mount = tx_if.mast_mount_m if tx_if.mast_mount_m is not None else site.mast_height_m
        for rx_if in profile.interfaces:
            if tx_if.interface_id == rx_if.interface_id:
                continue

            rx_mount = (
                rx_if.mast_mount_m if rx_if.mast_mount_m is not None else site.mast_height_m
            )
            v_sep = round(abs(tx_mount - rx_mount), 4)
            iso_db = compute_antenna_isolation_db(
                vertical_sep_m=v_sep,
                horizontal_sep_m=horizontal_sep_m,
                frequency_mhz=tx_if.radio.frequency_mhz,
            )
            coupled_tx_dbm = round(
                tx_if.radio.tx_power_dbm - iso_db - rx_if.filter_rejection_db,
                2,
            )
            df = round(abs(tx_if.radio.frequency_mhz - rx_if.radio.frequency_mhz), 6)

            if df < 0.25:
                noise_at_rx = coupled_tx_dbm
            else:
                oob_dbc_hz = -115.0 - min(20.0, 10.0 * math.log10(df))
                noise_at_rx = coupled_tx_dbm + oob_dbc_hz + 54.0

            delta_nr = min(200.0, noise_at_rx - rx_floor_dbm)
            desense_db = round(10.0 * math.log10(1.0 + 10.0 ** (delta_nr / 10.0)), 2)
            blocking_risk = (desense_db >= 3.0) or (coupled_tx_dbm > -10.0)
            mitigation = (
                "Add cavity bandpass filter or increase vertical mast separation"
                if blocking_risk
                else "none"
            )

            pairs.append(
                CoSiteDesensePair(
                    site_id=site.site_id,
                    aggressor_interface_id=tx_if.interface_id,
                    victim_interface_id=rx_if.interface_id,
                    freq_offset_mhz=df,
                    vertical_sep_m=v_sep,
                    spatial_isolation_db=iso_db,
                    filter_rejection_db=rx_if.filter_rejection_db,
                    coupled_tx_dbm=coupled_tx_dbm,
                    desense_db=desense_db,
                    blocking_risk=blocking_risk,
                    mitigation=mitigation,
                )
            )

    return pairs


def _eval_two_way_interface_link(
    site_a: SiteCandidate,
    radio_a: RadioConfig,
    site_b: SiteCandidate,
    radio_b: RadioConfig,
    noise_a_db: float,
    noise_b_db: float,
    elevation_fn: Optional[Callable[[float, float], float]],
    min_margin_db: float,
    client_env_loss_db: float = 0.0,
) -> Tuple[float, float, bool]:
    """Evaluate reciprocal two-way ITM margin between two configured interfaces."""
    d_km, prof = _build_leg_profile(site_a, site_b, elevation_fn)
    res = evaluate_point_to_point_link(
        prof,
        radio=radio_a,
        target_radio=radio_b,
        source_noise_penalty_db=noise_a_db,
        target_noise_penalty_db=noise_b_db,
        client_env_loss_db=client_env_loss_db,
        min_margin_db=min_margin_db,
    )
    if not res.ok or res.value is None:
        return (round(d_km, 2), -99.0, False)

    lb = res.value
    dl_margin = lb.downlink_margin_db if lb.downlink_margin_db is not None else lb.link_margin_db
    ul_margin = lb.uplink_margin_db if lb.uplink_margin_db is not None else lb.link_margin_db
    margin_db = round(min(dl_margin, ul_margin), 2)
    viable = lb.reachability_state == ReachabilityState.TWO_WAY and margin_db >= min_margin_db
    return (round(d_km, 2), margin_db, viable)


def find_multi_interface_route(
    origin: SiteCandidate,
    destination: SiteCandidate,
    sites: Sequence[SiteCandidate],
    profiles: Dict[str, MultiInterfaceSiteProfile],
    client_radio: Optional[RadioConfig] = None,
    client_env_loss_db: float = 0.0,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    max_rf_hops: int = 5,
    min_margin_db: float = 3.0,
) -> Result[FabricRouteResult]:
    """Find fewest-RF-hop, widest-margin route across multi-interface split-horizon bridges."""
    if max_rf_hops < 1 or max_rf_hops > 10:
        return Result.fail(
            code="INVALID_HOP_LIMIT",
            message=f"max_rf_hops must be between 1 and 10, got {max_rf_hops}.",
        )
    if client_env_loss_db < 0.0:
        return Result.fail(
            code="INVALID_LOSS_PENALTY",
            message=f"client_env_loss_db must be non-negative, got {client_env_loss_db}.",
        )

    site_map: Dict[str, SiteCandidate] = {origin.site_id: origin, destination.site_id: destination}
    for s in sites:
        if is_active_candidate(s):
            site_map.setdefault(s.site_id, s)

    iface_nodes: Dict[Tuple[str, str], Tuple[SiteCandidate, RadioInterfaceSpec, float, bool]] = {}
    for sid, site_obj in site_map.items():
        prof = profiles.get(sid)
        if prof is not None:
            for iface in prof.interfaces:
                iface_nodes[(sid, iface.interface_id)] = (
                    site_obj,
                    iface,
                    prof.noise_penalty_db,
                    False,
                )
        elif sid in (origin.site_id, destination.site_id):
            ep_radio = client_radio if client_radio is not None else RadioConfig()
            ep_iface = RadioInterfaceSpec(
                interface_id="__endpoint__",
                tier=InterfaceTier.ACCESS_INFILL,
                radio=ep_radio,
            )
            iface_nodes[(sid, ep_iface.interface_id)] = (site_obj, ep_iface, 0.0, True)

    start_keys = [k for k in sorted(iface_nodes) if k[0] == origin.site_id]
    goal_keys = {k for k in iface_nodes if k[0] == destination.site_id}
    if not start_keys or not goal_keys:
        return Result.success(
            FabricRouteResult(
                origin_id=origin.site_id,
                destination_id=destination.site_id,
                route_found=False,
                rf_hops=0,
                bridge_transitions=0,
                bottleneck_margin_db=-99.0,
                legs=[],
            )
        )

    if origin.site_id == destination.site_id:
        return Result.success(
            FabricRouteResult(
                origin_id=origin.site_id,
                destination_id=destination.site_id,
                route_found=True,
                rf_hops=0,
                bridge_transitions=0,
                bottleneck_margin_db=99.0,
                legs=[],
            )
        )

    adj: Dict[Tuple[str, str], List[Tuple[Tuple[str, str], FabricHopLeg, bool]]] = {
        k: [] for k in iface_nodes
    }

    # Build intra-site split-horizon bridge edges
    by_site: Dict[str, List[Tuple[str, str]]] = {}
    for key in sorted(iface_nodes):
        by_site.setdefault(key[0], []).append(key)
    for sid, keys in by_site.items():
        for ka in keys:
            bg_a = iface_nodes[ka][1].bridge_group
            if not bg_a:
                continue
            for kb in keys:
                if ka == kb:
                    continue
                if iface_nodes[kb][1].bridge_group == bg_a:
                    leg = FabricHopLeg(
                        source_site_id=sid,
                        source_interface_id=ka[1],
                        target_site_id=sid,
                        target_interface_id=kb[1],
                        leg_kind="intra_site_bridge",
                        distance_km=0.0,
                        link_margin_db=99.0,
                        azimuth_deg=0.0,
                    )
                    adj[ka].append((kb, leg, True))

    # Build inter-site compatible RF edges
    node_keys = sorted(iface_nodes.keys())
    for idx, ka in enumerate(node_keys):
        site_a, if_a, noise_a, ep_a = iface_nodes[ka]
        for kb in node_keys[idx + 1 :]:
            if kb[0] == ka[0]:
                continue
            site_b, if_b, noise_b, ep_b = iface_nodes[kb]
            if abs(if_a.radio.frequency_mhz - if_b.radio.frequency_mhz) > 0.125:
                continue

            env_loss = client_env_loss_db if (ep_a or ep_b) else 0.0
            d_km, margin_db, viable = _eval_two_way_interface_link(
                site_a,
                if_a.radio,
                site_b,
                if_b.radio,
                noise_a,
                noise_b,
                elevation_fn,
                min_margin_db,
                client_env_loss_db=env_loss,
            )
            if not viable:
                continue

            kind = (
                "rf_backhaul"
                if (
                    if_a.tier == InterfaceTier.BACKHAUL_BRIDGE
                    and if_b.tier == InterfaceTier.BACKHAUL_BRIDGE
                )
                else "rf_access"
            )
            leg_fwd = FabricHopLeg(
                source_site_id=site_a.site_id,
                source_interface_id=if_a.interface_id,
                target_site_id=site_b.site_id,
                target_interface_id=if_b.interface_id,
                leg_kind=kind,
                distance_km=d_km,
                link_margin_db=margin_db,
                azimuth_deg=round(forward_azimuth_deg(site_a.location, site_b.location), 2),
            )
            leg_rev = FabricHopLeg(
                source_site_id=site_b.site_id,
                source_interface_id=if_b.interface_id,
                target_site_id=site_a.site_id,
                target_interface_id=if_a.interface_id,
                leg_kind=kind,
                distance_km=d_km,
                link_margin_db=margin_db,
                azimuth_deg=round(forward_azimuth_deg(site_b.location, site_a.location), 2),
            )
            adj[ka].append((kb, leg_fwd, False))
            adj[kb].append((ka, leg_rev, False))

    # Hop-layered widest-path frontier across RF hops (0-cost bridge transitions inside each layer)
    # State tuple: (rf_hops, bridges, neg_btn, dist_km, node_key, prev_was_bridge, legs)
    best_rank: Dict[Tuple[Tuple[str, str], int], Tuple[int, float, float]] = {}
    frontier: List[
        Tuple[int, int, float, float, Tuple[str, str], bool, Tuple[str, ...], Tuple[FabricHopLeg, ...]]
    ] = []
    for sk in start_keys:
        best_rank[(sk, 0)] = (0, -99.0, 0.0)
        frontier.append((0, 0, -99.0, 0.0, sk, False, (sk[0],), ()))

    best_goal: Optional[
        Tuple[int, int, float, float, Tuple[FabricHopLeg, ...]]
    ] = None

    while frontier:
        frontier.sort(key=lambda st: (st[0], st[1], st[2], st[3], st[4]))
        rf_h, br_c, neg_btn, dist_s, cur_k, prev_br, visited_sites, legs_t = frontier.pop(0)

        if cur_k in goal_keys and rf_h >= 1:
            cand_goal = (rf_h, br_c, neg_btn, dist_s, legs_t)
            if best_goal is None or cand_goal[:4] < best_goal[:4]:
                best_goal = cand_goal
            continue

        if best_goal is not None and rf_h > best_goal[0]:
            break

        for nxt_k, leg, is_bridge in adj.get(cur_k, ()):
            if is_bridge:
                if prev_br:
                    continue
                nxt_rf = rf_h
                nxt_br = br_c + 1
                nxt_visited = visited_sites
                nxt_btn = neg_btn
                nxt_dist = dist_s
            else:
                if rf_h + 1 > max_rf_hops or nxt_k[0] in visited_sites:
                    continue
                nxt_rf = rf_h + 1
                nxt_br = br_c
                nxt_visited = (*visited_sites, nxt_k[0])
                cur_btn = -neg_btn if legs_t else float("inf")
                nxt_btn = -round(min(cur_btn, leg.link_margin_db), 2)
                nxt_dist = round(dist_s + leg.distance_km, 2)

            state_key = (nxt_k, nxt_rf)
            rank = (nxt_br, nxt_btn, nxt_dist)
            if state_key in best_rank and rank >= best_rank[state_key]:
                continue
            best_rank[state_key] = rank
            frontier.append(
                (
                    nxt_rf,
                    nxt_br,
                    nxt_btn,
                    nxt_dist,
                    nxt_k,
                    is_bridge,
                    nxt_visited,
                    (*legs_t, leg),
                )
            )

    if best_goal is None:
        return Result.success(
            FabricRouteResult(
                origin_id=origin.site_id,
                destination_id=destination.site_id,
                route_found=False,
                rf_hops=0,
                bridge_transitions=0,
                bottleneck_margin_db=-99.0,
                legs=[],
            )
        )

    rf_h, br_c, neg_btn, _, best_legs = best_goal
    return Result.success(
        FabricRouteResult(
            origin_id=origin.site_id,
            destination_id=destination.site_id,
            route_found=True,
            rf_hops=rf_h,
            bridge_transitions=br_c,
            bottleneck_margin_db=round(-neg_btn, 2),
            legs=list(best_legs),
        )
    )


def _aimed_directional_radio(
    base_radio: RadioConfig,
    src_site: SiteCandidate,
    dst_site: SiteCandidate,
    gain_dbi: float,
    h_beamwidth_deg: float,
) -> Tuple[RadioConfig, float]:
    """Clone base_radio with directional Yagi pattern aimed toward dst_site."""
    az = round(forward_azimuth_deg(src_site.location, dst_site.location), 2) % 360.0
    pat = AntennaPattern(
        radiation_class=RadiationClass.DIRECTIONAL,
        azimuth_deg=az,
        h_beamwidth_deg=h_beamwidth_deg,
        v_beamwidth_deg=min(60.0, max(12.0, h_beamwidth_deg)),
        downtilt_deg=0.0,
        front_to_back_db=16.0,
    )
    aimed = base_radio.model_copy(
        update={
            "antenna_gain_dbi": gain_dbi,
            "antenna_pattern": pat,
        }
    )
    return aimed, az


def _count_connected_components(node_ids: Sequence[str], edges: Sequence[Tuple[str, str]]) -> int:
    """Count undirected connected components across node_ids."""
    adj: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    for u, v in edges:
        if u in adj and v in adj:
            adj[u].append(v)
            adj[v].append(u)
    visited: Set[str] = set()
    comps = 0
    for start in node_ids:
        if start in visited:
            continue
        comps += 1
        stack = [start]
        visited.add(start)
        while stack:
            cur = stack.pop()
            for nxt in adj[cur]:
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append(nxt)
    return comps


def solve_two_tier_fabric(
    trunk_sites: Sequence[SiteCandidate],
    infill_viewsheds: Sequence[ViewshedResult],
    target_coverage_fraction: float = 0.90,
    target_weights: Optional[Dict[str, float]] = None,
    trunk_radio: Optional[RadioConfig] = None,
    infill_uplink_radio: Optional[RadioConfig] = None,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    min_backhaul_margin_db: float = 6.0,
    directional_trunk_gain_dbi: float = 9.0,
    trunk_h_beamwidth_deg: float = 65.0,
    site_profiles: Optional[Dict[str, MultiInterfaceSiteProfile]] = None,
) -> Result[TwoTierFabricPlan]:
    """Solve directional trunk topology, filter backhaul-viable infills, and audit desense."""
    if not trunk_sites:
        return Result.fail(
            code="EMPTY_TRUNK_SITES",
            message="At least one active trunk summit site is required for two-tier fabric planning.",
        )
    if not (0.0 < target_coverage_fraction <= 1.0):
        return Result.fail(
            code="INVALID_COVERAGE_THRESHOLD",
            message=f"target_coverage_fraction must be in (0.0, 1.0], got {target_coverage_fraction}.",
        )

    active_trunks = [s for s in trunk_sites if is_active_candidate(s)]
    if not active_trunks:
        return Result.fail(
            code="EMPTY_TRUNK_SITES",
            message="No active trunk summit sites remain after filtering blocked/dismantled candidates.",
        )

    base_trunk = (
        trunk_radio
        if trunk_radio is not None
        else RadioConfig(
            frequency_mhz=906.875,
            tx_power_dbm=22.0,
            rx_sensitivity_dbm=-134.0,
            antenna_gain_dbi=directional_trunk_gain_dbi,
            cable_loss_db=0.5,
        )
    )
    base_feeder = infill_uplink_radio if infill_uplink_radio is not None else base_trunk

    # 1. Evaluate aimed directional links between trunk summits & build spanning trunk
    trunk_ids = [s.site_id for s in active_trunks]
    trunk_id_set = set(trunk_ids)
    viable_trunk_edges: List[Tuple[float, SiteCandidate, SiteCandidate, float, float]] = []

    for i, s_a in enumerate(active_trunks):
        for s_b in active_trunks[i + 1 :]:
            rad_a, az_ab = _aimed_directional_radio(
                base_trunk, s_a, s_b, directional_trunk_gain_dbi, trunk_h_beamwidth_deg
            )
            rad_b, az_ba = _aimed_directional_radio(
                base_trunk, s_b, s_a, directional_trunk_gain_dbi, trunk_h_beamwidth_deg
            )
            _, margin_db, viable = _eval_two_way_interface_link(
                s_a, rad_a, s_b, rad_b, 0.0, 0.0, elevation_fn, min_backhaul_margin_db
            )
            if viable:
                viable_trunk_edges.append((margin_db, s_a, s_b, az_ab, az_ba))

    comp_count = _count_connected_components(
        trunk_ids, [(e[1].site_id, e[2].site_id) for e in viable_trunk_edges]
    )
    trunk_connected = comp_count == 1

    # Kruskal maximum-margin spanning forest for aimed directional trunk assignments
    parent: Dict[str, str] = {nid: nid for nid in trunk_ids}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    antenna_assignments: List[DirectedAntennaAssignment] = []
    viable_trunk_edges.sort(key=lambda item: (-item[0], item[1].site_id, item[2].site_id))
    for margin_db, s_a, s_b, az_ab, az_ba in viable_trunk_edges:
        ra, rb = _find(s_a.site_id), _find(s_b.site_id)
        if ra == rb:
            continue
        parent[ra] = rb
        antenna_assignments.append(
            DirectedAntennaAssignment(
                site_id=s_a.site_id,
                interface_id="backhaul-0",
                peer_site_id=s_b.site_id,
                azimuth_deg=az_ab,
                downtilt_deg=0.0,
                link_margin_db=margin_db,
            )
        )
        antenna_assignments.append(
            DirectedAntennaAssignment(
                site_id=s_b.site_id,
                interface_id="backhaul-0",
                peer_site_id=s_a.site_id,
                azimuth_deg=az_ba,
                downtilt_deg=0.0,
                link_margin_db=margin_db,
            )
        )

    # 2. Filter candidate infills requiring two-way backhaul uplink into trunk
    viable_viewsheds: List[ViewshedResult] = []
    unconnected_infill_ids: List[str] = []
    feeder_assignments: Dict[str, DirectedAntennaAssignment] = {}

    for vs in infill_viewsheds:
        rep = vs.repeater
        if not is_active_candidate(rep):
            continue
        if rep.site_id in trunk_id_set:
            viable_viewsheds.append(vs)
            continue

        best_peer: Optional[Tuple[float, SiteCandidate, float]] = None
        for t_site in active_trunks:
            rad_in, az_up = _aimed_directional_radio(
                base_feeder, rep, t_site, directional_trunk_gain_dbi, trunk_h_beamwidth_deg
            )
            rad_tk, _ = _aimed_directional_radio(
                base_trunk, t_site, rep, directional_trunk_gain_dbi, trunk_h_beamwidth_deg
            )
            _, margin_db, viable = _eval_two_way_interface_link(
                rep, rad_in, t_site, rad_tk, 0.0, 0.0, elevation_fn, min_backhaul_margin_db
            )
            if viable:
                cand_tuple = (margin_db, t_site, az_up)
                if best_peer is None or (margin_db, t_site.site_id) > (
                    best_peer[0],
                    best_peer[1].site_id,
                ):
                    best_peer = cand_tuple

        if best_peer is None:
            unconnected_infill_ids.append(rep.site_id)
        else:
            margin_db, t_site, az_up = best_peer
            viable_viewsheds.append(vs)
            feeder_assignments[rep.site_id] = DirectedAntennaAssignment(
                site_id=rep.site_id,
                interface_id="backhaul-0",
                peer_site_id=t_site.site_id,
                azimuth_deg=az_up,
                downtilt_deg=0.0,
                link_margin_db=margin_db,
            )

    # 3. Run greedy weighted minimum set-cover across backhaul-viable viewsheds
    selected_sites: List[SiteCandidate] = []
    covered_target_ids: List[str] = []
    achieved_weighted = 0.0

    if viable_viewsheds:
        cover_res = solve_minimum_set_cover(
            viable_viewsheds,
            target_coverage_fraction=target_coverage_fraction,
            target_weights=target_weights,
        )
        if cover_res.ok and cover_res.value is not None:
            selected_sites = list(cover_res.value.selected_sites)
            covered_target_ids = list(cover_res.value.covered_target_ids)
            achieved_weighted = cover_res.value.achieved_weighted_coverage_fraction

    infill_site_ids: List[str] = []
    seen_active_ids: Set[str] = set(trunk_id_set)
    active_sites_list: List[SiteCandidate] = list(active_trunks)

    for s in selected_sites:
        if s.site_id not in trunk_id_set:
            infill_site_ids.append(s.site_id)
            if s.site_id in feeder_assignments:
                antenna_assignments.append(feeder_assignments[s.site_id])
        if s.site_id not in seen_active_ids:
            seen_active_ids.add(s.site_id)
            active_sites_list.append(s)

    # 4. Aggregate co-site desense audit across active trunk + selected infill sites
    cosite_pairs: List[CoSiteDesensePair] = []
    for s in active_sites_list:
        prof = site_profiles.get(s.site_id) if site_profiles is not None else None
        if prof is None:
            prof = MultiInterfaceSiteProfile(
                site_id=s.site_id,
                interfaces=[
                    RadioInterfaceSpec(
                        interface_id="access-0",
                        tier=InterfaceTier.ACCESS_INFILL,
                        radio=RadioConfig(frequency_mhz=915.0, tx_power_dbm=22.0),
                        mast_mount_m=s.mast_height_m,
                        bridge_group="trunk",
                    ),
                    RadioInterfaceSpec(
                        interface_id="backhaul-0",
                        tier=InterfaceTier.BACKHAUL_BRIDGE,
                        radio=base_trunk,
                        mast_mount_m=s.mast_height_m + 3.0,
                        bridge_group="trunk",
                    ),
                ],
            )
        cosite_pairs.extend(evaluate_cosite_desense(s, prof))

    cosite_blocking_count = sum(1 for p in cosite_pairs if p.blocking_risk)

    return Result.success(
        TwoTierFabricPlan(
            trunk_site_ids=trunk_ids,
            infill_site_ids=infill_site_ids,
            unconnected_infill_ids=sorted(set(unconnected_infill_ids)),
            covered_target_ids=covered_target_ids,
            achieved_weighted_coverage_fraction=achieved_weighted,
            trunk_connected=trunk_connected,
            antenna_assignments=antenna_assignments,
            cosite_desense_pairs=cosite_pairs,
            cosite_blocking_count=cosite_blocking_count,
        )
    )
