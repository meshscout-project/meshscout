"""Hermetic unit tests for Vermont VCGI and generic OSM regional adapters."""

from __future__ import annotations

import io
import json
import time
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from meshscout.adapters.base import (
    BaseRegionalAdapter,
    RateLimitBackoff,
    RateLimitConfig,
)
from meshscout.adapters.generic_osm import (
    OSMRegionalAdapter,
    build_overpass_query,
)
from meshscout.adapters.vt_vcgi import (
    DEFAULT_VCGI_FIXTURE_PATH,
    VERMONT_STATE_BOUNDS,
    OwnershipTier,
    VCGIRegionalAdapter,
    classify_ownership_tier,
)
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)


@pytest.fixture
def chittenden_bounds() -> RegionalBounds:
    """Fixture defining Chittenden County regional bounding box."""
    return RegionalBounds(
        name="Vermont_Chittenden_County",
        min_lat=44.25,
        max_lat=44.60,
        min_lon=-73.35,
        max_lon=-72.80,
    )


@pytest.fixture
def test_rate_limiter() -> RateLimitBackoff:
    """Zero-delay rate limiter for hermetic fast testing."""
    return RateLimitBackoff(
        config=RateLimitConfig(
            min_delay=0.0,
            max_delay=0.0,
            max_retries=2,
            disabled=True,
        )
    )


# ---------------------------------------------------------------------------
# Protocol Conformance Tests
# ---------------------------------------------------------------------------

def test_vcgi_adapter_protocol_conformance(chittenden_bounds: RegionalBounds, test_rate_limiter: RateLimitBackoff):
    """Verify VCGIRegionalAdapter satisfies BaseRegionalAdapter protocol."""
    adapter = VCGIRegionalAdapter(
        bounds=chittenden_bounds,
        offline_mode=True,
        rate_limiter=test_rate_limiter,
    )
    assert isinstance(adapter, BaseRegionalAdapter)
    assert adapter.adapter_name == "vt_vcgi"
    assert adapter.bounds == chittenden_bounds
    health = adapter.health_check()
    assert health.ok is True
    assert health.value is True


def test_osm_adapter_protocol_conformance(chittenden_bounds: RegionalBounds, test_rate_limiter: RateLimitBackoff):
    """Verify OSMRegionalAdapter satisfies BaseRegionalAdapter protocol."""
    adapter = OSMRegionalAdapter(
        bounds=chittenden_bounds,
        offline_mode=True,
        rate_limiter=test_rate_limiter,
    )
    assert isinstance(adapter, BaseRegionalAdapter)
    assert adapter.adapter_name == "osm_overpass"
    assert adapter.bounds == chittenden_bounds
    health = adapter.health_check()
    assert health.ok is True
    assert health.value is True


# ---------------------------------------------------------------------------
# VCGI Fixture Parsing & Geofenced Bounds Tests
# ---------------------------------------------------------------------------

def test_vcgi_parse_bundled_fixture(test_rate_limiter: RateLimitBackoff):
    """Verify bundled VCGI sample fixture loads and parses into valid SiteCandidate objects."""
    adapter = VCGIRegionalAdapter(
        offline_mode=True,
        rate_limiter=test_rate_limiter,
    )
    start = time.perf_counter()
    res = adapter.fetch_sites()
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # Must execute hermetically and fast (<100ms)
    assert elapsed_ms < 100.0, f"VCGI fixture parse took {elapsed_ms:.2f}ms (expected <100ms)"
    assert res.ok is True
    assert res.value is not None

    sites = res.value
    assert len(sites) >= 10

    # Ensure all site types of interest are present
    types_found = {s.site_type for s in sites}
    assert SiteType.WATER_TOWER in types_found
    assert SiteType.COMMUNICATIONS_TOWER in types_found
    assert SiteType.BUILDING_ROOFTOP in types_found

    # Validate schema invariants for every parsed site
    for site in sites:
        assert isinstance(site, SiteCandidate)
        assert len(site.site_id) > 0
        assert len(site.name) > 0
        assert -90.0 <= site.location.lat <= 90.0
        assert -180.0 <= site.location.lon <= 180.0
        assert site.mast_height_m > 0.0
        assert 0.0 <= site.solar_exposure_pct <= 100.0
        assert isinstance(site.access_difficulty, AccessDifficulty)
        assert site.notes is not None


