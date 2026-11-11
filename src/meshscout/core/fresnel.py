"""Pure mathematical Line-of-Sight (LOS), Earth curvature, and Fresnel zone analysis.

Implements Functional Core calculations for RF path clearance, 4/3 Earth refraction
bulge, First Fresnel zone radius, radio horizon, and Fresnel-Kirchhoff knife-edge
diffraction parameter (nu).
"""

from __future__ import annotations

import math
from typing import List, Optional
from pydantic import BaseModel, Field

from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    Result,
)

# Physical constants
EARTH_RADIUS_M: float = 6_371_000.0
SPEED_OF_LIGHT_M_S: float = 299_792_458.0
DEFAULT_K_FACTOR: float = 4.0 / 3.0


class FresnelPointAnalysis(BaseModel):
    """Per-point Line-of-Sight and First Fresnel zone clearance evaluation."""

    distance_m: float = Field(..., ge=0.0, description="Distance from source site in meters")
    terrain_elevation_m: float = Field(..., description="Raw terrain elevation above sea level in meters")
    earth_bulge_m: float = Field(..., ge=0.0, description="Refracted Earth curvature bulge height in meters")
    effective_terrain_height_m: float = Field(
        ..., description="Terrain elevation plus Earth curvature bulge in meters"
    )
    los_height_m: float = Field(..., description="Direct Line-of-Sight ray altitude in meters")
    clearance_m: float = Field(
        ..., description="Vertical clearance (los_height_m - effective_terrain_height_m) in meters"
    )
    first_fresnel_radius_m: float = Field(
        ..., ge=0.0, description="First Fresnel zone radius (F1) at this point in meters"
    )
    clearance_ratio: float = Field(
        ..., description="Ratio of vertical clearance to First Fresnel radius (clearance_m / F1)"
    )
    knife_edge_nu: float = Field(
        ..., description="Fresnel-Kirchhoff diffraction parameter nu at this point"
    )


class FresnelProfileResult(BaseModel):
    """Aggregate Line-of-Sight and Fresnel zone clearance evaluation across an elevation profile."""

    source_id: str = Field(..., min_length=1)
    target_id: str = Field(..., min_length=1)
    total_distance_m: float = Field(..., gt=0.0)
    frequency_mhz: float = Field(..., gt=0.0)
    k_factor: float = Field(..., gt=0.0)
    has_line_of_sight: bool = Field(
        ..., description="True if all intermediate points have strictly positive vertical clearance"
    )
    fresnel_60pct_clear: bool = Field(
        ..., description="True if minimum clearance ratio across intermediate points >= required fraction (0.60)"
    )
    min_clearance_m: float = Field(..., description="Minimum vertical clearance in meters along path")
    min_clearance_ratio: float = Field(
        ..., description="Minimum clearance-to-F1 ratio across intermediate path points"
    )
    max_knife_edge_nu: float = Field(
        ..., description="Maximum Fresnel-Kirchhoff diffraction parameter nu along path"
    )
    worst_obstruction_point: Optional[ElevationPoint] = Field(
        default=None, description="Intermediate terrain sample with the worst diffraction parameter nu"
    )
    point_analyses: List[FresnelPointAnalysis] = Field(default_factory=list)


