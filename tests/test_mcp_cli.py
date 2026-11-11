"""Unit tests for MeshScout MCP Stdio Server (`mcp_server.py`) and CLI (`cli.py`)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from meshscout.cli import build_parser, create_fallback_sse_app, main
from meshscout.mcp_server import MeshScoutMCPServer


def test_mcp_initialize_and_tools_list() -> None:
    """Verify MCP JSON-RPC 2.0 `initialize` and `tools/list` return all 11 MeshScout tools."""
    server = MeshScoutMCPServer()

    init_resp = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init_resp is not None
    assert init_resp["id"] == 1
    assert init_resp["result"]["serverInfo"]["name"] == "meshscout-mcp"
    assert "tools" in init_resp["result"]["capabilities"]
    assert "resources" in init_resp["result"]["capabilities"]
    assert "prompts" in init_resp["result"]["capabilities"]

    list_resp = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert list_resp is not None
    assert list_resp["id"] == 2
    tools = list_resp["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    assert tool_names == {
        "scout_repeater_sites",
        "evaluate_link_budget",
        "inspect_site_feasibility",
        "advise_node_role_and_airtime",
        "recommend_backhaul_architecture",
        "provision_node_radio",
        "simulate_winter_solar_survival",
        "analyze_mesh_coverage_gaps",
        "calibrate_empirical_clutter",
        "generate_landowner_brief",
        "stage_offline_field_kit",
        "manage_living_mesh_state",
        "advise_eirp",
        "list_region_packs",
    }
    assert len(tools) == 14


def test_mcp_call_scout_repeater_sites() -> None:
    """Verify `tools/call` for `scout_repeater_sites` executes offline viewshed + set-cover + scoring."""
    server = MeshScoutMCPServer()
    resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "scout_repeater_sites",
                "arguments": {
                    "region": "vt_chittenden",
                    "min_coverage": 0.90,
                    "max_repeaters": 5,
                    "no_delay": True,
                },
            },
        }
    )
    assert resp is not None
    assert resp["id"] == 10
    result = resp["result"]
    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload["ok"] is True
    assert payload["total_candidates_evaluated"] >= 10
    assert payload["achieved_coverage_fraction"] >= 0.90
    assert payload["threshold_met"] is True
    assert len(payload["selected_repeaters"]) >= 1
    assert len(payload["top_ranked_sites"]) >= 5


def test_mcp_call_evaluate_link_budget() -> None:
    """Verify `tools/call` for `evaluate_link_budget` between Mount Mansfield and Essex Junction."""
    server = MeshScoutMCPServer()
    resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "evaluate_link_budget",
                "arguments": {
                    "source_lat": 44.5437,
                    "source_lon": -72.8143,
                    "source_elev_m": 1339.0,
                    "target_lat": 44.4900,
                    "target_lon": -73.1100,
                    "target_elev_m": 105.0,
                    "frequency_mhz": 915.0,
                    "tx_power_dbm": 20.0,
                },
            },
        }
    )
    assert resp is not None
    result = resp["result"]
    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload["ok"] is True
    assert payload["link_budget"]["distance_km"] > 20.0
    assert payload["link_budget"]["has_line_of_sight"] is True
    assert payload["fresnel_analysis"]["fresnel_60pct_clear"] is True


def test_mcp_call_inspect_site_feasibility() -> None:
    """Verify `tools/call` for `inspect_site_feasibility` evaluates desense risk and cavity filter guidance."""
    server = MeshScoutMCPServer()
    resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "inspect_site_feasibility",
                "arguments": {
                    "site_id": "VT-PEAK-01",
                    "nearby_850_900mhz_erp_watts": 250.0,
                },
            },
        }
    )
    assert resp is not None
    result = resp["result"]
    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload["ok"] is True
    assert payload["site_id"] == "VT-PEAK-01"
    assert payload["viability"]["requires_cavity_filter"] is True


def test_mcp_call_advise_node_role_and_airtime() -> None:
    """Verify `tools/call` for `advise_node_role_and_airtime` returns role, airtime, and forecast."""
    server = MeshScoutMCPServer()
    resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "advise_node_role_and_airtime",
                "arguments": {
                    "site_id": "VT-PEAK-01",
                    "exposed_population": 8000,
                    "overlapping_router_count": 0,
                    "protocol_family": "Meshtastic",
                },
            },
        }
    )
    assert resp is not None
    result = resp["result"]
    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload["ok"] is True
    assert payload["site_id"] == "VT-PEAK-01"
    assert payload["recommendation"]["recommended_role"] in ("ROUTER", "ROUTER_LATE")
    assert payload["airtime"]["total_airtime_ms"] > 0
    assert payload["forecast"]["expected_nodes"] >= 0


def test_mcp_call_recommend_backhaul_architecture() -> None:
    """Verify `tools/call` for `recommend_backhaul_architecture` evaluates summit link decoupling."""
    server = MeshScoutMCPServer()
    resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "recommend_backhaul_architecture",
                "arguments": {
                    "source_site_id": "VT-PEAK-01",
                    "target_site_id": "VT-PEAK-05",
                    "channel_utilization_pct": 10.0,
                },
            },
        }
    )
    assert resp is not None
    result = resp["result"]
    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload["ok"] is True
    assert payload["source_site_id"] == "VT-PEAK-01"
    assert payload["target_site_id"] == "VT-PEAK-05"
    assert payload["recommendation"]["architecture"] in ("direct_lora", "dual_radio_pi_bridge", "microwave_ip_5_8ghz")
    assert payload["recommendation"]["required_vertical_isolation_m"] >= 3.0


def test_mcp_call_provision_node_radio() -> None:
    """Verify `tools/call` for `provision_node_radio` across protocols and error cases."""
    server = MeshScoutMCPServer()

    # 1. Meshtastic URL and QR SVG
    resp_mt = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {
                "name": "provision_node_radio",
                "arguments": {
                    "site_id": "VT-PEAK-01",
                    "target": "meshtastic",
                    "channel_name": "VermontMesh",
                },
            },
        }
    )
    assert resp_mt is not None
    res_mt = resp_mt["result"]
    assert res_mt["isError"] is False
    payload_mt = res_mt["structuredContent"]
    assert payload_mt["ok"] is True
    assert payload_mt["target"] == "meshtastic"
    assert "https://meshtastic.org/e/#" in payload_mt["raw_url_or_text"]
    assert "<svg" in payload_mt["inline_svg_qr"]
    assert len(payload_mt["cli_commands"]) > 0

    # 2. MeshCore CLI commands
    resp_mc = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {
                "name": "provision_node_radio",
                "arguments": {
                    "site_id": "VT-PEAK-01",
                    "target": "meshcore",
                },
            },
        }
    )
    assert resp_mc is not None
    payload_mc = resp_mc["result"]["structuredContent"]
    assert payload_mc["ok"] is True
    assert payload_mc["target"] == "meshcore"
    assert "meshcore" in payload_mc["cli_commands"][0]

    # 3. Reticulum rns.conf stanza
    resp_ret = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {
                "name": "provision_node_radio",
                "arguments": {
                    "site_id": "VT-PEAK-01",
                    "target": "reticulum",
                },
            },
        }
    )
    assert resp_ret is not None
    payload_ret = resp_ret["result"]["structuredContent"]
    assert payload_ret["ok"] is True
    assert payload_ret["target"] == "reticulum"
    assert "[[RNode-" in payload_ret["raw_url_or_text"]

    # 4. Error: Invalid site ID
    resp_bad_site = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 23,
            "method": "tools/call",
            "params": {
                "name": "provision_node_radio",
                "arguments": {"site_id": "NON-EXISTENT-SITE-XYZ"},
            },
        }
    )
    assert resp_bad_site is not None
    assert resp_bad_site["result"]["isError"] is True
    assert resp_bad_site["result"]["structuredContent"]["ok"] is False
    assert resp_bad_site["result"]["structuredContent"]["error"]["code"] == "SITE_NOT_FOUND"

    # 5. Error: Invalid target
    resp_bad_tgt = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 24,
            "method": "tools/call",
            "params": {
                "name": "provision_node_radio",
                "arguments": {"site_id": "VT-PEAK-01", "target": "unsupported_protocol"},
            },
        }
    )
    assert resp_bad_tgt is not None
    assert resp_bad_tgt["result"]["isError"] is True
    assert resp_bad_tgt["result"]["structuredContent"]["ok"] is False
    assert resp_bad_tgt["result"]["structuredContent"]["error"]["code"] == "INVALID_TARGET"


def test_mcp_call_simulate_winter_solar_survival() -> None:
    """Verify `tools/call` for `simulate_winter_solar_survival` across chemistries and error cases."""
    server = MeshScoutMCPServer()

    # 1. LTO battery simulation by site_id
    resp_lto = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {
                "name": "simulate_winter_solar_survival",
                "arguments": {
                    "site_id": "VT-PEAK-01",
                    "panel_watts": 15.0,
                    "battery_chemistry": "lto",
                    "battery_capacity_wh": 30.0,
                    "consecutive_cloudy_days": 5,
                },
            },
        }
    )
    assert resp_lto is not None
    res_lto = resp_lto["result"]
    assert res_lto["isError"] is False
    payload_lto = res_lto["structuredContent"]
    assert payload_lto["ok"] is True
    assert payload_lto["setup"]["battery_chemistry"] == "lto"
    assert payload_lto["survived_winter_streak"] is True
    assert len(payload_lto["daily_timeline"]) == 30

    # 2. LiFePO4 battery simulation by lat/lon with sub-zero lockout
    resp_lifepo4 = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {
                "name": "simulate_winter_solar_survival",
                "arguments": {
                    "lat": 44.5437,
                    "lon": -72.8143,
                    "panel_watts": 10.0,
                    "battery_chemistry": "lifepo4",
                    "battery_capacity_wh": 20.0,
                    "consecutive_cloudy_days": 7,
                },
            },
        }
    )
    assert resp_lifepo4 is not None
    payload_lifepo4 = resp_lifepo4["result"]["structuredContent"]
    assert payload_lifepo4["ok"] is True
    assert payload_lifepo4["setup"]["battery_chemistry"] == "lifepo4"
    assert payload_lifepo4["recommended_battery_wh"] > 0.0

    # 3. Error: Missing coordinates and site_id
    resp_no_coord = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 32,
            "method": "tools/call",
            "params": {
                "name": "simulate_winter_solar_survival",
                "arguments": {},
            },
        }
    )
    assert resp_no_coord is not None
    assert resp_no_coord["result"]["isError"] is True
    assert resp_no_coord["result"]["structuredContent"]["error"]["code"] == "MISSING_COORDINATES"

    # 4. Error: Invalid battery chemistry
    resp_bad_chem = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 33,
            "method": "tools/call",
            "params": {
                "name": "simulate_winter_solar_survival",
                "arguments": {"site_id": "VT-PEAK-01", "battery_chemistry": "unobtainium"},
            },
        }
    )
    assert resp_bad_chem is not None
    assert resp_bad_chem["result"]["isError"] is True
    assert resp_bad_chem["result"]["structuredContent"]["error"]["code"] == "INVALID_BATTERY_CHEMISTRY"


def test_mcp_call_analyze_mesh_coverage_gaps() -> None:
    """Verify `tools/call` for `analyze_mesh_coverage_gaps` with fixtures and custom telemetry."""
    server = MeshScoutMCPServer()

    # 1. Bundled fixture gap analysis
    resp_fix = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 40,
            "method": "tools/call",
            "params": {
                "name": "analyze_mesh_coverage_gaps",
                "arguments": {
                    "coverage_radius_km": 8.0,
                    "use_fixture": True,
                },
            },
        }
    )
    assert resp_fix is not None
    res_fix = resp_fix["result"]
    assert res_fix["isError"] is False
    payload_fix = res_fix["structuredContent"]
    assert payload_fix["ok"] is True
    assert payload_fix["total_towns_checked"] >= 10
    assert payload_fix["unobserved_towns_count"] >= 0
    assert len(payload_fix["ranked_solution_sites"]) >= 1

    # 2. Custom JSON packets gap analysis
    custom_packets = json.dumps(
        [
            {
                "node_id": "!test01",
                "short_name": "TEST",
                "long_name": "Test Node Burlington",
                "lat": 44.4759,
                "lon": -73.2121,
                "rssi_dbm": -85.0,
                "snr_db": 8.0,
            }
        ]
    )
    resp_custom = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 41,
            "method": "tools/call",
            "params": {
                "name": "analyze_mesh_coverage_gaps",
                "arguments": {
                    "coverage_radius_km": 10.0,
                    "custom_json_or_ndjson": custom_packets,
                },
            },
        }
    )
    assert resp_custom is not None
    payload_custom = resp_custom["result"]["structuredContent"]
    assert payload_custom["ok"] is True
    assert payload_custom["heard_nodes_count"] == 1

    # 3. Error: Negative coverage radius
    resp_bad_radius = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {
                "name": "analyze_mesh_coverage_gaps",
                "arguments": {"coverage_radius_km": -5.0},
            },
        }
    )
    assert resp_bad_radius is not None
    assert resp_bad_radius["result"]["isError"] is True
    assert resp_bad_radius["result"]["structuredContent"]["error"]["code"] == "INVALID_COVERAGE_RADIUS"


def test_mcp_call_calibrate_empirical_clutter() -> None:
    """Verify `tools/call` for `calibrate_empirical_clutter` with wardrive telemetry."""
    server = MeshScoutMCPServer()

    # 1. Successful calibration with VT-MANS-01 against bundled wardrive sample
    resp_cal = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 50,
            "method": "tools/call",
            "params": {
                "name": "calibrate_empirical_clutter",
                "arguments": {
                    "transmitter_site_id": "VT-MANS-01",
                    "use_fixture": True,
                },
            },
        }
    )
    assert resp_cal is not None
    res_cal = resp_cal["result"]
    assert res_cal["isError"] is False
    payload_cal = res_cal["structuredContent"]
    assert payload_cal["ok"] is True
    assert payload_cal["transmitter_site_id"] == "VT-MANS-01"
    assert payload_cal["matched_packets_count"] >= 10
    assert payload_cal["rmse_db"] >= 0.0
    assert payload_cal["recommended_canopy_adjustment_db"] >= 0.0

    # 2. Error: Site not found
    resp_bad_site = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 51,
            "method": "tools/call",
            "params": {
                "name": "calibrate_empirical_clutter",
                "arguments": {"transmitter_site_id": "NON-EXISTENT-TX"},
            },
        }
    )
    assert resp_bad_site is not None
    assert resp_bad_site["result"]["isError"] is True
    assert resp_bad_site["result"]["structuredContent"]["error"]["code"] == "SITE_NOT_FOUND"

    # 3. Error: No matching packets for site in wardrive log
    resp_no_match = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 52,
            "method": "tools/call",
            "params": {
                "name": "calibrate_empirical_clutter",
                "arguments": {
                    "transmitter_site_id": "VT-PEAK-01",
                    "use_fixture": True,
                },
            },
        }
    )
    assert resp_no_match is not None
    assert resp_no_match["result"]["isError"] is True
    assert resp_no_match["result"]["structuredContent"]["error"]["code"] == "NO_MATCHING_PACKETS"


def test_mcp_call_generate_landowner_brief() -> None:
    """Verify `tools/call` for `generate_landowner_brief` produces 1-page HTML brief."""
    server = MeshScoutMCPServer()

    # 1. Valid site landowner brief
    resp_brief = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 60,
            "method": "tools/call",
            "params": {
                "name": "generate_landowner_brief",
                "arguments": {
                    "site_id": "VT-PEAK-01",
                    "contact_org": "Vermont Community Emergency Mesh Initiative",
                },
            },
        }
    )
    assert resp_brief is not None
    res_brief = resp_brief["result"]
    assert res_brief["isError"] is False
    payload_brief = res_brief["structuredContent"]
    assert payload_brief["ok"] is True
    assert payload_brief["site_id"] == "VT-PEAK-01"
    assert "<!DOCTYPE html>" in payload_brief["html_brief"]
    assert "Civic Emergency Communications Host Brief" in payload_brief["html_brief"]
    assert "Vermont Community Emergency Mesh Initiative" in payload_brief["html_brief"]

    # 2. Error: Site not found
    resp_bad_site = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 61,
            "method": "tools/call",
            "params": {
                "name": "generate_landowner_brief",
                "arguments": {"site_id": "NON-EXISTENT-SITE"},
            },
        }
    )
    assert resp_bad_site is not None
    assert resp_bad_site["result"]["isError"] is True
    assert resp_bad_site["result"]["structuredContent"]["error"]["code"] == "SITE_NOT_FOUND"


def test_cli_scout_link_and_feasibility_offline(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify CLI `scout`, `link`, and `feasibility` subcommands execute offline and return 0."""
    # 1. CLI scout --no-delay --json
    rc_scout = main(["scout", "--region", "vt_chittenden", "--no-delay", "--json"])
    assert rc_scout == 0
    out_scout = json.loads(capsys.readouterr().out)
    assert out_scout["ok"] is True
    assert out_scout["threshold_met"] is True

    # 2. CLI link --source ... --target ... --no-delay --json
    rc_link = main(
        [
            "link",
            "--source",
            "44.5437,-72.8143,1339.0",
            "--target",
            "44.4900,-73.1100,105.0",
            "--no-delay",
            "--json",
        ]
    )
    assert rc_link == 0
    out_link = json.loads(capsys.readouterr().out)
    assert out_link["ok"] is True
    assert out_link["link_budget"]["link_margin_db"] > 10.0

    # 3. CLI feasibility --site-id VT-PEAK-01 --json
    rc_feas = main(["feasibility", "--site-id", "VT-PEAK-01", "--emitter-watts", "100", "--json"])
    assert rc_feas == 0
    out_feas = json.loads(capsys.readouterr().out)
    assert out_feas["ok"] is True
    assert out_feas["site_id"] == "VT-PEAK-01"


