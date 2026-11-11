"""Tests for Vermont 14 Counties adapter and fixture dataset."""

from __future__ import annotations

import time
from typing import List

import pytest

from meshscout.adapters.vt_counties import (
    VERMONT_COUNTY_BOUNDS,
    VERMONT_STATE_BOUNDS,
    list_vermont_counties,
    load_county_candidates,
    load_regional_fixtures,
)
from meshscout.core.contracts import AccessDifficulty, SiteCandidate, SiteType

EXPECTED_14_COUNTIES = [
    "Addison",
    "Bennington",
    "Caledonia",
    "Chittenden",
    "Essex",
    "Franklin",
    "Grand Isle",
    "Lamoille",
    "Orange",
    "Orleans",
    "Rutland",
    "Washington",
    "Windham",
    "Windsor",
]


def test_all_14_counties_present_and_sorted() -> None:
    """Verify all 14 Vermont counties exist in bounds dictionary and list is alphabetical."""
    counties = list_vermont_counties()
    assert len(counties) == 14
    assert counties == EXPECTED_14_COUNTIES
    for county_name in EXPECTED_14_COUNTIES:
        assert county_name in VERMONT_COUNTY_BOUNDS
        bounds = VERMONT_COUNTY_BOUNDS[county_name]
        assert bounds.name == f"Vermont_{county_name.replace(' ', '_')}_County"


def test_county_bounds_wgs84_valid_vermont_extent() -> None:
    """Verify bounds for each county are strictly inside Vermont WGS84 bounding box.

    Vermont geographical extent:
    Latitude:  42.7 <= lat <= 45.1
    Longitude: -73.5 <= lon <= -71.4
    """
    for county_name, bounds in VERMONT_COUNTY_BOUNDS.items():
        assert bounds.min_lat < bounds.max_lat, f"{county_name} invalid lat range"
        assert bounds.min_lon < bounds.max_lon, f"{county_name} invalid lon range"

        assert 42.7 <= bounds.min_lat <= 45.1, f"{county_name} min_lat out of Vermont bounds: {bounds.min_lat}"
        assert 42.7 <= bounds.max_lat <= 45.1, f"{county_name} max_lat out of Vermont bounds: {bounds.max_lat}"
        assert -73.5 <= bounds.min_lon <= -71.4, f"{county_name} min_lon out of Vermont bounds: {bounds.min_lon}"
        assert -73.5 <= bounds.max_lon <= -71.4, f"{county_name} max_lon out of Vermont bounds: {bounds.max_lon}"


@pytest.mark.parametrize(
    "county",
    ["Rutland", "Washington", "Lamoille", "Windham", "Addison", "Bennington", "Caledonia", "Chittenden", "Essex", "Franklin", "Grand Isle", "Orange", "Orleans", "Windsor"],
)
def test_load_individual_counties(county: str) -> None:
    """Verify loading sites for each individual county returns valid candidates."""
    res = load_county_candidates(county)
    assert res.ok, f"Failed loading county {county}: {res.error}"
    assert res.value is not None
    assert len(res.value) >= 3, f"Expected at least 3 sites for {county}, got {len(res.value)}"


def test_load_case_insensitive_and_suffix() -> None:
    """Verify county lookup supports case-insensitivity and 'County' suffix."""
    res_lower = load_county_candidates("rutland")
    assert res_lower.ok
    assert len(res_lower.value) == 4

    res_upper = load_county_candidates("WASHINGTON")
    assert res_upper.ok
    assert len(res_upper.value) == 4

    res_suffix = load_county_candidates("Lamoille County")
    assert res_suffix.ok
    assert len(res_suffix.value) == 4

    res_prefix = load_county_candidates("vt_windham")
    assert res_prefix.ok
    assert len(res_prefix.value) == 3


def test_load_statewide_candidates() -> None:
    """Verify loading statewide or 'all' returns candidates across all 14 counties."""
    for query in ["all", "vt_statewide", "vermont", "vt"]:
        res = load_county_candidates(query)
        assert res.ok
        assert res.value is not None
        assert len(res.value) >= 42  # At least 3 sites * 14 counties = 42 minimum


