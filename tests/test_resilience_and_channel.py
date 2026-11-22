"""Unit tests for MeshScout v0.15.0 resilience, channel planning, terrain, and export suites."""

from __future__ import annotations

import json
from pathlib import Path
import warnings
import xml.etree.ElementTree as ET

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*BlockingPortal.*", category=DeprecationWarning)
    from fastapi.testclient import TestClient

import pytest

from meshscout.cli import build_parser, main as cli_main
from meshscout.core.archetypes import COMMUNITY_SITE_ARCHETYPES, SiteArchetype
from meshscout.core.contracts import Coordinate, RadioConfig, SiteCandidate, SiteType
from meshscout.core.optimizer import find_optimal_mesh_route
from meshscout.core.presets import (
    HARDWARE_PRESETS,
    MESHTASTIC_BAND_PLANS,
    PROTOCOL_PROFILES,
    build_radio_config,
)
from meshscout.core.provisioning import (
    ProvisioningTarget,
    generate_meshcore_serial_script,
    generate_reticulum_rnode_stanza,
    generate_site_provisioning,
)
from meshscout.core.resilience import (
    DEFAULT_BOM_UNIT_COSTS_USD,
    evaluate_topology_resilience,
    generate_rollout_bom,
)
from meshscout.core.traffic import (
    advise_node_role,
    compute_meshtastic_channel_slot,
    evaluate_hidden_terminal_matrix,
)
from meshscout.core.viewshed import compute_horizon_skyline, find_local_highpoint
from meshscout.mcp_server import MeshScoutMCPServer
from meshscout.reporting import (
    export_atak_cot_xml,
    export_link_matrix_csv,
    parse_bulk_sites_csv,
)
from meshscout.web.app import create_web_app


def _make_site(
    site_id: str,
    name: str = "Test Site",
    lat: float = 44.50,
    lon: float = -73.00,
    elevation_m: float = 150.0,
    site_type: SiteType = SiteType.MOUNTAIN_PEAK,
    mast_height_m: float = 10.0,
) -> SiteCandidate:
    """Create a deterministic SiteCandidate fixture."""
    return SiteCandidate(
        site_id=site_id,
        name=name,
        location=Coordinate(lat=lat, lon=lon, elevation_m=elevation_m),
        site_type=site_type,
        mast_height_m=mast_height_m,
    )


def test_presets_8_radios_and_band_plans() -> None:
    """Verify 8 hardware presets, Meshtastic regional band plans, and US915 LongFast profile."""
    assert len(HARDWARE_PRESETS) == 8
    for preset_id in (
        "STATION_G3_REPEATER",
        "HELTEC_V4_PA",
        "HELTEC_T114_PORTABLE",
        "SEEED_XIAO_NRF52_SOLAR",
    ):
        assert preset_id in HARDWARE_PRESETS
        assert build_radio_config(hardware_id=preset_id).ok is True

    assert MESHTASTIC_BAND_PLANS["US"] == (902.0, 928.0)
    assert MESHTASTIC_BAND_PLANS["CA"] == (902.0, 928.0)
    assert MESHTASTIC_BAND_PLANS["ANZ"] == (915.0, 928.0)
    assert MESHTASTIC_BAND_PLANS["EU_868"] == (869.4, 869.65)
    assert PROTOCOL_PROFILES["MESHTASTIC_LONGFAST"].frequency_mhz == 915.0


