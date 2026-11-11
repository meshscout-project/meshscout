"""Tests for North American 65-jurisdiction catalog and bounds resolution."""

from __future__ import annotations

import pytest

from meshscout.adapters.regions import (
    NORTH_AMERICA_CATALOG,
    NorthAmericaRegionCode,
    RegionCode,
    StateCode,
    StateInfo,
    detect_region_code,
    get_state_info,
    list_north_america_regions,
    list_supported_states,
    normalize_jurisdiction,
    resolve_north_america_bounds,
    resolve_regional_bounds,
)
from meshscout.core.contracts import Coordinate, RegionalBounds


def test_north_america_region_code_enum() -> None:
    """Verify NorthAmericaRegionCode enum defines exactly 65 jurisdictions."""
    assert len(NorthAmericaRegionCode) == 65

    # 50 US States
    us_states = [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    ]
    for code in us_states:
        member = getattr(NorthAmericaRegionCode, code, None)
        assert member is not None, f"Missing US state {code}"
        assert member.value == code

    # District & Territory
    assert NorthAmericaRegionCode.DC.value == "DC"
    assert NorthAmericaRegionCode.PR.value == "PR"

    # 10 Canadian Provinces
    ca_provinces = [
        "CA_AB", "CA_BC", "CA_MB", "CA_NB", "CA_NL",
        "CA_NS", "CA_ON", "CA_PE", "CA_QC", "CA_SK",
    ]
    for code in ca_provinces:
        member = getattr(NorthAmericaRegionCode, code, None)
        assert member is not None, f"Missing CA province {code}"
        assert member.value == code

    # 3 Canadian Territories
    ca_territories = ["CA_NT", "CA_NU", "CA_YT"]
    for code in ca_territories:
        member = getattr(NorthAmericaRegionCode, code, None)
        assert member is not None, f"Missing CA territory {code}"
        assert member.value == code


def test_state_code_preserved() -> None:
    """Verify existing StateCode enum and RegionCode alias remain untouched with 6 items."""
    assert RegionCode is StateCode
    assert len(StateCode) == 6
    expected_codes = ["VT", "NH", "NY", "ME", "MA", "CA_QC"]
    assert [s.value for s in StateCode] == expected_codes


def test_north_america_catalog_completeness() -> None:
    """Verify NORTH_AMERICA_CATALOG defines valid metadata and bounds for all 65 jurisdictions."""
    assert len(NORTH_AMERICA_CATALOG) == 65

    us_count = 0
    ca_count = 0

    for code_enum in NorthAmericaRegionCode:
        code = code_enum.value
        assert code in NORTH_AMERICA_CATALOG, f"Missing {code} in NORTH_AMERICA_CATALOG"
        info = NORTH_AMERICA_CATALOG[code]

        assert isinstance(info, StateInfo)
        assert info.state_code == code
        assert len(info.name) > 0
        assert len(info.default_subregion) > 0

        # Validate bounding box invariant
        assert isinstance(info.bounds, RegionalBounds)
        assert info.bounds.min_lat < info.bounds.max_lat
        assert info.bounds.min_lon < info.bounds.max_lon

        if info.country == "US":
            us_count += 1
            assert info.is_province is False
        elif info.country == "CA":
            ca_count += 1
            assert info.is_province is True
        else:
            pytest.fail(f"Unexpected country code {info.country} for {code}")

    assert us_count == 52  # 50 States + DC + PR
    assert ca_count == 13  # 10 Provinces + 3 Territories


def test_alaska_antimeridian_clip() -> None:
    """Verify Alaska (AK) bounds are clipped at the antimeridian per RegionalBounds invariants."""
    ak_info = NORTH_AMERICA_CATALOG["AK"]
    assert ak_info.bounds.min_lon == pytest.approx(-179.99)
    assert ak_info.bounds.max_lon == pytest.approx(-129.9)
    assert ak_info.bounds.min_lat == pytest.approx(51.2)
    assert ak_info.bounds.max_lat == pytest.approx(71.4)
    assert ak_info.bounds.min_lon < ak_info.bounds.max_lon


def test_list_north_america_regions() -> None:
    """Verify list_north_america_regions with and without country filtering."""
    all_regions = list_north_america_regions()
    assert len(all_regions) == 65

    us_regions = list_north_america_regions(country="US")
    assert len(us_regions) == 52
    assert all(r["country"] == "US" for r in us_regions)

    ca_regions = list_north_america_regions(country="CA")
    assert len(ca_regions) == 13
    assert all(r["country"] == "CA" for r in ca_regions)

    ca_case = list_north_america_regions(country="ca")
    assert len(ca_case) == 13

    none_regions = list_north_america_regions(country="MX")
    assert len(none_regions) == 0