def test_candidate_contract_conformance() -> None:
    """Verify every loaded candidate conforms to SiteCandidate contract with positive elevation and valid type."""
    res = load_county_candidates("all")
    assert res.ok
    assert res.value is not None

    seen_ids = set()
    valid_types = set(SiteType)
    valid_diffs = set(AccessDifficulty)

    for site in res.value:
        assert isinstance(site, SiteCandidate)
        assert site.site_id not in seen_ids, f"Duplicate site_id: {site.site_id}"
        seen_ids.add(site.site_id)

        assert site.name and len(site.name) > 0
        assert site.location.elevation_m > 0.0, f"Site {site.site_id} must have positive elevation"
        assert site.site_type in valid_types, f"Site {site.site_id} invalid site_type: {site.site_type}"
        assert site.access_difficulty in valid_diffs
        assert site.mast_height_m >= 0.0
        assert 0.0 <= site.solar_exposure_pct <= 100.0

        # Location must be inside Vermont
        assert 42.7 <= site.location.lat <= 45.1
        assert -73.5 <= site.location.lon <= -71.4


def test_candidate_sites_within_county_bounds() -> None:
    """Verify that sites loaded for a county fall within that county's geographical bounds."""
    for county_name, bounds in VERMONT_COUNTY_BOUNDS.items():
        res = load_county_candidates(county_name)
        assert res.ok
        assert res.value is not None
        for site in res.value:
            assert bounds.contains(site.location), (
                f"Site {site.name} ({site.location.lat}, {site.location.lon}) outside {county_name} bounds"
            )


def test_loading_speed_benchmark() -> None:
    """Verify loading all 14 counties combined completes in < 50ms."""
    # Warm-up run
    load_county_candidates("all")

    # Timed run
    start_time = time.perf_counter()
    res = load_county_candidates("all")
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    assert res.ok
    assert res.value is not None
    assert elapsed_ms < 50.0, f"Loading speed took {elapsed_ms:.2f}ms (threshold: 50ms)"


def test_load_regional_fixtures_integration() -> None:
    """Verify seamless integration with load_regional_fixtures for county names and statewide."""
    # County loading
    rutland_bounds, rutland_sites = load_regional_fixtures("rutland")
    assert rutland_bounds.name == "Vermont_Rutland_County"
    assert len(rutland_sites) == 4

    washington_bounds, washington_sites = load_regional_fixtures("washington")
    assert washington_bounds.name == "Vermont_Washington_County"
    assert len(washington_sites) == 4

    lamoille_bounds, lamoille_sites = load_regional_fixtures("lamoille")
    assert lamoille_bounds.name == "Vermont_Lamoille_County"
    assert len(lamoille_sites) == 4

    windham_bounds, windham_sites = load_regional_fixtures("windham")
    assert windham_bounds.name == "Vermont_Windham_County"
    assert len(windham_sites) == 3

    # Statewide loading
    state_bounds, state_sites = load_regional_fixtures("vt_statewide")
    assert state_bounds.name == "Vermont_Statewide"
    assert len(state_sites) >= 42


def test_mcp_server_load_regional_fixtures_patched() -> None:
    """Verify meshscout.mcp_server.load_regional_fixtures routes county queries properly."""
    import meshscout.mcp_server as mcp

    bounds, sites = mcp.load_regional_fixtures("rutland")
    assert bounds.name == "Vermont_Rutland_County"
    assert len(sites) == 4

    bounds_was, sites_was = mcp.load_regional_fixtures("washington")
    assert bounds_was.name == "Vermont_Washington_County"
    assert len(sites_was) == 4


def test_unknown_county_returns_error() -> None:
    """Verify requesting an invalid county returns a structured Result.fail error."""
    res = load_county_candidates("Atlantis")
    assert not res.ok
    assert res.error is not None
    assert res.error.code == "UNKNOWN_COUNTY"


def test_chittenden_uvm_pmrc_research_tower() -> None:
    """Verify Chittenden County includes UVM Proctor Maple Research Canopy Tower."""
    res = load_county_candidates("chittenden")
    assert res.ok
    assert res.value is not None
    assert len(res.value) == 5

    pmrc_sites = [s for s in res.value if s.site_id == "VT-CHIT-UVM-PMRC"]
    assert len(pmrc_sites) == 1
    site = pmrc_sites[0]

    assert site.name == "UVM Proctor Maple Research Canopy Tower"
    assert site.site_type == SiteType.RESEARCH_TOWER
    assert site.source_url == "https://www.uvm.edu/~cwaite/metstations/Tower.html"
    assert site.mast_height_m == 22.0
    assert site.has_grid_power is True
    assert site.access_difficulty == AccessDifficulty.DRIVE_UP
    assert site.location.lat == 44.5302
    assert site.location.lon == -72.8693
    assert site.location.elevation_m == 415.0

