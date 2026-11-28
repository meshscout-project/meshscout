"""Hermetic unit and L3/L4 integration tests for directional RF and two-tier fabric planning."""

from __future__ import annotations

import json
import math
import warnings

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*BlockingPortal.*", category=DeprecationWarning)
    from fastapi.testclient import TestClient

from meshscout import cli, commands
from meshscout.core.contracts import (
    AntennaPattern,
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    InterfaceTier,
    MultiInterfaceSiteProfile,
    RadiationClass,
    RadioConfig,
    RadioInterfaceSpec,
    ReachabilityState,
    SiteCandidate,
    SiteType,
)
from meshscout.core.fabric import (
    evaluate_cosite_desense,
    find_multi_interface_route,
    solve_two_tier_fabric,
)
from meshscout.core.itm import (
    calculate_antenna_downtilt,
    calculate_azimuth_pattern_loss_db,
    evaluate_point_to_point_link,
    forward_azimuth_deg,
)
from meshscout.core.presets import (
    ANTENNA_PATTERN_PRESETS,
    PROTOCOL_PROFILES,
    build_radio_config,
    list_all_presets,
)
from meshscout.core.provisioning import generate_multi_interface_provisioning
from meshscout.core.regulatory import (
    RegulatoryDomain,
    TransmissionMode,
    advise_eirp,
    detect_regulatory_domain,
)
from meshscout.core.viewshed import (
    TargetGridPoint,
    compute_radial_viewshed_polygon,
    compute_viewshed,
    evaluate_target_coverage,
)
from meshscout.mcp_server import MeshScoutMCPServer
from meshscout.web.resilience_routes import build_resilience_router


def _make_site(
    site_id: str,
    lat: float,
    lon: float,
    elevation_m: float = 150.0,
    mast_height_m: float = 10.0,
    site_type: SiteType = SiteType.MOUNTAIN_PEAK,
    notes: str | None = None,
) -> SiteCandidate:
    return SiteCandidate(
        site_id=site_id,
        name=f"Site {site_id}",
        location=Coordinate(lat=lat, lon=lon, elevation_m=elevation_m),
        site_type=site_type,
        mast_height_m=mast_height_m,
        notes=notes,
    )


def _flat_elevation(lat: float, lon: float) -> float:
    return 100.0


def _build_flat_profile(
    src: SiteCandidate,
    dst: SiteCandidate,
    distance_km: float = 10.0,
) -> ElevationProfile:
    mid_lat = (src.location.lat + dst.location.lat) / 2.0
    mid_lon = (src.location.lon + dst.location.lon) / 2.0
    points = [
        ElevationPoint(distance_m=0.0, elevation_m=src.location.elevation_m, coordinate=src.location),
        ElevationPoint(
            distance_m=distance_km * 500.0,
            elevation_m=min(src.location.elevation_m, dst.location.elevation_m),
            coordinate=Coordinate(
                lat=mid_lat,
                lon=mid_lon,
                elevation_m=min(src.location.elevation_m, dst.location.elevation_m),
            ),
        ),
        ElevationPoint(
            distance_m=distance_km * 1000.0,
            elevation_m=dst.location.elevation_m,
            coordinate=dst.location,
        ),
    ]
    return ElevationProfile(
        source_site=src,
        target_site=dst,
        distance_km=distance_km,
        points=points,
    )


# ---------------------------------------------------------------------------
# 1. Contracts: AntennaPattern & MultiInterfaceSiteProfile
# ---------------------------------------------------------------------------


def test_contracts_antenna_pattern_and_multi_interface() -> None:
    """Validate RadiationClass, InterfaceTier, AntennaPattern bounds, and multi-interface contracts."""
    assert RadiationClass.OMNI.value == "omni"
    assert RadiationClass.SECTOR.value == "sector"
    assert RadiationClass.DIRECTIONAL.value == "directional"

    assert InterfaceTier.ACCESS_INFILL.value == "access_infill"
    assert InterfaceTier.BACKHAUL_BRIDGE.value == "backhaul_bridge"

    # Valid AntennaPattern boundary values
    pattern = AntennaPattern(
        radiation_class=RadiationClass.DIRECTIONAL,
        azimuth_deg=359.5,
        h_beamwidth_deg=65.0,
        v_beamwidth_deg=180.0,
        downtilt_deg=-45.0,
        front_to_back_db=45.0,
    )
    assert pattern.azimuth_deg == 359.5

    # Invalid AntennaPattern bounds
    for bad_kwargs in (
        {"azimuth_deg": -0.1},
        {"azimuth_deg": 360.0},
        {"h_beamwidth_deg": 0.0},
        {"h_beamwidth_deg": 360.1},
        {"v_beamwidth_deg": 0.0},
        {"v_beamwidth_deg": 180.1},
        {"downtilt_deg": -45.1},
        {"downtilt_deg": 45.1},
        {"front_to_back_db": -0.1},
        {"front_to_back_db": 45.1},
    ):
        with pytest.raises(ValidationError):
            AntennaPattern(**bad_kwargs)

    # Optional RadioConfig.antenna_pattern
    default_radio = RadioConfig()
    assert default_radio.antenna_pattern is None
    dir_radio = RadioConfig(antenna_pattern=pattern)
    assert dir_radio.antenna_pattern == pattern

    # RadioInterfaceSpec valid & invalid
    iface = RadioInterfaceSpec(
        interface_id="backhaul-0",
        tier=InterfaceTier.BACKHAUL_BRIDGE,
        radio=dir_radio,
        mast_mount_m=12.0,
        filter_rejection_db=35.0,
        bridge_group="trunk-a",
        protocol_family="MeshCore",
    )
    assert iface.tier == InterfaceTier.BACKHAUL_BRIDGE

    with pytest.raises(ValidationError):
        RadioInterfaceSpec(interface_id="")
    with pytest.raises(ValidationError):
        RadioInterfaceSpec(interface_id="if0", mast_mount_m=-0.5)
    with pytest.raises(ValidationError):
        RadioInterfaceSpec(interface_id="if0", filter_rejection_db=-1.0)

    # MultiInterfaceSiteProfile constraints
    profile = MultiInterfaceSiteProfile(
        site_id="VT-TEST-01",
        interfaces=[iface],
        noise_penalty_db=2.5,
    )
    assert profile.site_id == "VT-TEST-01"
    assert len(profile.interfaces) == 1

    with pytest.raises(ValidationError):
        MultiInterfaceSiteProfile(site_id="", interfaces=[iface])
    with pytest.raises(ValidationError):
        MultiInterfaceSiteProfile(site_id="VT-TEST-01", interfaces=[])
    with pytest.raises(ValidationError):
        MultiInterfaceSiteProfile(site_id="VT-TEST-01", interfaces=[iface], noise_penalty_db=-0.1)