def test_tarjan_spof_bridges_and_bom() -> None:
    """Verify Tarjan articulation points, bridges, standby healing, BOM pricing, and empty check."""
    a, b, c, d = (
        _make_site("A"),
        _make_site("B"),
        _make_site("C"),
        _make_site("D"),
    )

    # 1. 4-node linear bridge chain A-B-C-D
    chain_res = evaluate_topology_resilience(
        sites=[a, b, c, d],
        links=[("A", "B", 12.0), ("B", "C", 8.0), ("C", "D", 10.0)],
    )
    assert chain_res.ok is True and chain_res.value is not None
    chain = chain_res.value
    assert chain.connected_components == 1
    assert chain.largest_component_ratio == 1.0
    assert chain.articulation_site_ids == ["B", "C"]
    assert [(lnk.source_id, lnk.target_id, lnk.margin_db) for lnk in chain.bridge_links] == [
        ("A", "B", 12.0),
        ("B", "C", 8.0),
        ("C", "D", 10.0),
    ]
    assert chain.biconnected_score == 0.5

    # 2. 4-node lollipop graph (triangle A-B-C-A + bridge C-D)
    lol_res = evaluate_topology_resilience(
        sites=[a, b, c, d],
        links=[("A", "B", 15.0), ("B", "C", 14.0), ("A", "C", 11.0), ("C", "D", 7.5)],
    )
    assert lol_res.ok is True and lol_res.value is not None
    lol = lol_res.value
    assert lol.connected_components == 1
    assert lol.largest_component_ratio == 1.0
    assert lol.articulation_site_ids == ["C"]
    assert [(lnk.source_id, lnk.target_id, lnk.margin_db) for lnk in lol.bridge_links] == [
        ("C", "D", 7.5)
    ]
    assert lol.biconnected_score == 0.75

    # 3. Disconnected split (A-B bridge + C, D isolated? Use A-B-C + D disconnected) + standby heal
    s_non_heal = _make_site("S_NON_HEAL")
    s_heal = _make_site("S_HEAL")
    split_res = evaluate_topology_resilience(
        sites=[a, b, c, d],
        links=[("A", "B", 14.0), ("B", "C", 9.0)],
        standby_pool=[s_non_heal, s_heal],
        standby_links=[
            ("S_NON_HEAL", "A", 18.0),
            ("S_HEAL", "C", 11.0),
            ("S_HEAL", "D", 7.0),
        ],
    )
    assert split_res.ok is True and split_res.value is not None
    split = split_res.value
    assert split.connected_components == 2
    assert split.largest_component_ratio == 0.75
    assert split.articulation_site_ids == ["B"]
    assert [(lnk.source_id, lnk.target_id, lnk.margin_db) for lnk in split.bridge_links] == [
        ("A", "B", 14.0),
        ("B", "C", 9.0),
    ]
    assert split.biconnected_score == 0.75
    assert len(split.standby_candidates) == 2
    assert split.standby_candidates[0].site_id == "S_HEAL"
    assert split.standby_candidates[0].healed_components == 1
    assert split.standby_candidates[0].added_edges == 2
    assert split.standby_candidates[0].min_margin_db == 7.0
    assert split.standby_candidates[1].site_id == "S_NON_HEAL"
    assert split.standby_candidates[1].healed_components == 0

    # 4. RolloutBomReport pricing: solar kit only for solar_friendly=True + cavity filter for cavity_required_ids
    assert DEFAULT_BOM_UNIT_COSTS_USD["SOLAR_WINTER_KIT"] == 180.0
    assert DEFAULT_BOM_UNIT_COSTS_USD["CAVITY_FILTER_915"] == 120.0
    bom = generate_rollout_bom(
        sites=[a, b, c, d],
        site_hardware_map={
            "A": "RAK4631_SOLAR",
            "B": "STATION_G2_BACKBONE",
            "C": "STATION_G3_REPEATER",
            "D": "HELTEC_V3_HOME",
        },
        cavity_required_ids=["B", "C"],
    )
    by_code = {item.item_code: item for item in bom.line_items}
    assert by_code["RAK4631_SOLAR"].subtotal_usd == 95.0
    assert by_code["STATION_G2_BACKBONE"].subtotal_usd == 140.0
    assert by_code["STATION_G3_REPEATER"].subtotal_usd == 225.0
    assert by_code["HELTEC_V3_HOME"].subtotal_usd == 30.0
    assert by_code["SOLAR_WINTER_KIT"].quantity == 1
    assert by_code["SOLAR_WINTER_KIT"].subtotal_usd == 180.0
    assert by_code["CAVITY_FILTER_915"].quantity == 2
    assert by_code["CAVITY_FILTER_915"].subtotal_usd == 240.0
    assert bom.estimated_total_usd == 910.0

    bom_grid = generate_rollout_bom(
        sites=[a, b],
        site_hardware_map={"A": "STATION_G2_BACKBONE", "B": "HELTEC_V3_HOME"},
    )
    assert "SOLAR_WINTER_KIT" not in {item.item_code for item in bom_grid.line_items}
    assert bom_grid.estimated_total_usd == 170.0

    # 5. EMPTY_TOPOLOGY error on sites=[]
    empty_res = evaluate_topology_resilience(sites=[], links=[])
    assert empty_res.ok is False
    assert empty_res.error is not None
    assert empty_res.error.code == "EMPTY_TOPOLOGY"