def haversine_distance_m(c1: Coordinate, c2: Coordinate) -> float:
    """Calculate great-circle distance in meters between two geodetic coordinates."""
    lat1_rad = math.radians(c1.lat)
    lat2_rad = math.radians(c2.lat)
    dlat_rad = math.radians(c2.lat - c1.lat)
    dlon_rad = math.radians(c2.lon - c1.lon)

    a = (
        math.sin(dlat_rad / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon_rad / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_M * c


def haversine_distance_km(c1: Coordinate, c2: Coordinate) -> float:
    """Calculate great-circle distance in kilometers between two geodetic coordinates."""
    return haversine_distance_m(c1, c2) / 1000.0


def earth_curvature_bulge_m(
    d1_m: float, d2_m: float, k_factor: float = DEFAULT_K_FACTOR
) -> float:
    """Calculate refracted Earth curvature bulge height in meters at an intermediate point.

    Formula:
        h_bulge = (d1 * d2) / (2 * k * R_e)
    """
    if d1_m <= 0.0 or d2_m <= 0.0:
        return 0.0
    if k_factor <= 0.0:
        raise ValueError(f"k_factor must be strictly positive, got {k_factor}")
    return (d1_m * d2_m) / (2.0 * k_factor * EARTH_RADIUS_M)


def first_fresnel_radius_m(
    d1_m: float, d2_m: float, frequency_mhz: float = 915.0
) -> float:
    """Calculate the First Fresnel Zone radius (F1) in meters at an intermediate point.

    Formula:
        F1 = sqrt((lambda * d1 * d2) / (d1 + d2))
        where lambda = c / f
    """
    if frequency_mhz <= 0.0:
        raise ValueError(f"frequency_mhz must be strictly positive, got {frequency_mhz}")
    if d1_m <= 0.0 or d2_m <= 0.0:
        return 0.0
    total_d = d1_m + d2_m
    if total_d <= 0.0:
        return 0.0
    wavelength_m = SPEED_OF_LIGHT_M_S / (frequency_mhz * 1_000_000.0)
    return math.sqrt((wavelength_m * d1_m * d2_m) / total_d)


def radio_horizon_distance_km(
    height_agl_m: float, k_factor: float = DEFAULT_K_FACTOR
) -> float:
    """Calculate analytical radio horizon distance in kilometers for an antenna height.

    Formula:
        d_horizon = sqrt(2 * k * R_e * h) / 1000
    For k = 4/3 and R_e = 6,371,000 m, d_horizon_km ~= 4.1217 * sqrt(h_m).
    """
    if height_agl_m <= 0.0:
        return 0.0
    if k_factor <= 0.0:
        raise ValueError(f"k_factor must be strictly positive, got {k_factor}")
    return math.sqrt(2.0 * k_factor * EARTH_RADIUS_M * height_agl_m) / 1000.0


def knife_edge_diffraction_nu(
    obstruction_height_m: float,
    d1_m: float,
    d2_m: float,
    frequency_mhz: float = 915.0,
) -> float:
    """Calculate the dimensionless Fresnel-Kirchhoff diffraction parameter nu.

    Here obstruction_height_m is h_obs = effective_terrain_height_m - los_height_m
    (positive when terrain blocks the LOS ray, negative when LOS is clear).

    Formula:
        nu = h_obs * sqrt((2 * (d1 + d2)) / (lambda * d1 * d2)) = h_obs * sqrt(2) / F1
    """
    f1 = first_fresnel_radius_m(d1_m, d2_m, frequency_mhz=frequency_mhz)
    if f1 <= 0.0:
        return 0.0
    return obstruction_height_m * math.sqrt(2.0) / f1


def analyze_fresnel_clearance(
    profile: ElevationProfile,
    frequency_mhz: float = 915.0,
    k_factor: float = DEFAULT_K_FACTOR,
    required_clearance_fraction: float = 0.60,
) -> Result[FresnelProfileResult]:
    """Evaluate Line-of-Sight, 4/3 Earth bulge, and First Fresnel Zone clearance across a profile."""
    if frequency_mhz <= 0.0:
        return Result.fail(
            code="INVALID_FREQUENCY",
            message=f"Carrier frequency must be strictly positive, got {frequency_mhz} MHz.",
        )
    if k_factor <= 0.0:
        return Result.fail(
            code="INVALID_K_FACTOR",
            message=f"Refractive k_factor must be strictly positive, got {k_factor}.",
        )
    if len(profile.points) < 2:
        return Result.fail(
            code="INSUFFICIENT_PROFILE_POINTS",
            message=f"ElevationProfile requires at least 2 points, got {len(profile.points)}.",
        )

    total_distance_m = profile.points[-1].distance_m
    if total_distance_m <= 0.0:
        total_distance_m = profile.distance_km * 1000.0
    if total_distance_m <= 0.0:
        return Result.fail(
            code="ZERO_PATH_DISTANCE",
            message="Total path distance between source and target sites must be greater than zero.",
        )

    source_ant_alt_m = (
        profile.points[0].elevation_m + profile.source_site.mast_height_m
    )
    target_ant_alt_m = (
        profile.points[-1].elevation_m + profile.target_site.mast_height_m
    )

    point_analyses: List[FresnelPointAnalysis] = []
    min_clearance_m = float("inf")
    min_clearance_ratio = float("inf")
    max_knife_edge_nu = float("-inf")
    worst_point: Optional[ElevationPoint] = None

    for idx, pt in enumerate(profile.points):
        d1_m = max(0.0, min(pt.distance_m, total_distance_m))
        d2_m = max(0.0, total_distance_m - d1_m)
        frac = d1_m / total_distance_m

        los_height_m = source_ant_alt_m + frac * (target_ant_alt_m - source_ant_alt_m)
        bulge_m = earth_curvature_bulge_m(d1_m, d2_m, k_factor=k_factor)
        eff_terrain_m = pt.elevation_m + bulge_m
        clearance_m = los_height_m - eff_terrain_m
        f1_m = first_fresnel_radius_m(d1_m, d2_m, frequency_mhz=frequency_mhz)

        is_endpoint = idx == 0 or idx == len(profile.points) - 1 or f1_m <= 0.0
        if is_endpoint:
            c_ratio = float("inf") if clearance_m >= 0.0 else float("-inf")
            nu = 0.0
        else:
            c_ratio = clearance_m / f1_m
            h_obs = -clearance_m
            nu = knife_edge_diffraction_nu(
                obstruction_height_m=h_obs,
                d1_m=d1_m,
                d2_m=d2_m,
                frequency_mhz=frequency_mhz,
            )
            if clearance_m < min_clearance_m:
                min_clearance_m = clearance_m
            if c_ratio < min_clearance_ratio:
                min_clearance_ratio = c_ratio
            if nu > max_knife_edge_nu:
                max_knife_edge_nu = nu
                worst_point = pt

        point_analyses.append(
            FresnelPointAnalysis(
                distance_m=d1_m,
                terrain_elevation_m=pt.elevation_m,
                earth_bulge_m=bulge_m,
                effective_terrain_height_m=eff_terrain_m,
                los_height_m=los_height_m,
                clearance_m=clearance_m,
                first_fresnel_radius_m=f1_m,
                clearance_ratio=c_ratio if math.isfinite(c_ratio) else (100.0 if clearance_m >= 0.0 else -100.0),
                knife_edge_nu=nu,
            )
        )

    # Handle case where only 2 endpoints exist (no intermediate points)
    if not math.isfinite(min_clearance_m):
        min_clearance_m = min(
            profile.source_site.mast_height_m, profile.target_site.mast_height_m
        )
        min_clearance_ratio = 1.0 if min_clearance_m > 0.0 else 0.0
        max_knife_edge_nu = -1.0 if min_clearance_m > 0.0 else 0.0

    has_los = min_clearance_m > 0.0
    fresnel_clear = min_clearance_ratio >= required_clearance_fraction

    result = FresnelProfileResult(
        source_id=profile.source_site.site_id,
        target_id=profile.target_site.site_id,
        total_distance_m=total_distance_m,
        frequency_mhz=frequency_mhz,
        k_factor=k_factor,
        has_line_of_sight=has_los,
        fresnel_60pct_clear=fresnel_clear,
        min_clearance_m=min_clearance_m,
        min_clearance_ratio=min_clearance_ratio,
        max_knife_edge_nu=max_knife_edge_nu,
        worst_obstruction_point=worst_point,
        point_analyses=point_analyses,
    )
    return Result.success(result)