# ---------------------------------------------------------------------------
# 2. Regulatory: Directional P2P, DTS bandwidth, ETSI EN 300 220, ACMA LIPD
# ---------------------------------------------------------------------------


def test_regulatory_directional_p2p_and_etsi_acma() -> None:
    """Validate OMNI_P2MP vs DIRECTIONAL_P2P, bandwidth_khz DTS warning, ETSI, and ACMA."""
    # US 902-928 MHz: directional_p2p with gain > 6 dBi triggers 1:1 rule + 2400-2483.5 MHz scope warning
    dir_report = advise_eirp(
        tx_power_dbm=27.0,
        antenna_gain_dbi=9.0,
        frequency_mhz=915.0,
        domain=RegulatoryDomain.US_FCC_PART15,
        transmission_mode=TransmissionMode.DIRECTIONAL_P2P,
        bandwidth_khz=250.0,
    )
    assert dir_report.recommended_max_tx_dbm == 27.0
    assert any("2400-2483.5 MHz" in w and "1:1" in w for w in dir_report.warnings)
    assert any("500.0 kHz" in w for w in dir_report.warnings)

    # OMNI_P2MP without bandwidth_khz omits both the 2400-2483.5 MHz scope warning and DTS warning
    omni_report = advise_eirp(
        tx_power_dbm=27.0,
        antenna_gain_dbi=9.0,
        frequency_mhz=915.0,
        domain=RegulatoryDomain.US_FCC_PART15,
        transmission_mode=TransmissionMode.OMNI_P2MP,
        bandwidth_khz=None,
    )
    assert not any("2400-2483.5 MHz" in w for w in omni_report.warnings)
    assert not any("500.0 kHz" in w for w in omni_report.warnings)

    # DTS >= 500 kHz does not emit bandwidth warning
    dts_ok = advise_eirp(
        tx_power_dbm=24.0,
        antenna_gain_dbi=6.0,
        frequency_mhz=915.0,
        domain=RegulatoryDomain.CA_ISED_RSS247,
        transmission_mode=TransmissionMode.OMNI_P2MP,
        bandwidth_khz=500.0,
    )
    assert not any("500.0 kHz" in w for w in dts_ok.warnings)

    # EU ETSI EN 300 220 detection and sub-bands
    assert detect_regulatory_domain("EU") == RegulatoryDomain.EU_ETSI_EN300220
    assert detect_regulatory_domain("EU_868") == RegulatoryDomain.EU_ETSI_EN300220
    assert detect_regulatory_domain("ETSI") == RegulatoryDomain.EU_ETSI_EN300220

    etsi_hi = advise_eirp(
        tx_power_dbm=27.0,
        antenna_gain_dbi=2.15,
        frequency_mhz=869.525,
        domain=RegulatoryDomain.EU_ETSI_EN300220,
    )
    assert etsi_hi.conducted_limit_dbm == 29.15
    assert etsi_hi.eirp_limit_dbm == 29.15
    assert etsi_hi.warnings == []

    etsi_lo = advise_eirp(
        tx_power_dbm=14.0,
        antenna_gain_dbi=2.15,
        frequency_mhz=868.3,
        domain=RegulatoryDomain.EU_ETSI_EN300220,
    )
    assert etsi_lo.conducted_limit_dbm == 16.15
    assert etsi_lo.eirp_limit_dbm == 16.15
    assert etsi_lo.warnings == []

    etsi_oob = advise_eirp(
        tx_power_dbm=20.0,
        antenna_gain_dbi=3.0,
        frequency_mhz=915.0,
        domain=RegulatoryDomain.EU_ETSI_EN300220,
    )
    assert etsi_oob.conducted_limit_dbm == 16.15
    assert etsi_oob.eirp_limit_dbm == 16.15
    assert any("clamping limits to 16.15 dBm" in w for w in etsi_oob.warnings)

    # AU ACMA LIPD detection, 915-928 MHz 30.0 dBm ceiling, out-of-band warning
    assert detect_regulatory_domain("AU") == RegulatoryDomain.AU_ACMA_LIPD
    assert detect_regulatory_domain("ANZ") == RegulatoryDomain.AU_ACMA_LIPD
    assert detect_regulatory_domain("ACMA") == RegulatoryDomain.AU_ACMA_LIPD

    acma_ok = advise_eirp(
        tx_power_dbm=25.0,
        antenna_gain_dbi=5.0,
        frequency_mhz=920.0,
        domain=RegulatoryDomain.AU_ACMA_LIPD,
    )
    assert acma_ok.conducted_limit_dbm == 30.0
    assert acma_ok.eirp_limit_dbm == 30.0
    assert acma_ok.warnings == []

    acma_oob = advise_eirp(
        tx_power_dbm=28.0,
        antenna_gain_dbi=5.0,
        frequency_mhz=905.0,
        domain=RegulatoryDomain.AU_ACMA_LIPD,
    )
    assert any("915.0 - 928.0 MHz" in w for w in acma_oob.warnings)
    assert any("ACMA LIPD" in w for w in acma_oob.warnings)


# ---------------------------------------------------------------------------
# 3. ITM: Forward azimuth, azimuth pattern loss, downtilt, directional P2P
# ---------------------------------------------------------------------------