def test_get_state_info_include_national_flag() -> None:
    """Verify get_state_info preserves default False but returns all jurisdictions with include_national=True."""
    # Default False: unsupported for states outside original 6
    assert get_state_info("TX") is None
    assert get_state_info("TX", include_national=False) is None
    assert get_state_info("CA_ON") is None

    # include_national=True: returns valid StateInfo
    tx_info = get_state_info("TX", include_national=True)
    assert tx_info is not None
    assert tx_info.state_code == "TX"
    assert tx_info.name == "Texas"
    assert tx_info.country == "US"

    on_info = get_state_info("CA_ON", include_national=True)
    assert on_info is not None
    assert on_info.state_code == "CA_ON"
    assert on_info.name == "Ontario"
    assert on_info.country == "CA"
    assert on_info.is_province is True

    # Works with NorthAmericaRegionCode enum
    assert get_state_info(NorthAmericaRegionCode.TX, include_national=True) is not None

    # Preserved regional states work in both modes
    vt_def = get_state_info("VT")
    vt_nat = get_state_info("VT", include_national=True)
    assert vt_def is not None
    assert vt_nat is not None
    assert vt_def.state_code == vt_nat.state_code == "VT"


def test_list_supported_states_include_national_flag() -> None:
    """Verify list_supported_states returns 6 by default and 65 when include_national=True."""
    states_def = list_supported_states()
    assert len(states_def) == 6

    states_explicit_false = list_supported_states(include_national=False)
    assert len(states_explicit_false) == 6

    states_national = list_supported_states(include_national=True)
    assert len(states_national) == 65


def test_resolve_north_america_bounds_statewide() -> None:
    """Verify resolving statewide and provincial bounds across North America."""
    # US State
    res_tx = resolve_north_america_bounds("TX")
    assert res_tx.ok
    assert res_tx.value is not None
    assert res_tx.value.name == "Texas_Statewide"
    assert res_tx.value.min_lat == pytest.approx(25.84)
    assert res_tx.value.max_lat == pytest.approx(36.50)

    # Canadian Province
    res_on = resolve_north_america_bounds("CA_ON")
    assert res_on.ok
    assert res_on.value is not None
    assert res_on.value.name == "Ontario_Province"

    # Preserved VT bounds
    res_vt = resolve_north_america_bounds("VT")
    assert res_vt.ok
    assert res_vt.value is not None
    assert res_vt.value.name == "Vermont_Statewide"

    # With enum argument
    res_qc = resolve_north_america_bounds(NorthAmericaRegionCode.CA_QC)
    assert res_qc.ok
    assert res_qc.value is not None

    # Subregion keywords 'all' and 'statewide'
    res_bc_all = resolve_north_america_bounds("CA_BC", "all")
    assert res_bc_all.ok
    assert res_bc_all.value is not None
    assert res_bc_all.value.name == "British_Columbia_Province"

    res_bc_sw = resolve_north_america_bounds("CA_BC", "statewide")
    assert res_bc_sw.ok
    assert res_bc_sw.value == res_bc_all.value


def test_resolve_north_america_bounds_subregions() -> None:
    """Verify subregion and default bounds resolution in North American catalog."""
    # VT county subregion
    res_chit = resolve_north_america_bounds("VT", "chittenden")
    assert res_chit.ok
    assert res_chit.value is not None
    assert "Chittenden" in res_chit.value.name

    # NH county subregion
    res_coos = resolve_north_america_bounds("NH", "coos")
    assert res_coos.ok
    assert res_coos.value is not None

    # CA_QC subregion
    res_estrie = resolve_north_america_bounds("CA_QC", "estrie")
    assert res_estrie.ok
    assert res_estrie.value is not None

    # 'default' subregion resolution
    res_vt_def = resolve_north_america_bounds("VT", "default")
    assert res_vt_def.ok
    assert res_vt_def.value == res_chit.value

    # States without specific subregions resolve 'default' to statewide bounds
    res_tx_def = resolve_north_america_bounds("TX", "default")
    assert res_tx_def.ok
    assert res_tx_def.value is not None
    assert res_tx_def.value.name == "Texas_Statewide"


