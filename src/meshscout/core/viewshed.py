"""Pure mathematical Point-to-Multipoint Valley Basin Viewshed Engine for MeshScout.

Implements terrain-aware viewshed analysis along radial transects from a repeater
candidate to target basin grid points. Computes great-circle distances, intermediate
geodesic interpolation, 4/3 Earth curvature bulge, First Fresnel zone clearance,
knife-edge diffraction loss, and link margin coverage fractions without any I/O.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence
from pydantic import BaseModel, Field

from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RadioConfig,
    RegionalBounds,
    Result,
    SiteCandidate,
)

# Physical constants for RF propagation and geodesy
EARTH_RADIUS_KM: float = 6371.0
EFFECTIVE_EARTH_RADIUS_M: float = 6371000.0 * (4.0 / 3.0)  # k = 4/3 atmospheric refraction
SPEED_OF_LIGHT_M_S: float = 299792458.0


class TargetGridPoint(BaseModel):
    """A discrete receiver location in the target basin or valley floor."""

    target_id: str = Field(..., min_length=1, description="Unique identifier for the target point")
    coordinate: Coordinate
    rx_height_m: float = Field(default=2.0, ge=0.0, description="Receiver antenna height above ground in meters")
    population_weight: float = Field(
        default=1.0, gt=0.0, description="Relative population or priority importance weight"
    )


class TargetCoveragePoint(BaseModel):
    """Evaluated RF coverage metrics at a single target grid point."""

    target_id: str
    coordinate: Coordinate
    distance_km: float = Field(..., ge=0.0)
    has_line_of_sight: bool
    fresnel_clearance_ratio: float
    estimated_rx_dbm: float
    link_margin_db: float
    is_covered: bool


class ViewshedResult(BaseModel):
    """Aggregated point-to-multipoint viewshed coverage report for a candidate repeater."""

    repeater: SiteCandidate
    total_targets: int = Field(..., ge=0)
    covered_targets: int = Field(..., ge=0)
    coverage_fraction: float = Field(..., ge=0.0, le=1.0)
    weighted_coverage_fraction: float = Field(..., ge=0.0, le=1.0)
    target_results: List[TargetCoveragePoint] = Field(default_factory=list)
    covered_target_ids: List[str] = Field(default_factory=list)
    shadowed_target_ids: List[str] = Field(default_factory=list)


def haversine_distance_km(c1: Coordinate, c2: Coordinate) -> float:
    """Calculate the great-circle distance in kilometers between two coordinates."""
    lat1_rad = math.radians(c1.lat)
    lat2_rad = math.radians(c2.lat)
    dlat_rad = math.radians(c2.lat - c1.lat)
    dlon_rad = math.radians(c2.lon - c1.lon)

    a = (
        math.sin(dlat_rad / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon_rad / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_KM * c


def generate_target_grid(
    bounds: RegionalBounds,
    lat_steps: int = 5,
    lon_steps: int = 5,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    rx_height_m: float = 2.0,
    weight_fn: Optional[Callable[[float, float], float]] = None,
) -> Result[List[TargetGridPoint]]:
    """Generate a regular grid of TargetGridPoints across a RegionalBounds box.

    Args:
        bounds: Regional bounding box.
        lat_steps: Number of latitude grid divisions (>= 1).
        lon_steps: Number of longitude grid divisions (>= 1).
        elevation_fn: Optional pure function `(lat, lon) -> elevation_m` (defaults to 0.0m).
        rx_height_m: Receiver antenna height above ground in meters.
        weight_fn: Optional pure function `(lat, lon) -> population_weight` (defaults to 1.0).

    Returns:
        Result containing the list of generated TargetGridPoint instances.
    """
    if lat_steps < 1 or lon_steps < 1:
        return Result.fail(
            code="INVALID_GRID_DIMENSIONS",
            message=f"Grid steps must be >= 1 (got lat_steps={lat_steps}, lon_steps={lon_steps})",
        )

    points: List[TargetGridPoint] = []
    for i in range(lat_steps):
        lat_frac = 0.5 if lat_steps == 1 else i / (lat_steps - 1)
        lat = bounds.min_lat + lat_frac * (bounds.max_lat - bounds.min_lat)
        for j in range(lon_steps):
            lon_frac = 0.5 if lon_steps == 1 else j / (lon_steps - 1)
            lon = bounds.min_lon + lon_frac * (bounds.max_lon - bounds.min_lon)
            elev = float(elevation_fn(lat, lon)) if elevation_fn is not None else 0.0
            weight = float(weight_fn(lat, lon)) if weight_fn is not None else 1.0
            if weight <= 0.0:
                weight = 1.0
            points.append(
                TargetGridPoint(
                    target_id=f"GRID-{i:02d}-{j:02d}",
                    coordinate=Coordinate(lat=round(lat, 6), lon=round(lon, 6), elevation_m=elev),
                    rx_height_m=rx_height_m,
                    population_weight=weight,
                )
            )

    return Result.success(points)


def sample_transect_points(
    source_coord: Coordinate,
    target_coord: Coordinate,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    num_samples: int = 25,
) -> List[ElevationPoint]:
    """Sample intermediate terrain elevation points along the great-circle path.

    Endpoints use the exact elevation of `source_coord` and `target_coord`.
    Intermediate points query `elevation_fn(lat, lon)` when provided, or use a
    concave valley-basin profile `frac**2` between the low valley floor and high site
    when `elevation_fn` is None.
    """
    total_dist_m = haversine_distance_km(source_coord, target_coord) * 1000.0
    steps = max(2, num_samples)
    sampled: List[ElevationPoint] = []
    min_elev = min(source_coord.elevation_m, target_coord.elevation_m)
    max_elev = max(source_coord.elevation_m, target_coord.elevation_m)

    for idx in range(steps):
        frac = idx / (steps - 1)
        lat = source_coord.lat + frac * (target_coord.lat - source_coord.lat)
        lon = source_coord.lon + frac * (target_coord.lon - source_coord.lon)
        dist_m = frac * total_dist_m

        if idx == 0:
            elev = source_coord.elevation_m
        elif idx == steps - 1:
            elev = target_coord.elevation_m
        elif elevation_fn is not None:
            elev = float(elevation_fn(lat, lon))
        else:
            # Concave valley floor profile when no custom DEM callable is supplied
            if source_coord.elevation_m >= target_coord.elevation_m:
                elev = min_elev + (max_elev - min_elev) * ((1.0 - frac) ** 2.2)
            else:
                elev = min_elev + (max_elev - min_elev) * (frac ** 2.2)

        sampled.append(
            ElevationPoint(
                distance_m=dist_m,
                elevation_m=elev,
                coordinate=Coordinate(lat=lat, lon=lon, elevation_m=elev),
            )
        )

    return sampled


def _knife_edge_diffraction_db(nu: float) -> float:
    """Compute ITU-R P.526 single knife-edge diffraction loss in dB from parameter nu."""
    if nu <= -0.78:
        return 0.0
    inner = math.sqrt((nu - 0.1) ** 2 + 1.0) + nu - 0.1
    if inner <= 0.0:
        return 0.0
    return max(0.0, 6.9 + 20.0 * math.log10(inner))


def _free_space_path_loss_db(distance_km: float, frequency_mhz: float) -> float:
    """Compute Free-Space Path Loss (FSPL) in dB."""
    if distance_km <= 1e-6:
        return 0.0
    return 32.44 + 20.0 * math.log10(distance_km) + 20.0 * math.log10(frequency_mhz)


def evaluate_target_coverage(
    repeater: SiteCandidate,
    target: TargetGridPoint,
    radio: RadioConfig,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    profile: Optional[ElevationProfile] = None,
    num_samples: int = 25,
    min_margin_db: float = 6.0,
    require_los: bool = False,
) -> TargetCoveragePoint:
    """Evaluate point-to-point terrain viewshed and RF link margin from repeater to target."""
    if profile is not None and len(profile.points) >= 2:
        points = profile.points
        distance_km = (
            profile.distance_km
            if profile.distance_km > 0.0
            else haversine_distance_km(repeater.location, target.coordinate)
        )
    else:
        distance_km = haversine_distance_km(repeater.location, target.coordinate)
        points = sample_transect_points(
            source_coord=repeater.location,
            target_coord=target.coordinate,
            elevation_fn=elevation_fn,
            num_samples=num_samples,
        )

    total_dist_m = distance_km * 1000.0
    wavelength_m = SPEED_OF_LIGHT_M_S / (radio.frequency_mhz * 1e6)

    tx_alt_m = repeater.location.elevation_m + repeater.mast_height_m
    rx_alt_m = target.coordinate.elevation_m + target.rx_height_m

    # Co-located or very close target point
    if total_dist_m <= 1.0 or len(points) < 2:
        rx_power_dbm = radio.tx_power_dbm + 2.0 * radio.antenna_gain_dbi - 2.0 * radio.cable_loss_db
        link_margin_db = rx_power_dbm - radio.rx_sensitivity_dbm
        is_covered = link_margin_db >= min_margin_db
        return TargetCoveragePoint(
            target_id=target.target_id,
            coordinate=target.coordinate,
            distance_km=round(distance_km, 4),
            has_line_of_sight=True,
            fresnel_clearance_ratio=1.0,
            estimated_rx_dbm=round(rx_power_dbm, 2),
            link_margin_db=round(link_margin_db, 2),
            is_covered=is_covered,
        )

    min_fresnel_ratio = float("inf")
    max_nu = -float("inf")
    has_los = True

    # Evaluate intermediate terrain samples for Earth bulge and Fresnel obstruction
    interior_points = points[1:-1]
    for pt in interior_points:
        d1 = pt.distance_m
        d2 = total_dist_m - d1
        if d1 <= 0.0 or d2 <= 0.0:
            continue

        frac = d1 / total_dist_m
        los_height_m = tx_alt_m + frac * (rx_alt_m - tx_alt_m)
        earth_bulge_m = (d1 * d2) / (2.0 * EFFECTIVE_EARTH_RADIUS_M)
        effective_terrain_m = pt.elevation_m + earth_bulge_m

        # Clearance is positive when LOS ray is above effective terrain
        clearance_m = los_height_m - effective_terrain_m
        if clearance_m < 0.0:
            has_los = False

        fresnel_r1_m = math.sqrt((wavelength_m * d1 * d2) / total_dist_m)
        if fresnel_r1_m > 0.0:
            ratio = clearance_m / fresnel_r1_m
            if ratio < min_fresnel_ratio:
                min_fresnel_ratio = ratio

        # Fresnel-Kirchhoff diffraction parameter nu (positive when obstructed)
        obstruction_h = -clearance_m
        nu = obstruction_h * math.sqrt((2.0 * total_dist_m) / (wavelength_m * d1 * d2))
        if nu > max_nu:
            max_nu = nu

    if min_fresnel_ratio == float("inf"):
        min_fresnel_ratio = 1.0
    if max_nu == -float("inf"):
        max_nu = -2.0

    fspl_db = _free_space_path_loss_db(distance_km, radio.frequency_mhz)
    diffraction_db = _knife_edge_diffraction_db(max_nu)
    total_loss_db = fspl_db + diffraction_db + radio.environmental_clutter_db

    rx_power_dbm = (
        radio.tx_power_dbm
        + 2.0 * radio.antenna_gain_dbi
        - 2.0 * radio.cable_loss_db
        - total_loss_db
    )
    link_margin_db = rx_power_dbm - radio.rx_sensitivity_dbm

    if require_los:
        is_covered = has_los and (link_margin_db >= min_margin_db)
    else:
        is_covered = link_margin_db >= min_margin_db

    return TargetCoveragePoint(
        target_id=target.target_id,
        coordinate=target.coordinate,
        distance_km=round(distance_km, 4),
        has_line_of_sight=has_los,
        fresnel_clearance_ratio=round(min_fresnel_ratio, 4),
        estimated_rx_dbm=round(rx_power_dbm, 2),
        link_margin_db=round(link_margin_db, 2),
        is_covered=is_covered,
    )


def compute_viewshed(
    repeater: SiteCandidate,
    targets: Sequence[TargetGridPoint],
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    profiles_by_target: Optional[Dict[str, ElevationProfile]] = None,
    radio: Optional[RadioConfig] = None,
    min_margin_db: float = 6.0,
    require_los: bool = False,
    num_samples: int = 25,
) -> Result[ViewshedResult]:
    """Compute a Point-to-Multipoint viewshed coverage report from a repeater across target points.

    Args:
        repeater: Candidate repeater high-site.
        targets: Non-empty sequence of TargetGridPoints representing valley/basin locations.
        elevation_fn: Optional pure terrain elevation function `(lat, lon) -> elevation_m`.
        profiles_by_target: Optional lookup of precomputed ElevationProfiles keyed by `target_id`.
        radio: RF hardware parameters (defaults to standard 915 MHz LoRa configuration).
        min_margin_db: Minimum required link margin in dB to classify a point as covered.
        require_los: If True, requires unobstructed optical/radio LOS in addition to link margin.
        num_samples: Number of intermediate transect samples when sampling via `elevation_fn`.

    Returns:
        Result[ViewshedResult] with individual target metrics and coverage fractions.
    """
    if not targets:
        return Result.fail(
            code="EMPTY_TARGET_GRID",
            message="Cannot compute viewshed: targets sequence must contain at least one TargetGridPoint.",
        )

    if num_samples < 2:
        return Result.fail(
            code="INVALID_SAMPLE_COUNT",
            message=f"num_samples must be >= 2 (got {num_samples}).",
        )

    active_radio = radio if radio is not None else RadioConfig()
    profile_map = profiles_by_target or {}

    target_results: List[TargetCoveragePoint] = []
    covered_ids: List[str] = []
    shadowed_ids: List[str] = []
    total_weight = 0.0
    covered_weight = 0.0

    for target in targets:
        prof = profile_map.get(target.target_id)
        cov = evaluate_target_coverage(
            repeater=repeater,
            target=target,
            radio=active_radio,
            elevation_fn=elevation_fn,
            profile=prof,
            num_samples=num_samples,
            min_margin_db=min_margin_db,
            require_los=require_los,
        )
        target_results.append(cov)
        total_weight += target.population_weight

        if cov.is_covered:
            covered_ids.append(target.target_id)
            covered_weight += target.population_weight
        else:
            shadowed_ids.append(target.target_id)

    total_targets = len(targets)
    covered_targets = len(covered_ids)
    coverage_fraction = covered_targets / total_targets
    weighted_coverage_fraction = covered_weight / total_weight if total_weight > 0.0 else 0.0

    return Result.success(
        ViewshedResult(
            repeater=repeater,
            total_targets=total_targets,
            covered_targets=covered_targets,
            coverage_fraction=round(coverage_fraction, 4),
            weighted_coverage_fraction=round(weighted_coverage_fraction, 4),
            target_results=target_results,
            covered_target_ids=covered_ids,
            shadowed_target_ids=shadowed_ids,
        )
    )


class RadialViewshedPolygonResult(BaseModel):
    """360-degree elevation-occluded radial viewshed footprint."""

    origin_site_id: str
    origin_coordinate: Coordinate
    origin_total_height_m: float
    num_radials: int
    max_range_km: float
    radio_horizon_km: float
    los_polygon: List[List[float]] = Field(
        ..., description="Outer vertices [lat, lon] of line-of-sight perimeter"
    )
    diffracted_polygon: List[List[float]] = Field(
        ..., description="Outer vertices [lat, lon] of diffracted (0dB margin) perimeter"
    )
    los_area_sq_km: float = Field(default=0.0)
    diffracted_area_sq_km: float = Field(default=0.0)


def compute_radial_viewshed_polygon(
    origin: SiteCandidate,
    num_radials: int = 72,
    max_range_km: float = 60.0,
    radio: Optional[RadioConfig] = None,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    min_margin_db: float = 0.0,
    distance_steps: int = 30,
) -> Result[RadialViewshedPolygonResult]:
    """Compute a 360-degree elevation-occluded coverage polygon using radial horizon ray-casting.

    For each radial bearing, casts a ray outward from the transmitter to its radio horizon,
    evaluating terrain elevation, 4/3 Earth curvature, and intermediate ridge obstructions.
    Identifies the exact distance where line-of-sight is severed and where diffracted
    link margin drops below min_margin_db, returning closed boundary polygons.
    """
    if num_radials < 8:
        num_radials = 8

    active_radio = radio if radio is not None else RadioConfig()
    coord = origin.location
    tx_alt_m = max(1.0, coord.elevation_m + origin.mast_height_m)

    # Radio horizon calculation for TX + standard 2m RX
    d_tx_horiz_km = math.sqrt(2.0 * EFFECTIVE_EARTH_RADIUS_M * tx_alt_m) / 1000.0
    d_rx_horiz_km = math.sqrt(2.0 * EFFECTIVE_EARTH_RADIUS_M * 2.0) / 1000.0
    radio_horiz_km = round(d_tx_horiz_km + d_rx_horiz_km, 2)
    effective_max_km = min(max_range_km, max(12.0, radio_horiz_km))

    los_poly: List[List[float]] = []
    diff_poly: List[List[float]] = []
    delta_rad = (2.0 * math.pi) / num_radials
    los_area_sum = 0.0
    diff_area_sum = 0.0

    steps = max(10, distance_steps)
    step_km = effective_max_km / steps
    cos_origin_lat = max(0.2, math.cos(math.radians(coord.lat)))

    for r_idx in range(num_radials):
        az_deg = (360.0 / num_radials) * r_idx
        az_rad = math.radians(az_deg)
        sin_az = math.sin(az_rad)
        cos_az = math.cos(az_rad)

        max_horizon_elev_angle = -1e9
        d_ridge_m = 0.0
        los_cutoff_km = effective_max_km
        diff_cutoff_km = effective_max_km

        for s_idx in range(1, steps + 1):
            dist_km = s_idx * step_km
            d_m = dist_km * 1000.0

            pt_lat = coord.lat + (dist_km / 111.32) * cos_az
            pt_lon = coord.lon + (dist_km / (111.32 * cos_origin_lat)) * sin_az

            if elevation_fn is not None:
                terr_elev_m = float(elevation_fn(pt_lat, pt_lon))
            else:
                # Default terrain profile when no DEM callable is supplied:
                # Slight regional valley floor with distance-decaying slope
                terr_elev_m = max(20.0, coord.elevation_m * max(0.1, 1.0 - (dist_km / effective_max_km) ** 1.5))

            earth_drop_m = (d_m ** 2) / (2.0 * EFFECTIVE_EARTH_RADIUS_M)
            terrain_angle = (terr_elev_m - tx_alt_m - earth_drop_m) / d_m

            rx_alt_m = terr_elev_m + 2.0
            rx_elev_angle = (rx_alt_m - tx_alt_m - earth_drop_m) / d_m

            # Check if this point is in the geometric shadow of an intermediate peak
            if rx_elev_angle < max_horizon_elev_angle and d_ridge_m > 0.0:
                if los_cutoff_km == effective_max_km:
                    los_cutoff_km = max(0.5, dist_km - step_km)

                # Bullington / knife-edge diffraction past the horizon ridge
                obs_drop_m = (max_horizon_elev_angle - rx_elev_angle) * d_m
                wavelength_m = SPEED_OF_LIGHT_M_S / (active_radio.frequency_mhz * 1e6)
                d1_m = max(10.0, d_ridge_m)
                d2_m = max(10.0, d_m - d_ridge_m)
                nu = obs_drop_m * math.sqrt((2.0 * d_m) / (wavelength_m * d1_m * d2_m))
                diff_loss_db = _knife_edge_diffraction_db(nu)
                fspl_db = _free_space_path_loss_db(dist_km, active_radio.frequency_mhz)
                total_loss_db = fspl_db + diff_loss_db + active_radio.environmental_clutter_db
                rx_power_dbm = (
                    active_radio.tx_power_dbm
                    + 2.0 * active_radio.antenna_gain_dbi
                    - 2.0 * active_radio.cable_loss_db
                    - total_loss_db
                )
                margin_db = rx_power_dbm - active_radio.rx_sensitivity_dbm
                if margin_db < min_margin_db and diff_cutoff_km == effective_max_km:
                    diff_cutoff_km = dist_km
            else:
                # Test FSPL cutoff even if unblocked
                fspl_db = _free_space_path_loss_db(dist_km, active_radio.frequency_mhz)
                margin_db = (
                    active_radio.tx_power_dbm
                    + 2.0 * active_radio.antenna_gain_dbi
                    - 2.0 * active_radio.cable_loss_db
                    - fspl_db
                    - active_radio.environmental_clutter_db
                    - active_radio.rx_sensitivity_dbm
                )
                if margin_db < min_margin_db:
                    if los_cutoff_km == effective_max_km:
                        los_cutoff_km = dist_km
                    if diff_cutoff_km == effective_max_km:
                        diff_cutoff_km = dist_km

            if terrain_angle > max_horizon_elev_angle:
                max_horizon_elev_angle = terrain_angle
                d_ridge_m = d_m

        # Convert cutoffs to coordinates
        los_lat = coord.lat + (los_cutoff_km / 111.32) * cos_az
        los_lon = coord.lon + (los_cutoff_km / (111.32 * cos_origin_lat)) * sin_az
        los_poly.append([round(los_lat, 5), round(los_lon, 5)])
        los_area_sum += 0.5 * (los_cutoff_km ** 2) * delta_rad

        diff_lat = coord.lat + (diff_cutoff_km / 111.32) * cos_az
        diff_lon = coord.lon + (diff_cutoff_km / (111.32 * cos_origin_lat)) * sin_az
        diff_poly.append([round(diff_lat, 5), round(diff_lon, 5)])
        diff_area_sum += 0.5 * (diff_cutoff_km ** 2) * delta_rad

    if los_poly and los_poly[0] != los_poly[-1]:
        los_poly.append(list(los_poly[0]))
    if diff_poly and diff_poly[0] != diff_poly[-1]:
        diff_poly.append(list(diff_poly[0]))

    return Result.success(
        RadialViewshedPolygonResult(
            origin_site_id=origin.site_id,
            origin_coordinate=coord,
            origin_total_height_m=round(tx_alt_m, 1),
            num_radials=num_radials,
            max_range_km=round(effective_max_km, 1),
            radio_horizon_km=radio_horiz_km,
            los_polygon=los_poly,
            diffracted_polygon=diff_poly,
            los_area_sq_km=round(los_area_sum, 1),
            diffracted_area_sq_km=round(diff_area_sum, 1),
        )
    )