def test_mcp_call_manage_living_mesh_state(tmp_path: Path) -> None:
    """Verify `tools/call` for `manage_living_mesh_state` inspects and updates network state."""
    db_file = str(tmp_path / "test_mesh_state.db")
    server = MeshScoutMCPServer(db_path=db_file)

    # 1. Action: get_preferences
    resp_pref = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 70,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "get_preferences"},
            },
        }
    )
    assert resp_pref is not None
    assert resp_pref["result"]["isError"] is False
    res_pref = resp_pref["result"]["structuredContent"]
    assert res_pref["ok"] is True
    assert res_pref["action"] == "get_preferences"
    assert "home_name" in res_pref["preferences"]

    # 2. Action: set_home
    resp_home = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 71,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {
                    "action": "set_home",
                    "home_lat": 44.5021,
                    "home_lon": -73.0985,
                    "home_name": "Essex Field Station",
                },
            },
        }
    )
    assert resp_home is not None
    assert resp_home["result"]["isError"] is False
    res_home = resp_home["result"]["structuredContent"]
    assert res_home["ok"] is True
    assert res_home["preferences"]["home_name"] == "Essex Field Station"
    assert res_home["preferences"]["home_lat"] == pytest.approx(44.5021)
    assert res_home["preferences"]["home_lon"] == pytest.approx(-73.0985)

    # 3. Action: update_status (auto-seeds candidate site from regional fixtures)
    resp_up1 = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 72,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {
                    "action": "update_status",
                    "site_id": "VT-PEAK-01",
                    "status": "active_on_air",
                    "notes": "Summit station deployed",
                },
            },
        }
    )
    assert resp_up1 is not None
    assert resp_up1["result"]["isError"] is False
    res_up1 = resp_up1["result"]["structuredContent"]
    assert res_up1["ok"] is True
    assert res_up1["node"]["site_id"] == "VT-PEAK-01"
    assert res_up1["node"]["status"] == "active_on_air"
    assert res_up1["node"]["notes"] == "Summit station deployed"

    # 4. Action: update_status second site
    resp_up2 = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 73,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {
                    "action": "update_status",
                    "site_id": "VT-TWR-02",
                    "status": "testing",
                },
            },
        }
    )
    assert resp_up2 is not None
    assert resp_up2["result"]["isError"] is False
    assert resp_up2["result"]["structuredContent"]["node"]["status"] == "testing"

    # 5. Action: list (all)
    resp_list = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 74,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "list"},
            },
        }
    )
    assert resp_list is not None
    assert resp_list["result"]["isError"] is False
    res_list = resp_list["result"]["structuredContent"]
    assert res_list["ok"] is True
    assert res_list["total_nodes"] == 2
    listed_ids = {n["site_id"] for n in res_list["nodes"]}
    assert listed_ids == {"VT-PEAK-01", "VT-TWR-02"}

    # 6. Action: list with status filter
    resp_filter = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 75,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "list", "status": "testing"},
            },
        }
    )
    assert resp_filter is not None
    assert resp_filter["result"]["isError"] is False
    res_filter = resp_filter["result"]["structuredContent"]
    assert res_filter["total_nodes"] == 1
    assert res_filter["nodes"][0]["site_id"] == "VT-TWR-02"

    # 7. Action: update_status to dismantled
    resp_dis = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 76,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {
                    "action": "update_status",
                    "site_id": "VT-PEAK-01",
                    "status": "dismantled",
                },
            },
        }
    )
    assert resp_dis is not None
    assert resp_dis["result"]["isError"] is False
    res_dis = resp_dis["result"]["structuredContent"]
    assert res_dis["ok"] is True
    assert res_dis["node"]["status"] == "dismantled"

    # 8. Action: export_pack
    resp_exp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 77,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "export_pack"},
            },
        }
    )
    assert resp_exp is not None
    assert resp_exp["result"]["isError"] is False
    res_exp = resp_exp["result"]["structuredContent"]
    assert res_exp["ok"] is True
    pack = res_exp["pack"]
    assert "nodes" in pack
    assert len(pack["nodes"]) == 2

    # 9. Action: import_pack with dict into a new database
    db_target = str(tmp_path / "imported_mesh_state.db")
    server_target = MeshScoutMCPServer(db_path=db_target)
    resp_imp = server_target.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 78,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {
                    "action": "import_pack",
                    "pack": pack,
                },
            },
        }
    )
    assert resp_imp is not None
    assert resp_imp["result"]["isError"] is False
    res_imp = resp_imp["result"]["structuredContent"]
    assert res_imp["ok"] is True
    assert res_imp["imported_count"] == 2

    # 10. Action: import_pack with pack_json string
    resp_imp_json = server_target.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 79,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {
                    "action": "import_pack",
                    "pack_json": json.dumps(pack),
                },
            },
        }
    )
    assert resp_imp_json is not None
    assert resp_imp_json["result"]["isError"] is False
    assert resp_imp_json["result"]["structuredContent"]["ok"] is True

    # 11. Action: reconcile_dismantled
    resp_rec = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 80,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "reconcile_dismantled"},
            },
        }
    )
    assert resp_rec is not None
    assert resp_rec["result"]["isError"] is False
    res_rec = resp_rec["result"]["structuredContent"]
    assert res_rec["ok"] is True
    assert "reconciled_count" in res_rec
    assert isinstance(res_rec["dismantled_ids"], list)

    # 12. Error handling
    # Unknown action
    err_act = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 81,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "invalid_action"},
            },
        }
    )
    assert err_act is not None
    assert err_act["result"]["isError"] is True
    assert err_act["result"]["structuredContent"]["error"]["code"] == "INVALID_ACTION"

    # Missing site_id for update_status
    err_site = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 82,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "update_status", "status": "candidate"},
            },
        }
    )
    assert err_site is not None
    assert err_site["result"]["isError"] is True
    assert err_site["result"]["structuredContent"]["error"]["code"] == "MISSING_SITE_ID"

    # Invalid status
    err_stat = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 83,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {
                    "action": "update_status",
                    "site_id": "VT-PEAK-01",
                    "status": "bad_status",
                },
            },
        }
    )
    assert err_stat is not None
    assert err_stat["result"]["isError"] is True
    assert err_stat["result"]["structuredContent"]["error"]["code"] == "INVALID_STATUS"

    # Missing pack for import_pack
    err_pack = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 84,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "import_pack"},
            },
        }
    )
    assert err_pack is not None
    assert err_pack["result"]["isError"] is True
    assert err_pack["result"]["structuredContent"]["error"]["code"] == "MISSING_PACK"

    # Invalid pack_json for import_pack
    err_pack_json = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 85,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "import_pack", "pack_json": "not-valid-json"},
            },
        }
    )
    assert err_pack_json is not None
    assert err_pack_json["result"]["isError"] is True
    assert err_pack_json["result"]["structuredContent"]["error"]["code"] == "INVALID_PACK_JSON"


