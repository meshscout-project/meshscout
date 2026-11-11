"""Unit tests for Multi-Origin Composite Viewshed and Backhaul Link Matrix Engine."""

import pytest
from meshscout.core.contracts import Coordinate, RadioConfig, SiteCandidate
from meshscout.core.composite_viewshed import (
    BackhaulLinkStatus,
    CompositeViewshedResult,
    compute_composite_viewshed,
    _synthetic_vermont_elevation_fn,
)


@pytest.fixture
def mansfield_site() -> SiteCandidate:
    """Mount Mansfield summit high-site candidate."""
    return SiteCandidate(
        site_id="VT-CHIT-MANS-01",
        name="Mount Mansfield Summit",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        mast_height_m=15.0,
    )


@pytest.fixture
def bolton_site() -> SiteCandidate:
    """Bolton Mountain peak candidate."""
    return SiteCandidate(
        site_id="VT-CHIT-BOLT-01",
        name="Bolton Mountain Peak",
        location=Coordinate(lat=44.4285, lon=-72.8550, elevation_m=1123.0),
        mast_height_m=15.0,
    )


@pytest.fixture
def valley_site_west() -> SiteCandidate:
    """Low valley site on west side of the Green Mountain ridge (Burlington waterfront)."""
    return SiteCandidate(
        site_id="VT-VALLEY-WEST",
        name="Burlington Waterfront Low",
        location=Coordinate(lat=44.4759, lon=-73.2200, elevation_m=35.0),
        mast_height_m=2.0,
    )


@pytest.fixture
def valley_site_east() -> SiteCandidate:
    """Low valley site on east side of the Green Mountain ridge (Stowe village basin)."""
    return SiteCandidate(
        site_id="VT-VALLEY-EAST",
        name="Stowe Village Basin Low",
        location=Coordinate(lat=44.4654, lon=-72.6874, elevation_m=220.0),
        mast_height_m=2.0,
    )


def test_empty_origins_returns_empty_result():
    """Verify empty origins sequence returns a valid success Result with empty composite models."""
    res = compute_composite_viewshed(origins=[])
    assert res.ok is True
    assert res.value is not None

    cv = res.value
    assert isinstance(cv, CompositeViewshedResult)
    assert cv.origin_site_ids == []
    assert cv.individual_polygons == {}
    assert cv.composite_polygons == []
    assert cv.total_illuminated_area_sq_km == 0.0
    assert cv.illuminated_towns == []
    assert cv.intersite_backhaul_links == []


def test_single_origin_returns_single_viewshed_polygon(mansfield_site):
    """Verify single origin produces exactly 1 individual polygon, 1 composite ring, and no backhaul links."""
    res = compute_composite_viewshed(origins=[mansfield_site], max_range_km=40.0, num_radials=36)
    assert res.ok is True
    assert res.value is not None

    cv = res.value
    assert cv.origin_site_ids == ["VT-CHIT-MANS-01"]
    assert len(cv.individual_polygons) == 1
    assert "VT-CHIT-MANS-01" in cv.individual_polygons

    # Closed polygon linear ring has 37 vertices [lon, lat] (36 radials + closed ring)
    mansfield_poly = cv.individual_polygons["VT-CHIT-MANS-01"]
    assert len(mansfield_poly) == 37
    assert mansfield_poly[0] == mansfield_poly[-1]
    # Coordinates in individual_polygons must be [lon, lat]
    for pt in mansfield_poly:
        assert len(pt) == 2
        lon, lat = pt
        assert -75.0 <= lon <= -70.0
        assert 43.0 <= lat <= 46.0

    assert len(cv.composite_polygons) == 1
    assert cv.composite_polygons[0] == mansfield_poly
    assert cv.total_illuminated_area_sq_km > 0.0
    # No pairwise backhaul links for a single site
    assert cv.intersite_backhaul_links == []
    # Municipal towns within Mansfield reach
    assert len(cv.illuminated_towns) > 0
    assert "Burlington" in cv.illuminated_towns