def test_resolve_north_america_bounds_errors() -> None:
    """Verify error reporting for unknown regions and subregions."""
    res_invalid = resolve_north_america_bounds("INVALID_XYZ")
    assert not res_invalid.ok
    assert res_invalid.error is not None
    assert res_invalid.error.code == "UNSUPPORTED_REGION"

    res_sub_err = resolve_north_america_bounds("VT", "nonexistent_county")
    assert not res_sub_err.ok
    assert res_sub_err.error is not None
    assert res_sub_err.error.code == "UNKNOWN_SUBREGION"


def test_normalize_jurisdiction() -> None:
    """Verify mapping of country and state/province string variations to canonical codes."""
    # Exact and full name matches for US
    assert normalize_jurisdiction("US", "VT") == "VT"
    assert normalize_jurisdiction("US", "Vermont") == "VT"
    assert normalize_jurisdiction("US", "vermont") == "VT"
    assert normalize_jurisdiction("US", "US-VT") == "VT"
    assert normalize_jurisdiction("US", "Texas") == "TX"
    assert normalize_jurisdiction("US", "TX") == "TX"
    assert normalize_jurisdiction("US", "District of Columbia") == "DC"
    assert normalize_jurisdiction("US", "Puerto Rico") == "PR"

    # Canada variations and accents
    assert normalize_jurisdiction("CA", "QC") == "CA_QC"
    assert normalize_jurisdiction("CA", "Québec") == "CA_QC"
    assert normalize_jurisdiction("CA", "PQ") == "CA_QC"
    assert normalize_jurisdiction("CA", "P.Q.") == "CA_QC"
    assert normalize_jurisdiction("CA", "Ontario") == "CA_ON"
    assert normalize_jurisdiction("CA", "CA-ON") == "CA_ON"
    assert normalize_jurisdiction("CA", "British Columbia") == "CA_BC"
    assert normalize_jurisdiction("CA", "BC") == "CA_BC"
    assert normalize_jurisdiction("CA", "Prince Edward Island") == "CA_PE"
    assert normalize_jurisdiction("CA", "Île-du-Prince-Édouard") == "CA_PE"
    assert normalize_jurisdiction("CA", "PEI") == "CA_PE"
    assert normalize_jurisdiction("CA", "Yukon") == "CA_YT"
    assert normalize_jurisdiction("CA", "NWT") == "CA_NT"

    # Country empty or omitted: should resolve cleanly
    assert normalize_jurisdiction("", "Ontario") == "CA_ON"
    assert normalize_jurisdiction("", "Québec") == "CA_QC"
    assert normalize_jurisdiction("", "PQ") == "CA_QC"
    assert normalize_jurisdiction("", "Vermont") == "VT"
    assert normalize_jurisdiction("", "CA-ON") == "CA_ON"

    # Mismatched country / invalid inputs
    assert normalize_jurisdiction("US", "QC") is None
    assert normalize_jurisdiction("CA", "VT") is None
    assert normalize_jurisdiction("", "") is None
    assert normalize_jurisdiction("US", "NonexistentState") is None


def test_detect_region_code() -> None:
    """Verify coordinate fallback detection resolves overlapping bounding boxes by smallest area."""
    # Acceptance criteria specific test points
    burlington = Coordinate(lat=44.476, lon=-73.212)
    assert detect_region_code(burlington) == "VT"

    sherbrooke = Coordinate(lat=45.404, lon=-71.893)
    assert detect_region_code(sherbrooke) == "CA_QC"

    # Additional spot checks
    austin = Coordinate(lat=30.2672, lon=-97.7431)
    assert detect_region_code(austin) == "TX"

    anchorage = Coordinate(lat=61.2181, lon=-149.9003)
    assert detect_region_code(anchorage) == "AK"

    honolulu = Coordinate(lat=21.3069, lon=-157.8583)
    assert detect_region_code(honolulu) == "HI"

    # Outside all bounding boxes (e.g. Atlantic Ocean)
    ocean = Coordinate(lat=0.0, lon=0.0)
    assert detect_region_code(ocean) is None

    # Supports dict input as well
    assert detect_region_code({"lat": 44.476, "lon": -73.212}) == "VT"


def test_existing_resolve_regional_bounds_unaffected() -> None:
    """Ensure existing resolve_regional_bounds preserves UNSUPPORTED_STATE for states like TX."""
    res_tx = resolve_regional_bounds("TX")
    assert not res_tx.ok
    assert res_tx.error is not None
    assert res_tx.error.code == "UNSUPPORTED_STATE"

    res_vt = resolve_regional_bounds("VT")
    assert res_vt.ok
    assert res_vt.value is not None
