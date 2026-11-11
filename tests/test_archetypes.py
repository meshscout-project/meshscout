"""Unit and integration tests for MeshScout site archetypes and MCP guardrails."""
from __future__ import annotations

import json
from fastapi.testclient import TestClient

from meshscout.core.archetypes import (
    COMMUNITY_SITE_ARCHETYPES,
    ProtocolRoleMapping,
    SiteArchetype,
    SiteArchetypeSpec,
    SplitHorizonStrategy,
    classify_site_archetype,
    get_archetype_recommendation,
)
from meshscout.core.contracts import Coordinate, SiteCandidate, SiteType
from meshscout.mcp_server import MeshScoutMCPServer
from meshscout.web.app import app


def test_archetype_catalog_completeness():
    """Verify all 5 canonical archetypes are populated with required specs and protocol mappings."""
    assert len(COMMUNITY_SITE_ARCHETYPES) == 5
    required_archetypes = {
        SiteArchetype.ALPINE_MEGA_SUMMIT,
        SiteArchetype.CIVIC_VALLEY_INFILL,
        SiteArchetype.MEMBER_ROOFTOP_BASE,
        SiteArchetype.VEHICULAR_MOBILE,
        SiteArchetype.HANDHELD_CLIENT,
    }
    assert set(COMMUNITY_SITE_ARCHETYPES.keys()) == required_archetypes

    required_protocols = {"Meshtastic", "MeshCore", "Reticulum", "GenericLoRa"}
    for arch, spec in COMMUNITY_SITE_ARCHETYPES.items():
        assert isinstance(spec, SiteArchetypeSpec)
        assert spec.label
        assert spec.description
        assert set(spec.protocol_mappings.keys()) == required_protocols
        for proto, mapping in spec.protocol_mappings.items():
            assert isinstance(mapping, ProtocolRoleMapping)
            assert mapping.protocol_family == proto
            assert mapping.role_name
            assert isinstance(mapping.split_horizon_strategy, SplitHorizonStrategy)
            assert mapping.cli_command_template


def test_site_classification():
    """Verify classification logic across mountain peaks, civic infrastructure, and rooftops."""
    # Alpine summit: Mountain peak
    mansfield = SiteCandidate(
        site_id="VT-CHI-01",
        name="Mount Mansfield",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=15.0,
    )
    assert classify_site_archetype(mansfield) == SiteArchetype.ALPINE_MEGA_SUMMIT

    # Alpine summit: High elevation tower
    killington = SiteCandidate(
        site_id="VT-RUT-01",
        name="Killington Peak",
        location=Coordinate(lat=43.6045, lon=-72.8203, elevation_m=1289.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=20.0,
    )
    assert classify_site_archetype(killington) == SiteArchetype.ALPINE_MEGA_SUMMIT

    # Civic Valley Infill: Water Tower
    water_tank = SiteCandidate(
        site_id="VT-WAS-01",
        name="Montpelier High Tank",
        location=Coordinate(lat=44.2601, lon=-72.5754, elevation_m=260.0),
        site_type=SiteType.WATER_TOWER,
        mast_height_m=25.0,
    )
    assert classify_site_archetype(water_tank) == SiteArchetype.CIVIC_VALLEY_INFILL

    # Civic Valley Infill: Silo or Comm Tower with tall mast
    silo = SiteCandidate(
        site_id="VT-ADD-04",
        name="Middlebury Co-op Silo",
        location=Coordinate(lat=44.0153, lon=-73.1673, elevation_m=120.0),
        site_type=SiteType.SILO,
        mast_height_m=22.0,
    )
    assert classify_site_archetype(silo) == SiteArchetype.CIVIC_VALLEY_INFILL

    # Member Rooftop Base
    home = SiteCandidate(
        site_id="VT-HOME-01",
        name="Essex Junction Chimney",
        location=Coordinate(lat=44.4901, lon=-73.1102, elevation_m=105.0),
        site_type=SiteType.BUILDING_ROOFTOP,
        mast_height_m=5.0,
    )
    assert classify_site_archetype(home) == SiteArchetype.MEMBER_ROOFTOP_BASE


def test_get_archetype_recommendation():
    """Verify recommendation retrieval across protocol families."""
    rec_meshcore = get_archetype_recommendation(SiteArchetype.ALPINE_MEGA_SUMMIT, "MeshCore")
    assert rec_meshcore["selected_protocol"] == "MeshCore"
    assert "repeater" in rec_meshcore["role_mapping"]["role_name"]

    rec_reticulum = get_archetype_recommendation(SiteArchetype.ALPINE_MEGA_SUMMIT, "Reticulum")
    assert rec_reticulum["selected_protocol"] == "Reticulum"
    assert rec_reticulum["role_mapping"]["split_horizon_strategy"] == "native_layer3_routing"

    rec_meshtastic = get_archetype_recommendation(SiteArchetype.ALPINE_MEGA_SUMMIT, "Meshtastic")
    assert rec_meshtastic["selected_protocol"] == "Meshtastic"
    assert rec_meshtastic["role_mapping"]["split_horizon_strategy"] == "hardware_dual_radio"


def test_mcp_resource_site_architectures():
    """Verify MCP resource listing and reading for site-architectures."""
    server = MeshScoutMCPServer()
    list_res = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    uris = [r["uri"] for r in list_res["result"]["resources"]]
    assert "meshscout://presets/site-architectures" in uris

    read_res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "resources/read",
        "params": {"uri": "meshscout://presets/site-architectures"},
    })
    assert "result" in read_res
    text = read_res["result"]["contents"][0]["text"]
    data = json.loads(text)
    assert "alpine_mega_summit" in data
    assert "civic_valley_infill" in data
    assert len(data) == 5