def test_vcgi_bounds_containment_filtering(chittenden_bounds: RegionalBounds, test_rate_limiter: RateLimitBackoff):
    """Verify bounding box filtering excludes sites outside county bounds."""
    adapter = VCGIRegionalAdapter(
        bounds=chittenden_bounds,
        offline_mode=True,
        rate_limiter=test_rate_limiter,
    )
    res_county = adapter.fetch_sites(bounds=chittenden_bounds)
    assert res_county.ok is True
    county_sites = res_county.value or []

    # All returned sites must be within Chittenden County bounds
    for s in county_sites:
        assert chittenden_bounds.contains(s.location), (
            f"Site {s.site_id} ({s.location.lat}, {s.location.lon}) is outside {chittenden_bounds.name}"
        )

    # Statewide query should include out-of-county sites (e.g. Waterbury)
    res_state = adapter.fetch_sites(bounds=VERMONT_STATE_BOUNDS)
    assert res_state.ok is True
    state_sites = res_state.value or []

    assert len(state_sites) > len(county_sites)
    waterbury = next((s for s in state_sites if "Waterbury" in s.name or "VT-VCGI-STA-001" == s.site_id), None)
    assert waterbury is not None
    assert not chittenden_bounds.contains(waterbury.location)
    assert VERMONT_STATE_BOUNDS.contains(waterbury.location)


# ---------------------------------------------------------------------------
# Ownership Tier Classification Tests
# ---------------------------------------------------------------------------

def test_ownership_tier_classification_by_string():
    """Verify keyword-based classification of municipal, state, and private ownership."""
    # Municipal
    assert classify_ownership_tier("City of Burlington Water Department") == OwnershipTier.MUNICIPAL
    assert classify_ownership_tier("Town of Essex Public Works") == OwnershipTier.MUNICIPAL
    assert classify_ownership_tier("Village of Essex Junction Water District") == OwnershipTier.MUNICIPAL
    assert classify_ownership_tier("Richmond Volunteer Fire Department") == OwnershipTier.MUNICIPAL
    assert classify_ownership_tier("South Burlington Fire District #1") == OwnershipTier.MUNICIPAL
    assert classify_ownership_tier("Burlington DPW Depot") == OwnershipTier.MUNICIPAL
    assert classify_ownership_tier("Town of Richmond") == OwnershipTier.MUNICIPAL

    # State
    assert classify_ownership_tier("State of Vermont Department of Public Safety") == OwnershipTier.STATE
    assert classify_ownership_tier("Vermont Agency of Transportation (VTrans)") == OwnershipTier.STATE
    assert classify_ownership_tier("State Police Troop A Barracks") == OwnershipTier.STATE
    assert classify_ownership_tier("University of Vermont (UVM) Mount Mansfield Lab") == OwnershipTier.STATE
    assert classify_ownership_tier("State of Vermont BGS") == OwnershipTier.STATE
    assert classify_ownership_tier("Vermont Agency of Natural Resources") == OwnershipTier.STATE

    # Private / Commercial
    assert classify_ownership_tier("American Tower Corp") == OwnershipTier.PRIVATE_COMMERCIAL
    assert classify_ownership_tier("Crown Castle LLC") == OwnershipTier.PRIVATE_COMMERCIAL
    assert classify_ownership_tier("SBA Communications Monopole") == OwnershipTier.PRIVATE_COMMERCIAL
    assert classify_ownership_tier("Verizon Wireless Cell Site") == OwnershipTier.PRIVATE_COMMERCIAL
    assert classify_ownership_tier("AT&T Mobility Tower") == OwnershipTier.PRIVATE_COMMERCIAL
    assert classify_ownership_tier("Green Mountain Power Utility Substation") == OwnershipTier.PRIVATE_COMMERCIAL
    assert classify_ownership_tier("Private Agri Silo Facility") == OwnershipTier.PRIVATE_COMMERCIAL


def test_ownership_tier_classification_by_attributes():
    """Verify categorical attribute codes correctly classify ownership."""
    # Explicit OWNER_TYPE codes
    assert classify_ownership_tier(attributes={"OWNER_TYPE": "MUNI"}) == OwnershipTier.MUNICIPAL
    assert classify_ownership_tier(attributes={"OWNER_TYPE": "STATE"}) == OwnershipTier.STATE
    assert classify_ownership_tier(attributes={"OWNER_TYPE": "PRIV"}) == OwnershipTier.PRIVATE_COMMERCIAL
    assert classify_ownership_tier(attributes={"OWNER_TYPE": "COMMERCIAL"}) == OwnershipTier.PRIVATE_COMMERCIAL

    # PUB_PRIV flag
    assert classify_ownership_tier(attributes={"PUB_PRIV": "PRIV", "NAME": "Telecom Lattice"}) == OwnershipTier.PRIVATE_COMMERCIAL


