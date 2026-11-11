"""Hermetic unit tests for LoRa airtime, traffic forecasting, role advisory, and backhaul."""

import json
from pathlib import Path
import pytest

from meshscout.core.contracts import Coordinate, SiteCandidate, SiteType
from meshscout.core.traffic import (
    BackhaulArchitecture,
    MeshCoreRole,
    MeshtasticRole,
    ReticulumRole,
    advise_node_role,
    compute_antenna_isolation_db,
    compute_lora_airtime_ms,
    compute_lora_sensitivity_dbm,
    forecast_channel_utilization,
    recommend_summit_backhaul,
)


# ==============================================================================
# 1. LoRa Airtime & Semtech AN1200.13 Golden Vectors
# ==============================================================================

def test_lora_airtime_golden_vector():
    """Verify Semtech AN1200.13 golden vector:

    SF7, BW125 kHz, CR 4/5 (cr=1), preamble 8, 10 bytes payload,
    explicit header, CRC on -> 41.2 ms (+/- 0.1 ms).
    """
    res = compute_lora_airtime_ms(
        payload_bytes=10,
        sf=7,
        bw_hz=125000.0,
        cr=1,
        preamble=8,
        explicit_header=True,
        crc=True,
    )

    # Expected: ~41.216 ms
    assert res.total_airtime_ms == pytest.approx(41.2, abs=0.1)
    assert res.sf == 7
    assert res.bw_hz == 125000.0
    assert res.cr == 1
    assert res.ldro_enabled is False
    assert res.symbol_time_ms == pytest.approx(1.024, rel=1e-3)
    assert res.preamble_time_ms == pytest.approx(12.544, abs=0.01)
    assert res.payload_time_ms == pytest.approx(28.672, abs=0.01)


def test_lora_airtime_ldro_threshold():
    """Verify Low Data Rate Optimization (LDRO) triggers at T_sym >= 16 ms."""
    # SF11 at BW62.5 kHz: T_sym = 2048 / 62500 = 32.768 ms >= 16 ms -> LDRO True
    res_ldro = compute_lora_airtime_ms(
        payload_bytes=10,
        sf=11,
        bw_hz=62500.0,
    )
    assert res_ldro.ldro_enabled is True
    assert res_ldro.symbol_time_ms == pytest.approx(32.768, rel=1e-3)

    # SF11 at BW250 kHz: T_sym = 2048 / 250000 = 8.192 ms < 16 ms -> LDRO False
    res_noldro = compute_lora_airtime_ms(
        payload_bytes=10,
        sf=11,
        bw_hz=250000.0,
    )
    assert res_noldro.ldro_enabled is False
    assert res_noldro.symbol_time_ms == pytest.approx(8.192, rel=1e-3)

    # SF12 at BW125 kHz: T_sym = 4096 / 125000 = 32.768 ms -> LDRO True
    res_sf12 = compute_lora_airtime_ms(
        payload_bytes=24,
        sf=12,
        bw_hz=125000.0,
    )
    assert res_sf12.ldro_enabled is True


def test_lora_airtime_validation():
    """Verify parameter validations on compute_lora_airtime_ms."""
    with pytest.raises(ValueError, match="Spreading factor"):
        compute_lora_airtime_ms(payload_bytes=10, sf=5, bw_hz=125000.0)

    with pytest.raises(ValueError, match="Spreading factor"):
        compute_lora_airtime_ms(payload_bytes=10, sf=13, bw_hz=125000.0)

    with pytest.raises(ValueError, match="Bandwidth must be positive"):
        compute_lora_airtime_ms(payload_bytes=10, sf=7, bw_hz=0.0)

    with pytest.raises(ValueError, match="Coding rate"):
        compute_lora_airtime_ms(payload_bytes=10, sf=7, bw_hz=125000.0, cr=5)


# ==============================================================================
# 2. Receiver Sensitivity & Antenna Isolation
# ==============================================================================

def test_lora_sensitivity_dbm():
    """Verify receiver sensitivity formula: -174 + 10*log10(BW) + NF + SNR_min(SF)."""
    sens_sf7 = compute_lora_sensitivity_dbm(sf=7, bw_hz=125000.0, nf_db=6.0)
    # -174 + 50.969 + 6.0 + (-7.5) = -124.53 dBm
    assert sens_sf7 == pytest.approx(-124.53, abs=0.1)

    sens_sf12 = compute_lora_sensitivity_dbm(sf=12, bw_hz=125000.0, nf_db=6.0)
    # -174 + 50.969 + 6.0 + (-20.0) = -137.03 dBm
    assert sens_sf12 == pytest.approx(-137.03, abs=0.1)
    # Higher SF must yield better (more sensitive / lower dBm) reception
    assert sens_sf12 < sens_sf7