def test_djb2_longfast_slot_20_us915() -> None:
    """Verify Meshtastic djb2 channel slot hash, EU_868 clamping, explicit override, and error codes."""
    us_res = compute_meshtastic_channel_slot("LongFast", "US", 250.0, 0)
    assert us_res.ok is True and us_res.value is not None
    plan = us_res.value
    assert plan.hash_uint32 == 130429955
    assert plan.slot_index == 19
    assert plan.frequency_slot == 20
    assert plan.center_freq_mhz == 906.875
    assert plan.num_channels == 104
    assert plan.guard_band_mhz == 0.0

    eu_res = compute_meshtastic_channel_slot("LongFast", "EU_868", 250.0, 0)
    assert eu_res.ok is True and eu_res.value is not None
    assert eu_res.value.num_channels == 1
    assert eu_res.value.slot_index == 0
    assert eu_res.value.frequency_slot == 1
    assert eu_res.value.center_freq_mhz == 869.525

    override_res = compute_meshtastic_channel_slot("LongFast", "US", 250.0, explicit_channel_num=2)
    assert override_res.ok is True and override_res.value is not None
    assert override_res.value.slot_index == 1
    assert override_res.value.frequency_slot == 2
    assert override_res.value.center_freq_mhz == 902.375

    for bad_call in (
        compute_meshtastic_channel_slot("LongFast", "MARS", 250.0, 0),
        compute_meshtastic_channel_slot("LongFast", "US", 0.0, 0),
        compute_meshtastic_channel_slot("LongFast", "US", -125.0, 0),
        compute_meshtastic_channel_slot("LongFast", "US", 250.0, -1),
        compute_meshtastic_channel_slot("LongFast", "US", 250.0, 105),
        compute_meshtastic_channel_slot("LongFast", "EU_868", 250.0, 2),
    ):
        assert bad_call.ok is False
        assert bad_call.error is not None
        assert bad_call.error.code == "INVALID_CHANNEL_PARAMS"


def test_hidden_terminal_capture_threshold() -> None:
    """Verify LoRa 6 dB capture threshold for hidden terminals and CLIENT_BASE residential clearance."""
    destructive = evaluate_hidden_terminal_matrix(
        site_ids=["H", "A", "B"],
        pairwise_rx_dbm={
            ("A", "H"): -95.0,
            ("B", "H"): -98.0,
            ("A", "B"): -999.0,
            ("B", "A"): -999.0,
        },
    )
    assert len(destructive) == 1
    assert destructive[0].hub_site_id == "H"
    assert destructive[0].sir_db == 3.0
    assert destructive[0].collision_destructive is True
    assert destructive[0].captured_winner is None

    captured = evaluate_hidden_terminal_matrix(
        site_ids=["H", "A", "B"],
        pairwise_rx_dbm={
            ("A", "H"): -95.0,
            ("B", "H"): -110.0,
            ("A", "B"): -140.0,
            ("B", "A"): -140.0,
        },
    )
    assert len(captured) == 1
    assert captured[0].sir_db == 15.0
    assert captured[0].collision_destructive is False
    assert captured[0].captured_winner == "A"

    rooftop = _make_site(
        "VT-ROOF-01",
        name="Residential Rooftop Hub",
        elevation_m=70.0,
        site_type=SiteType.BUILDING_ROOFTOP,
        mast_height_m=6.0,
    )
    rec_base = advise_node_role(site=rooftop, requested_role="CLIENT_BASE")
    assert rec_base.recommended_role == "CLIENT_BASE"
    assert rec_base.town_killer_risk is False
    assert "TOWN_KILLER_RISK" not in rec_base.risk_message
    assert "--set device.role CLIENT_BASE" in rec_base.cli_command

    rec_router = advise_node_role(site=rooftop, requested_role="ROUTER")
    assert rec_router.recommended_role == "CLIENT"
    assert rec_router.town_killer_risk is True
    assert "TOWN_KILLER_RISK" in rec_router.risk_message


