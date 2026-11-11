"""Pure mathematical Multi-Origin Composite Viewshed and Backhaul Matrix Engine for MeshScout.

Aggregates 360-degree radial viewshed polygons across multiple candidate repeater sites,
computes total illuminated coverage footprint, identifies municipal town illumination,
and calculates inter-site microwave/VHF backhaul line-of-sight and link margins.
Follows zero runtime dependencies beyond pydantic>=2.0.0.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from pydantic import BaseModel, Field

from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RadioConfig,
    Result,
    SiteCandidate,
)
from meshscout.core.itm import evaluate_point_to_point_link
from meshscout.core.viewshed import (
    compute_radial_viewshed_polygon,
    haversine_distance_km,
)

# Physical geodesy constant for 4/3 Earth curvature refraction
EFFECTIVE_EARTH_RADIUS_M: float = 6371000.0 * (4.0 / 3.0)


def _synthetic_vermont_elevation_fn(lat: float, lon: float) -> float:
    """Forwarder to deduplicated synthetic Vermont elevation model in elevation adapter."""
    global _synthetic_vermont_elevation_fn
    from meshscout.adapters.elevation import _synthetic_vermont_elevation_fn as _fn

    _synthetic_vermont_elevation_fn = _fn
    return _fn(lat, lon)


def _point_in_polygon(lon: float, lat: float, poly: Sequence[Sequence[float]]) -> bool:
    """Ray casting algorithm to test whether [lon, lat] is inside a polygon ring [[lon, lat], ...]."""
    inside = False
    n = len(poly)
    if n < 3:
        return False
    p1_lon, p1_lat = poly[0][0], poly[0][1]
    for i in range(1, n + 1):
        p2_lon, p2_lat = poly[i % n][0], poly[i % n][1]
        if lat > min(p1_lat, p2_lat):
            if lat <= max(p1_lat, p2_lat):
                if lon <= max(p1_lon, p2_lon):
                    if p1_lat != p2_lat:
                        xinters = (lat - p1_lat) * (p2_lon - p1_lon) / (p2_lat - p1_lat) + p1_lon
                    else:
                        xinters = p1_lon
                    if p1_lon == p2_lon or lon <= xinters:
                        inside = not inside
        p1_lon, p1_lat = p2_lon, p2_lat
    return inside


def _extract_town_info(name_key: str, data: Dict[str, Any]) -> Optional[Tuple[str, float, float]]:
    """Extract (town_name, lat, lon) from varied town dictionary representations."""
    name = str(data.get("name") or name_key)
    if "lat" in data and "lon" in data and data["lat"] is not None and data["lon"] is not None:
        try:
            return name, float(data["lat"]), float(data["lon"])
        except (ValueError, TypeError):
            pass

    if (
        "coordinates" in data
        and isinstance(data["coordinates"], (list, tuple))
        and len(data["coordinates"]) >= 2
    ):
        try:
            # GeoJSON convention: [lon, lat]
            return name, float(data["coordinates"][1]), float(data["coordinates"][0])
        except (ValueError, TypeError):
            pass

    if "coordinate" in data:
        c = data["coordinate"]
        if hasattr(c, "lat") and hasattr(c, "lon"):
            return name, float(c.lat), float(c.lon)
        if isinstance(c, dict) and "lat" in c and "lon" in c:
            try:
                return name, float(c["lat"]), float(c["lon"])
            except (ValueError, TypeError):
                pass

    return None


def _check_direct_line_of_sight(
    origin: SiteCandidate,
    target_lat: float,
    target_lon: float,
    target_elev_m: float,
    elevation_fn: Callable[[float, float], float],
    num_samples: int = 15,
) -> bool:
    """Evaluate if an unobstructed optical line-of-sight ray exists between origin and target point."""
    target_coord = Coordinate(lat=target_lat, lon=target_lon, elevation_m=target_elev_m)
    d_km = haversine_distance_km(origin.location, target_coord)
    if d_km <= 0.0:
        return True

    tx_alt = origin.location.elevation_m + origin.mast_height_m
    rx_alt = target_elev_m + 2.0
    d_total_m = d_km * 1000.0

    target_earth_drop = (d_total_m ** 2) / (2.0 * EFFECTIVE_EARTH_RADIUS_M)
    target_elev_angle = (rx_alt - tx_alt - target_earth_drop) / d_total_m

    for s in range(1, num_samples):
        frac = s / float(num_samples)
        d_m = frac * d_total_m
        lat = origin.location.lat + frac * (target_lat - origin.location.lat)
        lon = origin.location.lon + frac * (target_lon - origin.location.lon)
        terr_elev = float(elevation_fn(lat, lon))
        earth_drop = (d_m ** 2) / (2.0 * EFFECTIVE_EARTH_RADIUS_M)
        elev_angle = (terr_elev - tx_alt - earth_drop) / d_m
        if elev_angle > target_elev_angle:
            return False
    return True


class BackhaulLinkStatus(BaseModel):
    """Pairwise RF backhaul line-of-sight and link margin evaluation between two candidate sites."""

    site_a_id: str
    site_b_id: str
    distance_km: float
    has_line_of_sight: bool
    link_margin_db: float
    fresnel_clearance_ratio: float


class CompositeViewshedResult(BaseModel):
    """Multi-origin composite viewshed coverage, municipal reach, and intersite backhaul analysis."""

    origin_site_ids: List[str]
    individual_polygons: Dict[str, List[List[float]]] = Field(
        default_factory=dict,
        description="Per-site [lon, lat] coordinates forming each site's 360-deg viewshed polygon",
    )
    composite_polygons: List[List[List[float]]] = Field(
        default_factory=list,
        description="List of [lon, lat] coordinate rings for the composite multi-site footprint",
    )
    total_illuminated_area_sq_km: float = Field(
        default=0.0,
        description="Estimated total illuminated ground area in sq km",
    )
    illuminated_towns: List[str] = Field(
        default_factory=list,
        description="List of municipal town names having line-of-sight to at least one origin site",
    )
    intersite_backhaul_links: List[BackhaulLinkStatus] = Field(
        default_factory=list,
        description="Pairwise line-of-sight analysis between the candidate sites",
    )


def compute_composite_viewshed(
    origins: Sequence[SiteCandidate],
    max_range_km: float = 60.0,
    num_radials: int = 72,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
    reference_towns: Optional[Dict[str, Dict[str, Any]]] = None,
    radio_config: Optional[RadioConfig] = None,
) -> Result[CompositeViewshedResult]:
    """Compute combined multi-origin viewshed coverage, illuminated towns, and inter-site backhaul links.

    Args:
        origins: Sequence of candidate high sites / repeaters.
        max_range_km: Maximum radial viewshed ray-cast horizon distance in kilometers.
        num_radials: Number of radial bearings evaluated per site (minimum 8).
        elevation_fn: Optional digital elevation model lookup function (lat, lon) -> elevation_m.
        reference_towns: Optional dictionary of municipal reference town locations.
        radio_config: Optional RF transceiver configuration.

    Returns:
        Result[CompositeViewshedResult] with individual & composite polygons, illuminated towns,
        and pairwise backhaul link statuses.
    """
    if not origins:
        return Result.success(
            CompositeViewshedResult(
                origin_site_ids=[],
                individual_polygons={},
                composite_polygons=[],
                total_illuminated_area_sq_km=0.0,
                illuminated_towns=[],
                intersite_backhaul_links=[],
            )
        )

    active_elevation_fn: Callable[[float, float], float] = (
        elevation_fn if elevation_fn is not None else _synthetic_vermont_elevation_fn
    )
    active_radio = radio_config if radio_config is not None else RadioConfig()

    origin_site_ids: List[str] = [site.site_id for site in origins]
    individual_polygons: Dict[str, List[List[float]]] = {}
    composite_polygons: List[List[List[float]]] = []
    site_areas_sq_km: List[float] = []

    # 1. Compute radial viewshed polygon for each candidate site
    for site in origins:
        res = compute_radial_viewshed_polygon(
            origin=site,
            num_radials=num_radials,
            max_range_km=max_range_km,
            radio=active_radio,
            elevation_fn=active_elevation_fn,
        )
        if not res.ok or res.value is None:
            continue

        # Convert [lat, lon] to GeoJSON standard [lon, lat] coordinates
        poly_lon_lat: List[List[float]] = [[pt[1], pt[0]] for pt in res.value.los_polygon]
        individual_polygons[site.site_id] = poly_lon_lat
        composite_polygons.append(poly_lon_lat)
        site_areas_sq_km.append(res.value.los_area_sq_km)

    # 2. Aggregate composite footprint area with overlap deduplication
    raw_area_sum = sum(site_areas_sq_km)
    if len(origins) <= 1:
        total_illuminated_area_sq_km = round(raw_area_sum, 1)
    else:
        # Check pairwise distances between origin sites
        has_near_pair = False
        for i in range(len(origins)):
            for j in range(i + 1, len(origins)):
                d = haversine_distance_km(origins[i].location, origins[j].location)
                if d < (1.5 * max_range_km):
                    has_near_pair = True
                    break
            if has_near_pair:
                break

        # Standard multi-site overlap factor discount for adjacent/co-regional sites
        overlap_factor = 0.85 if has_near_pair else 1.0
        total_illuminated_area_sq_km = round(raw_area_sum * overlap_factor, 1)

    # 3. Evaluate inter-site microwave / VHF backhaul links
    intersite_backhaul_links: List[BackhaulLinkStatus] = []
    for i in range(len(origins)):
        for j in range(i + 1, len(origins)):
            site_a = origins[i]
            site_b = origins[j]

            dist_km = haversine_distance_km(site_a.location, site_b.location)
            if dist_km <= 0.0:
                intersite_backhaul_links.append(
                    BackhaulLinkStatus(
                        site_a_id=site_a.site_id,
                        site_b_id=site_b.site_id,
                        distance_km=0.0,
                        has_line_of_sight=True,
                        link_margin_db=99.0,
                        fresnel_clearance_ratio=1.0,
                    )
                )
                continue

            # Build intermediate elevation profile transect
            total_d_m = dist_km * 1000.0
            num_samples = max(20, min(100, int(dist_km * 2)))
            points: List[ElevationPoint] = []

            for s in range(num_samples + 1):
                frac = s / float(num_samples)
                lat = site_a.location.lat + frac * (site_b.location.lat - site_a.location.lat)
                lon = site_a.location.lon + frac * (site_b.location.lon - site_a.location.lon)
                elev = float(active_elevation_fn(lat, lon))
                pt_coord = Coordinate(
                    lat=round(lat, 6),
                    lon=round(lon, 6),
                    elevation_m=round(elev, 2),
                )
                points.append(
                    ElevationPoint(
                        distance_m=round(frac * total_d_m, 2),
                        elevation_m=round(elev, 2),
                        coordinate=pt_coord,
                    )
                )

            profile = ElevationProfile(
                source_site=site_a,
                target_site=site_b,
                distance_km=round(dist_km, 4),
                points=points,
            )

            link_res = evaluate_point_to_point_link(profile=profile, radio=active_radio)
            if link_res.ok and link_res.value is not None:
                intersite_backhaul_links.append(
                    BackhaulLinkStatus(
                        site_a_id=site_a.site_id,
                        site_b_id=site_b.site_id,
                        distance_km=round(link_res.value.distance_km, 3),
                        has_line_of_sight=link_res.value.has_line_of_sight,
                        link_margin_db=round(link_res.value.link_margin_db, 2),
                        fresnel_clearance_ratio=round(link_res.value.fresnel_clearance_ratio, 3),
                    )
                )
            else:
                intersite_backhaul_links.append(
                    BackhaulLinkStatus(
                        site_a_id=site_a.site_id,
                        site_b_id=site_b.site_id,
                        distance_km=round(dist_km, 3),
                        has_line_of_sight=False,
                        link_margin_db=-99.0,
                        fresnel_clearance_ratio=0.0,
                    )
                )

    # 4. Determine municipal reference town illumination
    towns_data: Dict[str, Dict[str, Any]] = reference_towns if reference_towns is not None else {}
    if reference_towns is None:
        try:
            from meshscout.adapters.geodata import VERMONT_REFERENCE_TOWNS_DATA

            towns_data = VERMONT_REFERENCE_TOWNS_DATA
        except ImportError:
            towns_data = {}

    illuminated_towns_set: set[str] = set()

    for town_key, tdata in towns_data.items():
        info = _extract_town_info(town_key, tdata)
        if info is None:
            continue
        town_name, t_lat, t_lon = info

        # Check against all origin sites
        is_illuminated = False
        for site in origins:
            poly = individual_polygons.get(site.site_id)
            if poly and _point_in_polygon(t_lon, t_lat, poly):
                is_illuminated = True
                break

            # Fallback check if within max_range_km with direct line of sight
            d_to_site = haversine_distance_km(
                site.location, Coordinate(lat=t_lat, lon=t_lon, elevation_m=0.0)
            )
            if d_to_site <= max_range_km:
                t_elev = float(tdata.get("elevation_m") or active_elevation_fn(t_lat, t_lon))
                if _check_direct_line_of_sight(
                    origin=site,
                    target_lat=t_lat,
                    target_lon=t_lon,
                    target_elev_m=t_elev,
                    elevation_fn=active_elevation_fn,
                ):
                    is_illuminated = True
                    break

        if is_illuminated:
            illuminated_towns_set.add(town_name)

    illuminated_towns = sorted(list(illuminated_towns_set))

    return Result.success(
        CompositeViewshedResult(
            origin_site_ids=origin_site_ids,
            individual_polygons=individual_polygons,
            composite_polygons=composite_polygons,
            total_illuminated_area_sq_km=total_illuminated_area_sq_km,
            illuminated_towns=illuminated_towns,
            intersite_backhaul_links=intersite_backhaul_links,
        )
    )
