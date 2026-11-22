"""Day-0 MCP Alignment Invariant and Verification Test Suite.

Ensures that 100% of core domain capabilities and adapters in MeshScout
are exposed through MCP tools, resources, and prompts on Day 0.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List
import pytest

from meshscout.core.contracts import Coordinate, SiteCandidate, SiteType
from meshscout.core.packs import PackSourceInfo, export_region_pack, install_region_pack
from meshscout.core.tower_registry import UnifiedTowerRegistry
from meshscout import mcp_server, mcp_tool_helpers
from meshscout.mcp_server import (
    DOMAIN_CAPABILITY_MAP,
    MCP_PROMPTS_MANIFEST,
    MCP_RESOURCES_MANIFEST,
    MCP_TOOLS_MANIFEST,
    MeshScoutMCPServer,
    verify_domain_mcp_coverage,
)


def test_domain_capability_coverage_100pct() -> None:
    """Test 1: Verify that every mapped domain module has active MCP tools or resources."""
    is_valid, issues = verify_domain_mcp_coverage()
    assert is_valid, f"Domain MCP coverage verification failed: {issues}"
    assert len(issues) == 0

    manifest_tool_names = {t["name"] for t in MCP_TOOLS_MANIFEST}
    manifest_resource_uris = {r["uri"] for r in MCP_RESOURCES_MANIFEST}

    # Verify every registered domain has at least one active tool or resource
    for domain, capability in DOMAIN_CAPABILITY_MAP.items():
        tools = capability.get("tools", [])
        resources = capability.get("resources", [])
        total_endpoints = len(tools) + len(resources)
        assert total_endpoints > 0, (
            f"Domain capability '{domain}' has zero MCP endpoints mapped."
        )

        for tool in tools:
            assert tool in manifest_tool_names, (
                f"Domain '{domain}' maps unknown tool '{tool}' not in MCP_TOOLS_MANIFEST."
            )

        for resource in resources:
            assert resource in manifest_resource_uris, (
                f"Domain '{domain}' maps unknown resource '{resource}' not in MCP_RESOURCES_MANIFEST."
            )


def test_no_unbound_mcp_handlers() -> None:
    """Test 2: Verify every tool in MCP_TOOLS_MANIFEST has a callable handler in MeshScoutMCPServer."""
    server = MeshScoutMCPServer()
    manifest_tool_names = [t["name"] for t in MCP_TOOLS_MANIFEST]

    assert len(manifest_tool_names) == 15, (
        f"Expected 15 MCP tools, found {len(manifest_tool_names)}."
    )

    for tool_name in manifest_tool_names:
        assert tool_name in server._handlers, (
            f"Tool '{tool_name}' in MCP_TOOLS_MANIFEST lacks a registered handler in MeshScoutMCPServer."
        )
        handler = server._handlers[tool_name]
        assert callable(handler), (
            f"Registered handler for tool '{tool_name}' is not callable."
        )


def test_mcp_schema_strictness() -> None:
    """Test 3: Verify every tool in MCP_TOOLS_MANIFEST has valid non-empty schema and description."""
    for tool in MCP_TOOLS_MANIFEST:
        tool_name = tool.get("name", "<unnamed>")
        description = tool.get("description", "")
        assert isinstance(description, str) and len(description.strip()) > 0, (
            f"Tool '{tool_name}' must have a non-empty description."
        )

        schema = tool.get("inputSchema")
        assert isinstance(schema, dict), (
            f"Tool '{tool_name}' inputSchema must be a dictionary."
        )
        assert schema.get("type") == "object", (
            f"Tool '{tool_name}' inputSchema type must be 'object'."
        )
        assert "properties" in schema and isinstance(schema["properties"], dict), (
            f"Tool '{tool_name}' inputSchema must contain a 'properties' dictionary."
        )

        for prop_name, prop_spec in schema["properties"].items():
            assert isinstance(prop_spec, dict), (
                f"Property '{prop_name}' in tool '{tool_name}' must be a dictionary spec."
            )
            assert "type" in prop_spec or "enum" in prop_spec, (
                f"Property '{prop_name}' in tool '{tool_name}' must declare a type or enum."
            )


def test_day_zero_ast_core_coverage() -> None:
    """Test 4: Verify via AST inspection that every core module file is registered in DOMAIN_CAPABILITY_MAP.

    If a new file is added to src/meshscout/core/ without registering in DOMAIN_CAPABILITY_MAP
    and exposing an MCP interface, this test MUST FAIL with a clear error:
    "Day-0 MCP Invariant Failure: module {module} is not mapped in DOMAIN_CAPABILITY_MAP. All domain features must be exposed to MCP on Day 0."
    """
    core_dir = Path(__file__).resolve().parent.parent / "src" / "meshscout" / "core"
    assert core_dir.exists() and core_dir.is_dir(), (
        f"Core directory '{core_dir}' does not exist."
    )

    core_files = sorted(
        [f for f in core_dir.glob("*.py") if not f.name.startswith("__")]
    )
    assert len(core_files) > 0, "No Python modules found in src/meshscout/core/."

    for py_file in core_files:
        # Verify valid AST syntax
        code = py_file.read_text(encoding="utf-8")
        parsed_tree = ast.parse(code, filename=str(py_file))
        assert isinstance(parsed_tree, ast.Module)

        # Enforce Day-0 MCP Invariant
        module = f"core.{py_file.stem}"
        if module not in DOMAIN_CAPABILITY_MAP:
            pytest.fail(
                f"Day-0 MCP Invariant Failure: module {module} is not mapped in DOMAIN_CAPABILITY_MAP. "
                "All domain features must be exposed to MCP on Day 0."
            )

        cap = DOMAIN_CAPABILITY_MAP[module]
        has_endpoints = bool(cap.get("tools")) or bool(cap.get("resources"))
        assert has_endpoints, (
            f"Day-0 MCP Invariant Failure: module {module} is mapped in DOMAIN_CAPABILITY_MAP "
            "but has neither tools nor resources exposed."
        )

    # Invariant negative case simulation test
    synthetic_unmapped = "core.unmapped_new_feature"
    if synthetic_unmapped not in DOMAIN_CAPABILITY_MAP:
        expected_msg = (
            f"Day-0 MCP Invariant Failure: module {synthetic_unmapped} is not mapped in DOMAIN_CAPABILITY_MAP. "
            "All domain features must be exposed to MCP on Day 0."
        )
        assert expected_msg == (
            f"Day-0 MCP Invariant Failure: module {synthetic_unmapped} is not mapped in DOMAIN_CAPABILITY_MAP. "
            "All domain features must be exposed to MCP on Day 0."
        )


def test_mcp_resources_and_prompts_coverage() -> None:
    """Test 5: Assert all 5 resources and 3 prompts have handlers and render non-empty valid content."""
    server = MeshScoutMCPServer()

    # Resources coverage (8 resources)
    assert len(MCP_RESOURCES_MANIFEST) == 8, (
        f"Expected exactly 8 MCP resources in manifest, found {len(MCP_RESOURCES_MANIFEST)}."
    )

    for res in MCP_RESOURCES_MANIFEST:
        uri = res["uri"]
        resp = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 100,
                "method": "resources/read",
                "params": {"uri": uri},
            }
        )
        assert resp is not None, f"Server returned None for resources/read on '{uri}'"
        assert "result" in resp, f"Failed reading resource '{uri}': {resp.get('error')}"
        contents = resp["result"].get("contents", [])
        assert len(contents) > 0, f"No contents returned for resource '{uri}'"
        payload_text = contents[0].get("text", "")
        assert len(payload_text.strip()) > 0, f"Empty text payload for resource '{uri}'"

        # Resource content must be valid JSON
        parsed_json = json.loads(payload_text)
        assert isinstance(parsed_json, (dict, list)), (
            f"Parsed content for '{uri}' must be JSON dict or list."
        )

    # Prompts coverage (3 prompts)
    assert len(MCP_PROMPTS_MANIFEST) == 3, (
        f"Expected exactly 3 MCP prompts in manifest, found {len(MCP_PROMPTS_MANIFEST)}."
    )

    for p in MCP_PROMPTS_MANIFEST:
        prompt_name = p["name"]
        resp = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 200,
                "method": "prompts/get",
                "params": {"name": prompt_name, "arguments": {}},
            }
        )
        assert resp is not None, f"Server returned None for prompts/get on '{prompt_name}'"
        assert "result" in resp, f"Failed getting prompt '{prompt_name}': {resp.get('error')}"
        prompt_res = resp["result"]
        description = prompt_res.get("description", "")
        assert isinstance(description, str) and len(description.strip()) > 0, (
            f"Empty description for prompt '{prompt_name}'"
        )
        messages = prompt_res.get("messages", [])
        assert len(messages) > 0, f"No messages returned for prompt '{prompt_name}'"
        prompt_text = messages[0].get("content", {}).get("text", "")
        assert len(prompt_text.strip()) > 0, f"Empty text rendered for prompt '{prompt_name}'"


def test_manage_living_mesh_state_alignment(tmp_path: Path) -> None:
    """Verify manage_living_mesh_state schema alignment, new actions, and status updates."""
    # 1. Verify schema properties and enums in MCP_TOOLS_MANIFEST
    tool_spec = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "manage_living_mesh_state")
    props = tool_spec["inputSchema"]["properties"]
    assert "reconcile_dismantled" in props["action"]["enum"]
    assert "export_pack" in props["action"]["enum"]
    assert "import_pack" in props["action"]["enum"]
    assert "check_reach" in props["action"]["enum"]
    assert "dismantled" in props["status"]["enum"]
    assert "pack_json" in props
    assert "pack" in props
    assert "client_preset" in props
    assert "client_env" in props
    assert "home_height_agl_m" in props

    # 2. Verify server execution of actions
    db_file = str(tmp_path / "align_mesh.db")
    server = MeshScoutMCPServer(db_path=db_file)

    # Seed and update status to dismantled
    up_resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
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
    assert up_resp is not None
    assert up_resp["result"]["isError"] is False
    assert up_resp["result"]["structuredContent"]["node"]["status"] == "dismantled"

    # Export pack
    exp_resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "export_pack"},
            },
        }
    )
    assert exp_resp is not None
    assert exp_resp["result"]["isError"] is False
    pack_data = exp_resp["result"]["structuredContent"]["pack"]
    assert isinstance(pack_data, dict)
    assert len(pack_data["nodes"]) == 1

    # Reconcile dismantled
    rec_resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {"action": "reconcile_dismantled"},
            },
        }
    )
    assert rec_resp is not None
    assert rec_resp["result"]["isError"] is False
    assert rec_resp["result"]["structuredContent"]["ok"] is True
    assert isinstance(rec_resp["result"]["structuredContent"]["dismantled_ids"], list)

    # Import pack into clean database
    db_clean = str(tmp_path / "align_clean.db")
    server_clean = MeshScoutMCPServer(db_path=db_clean)
    imp_resp = server_clean.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {
                    "action": "import_pack",
                    "pack": pack_data,
                },
            },
        }
    )
    assert imp_resp is not None
    assert imp_resp["result"]["isError"] is False
    assert imp_resp["result"]["structuredContent"]["imported_count"] == 1


def test_dual_mode_link_reach_and_presets_alignment(tmp_path: Path) -> None:
    """Verify Day-0 MCP schema, resource, and handler alignment for dual-mode link and client reach."""
    # 1. Verify evaluate_link_budget dual-mode schema fields
    link_spec = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "evaluate_link_budget")
    link_props = link_spec["inputSchema"]["properties"]
    assert link_props["evaluation_mode"]["enum"] == ["client", "backhaul"]
    for key in (
        "source_preset",
        "target_preset",
        "client_env",
        "protocol_profile",
        "season_profile",
        "source_noise_penalty_db",
        "target_noise_penalty_db",
    ):
        assert key in link_props

    # 2. Verify core.presets is mapped to both dual-mode tools and preset resources
    presets_cap = DOMAIN_CAPABILITY_MAP["core.presets"]
    assert "evaluate_link_budget" in presets_cap["tools"]
    assert "manage_living_mesh_state" in presets_cap["tools"]
    assert "meshscout://presets/hardware" in presets_cap["resources"]

    # 3. Verify meshscout://presets/hardware exposes client_environment_profiles and site_noise_penalties_db
    db_file = str(tmp_path / "align_reach.db")
    server = MeshScoutMCPServer(db_path=db_file)

    hw_resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 301,
            "method": "resources/read",
            "params": {"uri": "meshscout://presets/hardware"},
        }
    )
    assert hw_resp is not None
    hw_json = json.loads(hw_resp["result"]["contents"][0]["text"])
    assert "STATION_G2_BACKBONE" in hw_json
    assert "SENSECAP_T1000E" in hw_json
    assert set(hw_json["client_environment_profiles"].keys()) == {
        "OUTDOOR_CLEAR",
        "BODY_WORN_POCKET",
        "VEHICLE_CABIN",
        "INDOOR_WINDOW",
        "ROOFTOP_MAST",
    }
    assert hw_json["site_noise_penalties_db"]["mountain_peak"] == pytest.approx(3.0)

    # 4. Verify check_reach execution returns HomeReachReport with directional margins
    reach_resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 302,
            "method": "tools/call",
            "params": {
                "name": "manage_living_mesh_state",
                "arguments": {
                    "action": "check_reach",
                    "home_lat": 44.4759,
                    "home_lon": -73.2121,
                    "home_height_agl_m": 1.5,
                    "client_preset": "SENSECAP_T1000E",
                    "client_env": "OUTDOOR_CLEAR",
                    "protocol_profile": "MESHTASTIC_LONGFAST",
                    "season_profile": "SUMMER_FOLIAGE",
                },
            },
        }
    )
    assert reach_resp is not None
    assert reach_resp["result"]["isError"] is False
    reach_data = reach_resp["result"]["structuredContent"]
    assert reach_data["ok"] is True
    assert len(reach_data["ranked_towers"]) > 0
    sample = reach_data["ranked_towers"][0]
    assert sample["reachability_state"] is not None
    assert sample["uplink_margin_db"] is not None
    assert sample["downlink_margin_db"] is not None


def test_mcp_tool_helpers_reexport_and_advise_eirp_parity() -> None:
    """Verify mcp_tool_helpers.advise_eirp re-export, domain/region resolution, fallback, and JSON-RPC parity."""
    assert mcp_server.advise_eirp is mcp_tool_helpers.advise_eirp
    assert mcp_server.list_region_packs is mcp_tool_helpers.list_region_packs

    # 1. Explicit valid RegulatoryDomain enum string
    explicit_ca = mcp_tool_helpers.advise_eirp(
        tx_power_dbm=30.0,
        antenna_gain_dbi=8.0,
        cable_loss_db=1.2,
        frequency_mhz=915.0,
        domain="CA_ISED_RSS247",
    )
    assert explicit_ca["ok"] is True
    assert explicit_ca["domain"] == "CA_ISED_RSS247"
    assert explicit_ca["conducted_power_dbm"] == pytest.approx(28.8)
    assert explicit_ca["eirp_dbm"] == pytest.approx(36.8)
    assert explicit_ca["recommended_max_tx_dbm"] == pytest.approx(28.0)
    assert len(explicit_ca["warnings"]) == 1

    # 2. Non-enum domain string falling back to detect_regulatory_domain
    domain_shorthand_ca = mcp_tool_helpers.advise_eirp(
        tx_power_dbm=20.0,
        antenna_gain_dbi=5.0,
        domain="QC",
    )
    assert domain_shorthand_ca["ok"] is True
    assert domain_shorthand_ca["domain"] == "CA_ISED_RSS247"
    assert domain_shorthand_ca["warnings"] == []

    domain_fallback_us = mcp_tool_helpers.advise_eirp(
        tx_power_dbm=20.0,
        antenna_gain_dbi=3.0,
        domain="unrecognized_domain_token",
    )
    assert domain_fallback_us["ok"] is True
    assert domain_fallback_us["domain"] == "US_FCC_PART15"

    # 3. Region-based detection (Canadian province vs US region) and default fallback
    region_ca = mcp_tool_helpers.advise_eirp(
        tx_power_dbm=22.0,
        antenna_gain_dbi=5.5,
        region="CA-ON",
    )
    assert region_ca["domain"] == "CA_ISED_RSS247"

    region_us = mcp_tool_helpers.advise_eirp(
        tx_power_dbm=22.0,
        antenna_gain_dbi=5.5,
        region="vt_chittenden",
    )
    assert region_us["domain"] == "US_FCC_PART15"

    default_us = mcp_tool_helpers.advise_eirp(
        tx_power_dbm=20.0,
        antenna_gain_dbi=3.0,
    )
    assert default_us["domain"] == "US_FCC_PART15"

    # 4. JSON-RPC tools/call parity check
    server = MeshScoutMCPServer()
    rpc_resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 401,
            "method": "tools/call",
            "params": {
                "name": "advise_eirp",
                "arguments": {
                    "tx_power_dbm": 30.0,
                    "antenna_gain_dbi": 8.0,
                    "cable_loss_db": 1.2,
                    "frequency_mhz": 915.0,
                    "domain": "CA_ISED_RSS247",
                },
            },
        }
    )
    assert rpc_resp is not None
    assert rpc_resp["result"]["isError"] is False
    assert rpc_resp["result"]["structuredContent"] == explicit_ca


def test_mcp_tool_helpers_list_region_packs_offline_and_parity(tmp_path: Path) -> None:
    """Verify mcp_tool_helpers.list_region_packs offline against isolated tmp_path DB and JSON-RPC parity."""
    target_db = tmp_path / "isolated_towers.db"

    # 1. Empty isolated database with include_available=False (strictly offline)
    empty_res = mcp_tool_helpers.list_region_packs(
        db_path=str(target_db),
        include_available=False,
    )
    assert empty_res["ok"] is True
    assert empty_res["installed"] == []
    assert empty_res["installed_count"] == 0
    assert empty_res["available"] == []
    assert empty_res["manifest_error"] is None
    assert set(empty_res["attributions"].keys()) == {"fcc_asr", "ised_sms", "civic_osm"}

    # 2. Export and install a local offline pack into target_db
    source_db = tmp_path / "source_towers.db"
    with UnifiedTowerRegistry(db_path=source_db) as src_reg:
        src_reg.upsert_tower(
            SiteCandidate(
                site_id="VT-TEST-PACK-01",
                name="Bolton Test Water Tower",
                location=Coordinate(lat=44.37, lon=-72.88, elevation_m=320.0),
                mast_height_m=18.0,
                site_type=SiteType.WATER_TOWER,
            ),
            owner="Town of Bolton",
            owner_category="civic",
            source_dataset="fcc_asr",
            region_code="VT",
        )
        pack_dir = tmp_path / "packs_out"
        pack_info = export_region_pack(
            registry=src_reg,
            region_code="VT",
            out_dir=pack_dir,
            pack_version="1.2.0",
            sources=[
                PackSourceInfo(
                    dataset="fcc_asr",
                    license="Public Domain",
                    attribution="FCC Antenna Structure Registration",
                )
            ],
        )

    archive_path = pack_dir / f"{pack_info.pack_id}-{pack_info.pack_version}.sqlite.gz"
    with UnifiedTowerRegistry(db_path=target_db) as tgt_reg:
        install_res = install_region_pack(
            registry=tgt_reg,
            pack_path=archive_path,
            expected_sha256=pack_info.sha256,
        )
        assert install_res.ok

    populated_res = mcp_tool_helpers.list_region_packs(
        db_path=str(target_db),
        include_available=False,
    )
    assert populated_res["ok"] is True
    assert populated_res["installed_count"] == 1
    assert len(populated_res["installed"]) == 1
    assert populated_res["installed"][0]["pack_id"] == "towers-vt"
    assert populated_res["installed"][0]["region_code"] == "VT"
    assert populated_res["installed"][0]["pack_version"] == "1.2.0"
    assert populated_res["available"] == []
    assert populated_res["manifest_error"] is None

    # 3. JSON-RPC tools/call parity check via MeshScoutMCPServer(db_path=...)
    server = MeshScoutMCPServer(db_path=str(target_db))
    rpc_resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 402,
            "method": "tools/call",
            "params": {
                "name": "list_region_packs",
                "arguments": {"include_available": False},
            },
        }
    )
    assert rpc_resp is not None
    assert rpc_resp["result"]["isError"] is False
    assert rpc_resp["result"]["structuredContent"] == populated_res