def test_archetype_v27_client_base_migration() -> None:
    """Verify Meshtastic v2.7 role migration in COMMUNITY_SITE_ARCHETYPES and ROUTER_CLIENT removal."""
    alpine_mt = COMMUNITY_SITE_ARCHETYPES[SiteArchetype.ALPINE_MEGA_SUMMIT].protocol_mappings["Meshtastic"]
    assert alpine_mt.role_name == "ROUTER (Dual-Radio Split-Horizon Bridge)"
    assert alpine_mt.recommended_hop_limit == 3
    assert "--set device.role ROUTER" in alpine_mt.cli_command_template

    civic_mt = COMMUNITY_SITE_ARCHETYPES[SiteArchetype.CIVIC_VALLEY_INFILL].protocol_mappings["Meshtastic"]
    assert civic_mt.role_name == "ROUTER_LATE"
    assert civic_mt.recommended_hop_limit == 2
    assert "--set device.role ROUTER_LATE" in civic_mt.cli_command_template

    rooftop_mt = COMMUNITY_SITE_ARCHETYPES[SiteArchetype.MEMBER_ROOFTOP_BASE].protocol_mappings["Meshtastic"]
    assert rooftop_mt.role_name == "CLIENT_BASE (or CLIENT)"
    assert rooftop_mt.recommended_hop_limit == 3
    assert "--set device.role CLIENT_BASE" in rooftop_mt.cli_command_template

    serialized_catalog = json.dumps({k.value: v.model_dump() for k, v in COMMUNITY_SITE_ARCHETYPES.items()})
    assert "ROUTER_CLIENT" not in serialized_catalog


def test_find_local_highpoint_snaps_summit() -> None:
    """Verify local highpoint grid search snaps to off-center hill summit and validates grid params."""
    origin = Coordinate(lat=44.5000, lon=-73.0000, elevation_m=0.0)
    peak_lat = 44.5009
    peak_lon = -72.9994

    def hill_elev(lat: float, lon: float) -> float:
        return 500.0 - 1.0e8 * ((lat - peak_lat) ** 2 + (lon - peak_lon) ** 2)

    snap_res = find_local_highpoint(origin, hill_elev, radius_m=300.0, step_m=50.0)
    assert snap_res.ok is True and snap_res.value is not None
    snap = snap_res.value
    assert snap.snapped.elevation_m > snap.origin.elevation_m
    assert snap.gain_m > 0.0
    assert snap.offset_m > 0.0
    assert snap.samples_checked > 0

    for bad_radius, bad_step in ((0.0, 50.0), (-10.0, 50.0), (300.0, 0.0), (300.0, -5.0)):
        err_res = find_local_highpoint(origin, hill_elev, radius_m=bad_radius, step_m=bad_step)
        assert err_res.ok is False
        assert err_res.error is not None
        assert err_res.error.code == "INVALID_SEARCH_GRID"