def test_antenna_isolation_vertical_and_horizontal():
    """Verify antenna decoupling isolation at 915 MHz."""
    # Vertical 3m must provide >= 28 dB isolation per Land Mobile Radio standards
    iso_v3 = compute_antenna_isolation_db(vertical_sep_m=3.0, horizontal_sep_m=0.0, frequency_mhz=915.0)
    assert iso_v3 >= 28.0

    # Vertical 1m should also provide significant isolation
    iso_v1 = compute_antenna_isolation_db(vertical_sep_m=1.0, horizontal_sep_m=0.0, frequency_mhz=915.0)
    assert iso_v1 >= 28.0
    assert iso_v3 > iso_v1

    # Zero separation returns 0 dB
    iso_zero = compute_antenna_isolation_db(vertical_sep_m=0.0, horizontal_sep_m=0.0, frequency_mhz=915.0)
    assert iso_zero == 0.0

    # Horizontal separation
    iso_h10 = compute_antenna_isolation_db(vertical_sep_m=0.0, horizontal_sep_m=10.0, frequency_mhz=915.0)
    assert iso_h10 > 22.0


# ==============================================================================
# 3. Channel Utilization & Aloha Contention Forecaster
# ==============================================================================

def test_forecast_channel_utilization():
    """Verify duty cycle utilization and unslotted Aloha collision probability."""
    # 50 nodes generating 4 packets/hr with 3 hops (total 4 tx/packet) at 41.2ms
    # Total tx/hr = 50 * 4 * 4 = 800
    # Airtime = 800 * 0.0412 = 32.96 s -> 32.96 / 3600 = 0.9156%
    forecast = forecast_channel_utilization(
        exposed_population=50000,
        adoption_rate=0.001,
        packets_per_node_hour=4.0,
        airtime_ms=41.2,
        hop_limit=3,
        threshold_pct=25.0,
    )
    assert forecast.expected_nodes == 50
    assert forecast.channel_utilization_pct == pytest.approx(0.9156, rel=1e-2)
    assert forecast.exceeds_congestion_threshold is False
    assert 0.0 < forecast.aloha_collision_prob < 0.05

    # Heavy traffic: 2000 nodes generating 6 packets/hr with 3 hops
    # Total tx/hr = 2000 * 6 * 4 = 48,000 tx/hr
    # Airtime = 48,000 * 0.0412 = 1977.6 s -> 1977.6 / 3600 = 54.9%
    heavy_forecast = forecast_channel_utilization(
        exposed_population=2000000,
        adoption_rate=0.001,
        packets_per_node_hour=6.0,
        airtime_ms=41.2,
        hop_limit=3,
        threshold_pct=25.0,
    )
    assert heavy_forecast.expected_nodes == 2000
    assert heavy_forecast.channel_utilization_pct > 25.0
    assert heavy_forecast.exceeds_congestion_threshold is True
    assert heavy_forecast.aloha_collision_prob > 0.5


# ==============================================================================
# 4. Role Advisory & Town-Killer Mitigation
# ==============================================================================

@pytest.fixture
def mount_mansfield_site() -> SiteCandidate:
    """Prominent summit high site fixture."""
    return SiteCandidate(
        site_id="VT-PEAK-01",
        name="Mount Mansfield Summit Ridge",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=10.0,
        has_grid_power=True,
    )


@pytest.fixture
def essex_junction_home_site() -> SiteCandidate:
    """Residential low mast candidate fixture."""
    return SiteCandidate(
        site_id="VT-HOME-EJ01",
        name="Essex Junction Home Mast",
        location=Coordinate(lat=44.4900, lon=-73.1100, elevation_m=105.0),
        site_type=SiteType.CUSTOM,
        mast_height_m=6.0,
        has_grid_power=True,
    )


def test_mount_mansfield_role_recommendation(mount_mansfield_site):
    """Verify Mount Mansfield role assignments:

    - 0 overlapping routers -> ROUTER with coordination note.
    - >= 2 overlapping routers -> ROUTER_LATE with town_killer_risk=True.
    - Never recommends CLIENT_MUTE for an active summit repeater.
    """
    # Case 1: Zero overlapping routers -> ROUTER
    rec_zero = advise_node_role(
        site=mount_mansfield_site,
        viewshed_area_sq_km=800.0,
        exposed_population=60000,
        overlapping_router_count=0,
        protocol_family="Meshtastic",
    )
    assert rec_zero.recommended_role == MeshtasticRole.ROUTER.value
    assert rec_zero.town_killer_risk is False
    assert rec_zero.coordination_required is True
    assert rec_zero.recommended_preset == "MediumFast"
    assert rec_zero.recommended_hop_limit == 2
    assert rec_zero.recommended_role != MeshtasticRole.CLIENT_MUTE.value

    # Case 2: 2 overlapping routers -> ROUTER_LATE with town_killer_risk
    rec_two = advise_node_role(
        site=mount_mansfield_site,
        viewshed_area_sq_km=800.0,
        exposed_population=60000,
        overlapping_router_count=2,
        protocol_family="Meshtastic",
    )
    assert rec_two.recommended_role == MeshtasticRole.ROUTER_LATE.value
    assert rec_two.town_killer_risk is True
    assert "TOWN_KILLER_RISK" in rec_two.risk_message
    assert rec_two.coordination_required is True
    assert rec_two.recommended_role != MeshtasticRole.CLIENT_MUTE.value


