"""Multi-Hop Corridor Evaluation Engine for MeshScout.

Evaluates linear repeater chains and point-to-point hop sequences, computing per-hop
line-of-sight, link margin, Fresnel clearance, elevation delta, cumulative distance,
and identifying the bottleneck link.
Follows zero runtime dependencies beyond pydantic>=2.0.0.
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence
from pydantic import BaseModel, Field

from meshscout.core.composite_viewshed import _synthetic_vermont_elevation_fn
from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RadioConfig,
    Result,
    SiteCandidate,
)
from meshscout.core.itm import evaluate_point_to_point_link
from meshscout.core.viewshed import haversine_distance_km


class CorridorHopResult(BaseModel):
    """Evaluation result for an individual hop in a multi-hop corridor."""

    hop_index: int = Field(..., description="Zero-based index of this hop along the corridor")
    origin_site_id: str = Field(..., description="Site ID of origin node")
    origin_name: str = Field(..., description="Name of origin node")
    target_site_id: str = Field(..., description="Site ID of target node")
    target_name: str = Field(..., description="Name of target node")
    distance_km: float = Field(..., description="Great-circle distance in kilometers")
    has_line_of_sight: bool = Field(..., description="True if line-of-sight is unobstructed")
    link_margin_db: float = Field(..., description="Fade margin in dB above receiver sensitivity")
    fresnel_clearance_ratio: float = Field(..., description="First Fresnel zone clearance ratio")
    elevation_delta_m: float = Field(..., description="Elevation change from origin to target in meters")


class MultiHopCorridorResult(BaseModel):
    """Evaluation result for an entire multi-hop corridor sequence."""

    node_ids: List[str] = Field(default_factory=list, description="Ordered sequence of node IDs")
    total_hops: int = Field(..., description="Total number of hops")
    total_distance_km: float = Field(..., description="Total cumulative distance in kilometers")
    all_clear_los: bool = Field(..., description="True if all hops have line-of-sight")
    worst_link_margin_db: float = Field(..., description="Lowest link margin across all hops (dB)")
    bottleneck_hop_index: Optional[int] = Field(default=None, description="Index of hop with lowest margin")
    hops: List[CorridorHopResult] = Field(default_factory=list, description="Detailed per-hop evaluation results")


def _build_hop_elevation_profile(
    origin: SiteCandidate,
    target: SiteCandidate,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    num_samples: int = 20,
) -> ElevationProfile:
    """Build a multi-point ElevationProfile along the great-circle path between two sites."""
    dist_km = haversine_distance_km(origin.location, target.location)
    total_d_m = max(dist_km * 1000.0, 1.0)
    dist_km_safe = total_d_m / 1000.0

    points: List[ElevationPoint] = []
    steps = max(2, num_samples)

    for i in range(steps):
        frac = i / float(steps - 1)
        lat = origin.location.lat + frac * (target.location.lat - origin.location.lat)
        lon = origin.location.lon + frac * (target.location.lon - origin.location.lon)
        d_m = round(frac * total_d_m, 2)

        if i == 0:
            elev = origin.location.elevation_m
        elif i == steps - 1:
            elev = target.location.elevation_m
        elif elevation_fn is not None:
            elev = float(elevation_fn(lat, lon))
        elif 42.0 <= lat <= 46.0 and -74.0 <= lon <= -71.0:
            elev = _synthetic_vermont_elevation_fn(lat, lon)
        else:
            elev = (
                origin.location.elevation_m
                + frac * (target.location.elevation_m - origin.location.elevation_m)
            )

        points.append(
            ElevationPoint(
                distance_m=d_m,
                elevation_m=round(elev, 2),
                coordinate=Coordinate(
                    lat=round(lat, 6),
                    lon=round(lon, 6),
                    elevation_m=round(elev, 2),
                ),
            )
        )

    return ElevationProfile(
        source_site=origin,
        target_site=target,
        distance_km=round(dist_km_safe, 4),
        points=points,
    )


def evaluate_multihop_corridor(
    nodes: Sequence[SiteCandidate],
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    radio_config: Optional[RadioConfig] = None,
) -> Result[MultiHopCorridorResult]:
    """Evaluate an end-to-end multi-hop corridor across an ordered sequence of node candidates.

    Args:
        nodes: Ordered sequence of SiteCandidate nodes along the corridor.
        elevation_fn: Optional terrain elevation query function (lat, lon) -> elevation_m.
        radio_config: Optional RF configuration for transceivers and link budget.

    Returns:
        Result[MultiHopCorridorResult] detailing per-hop metrics and bottleneck analysis.
    """
    if len(nodes) < 2:
        return Result.success(
            MultiHopCorridorResult(
                node_ids=[n.site_id for n in nodes],
                total_hops=0,
                total_distance_km=0.0,
                all_clear_los=True,
                worst_link_margin_db=999.0,
                bottleneck_hop_index=None,
                hops=[],
            )
        )

    active_radio = radio_config if radio_config is not None else RadioConfig()
    hops: List[CorridorHopResult] = []

    for i in range(len(nodes) - 1):
        origin = nodes[i]
        target = nodes[i + 1]

        profile = _build_hop_elevation_profile(
            origin=origin,
            target=target,
            elevation_fn=elevation_fn,
        )

        link_eval_res = evaluate_point_to_point_link(
            profile=profile,
            radio=active_radio,
        )

        if not link_eval_res.ok or link_eval_res.value is None:
            err_code = link_eval_res.error.code if link_eval_res.error else "LINK_EVALUATION_FAILED"
            err_msg = link_eval_res.error.message if link_eval_res.error else "Unknown ITM link failure"
            return Result.fail(
                code=err_code,
                message=f"Hop {i} ({origin.site_id} -> {target.site_id}) evaluation failed: {err_msg}",
            )

        link_eval = link_eval_res.value
        elevation_delta_m = target.location.elevation_m - origin.location.elevation_m

        hop_result = CorridorHopResult(
            hop_index=i,
            origin_site_id=origin.site_id,
            origin_name=origin.name,
            target_site_id=target.site_id,
            target_name=target.name,
            distance_km=round(link_eval.distance_km, 2),
            has_line_of_sight=link_eval.has_line_of_sight,
            link_margin_db=round(link_eval.link_margin_db, 2),
            fresnel_clearance_ratio=round(link_eval.fresnel_clearance_ratio, 2),
            elevation_delta_m=round(elevation_delta_m, 1),
        )
        hops.append(hop_result)

    total_distance_km = round(sum(h.distance_km for h in hops), 2)
    all_clear_los = all(h.has_line_of_sight for h in hops)
    worst_link_margin_db = min(h.link_margin_db for h in hops)
    bottleneck_hop_index = min(range(len(hops)), key=lambda idx: hops[idx].link_margin_db)

    return Result.success(
        MultiHopCorridorResult(
            node_ids=[n.site_id for n in nodes],
            total_hops=len(hops),
            total_distance_km=total_distance_km,
            all_clear_los=all_clear_los,
            worst_link_margin_db=worst_link_margin_db,
            bottleneck_hop_index=bottleneck_hop_index,
            hops=hops,
        )
    )