def test_fixture_ownership_tiers_distribution(test_rate_limiter: RateLimitBackoff):
    """Verify parsed fixture sites contain representatives of municipal, state, and private tiers."""
    adapter = VCGIRegionalAdapter(offline_mode=True, rate_limiter=test_rate_limiter)
    res = adapter.fetch_sites(bounds=VERMONT_STATE_BOUNDS)
    assert res.ok is True
    sites = res.value or []

    tiers_found = {adapter.classify_site_ownership(s) for s in sites}
    assert OwnershipTier.MUNICIPAL in tiers_found
    assert OwnershipTier.STATE in tiers_found
    assert OwnershipTier.PRIVATE_COMMERCIAL in tiers_found

    # Specific site checks
    wt_burlington = next(s for s in sites if s.site_id == "VT-VCGI-WT-001")
    assert adapter.classify_site_ownership(wt_burlington) == OwnershipTier.MUNICIPAL
    assert "[ownership: municipal]" in wt_burlington.notes.lower()

    com_state = next(s for s in sites if s.site_id == "VT-VCGI-COM-001")
    assert adapter.classify_site_ownership(com_state) == OwnershipTier.STATE
    assert "[ownership: state]" in com_state.notes.lower()

    com_priv = next(s for s in sites if s.site_id == "VT-VCGI-COM-003")
    assert adapter.classify_site_ownership(com_priv) == OwnershipTier.PRIVATE_COMMERCIAL
    assert "[ownership: private/commercial]" in com_priv.notes.lower()


# ---------------------------------------------------------------------------
# Generic OSM Adapter Query Construction & Mock Parsing Tests
# ---------------------------------------------------------------------------

def test_osm_adapter_query_construction(chittenden_bounds: RegionalBounds):
    """Verify OSM adapter constructs valid Overpass QL bounding box query."""
    adapter = OSMRegionalAdapter(bounds=chittenden_bounds)
    ql = adapter.build_query()

    assert "[out:json]" in ql
    assert "out center tags;" in ql

    # Verify bounding box coordinates (south, west, north, east)
    expected_bbox = (
        f"{chittenden_bounds.min_lat},"
        f"{chittenden_bounds.min_lon},"
        f"{chittenden_bounds.max_lat},"
        f"{chittenden_bounds.max_lon}"
    )
    assert expected_bbox in ql

    # Verify target structure filters
    assert 'node["man_made"="water_tower"]' in ql
    assert 'way["man_made"="water_tower"]' in ql
    assert 'node["man_made"="tower"]' in ql
    assert 'node["man_made"="mast"]' in ql
    assert 'node["amenity"="fire_station"]' in ql
    assert 'way["amenity"="fire_station"]' in ql


def test_osm_mock_response_parsing(chittenden_bounds: RegionalBounds):
    """Verify parsing OSM Overpass JSON response with nodes and ways."""
    adapter = OSMRegionalAdapter(bounds=chittenden_bounds, offline_mode=True)

    mock_overpass_payload = {
        "version": 0.6,
        "generator": "Overpass API",
        "elements": [
            {
                "type": "node",
                "id": 1001,
                "lat": 44.4425,
                "lon": -73.1120,
                "tags": {
                    "man_made": "water_tower",
                    "name": "Williston Water Tower",
                    "height": "32 m",
                    "ele": "115",
                    "operator": "Town of Williston",
                },
            },
            {
                "type": "way",
                "id": 2002,
                "center": {"lat": 44.4750, "lon": -73.2100},
                "tags": {
                    "amenity": "fire_station",
                    "name": "Burlington Fire Station 2",
                    "height": "10 m",
                    "operator": "City of Burlington",
                },
            },
            {
                "type": "node",
                "id": 3003,
                "lat": 44.5300,
                "lon": -73.1800,
                "tags": {
                    "man_made": "tower",
                    "tower:type": "communication",
                    "name": "Colchester Cell Tower",
                    "height": "40",
                    "operator": "American Tower Corp",
                },
            },
            {
                "type": "node",
                "id": 4004,
                "lat": 44.5400,
                "lon": -72.8100,
                "tags": {
                    "man_made": "tower",
                    "tower:type": "observation",
                    "name": "Mansfield Lookout Tower",
                    "height": "12 m",
                    "operator": "State of Vermont FPR",
                },
            },
            # Site outside Chittenden bounds - should be filtered
            {
                "type": "node",
                "id": 9999,
                "lat": 42.8000,
                "lon": -72.5000,
                "tags": {
                    "man_made": "water_tower",
                    "name": "Brattleboro Water Tank",
                },
            },
        ],
    }

    candidates = adapter.parse_overpass_response(mock_overpass_payload, bounds=chittenden_bounds)

    # 4 elements in bounds, 1 filtered out
    assert len(candidates) == 4

    wt = next(c for c in candidates if c.site_id == "OSM-N-1001")
    assert wt.name == "Williston Water Tower"
    assert wt.site_type == SiteType.WATER_TOWER
    assert wt.mast_height_m == 32.0
    assert wt.location.elevation_m == 115.0
    assert "[ownership: municipal]" in wt.notes.lower()

    fs = next(c for c in candidates if c.site_id == "OSM-W-2002")
    assert fs.name == "Burlington Fire Station 2"
    assert fs.site_type == SiteType.BUILDING_ROOFTOP
    assert fs.mast_height_m == 10.0
    assert "[ownership: municipal]" in fs.notes.lower()

    com = next(c for c in candidates if c.site_id == "OSM-N-3003")
    assert com.name == "Colchester Cell Tower"
    assert com.site_type == SiteType.COMMUNICATIONS_TOWER
    assert com.mast_height_m == 40.0
    assert "[ownership: private/commercial]" in com.notes.lower()

    lookout = next(c for c in candidates if c.site_id == "OSM-N-4004")
    assert lookout.name == "Mansfield Lookout Tower"
    assert lookout.site_type == SiteType.FIRE_LOOKOUT
    assert lookout.access_difficulty == AccessDifficulty.HIKE_IN
    assert "[ownership: state]" in lookout.notes.lower()