def test_itm_directional_azimuth_and_downtilt_bracket() -> None:
    """Validate forward_azimuth_deg, azimuth pattern loss, downtilt overrides, and directional link."""
    origin = Coordinate(lat=44.0, lon=-73.0, elevation_m=100.0)
    north = Coordinate(lat=44.1, lon=-73.0, elevation_m=100.0)
    east = Coordinate(lat=44.0, lon=-72.9, elevation_m=100.0)
    south = Coordinate(lat=43.9, lon=-73.0, elevation_m=100.0)
    west = Coordinate(lat=44.0, lon=-73.1, elevation_m=100.0)

    assert forward_azimuth_deg(origin, origin) == 0.0
    assert math.isclose(forward_azimuth_deg(origin, north), 0.0, abs_tol=0.1)
    assert math.isclose(forward_azimuth_deg(origin, east), 90.0, abs_tol=0.2)
    assert math.isclose(forward_azimuth_deg(origin, south), 180.0, abs_tol=0.1)
    assert math.isclose(forward_azimuth_deg(origin, west), 270.0, abs_tol=0.2)

    omni_pat = ANTENNA_PATTERN_PRESETS["OMNI_360"]
    yagi_pat = AntennaPattern(
        radiation_class=RadiationClass.DIRECTIONAL,
        azimuth_deg=90.0,
        h_beamwidth_deg=60.0,
        front_to_back_db=16.0,
    )
    assert calculate_azimuth_pattern_loss_db(123.0, None) == 0.0
    assert calculate_azimuth_pattern_loss_db(123.0, omni_pat) == 0.0
    assert calculate_azimuth_pattern_loss_db(90.0, yagi_pat) == 0.0
    # Half-beamwidth offset (30 deg for 60 deg BW): 12 * (30/60)^2 = 3.0 dB
    assert calculate_azimuth_pattern_loss_db(120.0, yagi_pat) == 3.0
    # Opposite bearing (270 deg -> delta=180) clamped to front_to_back_db = 16.0
    assert calculate_azimuth_pattern_loss_db(270.0, yagi_pat) == 16.0

    # Downtilt bracket: mechanical_downtilt_deg and v_beamwidth_override_deg vs legacy defaults
    summit = _make_site("SUMMIT", 44.5, -72.8, elevation_m=1300.0, mast_height_m=10.0)
    valley = _make_site("VALLEY", 44.5, -72.85, elevation_m=100.0, mast_height_m=2.0)

    legacy_dt = calculate_antenna_downtilt(
        source_site=summit,
        target_site=valley,
        distance_km=4.0,
        antenna_gain_dbi=8.0,
    )
    assert legacy_dt.vertical_beamwidth_deg == 10.0
    assert legacy_dt.is_overshooting is True
    assert legacy_dt.pattern_attenuation_db > 0.5

    tilted_dt = calculate_antenna_downtilt(
        source_site=summit,
        target_site=valley,
        distance_km=4.0,
        antenna_gain_dbi=8.0,
        mechanical_downtilt_deg=legacy_dt.look_down_angle_deg,
        v_beamwidth_override_deg=18.0,
    )
    assert tilted_dt.vertical_beamwidth_deg == 18.0
    assert tilted_dt.is_overshooting is False
    assert tilted_dt.pattern_attenuation_db == 0.0

    # Directional evaluate_point_to_point_link: on-axis vs mis-aimed symmetric and asymmetric
    src = _make_site("SRC", 44.0, -73.0, elevation_m=150.0, mast_height_m=10.0)
    dst = _make_site("DST", 44.0, -72.9, elevation_m=150.0, mast_height_m=10.0)
    profile = _build_flat_profile(src, dst, distance_km=8.0)
    az_fwd = forward_azimuth_deg(src.location, dst.location)
    az_rev = forward_azimuth_deg(dst.location, src.location)

    on_axis_src = RadioConfig(
        antenna_gain_dbi=9.0,
        antenna_pattern=AntennaPattern(
            radiation_class=RadiationClass.DIRECTIONAL,
            azimuth_deg=az_fwd,
            h_beamwidth_deg=65.0,
            v_beamwidth_deg=55.0,
            front_to_back_db=16.0,
        ),
    )
    on_axis_dst = RadioConfig(
        antenna_gain_dbi=9.0,
        antenna_pattern=AntennaPattern(
            radiation_class=RadiationClass.DIRECTIONAL,
            azimuth_deg=az_rev,
            h_beamwidth_deg=65.0,
            v_beamwidth_deg=55.0,
            front_to_back_db=16.0,
        ),
    )
    misaimed_dst = RadioConfig(
        antenna_gain_dbi=9.0,
        antenna_pattern=AntennaPattern(
            radiation_class=RadiationClass.DIRECTIONAL,
            azimuth_deg=az_fwd,  # aimed away from src
            h_beamwidth_deg=65.0,
            v_beamwidth_deg=55.0,
            front_to_back_db=16.0,
        ),
    )

    perp_src = RadioConfig(
        antenna_gain_dbi=9.0,
        antenna_pattern=AntennaPattern(
            radiation_class=RadiationClass.DIRECTIONAL,
            azimuth_deg=(az_fwd + 90.0) % 360.0,
            h_beamwidth_deg=65.0,
            v_beamwidth_deg=55.0,
            front_to_back_db=16.0,
        ),
    )

    sym_aligned = evaluate_point_to_point_link(profile, radio=on_axis_src)
    sym_mis = evaluate_point_to_point_link(profile, radio=misaimed_dst)
    sym_perp = evaluate_point_to_point_link(profile, radio=perp_src)
    assert sym_aligned.ok and sym_mis.ok and sym_perp.ok
    assert sym_aligned.value is not None and sym_mis.value is not None and sym_perp.value is not None
    # In symmetric mode, one end faces az_fwd and the other az_rev (0 + F/B), while perpendicular loses F/B on both
    assert sym_aligned.value.rx_power_dbm == sym_mis.value.rx_power_dbm
    assert math.isclose(
        sym_aligned.value.rx_power_dbm - sym_perp.value.rx_power_dbm,
        16.0,
        abs_tol=0.05,
    )

    asym_aligned = evaluate_point_to_point_link(
        profile, radio=on_axis_src, target_radio=on_axis_dst, min_margin_db=6.0
    )
    asym_mis = evaluate_point_to_point_link(
        profile, radio=on_axis_src, target_radio=misaimed_dst, min_margin_db=6.0
    )
    assert asym_aligned.ok and asym_mis.ok
    assert asym_aligned.value is not None and asym_mis.value is not None
    assert asym_aligned.value.reachability_state == ReachabilityState.TWO_WAY
    assert math.isclose(
        asym_aligned.value.rx_power_dbm - asym_mis.value.rx_power_dbm,
        16.0,
        abs_tol=0.05,
    )