def test_essex_junction_home_site_town_killer_demotion(essex_junction_home_site):
    """Verify that a residential low mast site attempting ROUTER is demoted to CLIENT."""
    rec = advise_node_role(
        site=essex_junction_home_site,
        viewshed_area_sq_km=15.0,
        exposed_population=10000,
        overlapping_router_count=0,
        protocol_family="Meshtastic",
        requested_role="ROUTER",
    )
    assert rec.recommended_role == MeshtasticRole.CLIENT.value
    assert rec.town_killer_risk is True
    assert "TOWN_KILLER_RISK" in rec.risk_message
    assert rec.coordination_required is False
    assert "CLIENT" in rec.cli_command


def test_multi_protocol_roles(mount_mansfield_site, essex_junction_home_site):
    """Verify MeshCore and Reticulum protocol family role recommendations."""
    # MeshCore
    mc_summit = advise_node_role(mount_mansfield_site, protocol_family="MeshCore")
    assert mc_summit.recommended_role == MeshCoreRole.REPEATER.value

    mc_home = advise_node_role(essex_junction_home_site, protocol_family="MeshCore")
    assert mc_home.recommended_role == MeshCoreRole.COMPANION.value

    # Reticulum
    rns_summit = advise_node_role(mount_mansfield_site, protocol_family="Reticulum")
    assert rns_summit.recommended_role == ReticulumRole.TRANSPORT.value

    rns_home = advise_node_role(essex_junction_home_site, protocol_family="Reticulum")
    assert rns_home.recommended_role == ReticulumRole.ENDPOINT.value


# ==============================================================================
# 5. Summit Backhaul Recommendations
# ==============================================================================

def test_summit_backhaul_recommendations(mount_mansfield_site):
    """Verify backhaul recommendations under varying congestion and line-of-sight."""
    site_bolton = SiteCandidate(
        site_id="VT-PEAK-02",
        name="Bolton Mountain",
        location=Coordinate(lat=44.4172, lon=-72.8503, elevation_m=1120.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=10.0,
    )

    # Low channel utilization (< 15%) -> DIRECT_LORA
    bh_direct = recommend_summit_backhaul(
        site_a=mount_mansfield_site,
        site_b=site_bolton,
        distance_km=14.5,
        line_of_sight=True,
        channel_utilization_pct=8.0,
    )
    assert bh_direct.architecture == BackhaulArchitecture.DIRECT_LORA
    assert bh_direct.required_vertical_isolation_m == 3.0
    assert bh_direct.estimated_isolation_db >= 28.0

    # Moderate channel utilization (20%) -> DUAL_RADIO_PI_BRIDGE
    bh_bridge = recommend_summit_backhaul(
        site_a=mount_mansfield_site,
        site_b=site_bolton,
        distance_km=14.5,
        line_of_sight=True,
        channel_utilization_pct=20.0,
    )
    assert bh_bridge.architecture == BackhaulArchitecture.DUAL_RADIO_PI_BRIDGE

    # Heavy channel utilization (>25%) with LOS -> MICROWAVE_IP_5_8GHZ
    bh_micro = recommend_summit_backhaul(
        site_a=mount_mansfield_site,
        site_b=site_bolton,
        distance_km=14.5,
        line_of_sight=True,
        channel_utilization_pct=32.0,
    )
    assert bh_micro.architecture == BackhaulArchitecture.MICROWAVE_IP_5_8GHZ
    assert any("microwave" in note.lower() for note in bh_micro.notes)

    # Heavy channel utilization without LOS -> DUAL_RADIO_PI_BRIDGE
    bh_obstructed = recommend_summit_backhaul(
        site_a=mount_mansfield_site,
        site_b=site_bolton,
        distance_km=14.5,
        line_of_sight=False,
        channel_utilization_pct=32.0,
    )
    assert bh_obstructed.architecture == BackhaulArchitecture.DUAL_RADIO_PI_BRIDGE


# ==============================================================================
# 6. Vermont Town Population Fixture
# ==============================================================================

def test_vt_town_population_fixture():
    """Verify that vt_town_population.json exists, contains all reference towns, and has valid data."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "vt_town_population.json"
    assert fixture_path.is_file(), f"Fixture missing at {fixture_path}"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Must contain key reference towns
    assert "Burlington" in data
    assert data["Burlington"]["population_2020"] == 44743
    assert data["Burlington"]["source_url"] == "https://data.census.gov"

    assert "Essex Junction" in data
    assert data["Essex Junction"]["population_2020"] == 10590

    assert "South Burlington" in data
    assert data["South Burlington"]["population_2020"] == 20292

    assert "Montpelier" in data
    assert data["Montpelier"]["population_2020"] == 8074

    assert "Rutland" in data
    assert data["Rutland"]["population_2020"] == 15807

    # Total reference towns count
    assert len(data) == 71

    # Verify every entry has valid metadata
    for town, info in data.items():
        assert "population_2020" in info, f"Missing population_2020 for {town}"
        assert "source_url" in info, f"Missing source_url for {town}"
        assert "retrieved_on" in info, f"Missing retrieved_on for {town}"
        if info["population_2020"] is not None:
            assert isinstance(info["population_2020"], int)
            assert info["population_2020"] > 0
