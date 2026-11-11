"""Tests for multi-state regional adapter catalog and bounds resolution."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from meshscout.adapters.regions import (
    CA_QC_SOUTHERN_BOUNDS,
    MA_STATE_BOUNDS,
    ME_STATE_BOUNDS,
    ME_SUBREGION_BOUNDS,
    NH_COUNTY_BOUNDS,
    NY_COUNTY_BOUNDS,
    QC_SUBREGION_BOUNDS,
    RegionCode,
    StateCode,
    StateInfo,
    SubregionInfo,
    get_state_info,
    list_supported_states,
    load_state_candidates,
    resolve_regional_bounds,
)
from meshscout.adapters.vt_counties import VERMONT_COUNTY_BOUNDS
from meshscout.core.contracts import RegionalBounds, Result, SiteCandidate


def test_region_code_alias() -> None:
    """Verify RegionCode is an alias for StateCode enum."""
    assert RegionCode is StateCode
    assert RegionCode.CA_QC.value == "CA_QC"
    assert RegionCode.ME.value == "ME"
    assert RegionCode.MA.value == "MA"


def test_list_supported_states() -> None:
    """Verify list_supported_states returns VT, NH, NY, ME, MA, CA_QC with complete metadata."""
    states = list_supported_states()
    assert len(states) == 6

    codes = [s["state_code"] for s in states]
    assert codes == ["VT", "NH", "NY", "ME", "MA", "CA_QC"]

    by_code = {s["state_code"]: s for s in states}
    assert by_code["VT"]["name"] == "Vermont"
    assert by_code["VT"]["default_subregion"] == "chittenden"
    assert by_code["VT"]["country"] == "US"
    assert by_code["VT"]["is_province"] is False
    assert len(by_code["VT"]["subregions"]) == 14

    assert by_code["NH"]["name"] == "New Hampshire"
    assert by_code["NH"]["default_subregion"] == "coos"
    assert by_code["NH"]["country"] == "US"
    assert by_code["NH"]["is_province"] is False
    assert len(by_code["NH"]["subregions"]) == 10

    assert "Adirondack" in by_code["NY"]["name"]
    assert by_code["NY"]["default_subregion"] == "essex_ny"
    assert by_code["NY"]["country"] == "US"
    assert by_code["NY"]["is_province"] is False
    assert len(by_code["NY"]["subregions"]) == 5

    assert by_code["ME"]["name"] == "Maine"
    assert by_code["ME"]["default_subregion"] == "oxford"
    assert by_code["ME"]["country"] == "US"
    assert by_code["ME"]["is_province"] is False
    assert len(by_code["ME"]["subregions"]) == 3

    assert by_code["MA"]["name"] == "Massachusetts"
    assert by_code["MA"]["country"] == "US"
    assert by_code["MA"]["is_province"] is False

    assert by_code["CA_QC"]["name"] == "Quebec"
    assert by_code["CA_QC"]["default_subregion"] == "estrie"
    assert by_code["CA_QC"]["country"] == "CA"
    assert by_code["CA_QC"]["is_province"] is True
    assert len(by_code["CA_QC"]["subregions"]) == 3


def test_get_state_info_valid() -> None:
    """Verify get_state_info returns StateInfo instances with valid bounds."""
    for code in ["VT", "vt", StateCode.VT]:
        vt = get_state_info(code)
        assert vt is not None
        assert isinstance(vt, StateInfo)
        assert vt.state_code == "VT"
        assert vt.country == "US"
        assert vt.is_province is False
        assert vt.bounds.min_lat == pytest.approx(42.7268)
        assert vt.bounds.max_lat == pytest.approx(45.0167)
        assert vt.bounds.min_lon == pytest.approx(-73.4379)
        assert vt.bounds.max_lon == pytest.approx(-71.5033)
        assert vt.default_subregion == "chittenden"
        assert len(vt.subregions) == 14

    for code in ["NH", "nh", StateCode.NH]:
        nh = get_state_info(code)
        assert nh is not None
        assert isinstance(nh, StateInfo)
        assert nh.state_code == "NH"
        assert nh.country == "US"
        assert nh.is_province is False
        assert nh.bounds.min_lat == pytest.approx(42.6970)
        assert nh.bounds.max_lat == pytest.approx(45.3054)
        assert nh.bounds.min_lon == pytest.approx(-72.5572)
        assert nh.bounds.max_lon == pytest.approx(-70.6106)
        assert nh.default_subregion == "coos"
        assert len(nh.subregions) == 10

    for code in ["NY", "ny", StateCode.NY]:
        ny = get_state_info(code)
        assert ny is not None
        assert isinstance(ny, StateInfo)
        assert ny.state_code == "NY"
        assert ny.country == "US"
        assert ny.is_province is False
        assert ny.bounds.min_lat == pytest.approx(43.2000)
        assert ny.bounds.max_lat == pytest.approx(45.0100)
        assert ny.bounds.min_lon == pytest.approx(-74.5000)
        assert ny.bounds.max_lon == pytest.approx(-73.3000)
        assert ny.default_subregion == "essex_ny"
        assert len(ny.subregions) == 5

    for code in ["ME", "me", StateCode.ME]:
        me = get_state_info(code)
        assert me is not None
        assert isinstance(me, StateInfo)
        assert me.state_code == "ME"
        assert me.country == "US"
        assert me.is_province is False
        assert me.bounds.min_lat == pytest.approx(43.0)
        assert me.bounds.max_lat == pytest.approx(47.5)
        assert me.bounds.min_lon == pytest.approx(-71.1)
        assert me.bounds.max_lon == pytest.approx(-66.9)
        assert me.default_subregion == "oxford"
        assert len(me.subregions) == 3
        assert "oxford" in me.subregions
        assert "franklin" in me.subregions
        assert "cumberland" in me.subregions

    for code in ["MA", "ma", StateCode.MA]:
        ma = get_state_info(code)
        assert ma is not None
        assert isinstance(ma, StateInfo)
        assert ma.state_code == "MA"
        assert ma.country == "US"
        assert ma.is_province is False
        assert ma.bounds.min_lat == pytest.approx(41.2)
        assert ma.bounds.max_lat == pytest.approx(42.9)
        assert ma.bounds.min_lon == pytest.approx(-73.5)
        assert ma.bounds.max_lon == pytest.approx(-69.9)

    for code in ["CA_QC", "ca_qc", "QC", StateCode.CA_QC]:
        qc = get_state_info(code)
        assert qc is not None
        assert isinstance(qc, StateInfo)
        assert qc.state_code == "CA_QC"
        assert qc.country == "CA"
        assert qc.is_province is True
        assert qc.bounds.min_lat == pytest.approx(44.99)
        assert qc.bounds.max_lat == pytest.approx(46.50)
        assert qc.bounds.min_lon == pytest.approx(-74.50)
        assert qc.bounds.max_lon == pytest.approx(-70.50)
        assert qc.default_subregion == "estrie"
        assert len(qc.subregions) == 3
        assert "estrie" in qc.subregions
        assert "monteregie" in qc.subregions
        assert "montreal" in qc.subregions


def test_get_state_info_invalid() -> None:
    """Verify get_state_info returns None for invalid or unsupported states."""
    assert get_state_info("TX") is None
    assert get_state_info("CA") is None
    assert get_state_info("") is None
    assert get_state_info(None) is None  # type: ignore[arg-type]


def test_resolve_regional_bounds_statewide() -> None:
    """Verify statewide bounds resolution when subregion is omitted or 'all'/'statewide'."""
    res_vt = resolve_regional_bounds("VT")
    assert res_vt.ok
    assert res_vt.value is not None
    assert res_vt.value.name == "Vermont_Statewide"
    assert res_vt.value.min_lat == pytest.approx(42.7268)
    assert res_vt.value.max_lat == pytest.approx(45.0167)
    assert res_vt.value.min_lon == pytest.approx(-73.4379)
    assert res_vt.value.max_lon == pytest.approx(-71.5033)

    res_nh = resolve_regional_bounds("NH", "all")
    assert res_nh.ok
    assert res_nh.value is not None
    assert res_nh.value.name == "New_Hampshire_Statewide"
    assert res_nh.value.min_lat == pytest.approx(42.6970)
    assert res_nh.value.max_lat == pytest.approx(45.3054)

    res_ny = resolve_regional_bounds("NY", "statewide")
    assert res_ny.ok
    assert res_ny.value is not None
    assert res_ny.value.name == "New_York_Adirondack_Champlain"
    assert res_ny.value.min_lat == pytest.approx(43.2000)
    assert res_ny.value.max_lat == pytest.approx(45.0100)

    res_me = resolve_regional_bounds("ME", "all")
    assert res_me.ok
    assert res_me.value is not None
    assert res_me.value.name == "Maine_Statewide"
    assert res_me.value.min_lat == pytest.approx(43.0)
    assert res_me.value.max_lat == pytest.approx(47.5)
    assert res_me.value.min_lon == pytest.approx(-71.1)
    assert res_me.value.max_lon == pytest.approx(-66.9)

    res_ma = resolve_regional_bounds("MA")
    assert res_ma.ok
    assert res_ma.value is not None
    assert res_ma.value.name == "Massachusetts_Statewide"
    assert res_ma.value.min_lat == pytest.approx(41.2)
    assert res_ma.value.max_lat == pytest.approx(42.9)

    res_qc = resolve_regional_bounds("CA_QC", "all")
    assert res_qc.ok
    assert res_qc.value is not None
    assert res_qc.value.name == "Quebec_Southern"
    assert res_qc.value.min_lat == pytest.approx(44.99)
    assert res_qc.value.max_lat == pytest.approx(46.50)
    assert res_qc.value.min_lon == pytest.approx(-74.50)
    assert res_qc.value.max_lon == pytest.approx(-70.50)


def test_resolve_regional_bounds_county_level() -> None:
    """Verify resolving county and subregion-level bounds."""
    # VT county checks
    res_chit = resolve_regional_bounds("VT", "chittenden")
    assert res_chit.ok
    assert res_chit.value == VERMONT_COUNTY_BOUNDS["Chittenden"]

    res_grand = resolve_regional_bounds("VT", "Grand Isle County")
    assert res_grand.ok
    assert res_grand.value == VERMONT_COUNTY_BOUNDS["Grand Isle"]

    # NH county checks
    res_coos = resolve_regional_bounds("NH", "coos")
    assert res_coos.ok
    assert res_coos.value == NH_COUNTY_BOUNDS["coos"]

    res_grafton = resolve_regional_bounds("nh", "Grafton County")
    assert res_grafton.ok
    assert res_grafton.value == NH_COUNTY_BOUNDS["grafton"]

    # NY county checks
    res_essex_ny = resolve_regional_bounds("NY", "essex_ny")
    assert res_essex_ny.ok
    assert res_essex_ny.value == NY_COUNTY_BOUNDS["essex_ny"]

    res_essex_alias = resolve_regional_bounds("ny", "essex")
    assert res_essex_alias.ok
    assert res_essex_alias.value == NY_COUNTY_BOUNDS["essex_ny"]

    res_clinton = resolve_regional_bounds("NY", "Clinton")
    assert res_clinton.ok
    assert res_clinton.value == NY_COUNTY_BOUNDS["clinton"]

    # CA_QC subregion checks
    res_estrie = resolve_regional_bounds("CA_QC", "estrie")
    assert res_estrie.ok
    assert res_estrie.value == QC_SUBREGION_BOUNDS["estrie"]
    assert res_estrie.value.min_lat == pytest.approx(45.0)
    assert res_estrie.value.max_lat == pytest.approx(45.6)
    assert res_estrie.value.min_lon == pytest.approx(-72.6)
    assert res_estrie.value.max_lon == pytest.approx(-70.8)

    res_monteregie = resolve_regional_bounds("CA_QC", "monteregie")
    assert res_monteregie.ok
    assert res_monteregie.value == QC_SUBREGION_BOUNDS["monteregie"]

    res_montreal = resolve_regional_bounds("CA_QC", "montreal")
    assert res_montreal.ok
    assert res_montreal.value == QC_SUBREGION_BOUNDS["montreal"]

    # ME subregion checks
    res_oxford = resolve_regional_bounds("ME", "oxford")
    assert res_oxford.ok
    assert res_oxford.value == ME_SUBREGION_BOUNDS["oxford"]

    res_franklin = resolve_regional_bounds("ME", "franklin")
    assert res_franklin.ok
    assert res_franklin.value == ME_SUBREGION_BOUNDS["franklin"]

    res_cumberland = resolve_regional_bounds("ME", "cumberland")
    assert res_cumberland.ok
    assert res_cumberland.value == ME_SUBREGION_BOUNDS["cumberland"]


def test_resolve_regional_bounds_default_subregion() -> None:
    """Verify 'default' subregion resolves to state default."""
    res_vt = resolve_regional_bounds("VT", "default")
    assert res_vt.ok
    assert res_vt.value == VERMONT_COUNTY_BOUNDS["Chittenden"]

    res_nh = resolve_regional_bounds("NH", "default")
    assert res_nh.ok
    assert res_nh.value == NH_COUNTY_BOUNDS["coos"]

    res_ny = resolve_regional_bounds("NY", "default")
    assert res_ny.ok
    assert res_ny.value == NY_COUNTY_BOUNDS["essex_ny"]

    res_me = resolve_regional_bounds("ME", "default")
    assert res_me.ok
    assert res_me.value == ME_SUBREGION_BOUNDS["oxford"]

    res_qc = resolve_regional_bounds("CA_QC", "default")
    assert res_qc.ok
    assert res_qc.value == QC_SUBREGION_BOUNDS["estrie"]

    res_ma = resolve_regional_bounds("MA", "default")
    assert res_ma.ok
    assert res_ma.value == MA_STATE_BOUNDS


def test_resolve_regional_bounds_unsupported_state() -> None:
    """Verify resolving bounds for unsupported states fails with UNSUPPORTED_STATE."""
    res = resolve_regional_bounds("TX")
    assert not res.ok
    assert res.error is not None
    assert res.error.code == "UNSUPPORTED_STATE"
    assert "TX" in res.error.message


def test_resolve_regional_bounds_unknown_subregion() -> None:
    """Verify resolving unknown county fails with UNKNOWN_SUBREGION."""
    res = resolve_regional_bounds("VT", "miami_dade")
    assert not res.ok
    assert res.error is not None
    assert res.error.code == "UNKNOWN_SUBREGION"
    assert "miami_dade" in res.error.message


def test_load_state_candidates_vt() -> None:
    """Verify loading VT state candidates delegates to load_county_candidates."""
    res_all = load_state_candidates("VT")
    assert res_all.ok
    assert res_all.value is not None
    assert len(res_all.value) > 20

    res_county = load_state_candidates("VT", "chittenden")
    assert res_county.ok
    assert res_county.value is not None
    assert len(res_county.value) >= 3


def test_load_state_candidates_nh_ny() -> None:
    """Verify NH and NY candidate loading and county-level filtering from sample fixtures."""
    # NH loading
    res_nh_all = load_state_candidates("NH")
    assert res_nh_all.ok
    assert res_nh_all.value is not None
    assert len(res_nh_all.value) >= 5

    res_nh_coos = load_state_candidates("NH", "coos")
    assert res_nh_coos.ok
    assert res_nh_coos.value is not None
    assert any("WASH" in c.site_id for c in res_nh_coos.value)

    # NY loading
    res_ny_all = load_state_candidates("NY")
    assert res_ny_all.ok
    assert res_ny_all.value is not None
    assert len(res_ny_all.value) >= 4

    res_ny_essex = load_state_candidates("NY", "essex_ny")
    assert res_ny_essex.ok
    assert res_ny_essex.value is not None
    assert len(res_ny_essex.value) == 2


def test_load_state_candidates_ca_qc_me_ma() -> None:
    """Verify CA_QC, ME, and MA candidate loading behavior."""
    # MA always returns Result.success([])
    res_ma = load_state_candidates("MA")
    assert res_ma.ok
    assert res_ma.value == []

    # CA_QC and ME return empty list when fixture files do not exist
    res_qc = load_state_candidates("CA_QC")
    assert res_qc.ok
    assert isinstance(res_qc.value, list)

    res_me = load_state_candidates("ME")
    assert res_me.ok
    assert isinstance(res_me.value, list)


def test_load_state_candidates_nh_ny_missing_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify NH and NY return Result.success([]) when fixture files do not exist."""
    import meshscout.adapters.regions as regions_mod

    monkeypatch.setattr(regions_mod, "FIXTURES_DIR", tmp_path / "nonexistent_dir")

    res_nh = load_state_candidates("NH")
    assert res_nh.ok
    assert res_nh.value == []

    res_ny = load_state_candidates("NY")
    assert res_ny.ok
    assert res_ny.value == []

    res_qc = load_state_candidates("CA_QC")
    assert res_qc.ok
    assert res_qc.value == []

    res_me = load_state_candidates("ME")
    assert res_me.ok
    assert res_me.value == []


def test_load_state_candidates_unsupported_state() -> None:
    """Verify load_state_candidates fails gracefully on unsupported state."""
    res = load_state_candidates("TX")
    assert not res.ok
    assert res.error is not None
    assert res.error.code == "UNSUPPORTED_STATE"


def test_adapters_init_exports() -> None:
    """Verify all public symbols are accessible from meshscout.adapters."""
    import meshscout.adapters as adapters

    expected = [
        "StateCode",
        "SubregionInfo",
        "StateInfo",
        "list_supported_states",
        "get_state_info",
        "resolve_regional_bounds",
        "load_state_candidates",
    ]
    for symbol in expected:
        assert hasattr(adapters, symbol), f"meshscout.adapters missing symbol: {symbol}"