# ---------------------------------------------------------------------------
# 4. Presets: GenericLoRa protocols and AntennaPattern presets
# ---------------------------------------------------------------------------


def test_presets_generic_lora_and_antenna_patterns() -> None:
    """Validate 8 PROTOCOL_PROFILES, 5 ANTENNA_PATTERN_PRESETS, and build_radio_config."""
    assert len(PROTOCOL_PROFILES) == 8
    wide = PROTOCOL_PROFILES["GENERIC_LORA_WIDE_500"]
    assert wide.network_family == "GenericLoRa"
    assert wide.bandwidth_khz == 500.0
    assert wide.spreading_factor == 7
    assert wide.rx_sensitivity_dbm == -120.5

    long_rng = PROTOCOL_PROFILES["GENERIC_LORA_LONG_62K5"]
    assert long_rng.network_family == "GenericLoRa"
    assert long_rng.bandwidth_khz == 62.5
    assert long_rng.spreading_factor == 12
    assert long_rng.rx_sensitivity_dbm == -141.5

    assert len(ANTENNA_PATTERN_PRESETS) == 5
    for key in (
        "OMNI_360",
        "SECTOR_VALLEY_120",
        "SECTOR_CORRIDOR_90",
        "YAGI_BACKHAUL_65",
        "YAGI_HIGHGAIN_38",
    ):
        assert key in ANTENNA_PATTERN_PRESETS

    cfg_res = build_radio_config(
        hardware_id="RAK4631_SOLAR",
        protocol_id="GENERIC_LORA_WIDE_500",
        season_id="WINTER_LEAF_OFF",
        antenna_preset_id="YAGI_BACKHAUL_65",
        azimuth_deg=405.0,
        downtilt_deg=3.5,
    )
    assert cfg_res.ok and cfg_res.value is not None
    assert cfg_res.value.antenna_pattern is not None
    assert cfg_res.value.antenna_pattern.radiation_class == RadiationClass.DIRECTIONAL
    assert cfg_res.value.antenna_pattern.azimuth_deg == 45.0
    assert cfg_res.value.antenna_pattern.downtilt_deg == 3.5

    bad_res = build_radio_config(antenna_preset_id="NONEXISTENT_ANTENNA")
    assert not bad_res.ok
    assert bad_res.error is not None
    assert bad_res.error.code == "UNKNOWN_ANTENNA_PRESET"

    all_presets = list_all_presets()
    assert "antenna_pattern_presets" in all_presets
    assert set(all_presets["antenna_pattern_presets"].keys()) == set(ANTENNA_PATTERN_PRESETS.keys())


# ---------------------------------------------------------------------------
# 5. Provisioning: Multi-interface protocol-agnostic synthesis
# ---------------------------------------------------------------------------


def test_multi_interface_protocol_agnostic_provisioning() -> None:
    """Validate generate_multi_interface_provisioning across Meshtastic, MeshCore, Reticulum, GenericLoRa, and fallback."""
    site = _make_site("VT-PROV-01", 44.5, -72.8, elevation_m=500.0, mast_height_m=15.0)
    yagi = ANTENNA_PATTERN_PRESETS["YAGI_BACKHAUL_65"].model_copy(update={"azimuth_deg": 180.0})

    profile = MultiInterfaceSiteProfile(
        site_id=site.site_id,
        interfaces=[
            RadioInterfaceSpec(
                interface_id="acc-mesh",
                tier=InterfaceTier.ACCESS_INFILL,
                radio=RadioConfig(frequency_mhz=915.0, tx_power_dbm=22.0),
                protocol_family="Meshtastic",
                bridge_group="grp-a",
            ),
            RadioInterfaceSpec(
                interface_id="bh-mc",
                tier=InterfaceTier.BACKHAUL_BRIDGE,
                radio=RadioConfig(
                    frequency_mhz=906.875,
                    tx_power_dbm=24.0,
                    antenna_gain_dbi=9.0,
                    antenna_pattern=yagi,
                ),
                protocol_family="MeshCore",
                bridge_group="grp-a",
            ),
            RadioInterfaceSpec(
                interface_id="bh-rns",
                tier=InterfaceTier.BACKHAUL_BRIDGE,
                radio=RadioConfig(frequency_mhz=908.0, tx_power_dbm=22.0),
                protocol_family="Reticulum",
                bridge_group="grp-a",
            ),
            RadioInterfaceSpec(
                interface_id="bh-gen",
                tier=InterfaceTier.BACKHAUL_BRIDGE,
                radio=RadioConfig(frequency_mhz=910.0, tx_power_dbm=20.0),
                protocol_family="GenericLoRa",
            ),
            RadioInterfaceSpec(
                interface_id="acc-unk",
                tier=InterfaceTier.ACCESS_INFILL,
                radio=RadioConfig(frequency_mhz=912.0, tx_power_dbm=20.0),
                protocol_family="CustomExperimentalProto",
            ),
            RadioInterfaceSpec(
                interface_id="acc-none",
                tier=InterfaceTier.ACCESS_INFILL,
                radio=RadioConfig(frequency_mhz=914.0, tx_power_dbm=20.0),
                protocol_family=None,
            ),
        ],
    )

    bundle = generate_multi_interface_provisioning(site, profile, bandwidth_khz=250.0, spreading_factor=11)
    assert bundle.interface_count == 6
    assert bundle.split_horizon_enabled is True
    assert bundle.bridge_groups == ["grp-a"]

    by_id = {item.interface_id: item for item in bundle.items}
    assert by_id["acc-mesh"].protocol_family == "Meshtastic"
    assert "ROUTER_LATE" in by_id["acc-mesh"].config_snippet
    assert "lora.override_frequency 915.000" in by_id["acc-mesh"].config_snippet

    assert by_id["bh-mc"].protocol_family == "MeshCore"
    assert "906.875" in by_id["bh-mc"].config_snippet
    assert "directional @ 180.0 deg" in by_id["bh-mc"].antenna_summary

    assert by_id["bh-rns"].protocol_family == "Reticulum"
    assert "[[RNode-VT-PROV-01-bh-rns]]" in by_id["bh-rns"].config_snippet
    assert "[reticulum]\n  enable_transport = True" in bundle.combined_config_text

    assert by_id["bh-gen"].protocol_family == "GenericLoRa"
    assert by_id["acc-unk"].protocol_family == "GenericLoRa"
    assert by_id["acc-none"].protocol_family == "GenericLoRa"
    assert "lora-iface --id acc-none" in by_id["acc-none"].config_snippet

    # Reticulum without bridge_group omits enable_transport = True
    no_bridge_profile = MultiInterfaceSiteProfile(
        site_id=site.site_id,
        interfaces=[
            RadioInterfaceSpec(
                interface_id="rns-solo",
                tier=InterfaceTier.ACCESS_INFILL,
                radio=RadioConfig(frequency_mhz=915.0, tx_power_dbm=20.0),
                protocol_family="Reticulum",
                bridge_group=None,
            )
        ],
    )
    solo_bundle = generate_multi_interface_provisioning(site, no_bridge_profile)
    assert solo_bundle.split_horizon_enabled is False
    assert "enable_transport = True" not in solo_bundle.combined_config_text


