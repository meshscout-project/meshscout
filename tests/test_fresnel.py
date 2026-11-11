"""Unit tests for meshscout.core.fresnel mathematical LOS, Earth bulge, and Fresnel analysis."""

from __future__ import annotations

import math
import pytest

from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    SiteCandidate,
    SiteType,
)
from meshscout.core.fresnel import (
    EARTH_RADIUS_M,
    SPEED_OF_LIGHT_M_S,
    analyze_fresnel_clearance,
    earth_curvature_bulge_m,
    first_fresnel_radius_m,
    haversine_distance_km,
    haversine_distance_m,
    knife_edge_diffraction_nu,
    radio_horizon_distance_km,
)


def _make_site(site_id: str, name: str, lat: float, lon: float, elev_m: float, mast_m: float = 6.0) -> SiteCandidate:
    return SiteCandidate(
        site_id=site_id,
        name=name,
        location=Coordinate(lat=lat, lon=lon, elevation_m=elev_m),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=mast_m,
    )


def test_haversine_distance_accuracy() -> None:
    """Verify great-circle Haversine distance between Mount Mansfield and Essex Junction."""
    mansfield = Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0)
    essex_jct = Coordinate(lat=44.4906, lon=-73.1112, elevation_m=105.0)

    dist_km = haversine_distance_km(mansfield, essex_jct)
    dist_m = haversine_distance_m(mansfield, essex_jct)

    assert math.isclose(dist_m, dist_km * 1000.0, rel_tol=1e-9)
    # Distance between Mansfield and Essex Jct is ~24.3 km
    assert 23.5 <= dist_km <= 25.0
    assert haversine_distance_m(mansfield, mansfield) == 0.0


@pytest.mark.parametrize("total_km", [10.0, 20.0, 50.0])
def test_earth_curvature_bulge_midpoint_and_symmetry(total_km: float) -> None:
    """Verify Earth bulge calculation at 10km, 20km, 50km with k=4/3 vs k=1.0 and symmetry."""
    total_m = total_km * 1000.0
    mid_m = total_m / 2.0

    bulge_k43 = earth_curvature_bulge_m(mid_m, mid_m, k_factor=4.0 / 3.0)
    bulge_k10 = earth_curvature_bulge_m(mid_m, mid_m, k_factor=1.0)

    expected_k43 = (mid_m * mid_m) / (2.0 * (4.0 / 3.0) * EARTH_RADIUS_M)
    expected_k10 = (mid_m * mid_m) / (2.0 * 1.0 * EARTH_RADIUS_M)

    assert math.isclose(bulge_k43, expected_k43, rel_tol=1e-9)
    assert math.isclose(bulge_k10, expected_k10, rel_tol=1e-9)
    # Refraction (k=4/3) reduces apparent Earth curvature bulge by 3/4 compared to k=1.0
    assert math.isclose(bulge_k43 / bulge_k10, 0.75, rel_tol=1e-9)

    # Symmetry check at 25% / 75%
    d1 = total_m * 0.25
    d2 = total_m * 0.75
    assert math.isclose(
        earth_curvature_bulge_m(d1, d2),
        earth_curvature_bulge_m(d2, d1),
        rel_tol=1e-12,
    )
    # Endpoints have zero bulge
    assert earth_curvature_bulge_m(0.0, total_m) == 0.0
    assert earth_curvature_bulge_m(total_m, 0.0) == 0.0


def test_first_fresnel_radius_915_and_868_mhz() -> None:
    """Verify First Fresnel zone radius at 915 MHz (US915) and 868 MHz (EU868)."""
    d1_m = 5000.0
    d2_m = 5000.0

    f1_915 = first_fresnel_radius_m(d1_m, d2_m, frequency_mhz=915.0)
    f1_868 = first_fresnel_radius_m(d1_m, d2_m, frequency_mhz=868.0)

    lambda_915 = SPEED_OF_LIGHT_M_S / 915_000_000.0
    expected_915 = math.sqrt((lambda_915 * d1_m * d2_m) / (d1_m + d2_m))
    assert math.isclose(f1_915, expected_915, rel_tol=1e-9)
    # At 10 km total (5 km midpoint) and 915 MHz, F1 is ~28.62 m
    assert math.isclose(f1_915, 28.62, abs_tol=0.05)

    # Lower frequency (868 MHz) has longer wavelength -> wider Fresnel zone than 915 MHz
    assert f1_868 > f1_915

    # Asymmetric distance symmetry
    assert math.isclose(
        first_fresnel_radius_m(2000.0, 8000.0, frequency_mhz=915.0),
        first_fresnel_radius_m(8000.0, 2000.0, frequency_mhz=915.0),
        rel_tol=1e-12,
    )
    assert first_fresnel_radius_m(0.0, 10000.0, frequency_mhz=915.0) == 0.0


@pytest.mark.parametrize("height_m", [2.0, 10.0, 25.0, 100.0, 1000.0])
def test_radio_horizon_benchmark_parity(height_m: float) -> None:
    """Verify analytical radio horizon matches the standard ~4.12 * sqrt(h_m) km formula."""
    horizon_km = radio_horizon_distance_km(height_m, k_factor=4.0 / 3.0)
    approx_km = 4.1217 * math.sqrt(height_m)
    assert math.isclose(horizon_km, approx_km, rel_tol=1e-3)
    assert radio_horizon_distance_km(0.0) == 0.0