def test_mcp_resources_list_and_read(tmp_path: Path) -> None:
    """Verify MCP `resources/list` and `resources/read` for hardware presets and statewide sites."""
    db_file = str(tmp_path / "test_resources.db")
    server = MeshScoutMCPServer(db_path=db_file)

    # 1. resources/list
    resp_list = server.handle_request({"jsonrpc": "2.0", "id": 80, "method": "resources/list"})
    assert resp_list is not None
    assert resp_list["id"] == 80
    resources = resp_list["result"]["resources"]
    uris = {r["uri"] for r in resources}
    expected_uris = {
        "meshscout://sites/all",
        "meshscout://presets/hardware",
        "meshscout://presets/protocols",
        "meshscout://state/living-mesh",
        "meshscout://fixtures/vt_counties",
        "meshscout://presets/site-architectures",
        "meshscout://regulatory/north-america",
        "meshscout://packs/installed",
    }
    assert uris == expected_uris

    # 2. resources/read meshscout://presets/hardware
    resp_hw = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 81,
            "method": "resources/read",
            "params": {"uri": "meshscout://presets/hardware"},
        }
    )
    assert resp_hw is not None
    assert resp_hw["id"] == 81
    contents_hw = resp_hw["result"]["contents"]
    assert len(contents_hw) == 1
    assert contents_hw[0]["uri"] == "meshscout://presets/hardware"
    assert contents_hw[0]["mimeType"] == "application/json"
    hw_data = json.loads(contents_hw[0]["text"])
    assert "RAK4631_SOLAR" in hw_data
    assert hw_data["RAK4631_SOLAR"]["typical_power_draw_mw"] > 0

    # 3. resources/read meshscout://sites/all
    resp_sites = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 82,
            "method": "resources/read",
            "params": {"uri": "meshscout://sites/all"},
        }
    )
    assert resp_sites is not None
    assert resp_sites["id"] == 82
    contents_sites = resp_sites["result"]["contents"]
    assert len(contents_sites) == 1
    assert contents_sites[0]["uri"] == "meshscout://sites/all"
    assert contents_sites[0]["mimeType"] == "application/json"
    sites_data = json.loads(contents_sites[0]["text"])
    assert isinstance(sites_data, list)
    assert len(sites_data) >= 10
    assert any(s["site_id"] == "VT-PEAK-01" for s in sites_data)

    # 4. resources/read meshscout://state/living-mesh
    resp_state = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 83,
            "method": "resources/read",
            "params": {"uri": "meshscout://state/living-mesh"},
        }
    )
    assert resp_state is not None
    state_data = json.loads(resp_state["result"]["contents"][0]["text"])
    assert "preferences" in state_data
    assert "nodes" in state_data

    # 5. resources/read meshscout://regulatory/north-america
    resp_reg = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 84,
            "method": "resources/read",
            "params": {"uri": "meshscout://regulatory/north-america"},
        }
    )
    assert resp_reg is not None
    assert resp_reg["id"] == 84
    reg_data = json.loads(resp_reg["result"]["contents"][0]["text"])
    assert isinstance(reg_data, list)
    assert len(reg_data) >= 65

    # 6. resources/read meshscout://packs/installed
    resp_packs = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 85,
            "method": "resources/read",
            "params": {"uri": "meshscout://packs/installed"},
        }
    )
    assert resp_packs is not None
    assert resp_packs["id"] == 85
    packs_data = json.loads(resp_packs["result"]["contents"][0]["text"])
    assert isinstance(packs_data, list)

    # 7. resources/read error for invalid URI
    resp_err = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 86,
            "method": "resources/read",
            "params": {"uri": "meshscout://invalid/resource"},
        }
    )
    assert resp_err is not None
    assert resp_err["error"]["code"] == -32602