# ---------------------------------------------------------------------------
# 6. Viewshed: Sector & Yagi directional polygon and target masking
# ---------------------------------------------------------------------------


def test_viewshed_sector_and_yagi_polygon_masking() -> None:
    """Validate evaluate_target_coverage and compute_radial_viewshed_polygon directional attenuation."""
    repeater = _make_site("VT-REP-01", 44.40, -73.00, elevation_m=300.0, mast_height_m=15.0)
    north_tgt = TargetGridPoint(
        target_id="NORTH-1",
        coordinate=Coordinate(lat=44.48, lon=-73.00, elevation_m=100.0),
    )
    south_tgt = TargetGridPoint(
        target_id="SOUTH-1",
        coordinate=Coordinate(lat=44.32, lon=-73.00, elevation_m=100.0),
    )

    radio_none = RadioConfig(tx_power_dbm=18.0, antenna_gain_dbi=6.0, antenna_pattern=None)
    radio_omni = RadioConfig(
        tx_power_dbm=18.0,
        antenna_gain_dbi=6.0,
        antenna_pattern=ANTENNA_PATTERN_PRESETS["OMNI_360"],
    )
    radio_sector_n = RadioConfig(
        tx_power_dbm=18.0,
        antenna_gain_dbi=6.0,
        antenna_pattern=ANTENNA_PATTERN_PRESETS["SECTOR_VALLEY_120"].model_copy(
            update={"azimuth_deg": 0.0}
        ),
    )
    radio_yagi_n = RadioConfig(
        tx_power_dbm=18.0,
        antenna_gain_dbi=6.0,
        antenna_pattern=ANTENNA_PATTERN_PRESETS["YAGI_HIGHGAIN_38"].model_copy(
            update={"azimuth_deg": 0.0}
        ),
    )

    cov_none_n = evaluate_target_coverage(repeater, north_tgt, radio_none, elevation_fn=_flat_elevation)
    cov_omni_n = evaluate_target_coverage(repeater, north_tgt, radio_omni, elevation_fn=_flat_elevation)
    assert cov_none_n.estimated_rx_dbm == cov_omni_n.estimated_rx_dbm
    assert cov_none_n.link_margin_db == cov_omni_n.link_margin_db

    cov_sec_n = evaluate_target_coverage(repeater, north_tgt, radio_sector_n, elevation_fn=_flat_elevation)
    cov_sec_s = evaluate_target_coverage(repeater, south_tgt, radio_sector_n, elevation_fn=_flat_elevation)
    assert cov_sec_n.estimated_rx_dbm == cov_omni_n.estimated_rx_dbm
    assert math.isclose(cov_sec_n.link_margin_db - cov_sec_s.link_margin_db, 18.0, abs_tol=0.05)

    cov_yagi_s = evaluate_target_coverage(repeater, south_tgt, radio_yagi_n, elevation_fn=_flat_elevation)
    assert math.isclose(cov_sec_n.link_margin_db - cov_yagi_s.link_margin_db, 22.0, abs_tol=0.05)

    # Radial viewshed polygon masking: calibrate power so F/B attenuation cuts off backlobe radials
    poly_radio_none = RadioConfig(
        tx_power_dbm=0.0,
        rx_sensitivity_dbm=-110.0,
        antenna_gain_dbi=3.0,
        cable_loss_db=0.0,
        antenna_pattern=None,
    )
    poly_radio_omni = poly_radio_none.model_copy(
        update={"antenna_pattern": ANTENNA_PATTERN_PRESETS["OMNI_360"]}
    )
    poly_radio_yagi = poly_radio_none.model_copy(
        update={
            "antenna_pattern": ANTENNA_PATTERN_PRESETS["YAGI_HIGHGAIN_38"].model_copy(
                update={"azimuth_deg": 0.0}
            )
        }
    )

    res_none = compute_radial_viewshed_polygon(
        origin=repeater,
        num_radials=24,
        max_range_km=35.0,
        radio=poly_radio_none,
        elevation_fn=_flat_elevation,
        min_margin_db=0.0,
    )
    res_omni = compute_radial_viewshed_polygon(
        origin=repeater,
        num_radials=24,
        max_range_km=35.0,
        radio=poly_radio_omni,
        elevation_fn=_flat_elevation,
        min_margin_db=0.0,
    )
    res_yagi = compute_radial_viewshed_polygon(
        origin=repeater,
        num_radials=24,
        max_range_km=35.0,
        radio=poly_radio_yagi,
        elevation_fn=_flat_elevation,
        min_margin_db=0.0,
    )
    assert res_none.ok and res_omni.ok and res_yagi.ok
    assert res_none.value is not None and res_omni.value is not None and res_yagi.value is not None

    assert res_none.value.los_area_sq_km == res_omni.value.los_area_sq_km
    assert res_none.value.diffracted_area_sq_km == res_omni.value.diffracted_area_sq_km
    assert res_yagi.value.diffracted_area_sq_km < res_omni.value.diffracted_area_sq_km


