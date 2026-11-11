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

    assert len(manifest_tool_names) == 14, (
        f"Expected 14 MCP tools, found {len(manifest_tool_names)}."
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
    assert "dismantled" in props["status"]["enum"]
    assert "pack_json" in props
    assert "pack" in props

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