def test_mcp_prompts_list_and_get() -> None:
    """Verify MCP `prompts/list` and `prompts/get` for design_regional_emergency_backbone."""
    server = MeshScoutMCPServer()

    # 1. prompts/list
    resp_list = server.handle_request({"jsonrpc": "2.0", "id": 90, "method": "prompts/list"})
    assert resp_list is not None
    assert resp_list["id"] == 90
    prompts = resp_list["result"]["prompts"]
    prompt_names = {p["name"] for p in prompts}
    assert prompt_names == {
        "design_regional_emergency_backbone",
        "audit_channel_contention",
        "prepare_selectboard_pitch",
    }

    # 2. prompts/get design_regional_emergency_backbone
    resp_get = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 91,
            "method": "prompts/get",
            "params": {
                "name": "design_regional_emergency_backbone",
                "arguments": {
                    "region": "vt_chittenden",
                    "target_coverage": "0.95",
                    "max_repeaters": "4",
                },
            },
        }
    )
    assert resp_get is not None
    assert resp_get["id"] == 91
    res_get = resp_get["result"]
    assert "emergency communications mesh backbone" in res_get["description"]
    messages = res_get["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    prompt_text = messages[0]["content"]["text"]
    assert "vt_chittenden" in prompt_text
    assert "0.95" in prompt_text
    assert "4" in prompt_text
    assert "scout_repeater_sites" in prompt_text
    assert "evaluate_link_budget" in prompt_text

    # 3. prompts/get audit_channel_contention
    resp_audit = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 92,
            "method": "prompts/get",
            "params": {
                "name": "audit_channel_contention",
                "arguments": {"site_id": "VT-PEAK-01", "exposed_population": 8000},
            },
        }
    )
    assert resp_audit is not None
    assert "VT-PEAK-01" in resp_audit["result"]["messages"][0]["content"]["text"]

    # 4. prompts/get prepare_selectboard_pitch
    resp_pitch = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 93,
            "method": "prompts/get",
            "params": {
                "name": "prepare_selectboard_pitch",
                "arguments": {"site_id": "VT-PEAK-01", "town_name": "Underhill"},
            },
        }
    )
    assert resp_pitch is not None
    assert "Underhill" in resp_pitch["result"]["messages"][0]["content"]["text"]

    # 5. prompts/get error for unknown prompt
    resp_err = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 94,
            "method": "prompts/get",
            "params": {"name": "non_existent_prompt"},
        }
    )
    assert resp_err is not None
    assert resp_err["error"]["code"] == -32602