# ---------------------------------------------------------------------------
# 7. Co-site Desense: Isolation and Cavity Filter Mitigation
# ---------------------------------------------------------------------------


def test_cosite_desense_isolation_and_filter_mitigation() -> None:
    """Validate evaluate_cosite_desense flags co-channel/narrow separation and clears with cavity filter + vertical sep."""
    site = _make_site("VT-COSITE-01", 44.5, -72.8, elevation_m=900.0, mast_height_m=15.0)

    risky_profile = MultiInterfaceSiteProfile(
        site_id=site.site_id,
        interfaces=[
            RadioInterfaceSpec(
                interface_id="tx-a",
                tier=InterfaceTier.ACCESS_INFILL,
                radio=RadioConfig(frequency_mhz=915.0, tx_power_dbm=28.0),
                mast_mount_m=10.0,
                filter_rejection_db=0.0,
            ),
            RadioInterfaceSpec(
                interface_id="rx-b",
                tier=InterfaceTier.BACKHAUL_BRIDGE,
                radio=RadioConfig(frequency_mhz=915.0, tx_power_dbm=28.0),
                mast_mount_m=10.5,
                filter_rejection_db=0.0,
            ),
        ],
    )
    risky_pairs = evaluate_cosite_desense(site, risky_profile)
    assert len(risky_pairs) == 2
    assert all(p.blocking_risk is True for p in risky_pairs)
    assert all(p.desense_db >= 3.0 for p in risky_pairs)
    assert all("cavity" in p.mitigation.lower() for p in risky_pairs)

    mitigated_profile = MultiInterfaceSiteProfile(
        site_id=site.site_id,
        interfaces=[
            RadioInterfaceSpec(
                interface_id="tx-a",
                tier=InterfaceTier.ACCESS_INFILL,
                radio=RadioConfig(frequency_mhz=915.0, tx_power_dbm=22.0),
                mast_mount_m=10.0,
                filter_rejection_db=55.0,
            ),
            RadioInterfaceSpec(
                interface_id="rx-b",
                tier=InterfaceTier.BACKHAUL_BRIDGE,
                radio=RadioConfig(frequency_mhz=906.875, tx_power_dbm=22.0),
                mast_mount_m=18.0,
                filter_rejection_db=55.0,
            ),
        ],
    )
    clean_pairs = evaluate_cosite_desense(site, mitigated_profile)
    assert len(clean_pairs) == 2
    assert all(p.blocking_risk is False for p in clean_pairs)
    assert all(p.desense_db < risky_pairs[0].desense_db for p in clean_pairs)
    assert all(p.mitigation == "none" for p in clean_pairs)


# ---------------------------------------------------------------------------
# 8. Multi-Interface Split-Horizon Bridge Routing
# ---------------------------------------------------------------------------


def test_multi_interface_split_horizon_bridge_route() -> None:
    """Validate find_multi_interface_route bridges across bridge_group and rejects invalid params."""
    origin = _make_site("ORIGIN", 44.40, -73.10, elevation_m=150.0, mast_height_m=10.0)
    relay = _make_site("RELAY", 44.45, -73.00, elevation_m=400.0, mast_height_m=15.0)
    dest = _make_site("DEST", 44.50, -72.90, elevation_m=450.0, mast_height_m=15.0)

    profiles = {
        origin.site_id: MultiInterfaceSiteProfile(
            site_id=origin.site_id,
            interfaces=[
                RadioInterfaceSpec(
                    interface_id="acc-0",
                    tier=InterfaceTier.ACCESS_INFILL,
                    radio=RadioConfig(frequency_mhz=915.0, tx_power_dbm=22.0, rx_sensitivity_dbm=-134.0),
                )
            ],
        ),
        relay.site_id: MultiInterfaceSiteProfile(
            site_id=relay.site_id,
            interfaces=[
                RadioInterfaceSpec(
                    interface_id="acc-0",
                    tier=InterfaceTier.ACCESS_INFILL,
                    radio=RadioConfig(frequency_mhz=915.0, tx_power_dbm=22.0, rx_sensitivity_dbm=-134.0),
                    bridge_group="bg-main",
                ),
                RadioInterfaceSpec(
                    interface_id="bh-0",
                    tier=InterfaceTier.BACKHAUL_BRIDGE,
                    radio=RadioConfig(
                        frequency_mhz=906.875,
                        tx_power_dbm=22.0,
                        rx_sensitivity_dbm=-134.0,
                        antenna_gain_dbi=9.0,
                    ),
                    bridge_group="bg-main",
                ),
            ],
        ),
        dest.site_id: MultiInterfaceSiteProfile(
            site_id=dest.site_id,
            interfaces=[
                RadioInterfaceSpec(
                    interface_id="bh-0",
                    tier=InterfaceTier.BACKHAUL_BRIDGE,
                    radio=RadioConfig(
                        frequency_mhz=906.875,
                        tx_power_dbm=22.0,
                        rx_sensitivity_dbm=-134.0,
                        antenna_gain_dbi=9.0,
                    ),
                )
            ],
        ),
    }

    route_res = find_multi_interface_route(
        origin=origin,
        destination=dest,
        sites=[origin, relay, dest],
        profiles=profiles,
        elevation_fn=_flat_elevation,
        max_rf_hops=5,
        min_margin_db=3.0,
    )
    assert route_res.ok and route_res.value is not None
    route = route_res.value
    assert route.route_found is True
    assert route.rf_hops == 2
    assert route.bridge_transitions == 1
    assert route.bottleneck_margin_db > 3.0
    assert [leg.leg_kind for leg in route.legs] == [
        "rf_access",
        "intra_site_bridge",
        "rf_backhaul",
    ]

    # Same-site trivial route & disconnected (different bridge_groups) route
    same_res = find_multi_interface_route(
        origin=origin, destination=origin, sites=[origin], profiles=profiles
    )
    assert same_res.ok and same_res.value is not None
    assert same_res.value.route_found is True and same_res.value.rf_hops == 0

    unbridged_profiles = {
        **profiles,
        relay.site_id: MultiInterfaceSiteProfile(
            site_id=relay.site_id,
            interfaces=[
                RadioInterfaceSpec(
                    interface_id="acc-0",
                    tier=InterfaceTier.ACCESS_INFILL,
                    radio=RadioConfig(frequency_mhz=915.0, tx_power_dbm=22.0, rx_sensitivity_dbm=-134.0),
                    bridge_group="bg-a",
                ),
                RadioInterfaceSpec(
                    interface_id="bh-0",
                    tier=InterfaceTier.BACKHAUL_BRIDGE,
                    radio=RadioConfig(frequency_mhz=906.875, tx_power_dbm=22.0, rx_sensitivity_dbm=-134.0),
                    bridge_group="bg-b",
                ),
            ],
        ),
    }
    no_route = find_multi_interface_route(
        origin=origin,
        destination=dest,
        sites=[origin, relay, dest],
        profiles=unbridged_profiles,
        elevation_fn=_flat_elevation,
    )
    assert no_route.ok and no_route.value is not None
    assert no_route.value.route_found is False

    # Validation error branches
    bad_hops_lo = find_multi_interface_route(
        origin=origin, destination=dest, sites=[origin, relay, dest], profiles=profiles, max_rf_hops=0
    )
    assert not bad_hops_lo.ok and bad_hops_lo.error is not None
    assert bad_hops_lo.error.code == "INVALID_HOP_LIMIT"

    bad_hops_hi = find_multi_interface_route(
        origin=origin, destination=dest, sites=[origin, relay, dest], profiles=profiles, max_rf_hops=11
    )
    assert not bad_hops_hi.ok and bad_hops_hi.error is not None
    assert bad_hops_hi.error.code == "INVALID_HOP_LIMIT"

    bad_loss = find_multi_interface_route(
        origin=origin,
        destination=dest,
        sites=[origin, relay, dest],
        profiles=profiles,
        client_env_loss_db=-1.0,
    )
    assert not bad_loss.ok and bad_loss.error is not None
    assert bad_loss.error.code == "INVALID_LOSS_PENALTY"


