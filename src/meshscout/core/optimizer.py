"""Greedy Weighted Minimum Set-Cover Repeater Optimizer for MeshScout.

Implements a pure Functional Core greedy approximation solver for selecting the
minimal-cost set of candidate repeaters required to achieve a target valley/basin
coverage threshold (e.g., >=90% population-weighted coverage).
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple
from pydantic import BaseModel, Field

from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RadioConfig,
    Result,
    SiteCandidate,
)
from meshscout.core.itm import evaluate_point_to_point_link
from meshscout.core.viewshed import ViewshedResult

# Relative deployment cost multipliers by physical access difficulty
ACCESS_COST_MULTIPLIERS: Dict[AccessDifficulty, float] = {
    AccessDifficulty.DRIVE_UP: 1.0,
    AccessDifficulty.MODERATE: 1.35,
    AccessDifficulty.HIKE_IN: 2.0,
    AccessDifficulty.HELICOPTER: 4.0,
}

# Discount multiplier when continuous AC grid power is available on site
GRID_POWER_DISCOUNT_FACTOR: float = 0.85


class RepeaterSelectionStep(BaseModel):
    """Audit record of a single greedy repeater selection step."""

    step: int = Field(..., ge=1, description="1-based greedy selection iteration index")
    site: SiteCandidate
    newly_covered_target_ids: List[str] = Field(
        default_factory=list,
        description="Target IDs newly covered by selecting this repeater",
    )
    newly_covered_weight: float = Field(
        ..., ge=0.0, description="Total marginal population/priority weight newly covered"
    )
    cost: float = Field(..., gt=0.0, description="Estimated deployment cost of this site")
    efficiency_score: float = Field(
        ..., ge=0.0, description="Marginal weighted coverage gain per unit deployment cost"
    )
    cumulative_coverage_fraction: float = Field(
        ..., ge=0.0, le=1.0, description="Cumulative unweighted target coverage fraction"
    )
    cumulative_weighted_coverage_fraction: float = Field(
        ..., ge=0.0, le=1.0, description="Cumulative weighted target coverage fraction"
    )


class SetCoverOptimizationResult(BaseModel):
    """Result of the greedy weighted minimum set-cover repeater optimization."""

    selected_sites: List[SiteCandidate] = Field(default_factory=list)
    selection_steps: List[RepeaterSelectionStep] = Field(default_factory=list)
    total_targets: int = Field(..., ge=0)
    covered_target_ids: List[str] = Field(default_factory=list)
    uncovered_target_ids: List[str] = Field(default_factory=list)
    achieved_coverage_fraction: float = Field(..., ge=0.0, le=1.0)
    achieved_weighted_coverage_fraction: float = Field(..., ge=0.0, le=1.0)
    target_coverage_threshold: float = Field(..., gt=0.0, le=1.0)
    threshold_met: bool
    total_cost: float = Field(..., ge=0.0)


def estimate_site_deployment_cost(
    site: SiteCandidate,
    custom_costs: Optional[Dict[str, float]] = None,
) -> float:
    """Estimate relative deployment and maintenance cost for a candidate repeater site.

    Accounts for:
      - Custom override in `custom_costs[site.site_id]` if provided and > 0.
      - `AccessDifficulty` multiplier (`DRIVE_UP=1.0`, `MODERATE=1.35`, `HIKE_IN=2.0`, `HELICOPTER=4.0`).
      - `has_grid_power` discount (`0.85x` when grid AC power is available vs off-grid solar/battery).
      - Minor solar penalty if off-grid and `solar_exposure_pct < 75.0`.
    """
    if custom_costs and site.site_id in custom_costs:
        override = float(custom_costs[site.site_id])
        if override <= 0.0:
            raise ValueError(f"Custom site cost for {site.site_id} must be > 0, got {override}")
        return round(override, 4)

    base_cost = ACCESS_COST_MULTIPLIERS.get(site.access_difficulty, 1.35)
    if site.has_grid_power:
        base_cost *= GRID_POWER_DISCOUNT_FACTOR
    elif site.solar_exposure_pct < 75.0:
        # Off-grid sites with poor solar exposure require oversized battery/PV arrays
        shading_penalty = 1.0 + ((75.0 - site.solar_exposure_pct) / 150.0)
        base_cost *= shading_penalty

    return round(max(0.01, base_cost), 4)


def _extract_universe_targets(viewsheds: Sequence[ViewshedResult]) -> List[str]:
    """Collect deterministic ordered universe of all target IDs across viewsheds."""
    seen: Set[str] = set()
    ordered: List[str] = []
    for vs in viewsheds:
        if vs.target_results:
            for tr in vs.target_results:
                if tr.target_id not in seen:
                    seen.add(tr.target_id)
                    ordered.append(tr.target_id)
        else:
            for tid in vs.covered_target_ids:
                if tid not in seen:
                    seen.add(tid)
                    ordered.append(tid)
            for tid in vs.shadowed_target_ids:
                if tid not in seen:
                    seen.add(tid)
                    ordered.append(tid)
    return ordered


def is_active_candidate(site: SiteCandidate) -> bool:
    """Return True if candidate site is not marked as blocked or dismantled."""
    status = getattr(site, "status", None) or getattr(site, "deployment_status", None)
    if status is not None:
        status_val = status.value if hasattr(status, "value") else str(status)
        if status_val.lower() in ("blocked", "dismantled"):
            return False
    if site.notes:
        notes_lower = site.notes.lower()
        if (
            "status: blocked" in notes_lower
            or "status: dismantled" in notes_lower
            or "[dismantled]" in notes_lower
            or "[blocked]" in notes_lower
            or notes_lower.strip() in ("blocked", "dismantled")
        ):
            return False
    return True


def solve_minimum_set_cover(
    viewsheds: Sequence[ViewshedResult],
    target_coverage_fraction: float = 0.90,
    max_repeaters: Optional[int] = None,
    target_weights: Optional[Dict[str, float]] = None,
    site_costs: Optional[Dict[str, float]] = None,
) -> Result[SetCoverOptimizationResult]:
    """Solve the weighted minimum set-cover problem to select optimal repeater placements.

    At each greedy step, selects the remaining candidate repeater $i$ that maximizes:
        efficiency_score = (sum_{t in S_i \\ C} w_t) / cost_i
    Breaking ties deterministically by:
        1. Highest marginal unweighted target count `|S_i \\ C|`
        2. Highest repeater elevation `site.location.elevation_m`
        3. Lexicographically smallest `site.site_id`
    """
    if not viewsheds:
        return Result.fail(
            code="EMPTY_VIEWSHED_CANDIDATES",
            message="Cannot optimize repeater placement: viewsheds sequence is empty.",
        )

    # Filter out candidates marked blocked or dismantled
    active_viewsheds = [vs for vs in viewsheds if is_active_candidate(vs.repeater)]
    if not active_viewsheds:
        return Result.fail(
            code="NO_ACTIVE_CANDIDATES",
            message="No active repeater candidates available (all candidates are blocked or dismantled).",
        )

    if not (0.0 < target_coverage_fraction <= 1.0):
        return Result.fail(
            code="INVALID_COVERAGE_THRESHOLD",
            message=f"target_coverage_fraction must be in (0.0, 1.0], got {target_coverage_fraction}.",
        )

    if max_repeaters is not None and max_repeaters < 1:
        return Result.fail(
            code="INVALID_MAX_REPEATERS",
            message=f"max_repeaters must be >= 1 when specified, got {max_repeaters}.",
        )

    universe_ids = _extract_universe_targets(viewsheds)
    if not universe_ids:
        return Result.fail(
            code="EMPTY_TARGET_UNIVERSE",
            message="No target points found across provided viewshed results.",
        )

    weights: Dict[str, float] = {}
    for tid in universe_ids:
        w = float(target_weights[tid]) if (target_weights and tid in target_weights) else 1.0
        if w <= 0.0:
            return Result.fail(
                code="INVALID_TARGET_WEIGHT",
                message=f"Weight for target '{tid}' must be strictly positive, got {w}.",
            )
        weights[tid] = w

    total_targets = len(universe_ids)
    total_universe_weight = sum(weights.values())
    universe_set = set(universe_ids)

    # Precompute candidate coverage sets and costs
    candidate_map: Dict[str, Tuple[SiteCandidate, Set[str], float]] = {}
    for vs in active_viewsheds:
        site_id = vs.repeater.site_id
        try:
            cost = estimate_site_deployment_cost(vs.repeater, custom_costs=site_costs)
        except ValueError as exc:
            return Result.fail(code="INVALID_SITE_COST", message=str(exc))

        cov_set = {tid for tid in vs.covered_target_ids if tid in universe_set}
        candidate_map[site_id] = (vs.repeater, cov_set, cost)

    covered_set: Set[str] = set()
    covered_weight: float = 0.0
    total_cost: float = 0.0
    selected_sites: List[SiteCandidate] = []
    selection_steps: List[RepeaterSelectionStep] = []
    remaining_ids: Set[str] = set(candidate_map.keys())

    step_idx = 0
    while remaining_ids:
        current_weighted_frac = covered_weight / total_universe_weight
        if current_weighted_frac >= target_coverage_fraction - 1e-9:
            break
        if max_repeaters is not None and len(selected_sites) >= max_repeaters:
            break

        best_site_id: Optional[str] = None
        best_new_targets: Set[str] = set()
        best_marginal_weight: float = 0.0
        best_cost: float = 1.0
        best_score: float = -1.0
        best_tie_key: Tuple[float, int, float] = (-1.0, 0, -float("inf"))

        for cid in sorted(remaining_ids):
            site, cov_set, cost = candidate_map[cid]
            new_targets = cov_set - covered_set
            if not new_targets:
                continue

            marginal_weight = sum(weights[tid] for tid in new_targets)
            score = marginal_weight / cost
            # Round score to 12 decimal places to prevent floating-point noise from breaking deterministic ties
            tie_key = (round(score, 12), len(new_targets), site.location.elevation_m)

            if tie_key > best_tie_key:
                best_tie_key = tie_key
                best_site_id = cid
                best_new_targets = new_targets
                best_marginal_weight = marginal_weight
                best_cost = cost
                best_score = score

        if best_site_id is None:
            # No remaining candidate covers any new uncovered target points
            break

        step_idx += 1
        chosen_site, _, _ = candidate_map[best_site_id]
        remaining_ids.remove(best_site_id)
        covered_set |= best_new_targets
        covered_weight += best_marginal_weight
        total_cost += best_cost
        selected_sites.append(chosen_site)

        cum_unweighted_frac = len(covered_set) / total_targets
        cum_weighted_frac = min(1.0, covered_weight / total_universe_weight)

        selection_steps.append(
            RepeaterSelectionStep(
                step=step_idx,
                site=chosen_site,
                newly_covered_target_ids=sorted(best_new_targets),
                newly_covered_weight=round(best_marginal_weight, 4),
                cost=round(best_cost, 4),
                efficiency_score=round(best_score, 4),
                cumulative_coverage_fraction=round(cum_unweighted_frac, 4),
                cumulative_weighted_coverage_fraction=round(cum_weighted_frac, 4),
            )
        )

    final_unweighted_frac = len(covered_set) / total_targets
    final_weighted_frac = min(1.0, covered_weight / total_universe_weight)
    threshold_met = final_weighted_frac >= (target_coverage_fraction - 1e-9)

    covered_list = [tid for tid in universe_ids if tid in covered_set]
    uncovered_list = [tid for tid in universe_ids if tid not in covered_set]

    return Result.success(
        SetCoverOptimizationResult(
            selected_sites=selected_sites,
            selection_steps=selection_steps,
            total_targets=total_targets,
            covered_target_ids=covered_list,
            uncovered_target_ids=uncovered_list,
            achieved_coverage_fraction=round(final_unweighted_frac, 4),
            achieved_weighted_coverage_fraction=round(final_weighted_frac, 4),
            target_coverage_threshold=target_coverage_fraction,
            threshold_met=threshold_met,
            total_cost=round(total_cost, 4),
        )
    )


class MeshHopLeg(BaseModel):
    """A single point-to-point link leg within a multi-hop mesh route."""
    source_site_id: str
    source_name: str
    target_site_id: str
    target_name: str
    distance_km: float
    link_margin_db: float
    has_line_of_sight: bool


class MeshRouteResult(BaseModel):
    """Multi-hop path across repeaters connecting two stations."""
    origin_id: str
    destination_id: str
    route_found: bool
    total_hops: int
    total_distance_km: float
    bottleneck_margin_db: float
    legs: List[MeshHopLeg] = Field(default_factory=list)
    intermediate_node_ids: List[str] = Field(default_factory=list)
    hop_limit_exceeded: bool = False
    guidance: str = ""


def _eval_hop_leg(
    s1: SiteCandidate,
    s2: SiteCandidate,
    radio: RadioConfig,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
) -> Tuple[float, float, bool]:
    """Helper to evaluate distance_km, link_margin_db, has_los between two nodes."""
    d_km = math.sqrt(
        ((s1.location.lat - s2.location.lat) * 111.13) ** 2
        + ((s1.location.lon - s2.location.lon) * 80.0) ** 2
    )
    total_d_m = max(1.0, d_km * 1000.0)
    points: List[ElevationPoint] = []
    for idx in range(15):
        frac = idx / 14.0
        lat = s1.location.lat + frac * (s2.location.lat - s1.location.lat)
        lon = s1.location.lon + frac * (s2.location.lon - s1.location.lon)
        if idx == 0:
            elev = s1.location.elevation_m
        elif idx == 14:
            elev = s2.location.elevation_m
        elif elevation_fn is not None:
            elev = float(elevation_fn(lat, lon))
        else:
            elev = min(s1.location.elevation_m, s2.location.elevation_m)
        points.append(
            ElevationPoint(
                distance_m=frac * total_d_m,
                elevation_m=elev,
                coordinate=Coordinate(lat=lat, lon=lon, elevation_m=elev),
            )
        )
    prof = ElevationProfile(source_site=s1, target_site=s2, distance_km=d_km, points=points)
    lb_res = evaluate_point_to_point_link(prof, radio=radio)
    if lb_res.ok and lb_res.value is not None:
        return (round(d_km, 2), round(lb_res.value.link_margin_db, 1), lb_res.value.has_line_of_sight)
    return (round(d_km, 2), -99.0, False)


def find_optimal_mesh_route(
    origin: SiteCandidate,
    destination: SiteCandidate,
    candidate_repeaters: Sequence[SiteCandidate],
    radio: Optional[RadioConfig] = None,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    max_hops: int = 3,
    min_link_margin_db: float = 3.0,
) -> Result[MeshRouteResult]:
    """Find the optimal multi-hop mesh packet route bridging origin and destination.

    Evaluates 1-hop direct, 2-hop (via single mountain/water tower repeater), and 3-hop
    paths, selecting the route that maximizes the bottleneck link fade margin.
    """
    active_radio = radio if radio is not None else RadioConfig()

    # 1. Direct link evaluation
    d0, m0, los0 = _eval_hop_leg(origin, destination, active_radio, elevation_fn)
    if m0 >= min_link_margin_db:
        return Result.success(
            MeshRouteResult(
                origin_id=origin.site_id,
                destination_id=destination.site_id,
                route_found=True,
                total_hops=1,
                total_distance_km=d0,
                bottleneck_margin_db=m0,
                legs=[
                    MeshHopLeg(
                        source_site_id=origin.site_id,
                        source_name=origin.name,
                        target_site_id=destination.site_id,
                        target_name=destination.name,
                        distance_km=d0,
                        link_margin_db=m0,
                        has_line_of_sight=los0,
                    )
                ],
                intermediate_node_ids=[],
                hop_limit_exceeded=False,
                guidance="Direct 1-hop line-of-sight link verified.",
            )
        )

    # 2. Two-hop repeater bridge evaluation
    # Filter candidates to exclude origin, destination, and inactive repeaters
    pool = [
        s for s in candidate_repeaters
        if s.site_id != origin.site_id
        and s.site_id != destination.site_id
        and is_active_candidate(s)
    ]

    best_2hop: Optional[Tuple[float, SiteCandidate, Tuple[float, float, bool], Tuple[float, float, bool]]] = None
    for rep in pool:
        d1, m1, los1 = _eval_hop_leg(origin, rep, active_radio, elevation_fn)
        if m1 < min_link_margin_db:
            continue
        d2, m2, los2 = _eval_hop_leg(rep, destination, active_radio, elevation_fn)
        if m2 < min_link_margin_db:
            continue
        bottleneck = min(m1, m2)
        if best_2hop is None or bottleneck > best_2hop[0]:
            best_2hop = (bottleneck, rep, (d1, m1, los1), (d2, m2, los2))

    if best_2hop is not None:
        btn, r, (d1, m1, los1), (d2, m2, los2) = best_2hop
        return Result.success(
            MeshRouteResult(
                origin_id=origin.site_id,
                destination_id=destination.site_id,
                route_found=True,
                total_hops=2,
                total_distance_km=round(d1 + d2, 2),
                bottleneck_margin_db=btn,
                legs=[
                    MeshHopLeg(
                        source_site_id=origin.site_id,
                        source_name=origin.name,
                        target_site_id=r.site_id,
                        target_name=r.name,
                        distance_km=d1,
                        link_margin_db=m1,
                        has_line_of_sight=los1,
                    ),
                    MeshHopLeg(
                        source_site_id=r.site_id,
                        source_name=r.name,
                        target_site_id=destination.site_id,
                        target_name=destination.name,
                        distance_km=d2,
                        link_margin_db=m2,
                        has_line_of_sight=los2,
                    ),
                ],
                intermediate_node_ids=[r.site_id],
                hop_limit_exceeded=False,
                guidance=f"2-hop backbone bridge via {r.name} [{r.site_id}] with {btn:+.1f}dB bottleneck margin.",
            )
        )

    # 3. Three-hop evaluation if max_hops >= 3
    if max_hops >= 3 and len(pool) >= 2:
        best_3hop: Optional[Tuple[float, SiteCandidate, SiteCandidate, List[Tuple[float, float, bool]]]] = None
        # Evaluate top candidate pairs
        for r1 in pool[:8]:
            d1, m1, los1 = _eval_hop_leg(origin, r1, active_radio, elevation_fn)
            if m1 < min_link_margin_db:
                continue
            for r2 in pool[:8]:
                if r1.site_id == r2.site_id:
                    continue
                d2, m2, los2 = _eval_hop_leg(r1, r2, active_radio, elevation_fn)
                if m2 < min_link_margin_db:
                    continue
                d3, m3, los3 = _eval_hop_leg(r2, destination, active_radio, elevation_fn)
                if m3 < min_link_margin_db:
                    continue
                bottleneck = min(m1, m2, m3)
                if best_3hop is None or bottleneck > best_3hop[0]:
                    best_3hop = (bottleneck, r1, r2, [(d1, m1, los1), (d2, m2, los2), (d3, m3, los3)])

        if best_3hop is not None:
            btn, r1, r2, legs_data = best_3hop
            (d1, m1, los1), (d2, m2, los2), (d3, m3, los3) = legs_data
            return Result.success(
                MeshRouteResult(
                    origin_id=origin.site_id,
                    destination_id=destination.site_id,
                    route_found=True,
                    total_hops=3,
                    total_distance_km=round(d1 + d2 + d3, 2),
                    bottleneck_margin_db=btn,
                    legs=[
                        MeshHopLeg(source_site_id=origin.site_id, source_name=origin.name, target_site_id=r1.site_id, target_name=r1.name, distance_km=d1, link_margin_db=m1, has_line_of_sight=los1),
                        MeshHopLeg(source_site_id=r1.site_id, source_name=r1.name, target_site_id=r2.site_id, target_name=r2.name, distance_km=d2, link_margin_db=m2, has_line_of_sight=los2),
                        MeshHopLeg(source_site_id=r2.site_id, source_name=r2.name, target_site_id=destination.site_id, target_name=destination.name, distance_km=d3, link_margin_db=m3, has_line_of_sight=los3),
                    ],
                    intermediate_node_ids=[r1.site_id, r2.site_id],
                    hop_limit_exceeded=False,
                    guidance=f"3-hop route via {r1.name} and {r2.name} with {btn:+.1f}dB bottleneck margin.",
                )
            )

    return Result.success(
        MeshRouteResult(
            origin_id=origin.site_id,
            destination_id=destination.site_id,
            route_found=False,
            total_hops=0,
            total_distance_km=d0,
            bottleneck_margin_db=m0,
            legs=[],
            intermediate_node_ids=[],
            hop_limit_exceeded=True,
            guidance=f"No viable mesh route found within {max_hops} hops. Increase repeater density or deploy on an intermediate summit.",
        )
    )
