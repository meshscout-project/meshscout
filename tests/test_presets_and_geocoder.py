"""Unit tests for MeshScout hardware/protocol/seasonal presets and privacy-fuzzed geocoder."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from meshscout.adapters.geocoder import (
    LOCAL_GAZETTEER,
    GeocodedLocation,
    PrivacyGeocoder,
    fuzz_coordinate,
    to_maidenhead,
)
from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RadioConfig,
    SiteCandidate,
    SiteType,
)
from meshscout.core.itm import evaluate_point_to_point_link
from meshscout.core.presets import (
    HARDWARE_PRESETS,
    PROTOCOL_PROFILES,
    SEASONAL_PROFILES,
    build_radio_config,
    list_all_presets,
)


def _sample_elevation_profile() -> ElevationProfile:
    """Create a deterministic 10 km elevation profile between Essex Junction and Underhill."""
    src_coord = Coordinate(lat=44.4906, lon=-73.1112, elevation_m=108.0)
    dst_coord = Coordinate(lat=44.5275, lon=-72.8950, elevation_m=215.0)
    src = SiteCandidate(
        site_id="VT-ESX-01",
        name="Essex Junction Five Corners",
        location=src_coord,
        site_type=SiteType.BUILDING_ROOFTOP,
        mast_height_m=8.0,
    )
    dst = SiteCandidate(
        site_id="VT-UND-01",
        name="Underhill Ridge",
        location=dst_coord,
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=12.0,
    )
    points = [
        ElevationPoint(distance_m=0.0, elevation_m=108.0, coordinate=src_coord),
        ElevationPoint(
            distance_m=5000.0,
            elevation_m=150.0,
            coordinate=Coordinate(lat=44.5090, lon=-73.0031, elevation_m=150.0),
        ),
        ElevationPoint(distance_m=10000.0, elevation_m=215.0, coordinate=dst_coord),
    ]
    return ElevationProfile(
        source_site=src,
        target_site=dst,
        distance_km=10.0,
        points=points,
    )


def test_all_presets_load_and_build_valid_radio_config() -> None:
    """Verify all hardware, protocol, and seasonal catalogs load and build valid RadioConfig objects."""
    expected_hw = {
        "RAK4631_SOLAR",
        "STATION_G2_BACKBONE",
        "HELTEC_V3_HOME",
        "SENSECAP_T1000E",
    }
    expected_proto = {
        "MESHTASTIC_LONGFAST",
        "MESHTASTIC_MEDIUMFAST",
        "MESHCORE_NARROW",
        "MESHCORE_STANDARD",
        "RETICULUM_RNODE_LONG",
        "RETICULUM_RNODE_FAST",
    }
    expected_seasons = {"WINTER_LEAF_OFF", "SUMMER_LEAF_ON"}

    assert set(HARDWARE_PRESETS.keys()) == expected_hw
    assert set(PROTOCOL_PROFILES.keys()) == expected_proto
    assert set(SEASONAL_PROFILES.keys()) == expected_seasons

    for hw_id in expected_hw:
        for proto_id in expected_proto:
            for season_id in expected_seasons:
                res = build_radio_config(
                    hardware_id=hw_id,
                    protocol_id=proto_id,
                    season_id=season_id,
                )
                assert res.ok is True
                assert isinstance(res.value, RadioConfig)
                assert res.value.frequency_mhz == 915.0

    catalog_dump = list_all_presets()
    assert set(catalog_dump["hardware_presets"].keys()) == expected_hw
    assert set(catalog_dump["protocol_profiles"].keys()) == expected_proto
    assert set(catalog_dump["seasonal_profiles"].keys()) == expected_seasons

    bad_hw = build_radio_config(hardware_id="NON_EXISTENT")
    assert bad_hw.ok is False
    assert bad_hw.error is not None
    assert bad_hw.error.code == "UNKNOWN_HARDWARE_PRESET"


def test_summer_leaf_on_reduces_link_margin_by_8_5_db() -> None:
    """Verify SUMMER_LEAF_ON reduces link margin by 8.5 dB compared to WINTER_LEAF_OFF."""
    profile = _sample_elevation_profile()

    winter_cfg_res = build_radio_config(
        hardware_id="RAK4631_SOLAR",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="WINTER_LEAF_OFF",
    )
    summer_cfg_res = build_radio_config(
        hardware_id="RAK4631_SOLAR",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="SUMMER_LEAF_ON",
    )
    assert winter_cfg_res.ok and winter_cfg_res.value is not None
    assert summer_cfg_res.ok and summer_cfg_res.value is not None

    winter_link = evaluate_point_to_point_link(profile, radio=winter_cfg_res.value)
    summer_link = evaluate_point_to_point_link(profile, radio=summer_cfg_res.value)
    assert winter_link.ok and winter_link.value is not None
    assert summer_link.ok and summer_link.value is not None

    margin_diff = round(winter_link.value.link_margin_db - summer_link.value.link_margin_db, 4)
    assert margin_diff == pytest.approx(8.5, abs=1e-4)


def test_meshcore_narrow_provides_plus_5_db_margin_over_meshtastic_longfast() -> None:
    """Verify MESHCORE_NARROW (-139 dBm) adds +5.0 dB link margin over MESHTASTIC_LONGFAST (-134 dBm)."""
    profile = _sample_elevation_profile()

    mt_res = build_radio_config(
        hardware_id="RAK4631_SOLAR",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="WINTER_LEAF_OFF",
    )
    mc_res = build_radio_config(
        hardware_id="RAK4631_SOLAR",
        protocol_id="MESHCORE_NARROW",
        season_id="WINTER_LEAF_OFF",
    )
    assert mt_res.ok and mt_res.value is not None
    assert mc_res.ok and mc_res.value is not None

    mt_link = evaluate_point_to_point_link(profile, radio=mt_res.value)
    mc_link = evaluate_point_to_point_link(profile, radio=mc_res.value)
    assert mt_link.ok and mt_link.value is not None
    assert mc_link.ok and mc_link.value is not None

    gain_db = round(mc_link.value.link_margin_db - mt_link.value.link_margin_db, 4)
    assert gain_db == pytest.approx(5.0, abs=1e-4)


def test_to_maidenhead_essex_junction() -> None:
    """Verify to_maidenhead computes true Maidenhead grids for Essex Junction coordinates."""
    coord = Coordinate(lat=44.4906, lon=-73.1112, elevation_m=108.0)
    grid6 = to_maidenhead(coord, precision=6)
    assert grid6.lower() == "fn34kl"
    assert grid6 == "FN34kl"

    grid4 = to_maidenhead(coord, precision=4)
    assert grid4 == "FN34"

    grid8 = to_maidenhead(coord, precision=8)
    assert len(grid8) == 8
    assert grid8.lower().startswith("fn34kl")

    # Eastern Essex / Williston border (lon -73.0800) falls into FN34ll
    coord_east = Coordinate(lat=44.4906, lon=-73.0800, elevation_m=108.0)
    assert to_maidenhead(coord_east, precision=6) == "FN34ll"


def test_fuzz_coordinate_snaps_nearby_houses_to_identical_200m_cell() -> None:
    """Verify two nearby house coordinates within the same 200m cell snap to the exact same fuzzed coordinate."""
    # Step size at 44.4906 deg lat:
    # lat_step = 200 / 111320 ≈ 0.0017966 (cell [44.49034..., 44.49214...])
    # lon_step ≈ 0.0025185 (cell [-73.11202..., -73.10950...])
    house_a = Coordinate(lat=44.49061, lon=-73.11125, elevation_m=108.0)
    house_b = Coordinate(lat=44.49145, lon=-73.11035, elevation_m=108.0)

    fuzzed_a = fuzz_coordinate(house_a, grid_m=200.0)
    fuzzed_b = fuzz_coordinate(house_b, grid_m=200.0)

    assert fuzzed_a.lat == fuzzed_b.lat
    assert fuzzed_a.lon == fuzzed_b.lon
    assert fuzzed_a.elevation_m == 108.0
    assert fuzzed_b.elevation_m == 108.0
    assert fuzzed_a != house_a


def test_privacy_geocoder_offline_speed_and_gazetteer(tmp_path: Path) -> None:
    """Verify PrivacyGeocoder resolves '05452' and 'Essex Junction, VT' offline in <10ms."""
    geocoder = PrivacyGeocoder(cache_db_path=tmp_path / "geocode_cache.sqlite", no_delay=True)

    t0 = time.perf_counter()
    res_zip = geocoder.geocode("05452", apply_privacy_fuzz=True, offline_only=True)
    elapsed_zip_ms = (time.perf_counter() - t0) * 1000.0

    assert res_zip.ok is True
    assert res_zip.value is not None
    assert elapsed_zip_ms < 500.0  # Resilient ceiling for CI runner I/O jitter
    assert res_zip.value.display_name == "Essex Junction, VT 05452"
    assert res_zip.value.privacy_fuzzed is True
    assert res_zip.value.source == "local_fixture"
    assert res_zip.value.maidenhead_grid.lower() == "fn34kl"
    assert res_zip.value.coordinate == res_zip.value.fuzzed_coordinate
    assert res_zip.value.raw_coordinate.lat == pytest.approx(44.4906)
    assert res_zip.value.raw_coordinate.lon == pytest.approx(-73.1112)

    t1 = time.perf_counter()
    res_town = geocoder.geocode("Essex Junction, VT", apply_privacy_fuzz=True, offline_only=True)
    elapsed_town_ms = (time.perf_counter() - t1) * 1000.0

    assert res_town.ok is True
    assert res_town.value is not None
    assert elapsed_town_ms < 500.0  # Resilient ceiling for CI runner I/O jitter
    assert res_town.value.coordinate == res_zip.value.coordinate

    # Raw LAT,LON,ELEV string parsing
    res_raw = geocoder.geocode("44.5437, -72.8143, 1339.0", apply_privacy_fuzz=False, offline_only=True)
    assert res_raw.ok is True
    assert res_raw.value is not None
    assert res_raw.value.privacy_fuzzed is False
    assert res_raw.value.coordinate == res_raw.value.raw_coordinate
    assert res_raw.value.coordinate.elevation_m == 1339.0


def test_privacy_geocoder_05464_cambridge_jeffersonville_offline(tmp_path: Path) -> None:
    """Verify '05464' and 'Jeffersonville, VT' resolve offline in <10ms in Lamoille County."""
    from meshscout.adapters.vt_counties import VERMONT_COUNTY_BOUNDS

    geocoder = PrivacyGeocoder(cache_db_path=tmp_path / "geocode_cache.sqlite", no_delay=True)

    t0 = time.perf_counter()
    res_zip = geocoder.geocode("05464", apply_privacy_fuzz=True, offline_only=True)
    elapsed_zip_ms = (time.perf_counter() - t0) * 1000.0

    assert res_zip.ok is True
    assert res_zip.value is not None
    assert elapsed_zip_ms < 500.0  # Resilient ceiling for CI runner I/O jitter
    assert res_zip.value.display_name == "Jeffersonville / Cambridge, VT 05464"
    assert res_zip.value.source == "local_fixture"
    assert res_zip.value.raw_coordinate.lat == pytest.approx(44.6436)
    assert res_zip.value.raw_coordinate.lon == pytest.approx(-72.8270)
    assert VERMONT_COUNTY_BOUNDS["Lamoille"].contains(res_zip.value.raw_coordinate)

    t1 = time.perf_counter()
    res_town = geocoder.geocode("Jeffersonville, VT", apply_privacy_fuzz=True, offline_only=True)
    elapsed_town_ms = (time.perf_counter() - t1) * 1000.0

    assert res_town.ok is True
    assert res_town.value is not None
    assert elapsed_town_ms < 500.0  # Resilient ceiling for CI runner I/O jitter
    assert res_town.value.display_name == "Jeffersonville / Cambridge, VT 05464"
    assert VERMONT_COUNTY_BOUNDS["Lamoille"].contains(res_town.value.raw_coordinate)

    # Cambridge, VT should also resolve to the same location
    res_cambridge = geocoder.geocode("Cambridge, VT", apply_privacy_fuzz=True, offline_only=True)
    assert res_cambridge.ok is True
    assert res_cambridge.value is not None
    assert res_cambridge.value.display_name == "Jeffersonville / Cambridge, VT 05464"


def test_privacy_geocoder_online_fallback_and_sqlite_caching(tmp_path: Path) -> None:
    """Verify unknown query with offline_only=False attempts online fallback and caches to SQLite."""
    cache_file = tmp_path / "geocode_cache.sqlite"
    geocoder = PrivacyGeocoder(cache_db_path=cache_file, no_delay=True)

    mock_nominatim_payload = [
        {
            "lat": "34.0736",
            "lon": "-118.4004",
            "display_name": "Beverly Hills, Los Angeles County, California, 90210, USA",
        }
    ]

    with patch.object(geocoder.rate_limiter, "execute", return_value=mock_nominatim_payload) as mock_exec:
        res = geocoder.geocode("90210", apply_privacy_fuzz=True, offline_only=False)
        assert res.ok is True
        assert res.value is not None
        assert res.value.source == "nominatim"
        assert res.value.display_name == "Beverly Hills, Los Angeles County, California, 90210, USA"
        assert res.value.raw_coordinate.lat == pytest.approx(34.0736)
        assert res.value.raw_coordinate.lon == pytest.approx(-118.4004)
        assert mock_exec.call_count == 1

    # Second query for same location must hit SQLite cache offline (<50ms) without calling online Nominatim
    with patch.object(geocoder.rate_limiter, "execute") as mock_exec_cached:
        t0 = time.perf_counter()
        res_cached = geocoder.geocode("90210", apply_privacy_fuzz=True, offline_only=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert res_cached.ok is True
        assert res_cached.value is not None
        assert res_cached.value.source == "sqlite_cache"
        assert elapsed_ms < 500.0  # Resilient ceiling for CI runner I/O jitter
        assert res_cached.value.display_name == "Beverly Hills, Los Angeles County, California, 90210, USA"
        mock_exec_cached.assert_not_called()

    # Query with offline_only=True for non-cached unknown location fails with LOCATION_NOT_FOUND_OFFLINE
    res_unknown_offline = geocoder.geocode("unknown-place-xyz", offline_only=True)
    assert res_unknown_offline.ok is False
    assert res_unknown_offline.error is not None
    assert res_unknown_offline.error.code == "LOCATION_NOT_FOUND_OFFLINE"

    # Query with offline_only=False where Nominatim returns empty list fails with LOCATION_NOT_FOUND
    with patch.object(geocoder.rate_limiter, "execute", return_value=[]):
        res_unknown_online = geocoder.geocode("nonexistent-somewhere-12345", offline_only=False)
        assert res_unknown_online.ok is False
        assert res_unknown_online.error is not None
        assert res_unknown_online.error.code == "LOCATION_NOT_FOUND"


def test_privacy_geocoder_vermont_municipal_alias_retry(tmp_path: Path) -> None:
    """Verify queries with postal 'Essex Junction' falling back to 'Essex' town boundary."""
    cache_file = tmp_path / "geocode_cache.sqlite"
    geocoder = PrivacyGeocoder(cache_db_path=cache_file, no_delay=True)

    calls = []

    def mock_fetch(fn):
        res = fn()
        calls.append(res)
        return res

    # First attempt (Essex Junction) returns empty; second attempt (Essex) succeeds
    mock_responses = [
        [],  # "Linden Lane, Essex Junction, VT" -> []
        [{"lat": "44.50239", "lon": "-73.05925", "display_name": "Linden Lane, Essex Center, Essex, VT 05452"}],
    ]

    with patch.object(geocoder.rate_limiter, "execute", side_effect=mock_responses) as mock_exec:
        res = geocoder.geocode("Linden Lane, Essex Junction, VT", apply_privacy_fuzz=True, offline_only=False)
        assert res.ok is True
        assert res.value is not None
        assert res.value.source == "nominatim"
        assert "Linden Lane" in res.value.display_name
        assert res.value.raw_coordinate.lat == pytest.approx(44.50239)
        assert res.value.raw_coordinate.lon == pytest.approx(-73.05925)
        assert mock_exec.call_count == 2