def test_horizon_skyline_360_profile() -> None:
    """Verify 360-degree horizon skyline returns expected azimuth sectors and detects northern ridge."""
    origin = Coordinate(lat=44.5000, lon=-73.0000, elevation_m=100.0)

    def ridge_north_fn(lat: float, lon: float) -> float:
        if lat >= origin.lat + 0.03 and abs(lon - origin.lon) <= 0.04:
            return 950.0
        return 100.0

    skyline = compute_horizon_skyline(
        origin=origin,
        mast_height_m=10.0,
        elevation_fn=ridge_north_fn,
        max_radius_km=20.0,
        azimuth_step_deg=30,
        radial_steps=20,
    )
    assert len(skyline) == 12
    assert all(0.0 <= pt.azimuth_deg < 360.0 for pt in skyline)

    by_az = {pt.azimuth_deg: pt for pt in skyline}
    assert by_az[0.0].horizon_angle_deg > by_az[180.0].horizon_angle_deg
    assert by_az[0.0].horizon_angle_deg > by_az[90.0].horizon_angle_deg
    assert by_az[0.0].horizon_angle_deg > by_az[270.0].horizon_angle_deg
    assert by_az[0.0].obstruction_elev_m == 950.0


def test_n_hop_dijkstra_beyond_three_hops() -> None:
    """Verify multi-hop Dijkstra routes 4 hops across a 10-repeater pool without [:8] truncation."""
    lat_step = 10.0 / 111.13  # ~10 km spacing per hop
    flat_elev = lambda _lat, _lon: 500.0

    origin = _make_site("ORIG", "Origin", lat=44.0, lon=-73.0, elevation_m=500.0, mast_height_m=30.0)
    dest = _make_site(
        "DEST",
        "Destination",
        lat=44.0 + 4.0 * lat_step,
        lon=-73.0,
        elevation_m=500.0,
        mast_height_m=30.0,
    )

    # First 8 pool items are far off-axis decoys; indices 8, 9, 10 (wait: 7 decoys + 3 relays = 10 pool items, indices 7, 8, 9)
    pool_of_10 = [
        _make_site(
            f"DECOY-{idx:02d}",
            f"Decoy {idx}",
            lat=44.0 + idx * 0.05,
            lon=-74.5,
            elevation_m=500.0,
            mast_height_m=30.0,
        )
        for idx in range(7)
    ] + [
        _make_site("RELAY-08", "Relay 8", lat=44.0 + 1.0 * lat_step, lon=-73.0, elevation_m=500.0, mast_height_m=30.0),
        _make_site("RELAY-09", "Relay 9", lat=44.0 + 2.0 * lat_step, lon=-73.0, elevation_m=500.0, mast_height_m=30.0),
        _make_site("RELAY-10", "Relay 10", lat=44.0 + 3.0 * lat_step, lon=-73.0, elevation_m=500.0, mast_height_m=30.0),
    ]
    assert len(pool_of_10) == 10

    # At 915 MHz: FSPL(10km)=111.67dB (+6.33dB margin); FSPL(20km)=117.69dB (+0.31dB < 3dB threshold)
    short_range_radio = RadioConfig(
        frequency_mhz=915.0,
        tx_power_dbm=0.0,
        rx_sensitivity_dbm=-118.0,
        antenna_gain_dbi=0.0,
        cable_loss_db=0.0,
    )

    three_hop = find_optimal_mesh_route(
        origin=origin,
        destination=dest,
        candidate_repeaters=pool_of_10,
        radio=short_range_radio,
        elevation_fn=flat_elev,
        max_hops=3,
        min_link_margin_db=3.0,
    )
    assert three_hop.ok is True and three_hop.value is not None
    assert three_hop.value.route_found is False
    assert three_hop.value.hop_limit_exceeded is True

    four_hop = find_optimal_mesh_route(
        origin=origin,
        destination=dest,
        candidate_repeaters=pool_of_10,
        radio=short_range_radio,
        elevation_fn=flat_elev,
        max_hops=4,
        min_link_margin_db=3.0,
    )
    assert four_hop.ok is True and four_hop.value is not None
    route = four_hop.value
    assert route.route_found is True
    assert route.total_hops == 4
    assert route.intermediate_node_ids == ["RELAY-08", "RELAY-09", "RELAY-10"]
    assert len(route.legs) == 4
    assert route.bottleneck_margin_db >= 3.0

    for invalid_hops in (0, 8):
        err = find_optimal_mesh_route(
            origin=origin,
            destination=dest,
            candidate_repeaters=pool_of_10,
            radio=short_range_radio,
            elevation_fn=flat_elev,
            max_hops=invalid_hops,
        )
        assert err.ok is False
        assert err.error is not None
        assert err.error.code == "INVALID_HOP_LIMIT"