def test_analyze_fresnel_unobstructed_mansfield_to_essex() -> None:
    """Verify unobstructed mountain-to-valley profile passes LOS and 60% Fresnel clearance."""
    source = _make_site("VT-MANS-01", "Mount Mansfield", 44.5437, -72.8143, 1339.0, mast_m=6.0)
    target = _make_site("VT-ESSX-01", "Essex Junction Hub", 44.4906, -73.1112, 105.0, mast_m=6.0)

    total_m = 24000.0
    points = [
        ElevationPoint(
            distance_m=0.0,
            elevation_m=1339.0,
            coordinate=source.location,
        ),
        ElevationPoint(
            distance_m=6000.0,
            elevation_m=650.0,
            coordinate=Coordinate(lat=44.53, lon=-72.89, elevation_m=650.0),
        ),
        ElevationPoint(
            distance_m=12000.0,
            elevation_m=280.0,
            coordinate=Coordinate(lat=44.51, lon=-72.96, elevation_m=280.0),
        ),
        ElevationPoint(
            distance_m=18000.0,
            elevation_m=160.0,
            coordinate=Coordinate(lat=44.50, lon=-73.04, elevation_m=160.0),
        ),
        ElevationPoint(
            distance_m=total_m,
            elevation_m=105.0,
            coordinate=target.location,
        ),
    ]
    profile = ElevationProfile(
        source_site=source,
        target_site=target,
        distance_km=total_m / 1000.0,
        points=points,
    )

    res = analyze_fresnel_clearance(profile, frequency_mhz=915.0)
    assert res.ok is True
    assert res.value is not None

    val = res.value
    assert val.has_line_of_sight is True
    assert val.fresnel_60pct_clear is True
    assert val.min_clearance_m > 100.0
    assert val.min_clearance_ratio >= 0.60
    assert val.max_knife_edge_nu < 0.0
    assert len(val.point_analyses) == 5


def test_analyze_fresnel_obstructed_central_ridge() -> None:
    """Verify obstructed profile with central ridge blocking LOS yields negative clearance and positive nu."""
    source = _make_site("VT-VAL-01", "Valley West", 44.45, -73.10, 120.0, mast_m=5.0)
    target = _make_site("VT-VAL-02", "Valley East", 44.45, -72.95, 120.0, mast_m=5.0)

    total_m = 10000.0
    ridge_point = ElevationPoint(
        distance_m=5000.0,
        elevation_m=210.0,  # 85m above the 125m LOS ray
        coordinate=Coordinate(lat=44.45, lon=-73.025, elevation_m=210.0),
    )
    points = [
        ElevationPoint(distance_m=0.0, elevation_m=120.0, coordinate=source.location),
        ElevationPoint(
            distance_m=2500.0,
            elevation_m=115.0,
            coordinate=Coordinate(lat=44.45, lon=-73.06, elevation_m=115.0),
        ),
        ridge_point,
        ElevationPoint(
            distance_m=7500.0,
            elevation_m=118.0,
            coordinate=Coordinate(lat=44.45, lon=-72.99, elevation_m=118.0),
        ),
        ElevationPoint(distance_m=total_m, elevation_m=120.0, coordinate=target.location),
    ]
    profile = ElevationProfile(
        source_site=source,
        target_site=target,
        distance_km=10.0,
        points=points,
    )

    res = analyze_fresnel_clearance(profile, frequency_mhz=915.0)
    assert res.ok is True
    assert res.value is not None

    val = res.value
    assert val.has_line_of_sight is False
    assert val.fresnel_60pct_clear is False
    assert val.min_clearance_m < 0.0
    assert val.min_clearance_ratio < 0.0
    assert val.max_knife_edge_nu > 0.0
    assert val.worst_obstruction_point is not None
    assert val.worst_obstruction_point.distance_m == 5000.0


def test_analyze_fresnel_invalid_inputs() -> None:
    """Verify Result.fail is returned on <2 points, zero distance, or invalid parameters."""
    source = _make_site("VT-A", "Site A", 44.45, -73.10, 100.0)
    target = _make_site("VT-B", "Site B", 44.46, -73.10, 100.0)

    single_pt_profile = ElevationProfile(
        source_site=source,
        target_site=target,
        distance_km=1.0,
        points=[ElevationPoint(distance_m=0.0, elevation_m=100.0, coordinate=source.location)],
    )
    res_insufficient = analyze_fresnel_clearance(single_pt_profile)
    assert res_insufficient.ok is False
    assert res_insufficient.error is not None
    assert res_insufficient.error.code == "INSUFFICIENT_PROFILE_POINTS"

    zero_dist_profile = ElevationProfile(
        source_site=source,
        target_site=source,
        distance_km=0.0,
        points=[
            ElevationPoint(distance_m=0.0, elevation_m=100.0, coordinate=source.location),
            ElevationPoint(distance_m=0.0, elevation_m=100.0, coordinate=source.location),
        ],
    )
    res_zero = analyze_fresnel_clearance(zero_dist_profile)
    assert res_zero.ok is False
    assert res_zero.error is not None
    assert res_zero.error.code == "ZERO_PATH_DISTANCE"

    valid_profile = ElevationProfile(
        source_site=source,
        target_site=target,
        distance_km=1.0,
        points=[
            ElevationPoint(distance_m=0.0, elevation_m=100.0, coordinate=source.location),
            ElevationPoint(distance_m=1000.0, elevation_m=100.0, coordinate=target.location),
        ],
    )
    res_bad_freq = analyze_fresnel_clearance(valid_profile, frequency_mhz=-10.0)
    assert res_bad_freq.ok is False
    assert res_bad_freq.error is not None
    assert res_bad_freq.error.code == "INVALID_FREQUENCY"