def test_multi_origin_composite_viewshed(mansfield_site, bolton_site):
    """Verify multi-origin viewshed aggregates individual polygons and evaluates backhaul."""
    origins = [mansfield_site, bolton_site]
    res = compute_composite_viewshed(origins=origins, max_range_km=50.0, num_radials=36)
    assert res.ok is True
    assert res.value is not None

    cv = res.value
    assert cv.origin_site_ids == ["VT-CHIT-MANS-01", "VT-CHIT-BOLT-01"]

    # Both sites have individual polygons
    assert "VT-CHIT-MANS-01" in cv.individual_polygons
    assert "VT-CHIT-BOLT-01" in cv.individual_polygons
    assert len(cv.individual_polygons) == 2

    # Composite polygons list contains both rings
    assert len(cv.composite_polygons) == 2

    # Total illuminated area > 0
    assert cv.total_illuminated_area_sq_km > 0.0

    # Intersite backhaul link analysis
    assert len(cv.intersite_backhaul_links) == 1
    link = cv.intersite_backhaul_links[0]
    assert isinstance(link, BackhaulLinkStatus)
    assert link.site_a_id == "VT-CHIT-MANS-01"
    assert link.site_b_id == "VT-CHIT-BOLT-01"
    assert link.distance_km > 0.0
    assert 10.0 <= link.distance_km <= 20.0

    # Key regional towns illuminated by composite network
    assert "Burlington" in cv.illuminated_towns
    assert "Stowe" in cv.illuminated_towns
    assert "Underhill" in cv.illuminated_towns


def test_pairwise_backhaul_clear_los_between_mountain_peaks(mansfield_site, bolton_site):
    """Verify mountain peak to mountain peak link has clear optical LOS and positive link margin."""
    res = compute_composite_viewshed(
        origins=[mansfield_site, bolton_site],
        max_range_km=40.0,
        num_radials=16,
    )
    assert res.ok is True
    assert res.value is not None
    assert len(res.value.intersite_backhaul_links) == 1

    link = res.value.intersite_backhaul_links[0]
    assert link.has_line_of_sight is True
    assert link.link_margin_db > 20.0
    assert link.fresnel_clearance_ratio >= 1.0


def test_pairwise_backhaul_obstructed_los_across_mountain_ridge(valley_site_west, valley_site_east):
    """Verify low valley sites on opposite sides of the Green Mountain spine report obstructed LOS."""
    res = compute_composite_viewshed(
        origins=[valley_site_west, valley_site_east],
        max_range_km=40.0,
        num_radials=16,
    )
    assert res.ok is True
    assert res.value is not None
    assert len(res.value.intersite_backhaul_links) == 1

    link = res.value.intersite_backhaul_links[0]
    assert link.has_line_of_sight is False
    assert link.fresnel_clearance_ratio < 1.0


def test_custom_reference_towns_dictionary(mansfield_site):
    """Verify custom reference_towns dictionary is respected and filtered accurately."""
    custom_towns = {
        "CustomUnderhill": {
            "name": "CustomUnderhill",
            "lat": 44.5275,
            "lon": -72.8950,
            "elevation_m": 215.0,
        },
        "FarAwayTown": {
            "name": "FarAwayTown",
            "lat": 41.0000,
            "lon": -71.0000,
            "elevation_m": 10.0,
        },
    }
    res = compute_composite_viewshed(
        origins=[mansfield_site],
        reference_towns=custom_towns,
        max_range_km=30.0,
        num_radials=16,
    )
    assert res.ok is True
    assert res.value is not None
    assert "CustomUnderhill" in res.value.illuminated_towns
    assert "FarAwayTown" not in res.value.illuminated_towns


def test_custom_radio_config_affects_viewshed(mansfield_site):
    """Verify customized RadioConfig (higher tx power and gain) produces valid viewshed output."""
    high_power_radio = RadioConfig(
        frequency_mhz=915.0,
        tx_power_dbm=30.0,
        antenna_gain_dbi=8.0,
        cable_loss_db=0.5,
        rx_sensitivity_dbm=-137.0,
    )
    res = compute_composite_viewshed(
        origins=[mansfield_site],
        radio_config=high_power_radio,
        max_range_km=60.0,
        num_radials=24,
    )
    assert res.ok is True
    assert res.value is not None
    assert res.value.total_illuminated_area_sq_km > 0.0