def test_meshcore_v114_serial_commands() -> None:
    """Verify MeshCore v1.14+ serial script truncation (<=23 UTF-8 bytes), order, and bundle integration."""
    long_utf8_name = "Mount Mansfield Summit — North Ridge Relay"
    assert len(long_utf8_name.encode("utf-8")) > 23
    site = _make_site(
        "VT-MC-01",
        name=long_utf8_name,
        lat=44.5437,
        lon=-72.8143,
        elevation_m=1339.0,
    )

    cmds = generate_meshcore_serial_script(
        site=site,
        freq_mhz=915.0,
        bw_khz=125.0,
        sf=10,
        cr=5,
        tx_power_dbm=22,
        flood_max_hops=3,
        loop_detect="moderate",
        path_hash_mode=1,
        rx_boost=True,
        fem_txgain_db=12,
    )
    assert len(cmds) == 12
    assert cmds[0].startswith("set name ")
    encoded_name = cmds[0].removeprefix("set name ").encode("utf-8")
    assert len(encoded_name) <= 23

    expected_prefixes = [
        "set name ",
        "set lat 44.543700",
        "set lon -72.814300",
        "set radio 915.0,125.0,10,5",
        "set tx 22",
        "set repeat on",
        "set flood.max 3",
        "set loop.detect moderate",
        "set path.hash.mode 1",
        "set radio.rxgain on",
        "set radio.fem.txgain 12",
        "reboot",
    ]
    for actual, prefix in zip(cmds, expected_prefixes):
        assert actual.startswith(prefix)

    bundle = generate_site_provisioning(site=site, target=ProvisioningTarget.MESHCORE)
    assert len(bundle.meshcore_serial_commands) >= 11
    assert bundle.meshcore_serial_commands[0].startswith("set name ")
    assert bundle.meshcore_serial_commands[-1] == "reboot"


def test_reticulum_ifac_and_airtime_stanza() -> None:
    """Verify backward-compatible default Reticulum RNode stanza and optional IFAC/airtime fields."""
    site = _make_site("VT-RNS-01", name="Reticulum Hub")
    baseline = generate_reticulum_rnode_stanza(site)
    expected_baseline = (
        "[[RNode-VT-RNS-01]]\n"
        "  type = RNodeInterface\n"
        "  interface_enabled = True\n"
        "  port = /dev/ttyUSB0\n"
        "  frequency = 915000000\n"
        "  bandwidth = 125000\n"
        "  txpower = 22\n"
        "  spreadingfactor = 11\n"
        "  codingrate = 5"
    )
    assert baseline == expected_baseline
    for omitted in (
        "network_name",
        "passphrase",
        "ifac_size",
        "id_callsign",
        "id_interval",
        "airtime_limit_short",
        "airtime_limit_long",
    ):
        assert omitted not in baseline

    extended = generate_reticulum_rnode_stanza(
        site=site,
        network_name="VT-Mesh",
        passphrase="sample-ifac-phrase-for-unit-test",
        ifac_size=16,
        id_callsign="W1VT",
        id_interval_sec=300,
        airtime_limit_short_pct=5.0,
        airtime_limit_long_pct=2.0,
    )
    assert "  network_name = VT-Mesh" in extended
    assert "  passphrase = sample-ifac-phrase-for-unit-test" in extended
    assert "  ifac_size = 16" in extended
    assert "  id_callsign = W1VT" in extended
    assert "  id_interval = 300" in extended
    assert "  airtime_limit_short = 5.0" in extended
    assert "  airtime_limit_long = 2.0" in extended