# ---------------------------------------------------------------------------
# 9. Two-Tier Fabric Solver: Aiming Yagis & Unconnected Island Rejection
# ---------------------------------------------------------------------------


def test_two_tier_infill_rejects_unconnected_island_and_aims_yagis() -> None:
    """Validate solve_two_tier_fabric aims Yagis, rejects unconnected islands, handles single-summit, and errors cleanly."""
    trunk_a = _make_site("TRUNK-A", 44.50, -72.90, elevation_m=1200.0, mast_height_m=15.0)
    trunk_b = _make_site("TRUNK-B", 44.55, -72.85, elevation_m=1150.0, mast_height_m=15.0)
    infill_ok = _make_site("INFILL-OK", 44.48, -72.92, elevation_m=200.0, mast_height_m=10.0)
    infill_island = _make_site("INFILL-ISLAND", 47.50, -68.00, elevation_m=50.0, mast_height_m=5.0)

    targets = [
        TargetGridPoint(target_id="T1", coordinate=Coordinate(lat=44.48, lon=-72.93, elevation_m=100.0)),
        TargetGridPoint(target_id="T2", coordinate=Coordinate(lat=44.49, lon=-72.91, elevation_m=100.0)),
        TargetGridPoint(target_id="T3", coordinate=Coordinate(lat=47.50, lon=-68.01, elevation_m=50.0)),
    ]

    # Weak feeder uplink radio + high min_backhaul_margin_db causes faraway infill_island to fail backhaul
    weak_feeder = RadioConfig(
        frequency_mhz=906.875,
        tx_power_dbm=10.0,
        rx_sensitivity_dbm=-110.0,
        antenna_gain_dbi=3.0,
    )
    trunk_radio = RadioConfig(
        frequency_mhz=906.875,
        tx_power_dbm=22.0,
        rx_sensitivity_dbm=-134.0,
        antenna_gain_dbi=9.0,
    )

    vs_ok = compute_viewshed(infill_ok, targets[:2], elevation_fn=_flat_elevation).value
    vs_island = compute_viewshed(infill_island, [targets[2]], elevation_fn=_flat_elevation).value
    assert vs_ok is not None and vs_island is not None

    plan_res = solve_two_tier_fabric(
        trunk_sites=[trunk_a, trunk_b],
        infill_viewsheds=[vs_ok, vs_island],
        target_coverage_fraction=0.60,
        trunk_radio=trunk_radio,
        infill_uplink_radio=weak_feeder,
        elevation_fn=_flat_elevation,
        min_backhaul_margin_db=10.0,
    )
    assert plan_res.ok and plan_res.value is not None
    plan = plan_res.value
    assert plan.trunk_connected is True
    assert "INFILL-ISLAND" in plan.unconnected_infill_ids
    assert "INFILL-ISLAND" not in plan.infill_site_ids
    assert "INFILL-OK" in plan.infill_site_ids

    expected_az_ab = round(forward_azimuth_deg(trunk_a.location, trunk_b.location), 2) % 360.0
    ab_assignments = [
        a
        for a in plan.antenna_assignments
        if a.site_id == "TRUNK-A" and a.peer_site_id == "TRUNK-B"
    ]
    assert len(ab_assignments) == 1
    assert ab_assignments[0].azimuth_deg == expected_az_ab

    # Single-summit trunk has trunk_connected=True
    single_res = solve_two_tier_fabric(
        trunk_sites=[trunk_a],
        infill_viewsheds=[vs_ok],
        target_coverage_fraction=0.50,
        elevation_fn=_flat_elevation,
    )
    assert single_res.ok and single_res.value is not None
    assert single_res.value.trunk_connected is True

    # Error handling: EMPTY_TRUNK_SITES and INVALID_COVERAGE_THRESHOLD
    empty_res = solve_two_tier_fabric(trunk_sites=[], infill_viewsheds=[vs_ok])
    assert not empty_res.ok and empty_res.error is not None
    assert empty_res.error.code == "EMPTY_TRUNK_SITES"

    blocked_trunk = _make_site("BLOCKED", 44.5, -72.9, notes="Status: Blocked")
    blocked_res = solve_two_tier_fabric(trunk_sites=[blocked_trunk], infill_viewsheds=[vs_ok])
    assert not blocked_res.ok and blocked_res.error is not None
    assert blocked_res.error.code == "EMPTY_TRUNK_SITES"

    bad_thresh = solve_two_tier_fabric(
        trunk_sites=[trunk_a], infill_viewsheds=[vs_ok], target_coverage_fraction=0.0
    )
    assert not bad_thresh.ok and bad_thresh.error is not None
    assert bad_thresh.error.code == "INVALID_COVERAGE_THRESHOLD"

    bad_thresh_hi = solve_two_tier_fabric(
        trunk_sites=[trunk_a], infill_viewsheds=[vs_ok], target_coverage_fraction=1.2
    )
    assert not bad_thresh_hi.ok and bad_thresh_hi.error is not None
    assert bad_thresh_hi.error.code == "INVALID_COVERAGE_THRESHOLD"