def test_mcp_tool_backhaul_split_horizon_guardrail():
    """Verify recommend_backhaul_architecture enforces split-horizon and returns warnings for alpine summits."""
    server = MeshScoutMCPServer()
    res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "recommend_backhaul_architecture",
            "arguments": {
                "source_site_id": "VT-CHI-01",
                "target_site_id": "VT-RUT-01",
                "protocol_family": "Reticulum",
            },
        },
    })
    assert "result" in res
    data = json.loads(res["result"]["content"][0]["text"])
    rec = data["recommendation"]
    assert rec["split_horizon_required"] is True
    assert "dual_radio" in rec["community_validated_architecture"]
    assert "CRITICAL" in rec["anti_pattern_warning"]
    assert data["archetype_guidance"]["selected_protocol"] == "Reticulum"


def test_mcp_tool_advise_role_archetype():
    """Verify advise_node_role_and_airtime embeds archetype classification and warnings."""
    server = MeshScoutMCPServer()
    res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {
            "name": "advise_node_role_and_airtime",
            "arguments": {
                "site_id": "VT-CHI-01",
                "exposed_population": 40000,
                "protocol_family": "MeshCore",
            },
        },
    })
    assert "result" in res
    data = json.loads(res["result"]["content"][0]["text"])
    assert data["site_archetype"] == "alpine_mega_summit"
    assert "anti_pattern_warning" in data
    assert data["archetype_guidance"]["archetype"] == "alpine_mega_summit"


def test_fastapi_archetype_endpoints():
    """Verify FastAPI REST endpoints for archetypes and site evaluation."""
    client = TestClient(app)

    # 1. GET /api/v1/archetypes
    res = client.get("/api/v1/archetypes")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["archetypes"]) == 5
    assert "alpine_mega_summit" in data["archetypes"]

    # 2. GET /api/v1/archetypes/VT-CHI-01/evaluate
    res_eval = client.get("/api/v1/archetypes/VT-CHI-01/evaluate?protocol_family=MeshCore")
    assert res_eval.status_code == 200
    eval_data = res_eval.json()
    assert eval_data["ok"] is True
    assert eval_data["site_id"] == "VT-CHI-01"
    assert eval_data["archetype"] == "alpine_mega_summit"
    assert eval_data["is_mega_summit"] is True
    assert eval_data["split_horizon_required"] is True
    assert eval_data["anti_pattern_warning"] is not None
    assert eval_data["protocol_recommendation"]["selected_protocol"] == "MeshCore"

    # 3. GET /api/v1/archetypes/NON_EXISTENT_ID/evaluate -> 404
    res_404 = client.get("/api/v1/archetypes/NON_EXISTENT_ID/evaluate")
    assert res_404.status_code == 404