def test_atak_cot_xml_schema() -> None:
    """Verify ATAK Cursor-on-Target 2.0 XML structure and safe XML escaping of site names."""
    site = _make_site(
        "VT-COT-01",
        name="Tower & <North>",
        lat=44.5437,
        lon=-72.8143,
        elevation_m=1339.0,
        mast_height_m=10.0,
    )
    xml_text = export_atak_cot_xml([site])
    root = ET.fromstring(xml_text)
    assert root.tag == "events"

    events = root.findall("event")
    assert len(events) == 1
    ev = events[0]
    assert ev.attrib["version"] == "2.0"
    assert ev.attrib["type"] == "a-f-G-I-U-T"
    assert ev.attrib["how"] == "h-e"
    assert ev.attrib["uid"] == "MESHSCOUT-VT-COT-01"

    point = ev.find("point")
    assert point is not None
    assert point.attrib["lat"] == "44.543700"
    assert point.attrib["lon"] == "-72.814300"
    assert point.attrib["hae"] == "1349.0"

    contact = ev.find("detail/contact")
    assert contact is not None
    assert contact.attrib["callsign"] == "Tower & <North>"


def test_bulk_csv_roundtrip() -> None:
    """Verify bulk CSV site import validation/limits and link matrix CSV export formatting."""
    valid_csv = (
        "Name,Lat,Lon,SiteType,ElevationM,MastM\n"
        "Bolton Ridge,44.489,-72.868,mountain_peak,1120.0,12.0\n"
        "Essex Tank,44.490,-73.110,water_tower,105.0,20.0\n"
    )
    res = parse_bulk_sites_csv(valid_csv)
    assert res.ok is True and res.value is not None
    assert len(res.value) == 2
    assert res.value[0].site_id == "CSV-001"
    assert res.value[0].site_type == SiteType.MOUNTAIN_PEAK
    assert res.value[0].location.elevation_m == 1120.0
    assert res.value[0].mast_height_m == 12.0
    assert res.value[1].site_id == "CSV-002"
    assert res.value[1].site_type == SiteType.WATER_TOWER

    for bad_csv in (
        "Foo,Bar\n1,2\n",
        "Name,Lat,Lon\nBad Lat,999.0,-73.0\n",
        "Name,Lat,Lon\nNonNumeric,abc,-73.0\n",
        "",
    ):
        err_res = parse_bulk_sites_csv(bad_csv)
        assert err_res.ok is False
        assert err_res.error is not None
        assert err_res.error.code == "INVALID_CSV_ROW"

    oversized_bytes = parse_bulk_sites_csv(valid_csv, max_csv_bytes=20)
    assert oversized_bytes.ok is False
    assert oversized_bytes.error is not None
    assert oversized_bytes.error.code == "CSV_LIMIT_EXCEEDED"

    oversized_rows = parse_bulk_sites_csv(valid_csv, max_rows=1)
    assert oversized_rows.ok is False
    assert oversized_rows.error is not None
    assert oversized_rows.error.code == "CSV_LIMIT_EXCEEDED"

    csv_out = export_link_matrix_csv(
        [
            {
                "source_id": "VT-PEAK-01",
                "target_id": "VT-TWR-02",
                "distance_km": 24.1,
                "margin_db": 14.5,
                "reachability_state": "two_way",
            }
        ]
    )
    lines = csv_out.strip().splitlines()
    assert lines[0] == "source_id,target_id,distance_km,margin_db,reachability_state"
    assert lines[1] == "VT-PEAK-01,VT-TWR-02,24.1,14.5,two_way"