# ---------------------------------------------------------------------------
# 10. L3 Commands, L4 CLI, L4 MCP, and L4 FastAPI Endpoints
# ---------------------------------------------------------------------------


def test_commands_fabric_cosite_and_regulatory_l3() -> None:
    """Validate L3 command handlers for fabric planning, co-site desense, and EIRP checks."""
    fabric_res = commands.plan_tiered_rf_fabric(region="vt_chittenden", target_coverage=0.80)
    assert fabric_res["ok"] is True
    assert "plan" in fabric_res
    assert len(fabric_res["plan"]["trunk_site_ids"]) >= 1

    cosite_ok = commands.evaluate_site_cosite_desense("VT-MANS-01")
    assert cosite_ok["ok"] is True
    assert cosite_ok["site_id"] == "VT-MANS-01"
    assert len(cosite_ok["pairs"]) == 2

    cosite_missing = commands.evaluate_site_cosite_desense("NONEXISTENT-SITE-99")
    assert cosite_missing["ok"] is False
    assert cosite_missing["error"]["code"] == "SITE_NOT_FOUND"

    eirp_dir = commands.advise_eirp(
        tx_power_dbm=27.0,
        antenna_gain_dbi=9.0,
        frequency_mhz=915.0,
        transmission_mode="directional_p2p",
        bandwidth_khz=250.0,
    )
    assert eirp_dir["ok"] is True
    assert eirp_dir["transmission_mode"] == "directional_p2p"
    assert any("2400-2483.5 MHz" in w for w in eirp_dir["warnings"])

    eirp_bad_mode = commands.advise_eirp(transmission_mode="invalid_topology")
    assert eirp_bad_mode["ok"] is False
    assert eirp_bad_mode["error"]["code"] == "INVALID_TRANSMISSION_MODE"

    eirp_bad_bw = commands.advise_eirp(bandwidth_khz=0.0)
    assert eirp_bad_bw["ok"] is False
    assert eirp_bad_bw["error"]["code"] == "INVALID_EIRP_PARAMS"


def test_cli_fabric_subcommand_execution(capsys: pytest.CaptureFixture[str]) -> None:
    """Validate CLI `fabric --json` and text subcommand execute cleanly."""
    exit_code = cli.main(["fabric", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert "plan" in payload
    assert "trunk_site_ids" in payload["plan"]

    exit_text = cli.main(["fabric"])
    assert exit_text == 0
    text_out = capsys.readouterr().out
    assert "Trunk Sites:" in text_out and "Infill Sites:" in text_out


def test_mcp_plan_tiered_rf_fabric_tool_call() -> None:
    """Validate MCP JSON-RPC `tools/call` invokes plan_tiered_rf_fabric cleanly."""
    server = MeshScoutMCPServer()
    resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {
                "name": "plan_tiered_rf_fabric",
                "arguments": {"region": "vt_chittenden", "target_coverage": 0.80},
            },
        }
    )
    assert resp is not None
    assert resp["id"] == 42
    result = resp["result"]
    assert result["isError"] is False
    parsed = json.loads(result["content"][0]["text"])
    assert parsed["ok"] is True
    assert "plan" in parsed


def test_web_fabric_and_cosite_desense_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate FastAPI /api/v1/topology/fabric and /api/v1/rf/cosite-desense endpoints."""
    app = FastAPI()
    app.include_router(build_resilience_router())

    with TestClient(app) as client:
        fab_ok = client.post("/api/v1/topology/fabric", json={"region": "vt_chittenden", "target_coverage": 0.80})
        assert fab_ok.status_code == 200
        fab_body = fab_ok.json()
        assert fab_body["ok"] is True
        assert "plan" in fab_body

        cosite_ok = client.post("/api/v1/rf/cosite-desense", json={"site_id": "VT-MANS-01"})
        assert cosite_ok.status_code == 200
        cosite_body = cosite_ok.json()
        assert cosite_body["ok"] is True
        assert cosite_body["site_id"] == "VT-MANS-01"

        cosite_404 = client.post("/api/v1/rf/cosite-desense", json={"site_id": "NONEXISTENT-SITE-99"})
        assert cosite_404.status_code == 404

        # Verify 404 mapping when regional topology resolves to empty candidate list
        monkeypatch.setattr(
            commands,
            "load_regional_fixtures",
            lambda region="vt_chittenden": (commands.VT_CHITTENDEN_BOUNDS, []),
        )
        fab_404 = client.post("/api/v1/topology/fabric", json={"region": "empty_region"})
        assert fab_404.status_code == 404