def test_mcp_cli_argument_parsing_stdio() -> None:
    """Verify MCP CLI argument parsing for stdio transport and defaults."""
    parser = build_parser()

    # 1. Default mcp command -> stdio
    args_default = parser.parse_args(["mcp"])
    assert args_default.command == "mcp"
    assert args_default.transport == "stdio"
    assert args_default.host == "127.0.0.1"
    assert args_default.port == 8000

    # 2. Explicit --transport stdio
    args_stdio = parser.parse_args(["mcp", "--transport", "stdio"])
    assert args_stdio.transport == "stdio"

    # 3. Legacy --stdio flag
    args_legacy = parser.parse_args(["mcp", "--stdio"])
    assert args_legacy.stdio is True


def test_mcp_cli_argument_parsing_sse() -> None:
    """Verify MCP CLI argument parsing for SSE transport and host/port options."""
    parser = build_parser()

    # 1. SSE with specified port
    args_sse = parser.parse_args(["mcp", "--transport", "sse", "--port", "8000"])
    assert args_sse.command == "mcp"
    assert args_sse.transport == "sse"
    assert args_sse.host == "127.0.0.1"
    assert args_sse.port == 8000

    # 2. SSE with custom host and port
    args_custom = parser.parse_args([
        "mcp",
        "--transport", "sse",
        "--host", "0.0.0.0",
        "--port", "9191",
    ])
    assert args_custom.transport == "sse"
    assert args_custom.host == "0.0.0.0"
    assert args_custom.port == 9191