def test_cli_slot_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify CLI slot subcommand parser defaults and JSON execution."""
    args = build_parser().parse_args(["slot"])
    assert args.command == "slot"
    assert args.channel == "LongFast"
    assert args.region == "US"

    exit_code = cli_main(["slot", "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["frequency_slot"] == 20
    assert payload["center_freq_mhz"] == 906.875


def test_mcp_backbone_resilience_smoke() -> None:
    """Verify MCP evaluate_backbone_resilience tool call succeeds cleanly."""
    resp = MeshScoutMCPServer().handle_request(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "evaluate_backbone_resilience",
                "arguments": {
                    "region": "vt_chittenden",
                    "site_ids": ["VT-PEAK-01", "VT-TWR-02"],
                },
            },
        }
    )
    assert resp is not None
    assert resp["id"] == 99
    assert resp["result"]["isError"] is False
    structured = resp["result"]["structuredContent"]
    assert structured["ok"] is True
    assert structured["report"]["node_count"] == 2
    assert structured["channel_slot"]["frequency_slot"] == 20


def test_web_resilience_and_channel_routes_smoke(tmp_path: Path) -> None:
    """Verify FastAPI v1 resilience, channel slot, highpoint, CoT, and CSV routes in tmp_path."""
    app = create_web_app(
        db_path=tmp_path / "mesh_state.db",
        tower_db_path=tmp_path / "towers.db",
        telemetry_db_path=":memory:",
    )
    with TestClient(app) as client:
        slot_resp = client.get("/api/v1/channel/slot")
        assert slot_resp.status_code == 200
        assert slot_resp.json()["ok"] is True
        assert slot_resp.json()["frequency_slot"] == 20

        hp_resp = client.get("/api/v1/sites/highpoint?lat=44.48&lon=-73.20")
        assert hp_resp.status_code == 200
        assert hp_resp.json()["ok"] is True
        assert hp_resp.json()["samples_checked"] > 0

        res_resp = client.post(
            "/api/v1/topology/resilience",
            json={"region": "vt_chittenden", "site_ids": ["VT-PEAK-01", "VT-TWR-02"]},
        )
        assert res_resp.status_code == 200
        assert res_resp.json()["ok"] is True
        assert res_resp.json()["report"]["node_count"] == 2

        cot_resp = client.post(
            "/api/v1/export/cot",
            json={"site_ids": ["VT-PEAK-01"]},
        )
        assert cot_resp.status_code == 200
        assert cot_resp.json()["ok"] is True
        assert cot_resp.json()["site_count"] == 1
        cot_root = ET.fromstring(cot_resp.json()["cot_xml"])
        assert cot_root.tag == "events"
        assert len(cot_root.findall("event")) == 1

        links_csv_resp = client.post(
            "/api/v1/export/links.csv",
            json={
                "links": [
                    {
                        "source_id": "VT-PEAK-01",
                        "target_id": "VT-TWR-02",
                        "distance_km": 24.1,
                        "margin_db": 12.0,
                        "reachability_state": "two_way",
                    }
                ]
            },
        )
        assert links_csv_resp.status_code == 200
        assert "text/csv" in links_csv_resp.headers["content-type"]
        assert links_csv_resp.text.splitlines()[0] == (
            "source_id,target_id,distance_km,margin_db,reachability_state"
        )

        valid_csv_resp = client.post(
            "/api/v1/import/sites.csv",
            content="Name,Lat,Lon,SiteType,ElevationM,MastM\nTest Ridge,44.50,-73.00,mountain_peak,400.0,12.0\n",
            headers={"Content-Type": "text/csv"},
        )
        assert valid_csv_resp.status_code == 200
        assert valid_csv_resp.json()["ok"] is True
        assert valid_csv_resp.json()["count"] == 1

        oversized_payload = b"Name,Lat,Lon\n" + (b"X,44.5,-73.1\n" * 22000)
        assert len(oversized_payload) > 262_144
        oversized_resp = client.post(
            "/api/v1/import/sites.csv",
            content=oversized_payload,
            headers={"Content-Type": "text/csv"},
        )
        assert oversized_resp.status_code == 413
        assert oversized_resp.json()["error"]["code"] == "CSV_LIMIT_EXCEEDED"