# ---------------------------------------------------------------------------
# Rate Limiter & Fallback Tests
# ---------------------------------------------------------------------------

def test_vcgi_online_mock_and_rate_limiter(chittenden_bounds: RegionalBounds, test_rate_limiter: RateLimitBackoff):
    """Verify live ArcGIS REST queries trigger RateLimitBackoff execution."""
    mock_esri_json = {
        "features": [
            {
                "attributes": {
                    "OBJECTID": 501,
                    "FACILITY_ID": "VT-ONLINE-01",
                    "FACNAME": "Shelburne Municipal Water Tank",
                    "FEATURE_TYPE": "Water Tower",
                    "OWNER": "Town of Shelburne",
                    "OWNER_TYPE": "MUNI",
                    "HEIGHT_M": 22.0,
                },
                "geometry": {"x": -73.2250, "y": 44.3800, "z": 80.0},
            }
        ]
    }
    encoded = json.dumps(mock_esri_json).encode("utf-8")
    mock_resp = io.BytesIO(encoded)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        adapter = VCGIRegionalAdapter(
            bounds=chittenden_bounds,
            arcgis_url="https://maps.vcgi.vermont.gov/arcgis/rest/services/Emergency/FeatureServer/0",
            offline_mode=False,
            rate_limiter=test_rate_limiter,
        )
        res = adapter.fetch_sites(bounds=chittenden_bounds)

        assert mock_urlopen.called
        assert res.ok is True
        sites = res.value or []
        assert len(sites) == 1
        assert sites[0].site_id == "VT-ONLINE-01"
        assert sites[0].name == "Shelburne Municipal Water Tank"
        assert sites[0].site_type == SiteType.WATER_TOWER


def test_vcgi_online_failure_falls_back_to_offline(chittenden_bounds: RegionalBounds, test_rate_limiter: RateLimitBackoff):
    """Verify live query network failure falls back to bundled offline records without error."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        adapter = VCGIRegionalAdapter(
            bounds=chittenden_bounds,
            arcgis_url="https://invalid.vcgi.vermont.gov/arcgis/rest/services/FeatureServer/0",
            offline_mode=False,
            rate_limiter=test_rate_limiter,
        )
        res = adapter.fetch_sites(bounds=chittenden_bounds)

        # Should fall back to bundled fixture and return success
        assert res.ok is True
        sites = res.value or []
        assert len(sites) > 0


def test_osm_online_failure_handling(chittenden_bounds: RegionalBounds, test_rate_limiter: RateLimitBackoff):
    """Verify OSM Overpass failure without fallback returns explicit Result failure."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Host unreachable")):
        adapter = OSMRegionalAdapter(
            bounds=chittenden_bounds,
            offline_mode=False,
            rate_limiter=test_rate_limiter,
        )
        res = adapter.fetch_sites(bounds=chittenden_bounds)

        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "OVERPASS_QUERY_FAILED"