def test_mcp_cli_execution_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify executing 'mcp --transport stdio' invokes MeshScoutMCPServer.run_stdio."""
    called = []

    def mock_run_stdio(self: MeshScoutMCPServer) -> None:
        called.append(True)

    monkeypatch.setattr(MeshScoutMCPServer, "run_stdio", mock_run_stdio)
    exit_code = main(["mcp", "--transport", "stdio"])
    assert exit_code == 0
    assert len(called) == 1


def test_mcp_cli_execution_sse_fastmcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify executing 'mcp --transport sse' invokes FastMCP.run when FastMCP is available."""
    called_transport = []

    class DummyFastMCP:
        def __init__(self) -> None:
            self.settings = type("Settings", (), {"host": "127.0.0.1", "port": 8000})()

        def run(self, transport: str = "stdio") -> None:
            called_transport.append(transport)

    monkeypatch.setattr("meshscout.cli.create_fastmcp_app", lambda host="127.0.0.1", port=8000: DummyFastMCP())
    exit_code = main(["mcp", "--transport", "sse", "--port", "8000"])
    assert exit_code == 0
    assert called_transport == ["sse"]


def test_mcp_cli_execution_sse_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify executing 'mcp --transport sse' falls back to uvicorn + create_fallback_sse_app."""
    uvicorn_runs = []

    class DummyServer(MeshScoutMCPServer):
        pass

    import uvicorn
    monkeypatch.setattr("meshscout.cli.create_fastmcp_app", lambda host="127.0.0.1", port=8000: DummyServer())
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port: uvicorn_runs.append((host, port)))

    exit_code = main(["mcp", "--transport", "sse", "--host", "0.0.0.0", "--port", "8085"])
    assert exit_code == 0
    assert uvicorn_runs == [("0.0.0.0", 8085)]


def test_mcp_fallback_sse_app_endpoints() -> None:
    """Verify fallback ASGI app handles GET /sse and POST /messages endpoints."""
    import asyncio
    from starlette.requests import Request
    from starlette.testclient import TestClient

    app = create_fallback_sse_app()
    client = TestClient(app)

    # 1. POST /messages with invalid JSON returns 400
    resp_bad = client.post("/messages", content=b"invalid json")
    assert resp_bad.status_code == 400

    # 2. POST /messages without session_id returns direct JSON-RPC response
    resp_direct = client.post(
        "/messages",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert resp_direct.status_code == 200
    direct_data = resp_direct.json()
    assert direct_data["id"] == 1
    assert direct_data["result"]["serverInfo"]["name"] == "meshscout-mcp"

    # 3. GET /sse establishes stream starting with endpoint event
    async def check_sse() -> str:
        sse_route = [r for r in app.routes if getattr(r, "path", None) == "/sse"][0]
        scope = {"type": "http", "method": "GET", "path": "/sse", "headers": []}
        req = Request(scope)
        resp = await sse_route.endpoint(req)
        first_chunk = await anext(resp.body_iterator)
        return first_chunk

    first_chunk = asyncio.run(check_sse())
    assert "event: endpoint" in first_chunk
    assert "/messages?session_id=" in first_chunk

    # Extract session_id for message routing
    session_id = first_chunk.split("session_id=")[1].split("\r")[0].split("\n")[0].strip()
    assert len(session_id) > 0

    # 4. POST /messages?session_id=... queues response and returns 202 Accepted
    resp_routed = client.post(
        f"/messages?session_id={session_id}",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert resp_routed.status_code == 202


def test_mcp_call_advise_eirp() -> None:
    """Verify `tools/call` for `advise_eirp` evaluates RF EIRP and conducted limits."""
    server = MeshScoutMCPServer()
    resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 110,
            "method": "tools/call",
            "params": {
                "name": "advise_eirp",
                "arguments": {
                    "tx_power_dbm": 30.0,
                    "antenna_gain_dbi": 8.0,
                    "cable_loss_db": 1.2,
                },
            },
        }
    )
    assert resp is not None
    assert resp["id"] == 110
    assert "result" in resp
    content = resp["result"]["content"][0]["text"]
    data = json.loads(content)
    assert data["ok"] is True
    assert data["eirp_dbm"] == 36.8
    assert data["recommended_max_tx_dbm"] == 28.0
    assert len(data["warnings"]) == 1


def test_mcp_call_list_region_packs(tmp_path: Path) -> None:
    """Verify `tools/call` for `list_region_packs` returns installed packs."""
    db_file = str(tmp_path / "towers.db")
    server = MeshScoutMCPServer(db_path=db_file)
    resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 111,
            "method": "tools/call",
            "params": {
                "name": "list_region_packs",
                "arguments": {},
            },
        }
    )
    assert resp is not None
    assert resp["id"] == 111
    assert "result" in resp
    content = resp["result"]["content"][0]["text"]
    data = json.loads(content)
    assert data["ok"] is True
    assert "installed" in data
    assert "available" in data


def test_mcp_notifications_and_ping() -> None:
    """Verify JSON-RPC 2.0 notifications return None and ping returns result."""
    server = MeshScoutMCPServer()

    # Notification with no id
    assert server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert server.handle_request({"jsonrpc": "2.0", "method": "some_notice"}) is None

    # Ping method
    ping_resp = server.handle_request({"jsonrpc": "2.0", "id": 99, "method": "ping"})
    assert ping_resp is not None
    assert ping_resp["id"] == 99
    assert ping_resp["result"] == {}


def test_cli_flags_and_arguments() -> None:
    """Verify CLI parser flags for scout delay, towers ingest alias, and multi-region remove."""
    parser = build_parser()

    # scout --delay
    args = parser.parse_args(["scout", "--region", "vt_chittenden", "--delay", "0.05"])
    assert args.delay == 0.05

    # towers ingest with positional source and --input
    args_ingest = parser.parse_args(["towers", "ingest", "fcc_asr", "--input", "test.zip"])
    assert args_ingest.pos_source == "fcc_asr"
    assert args_ingest.path == "test.zip"

    # regions remove with multiple regions
    args_rem = parser.parse_args(["regions", "remove", "vt", "nh", "me"])
    assert args_rem.regions == ["vt", "nh", "me"]


def test_elevation_dem_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify HGTElevationTileReader respects MESHSCOUT_DEM_DIR environment variable."""
    from meshscout.adapters.elevation import HGTElevationTileReader

    custom_dem = tmp_path / "custom_dem"
    custom_dem.mkdir()
    monkeypatch.setenv("MESHSCOUT_DEM_DIR", str(custom_dem))

    reader = HGTElevationTileReader()
    assert reader.dem_dir == custom_dem



