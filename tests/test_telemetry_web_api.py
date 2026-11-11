"""Unit and integration tests for Telemetry Web Workbench API (TASK-1100).

Tests live telemetry nodes querying, protocol filtering, spatial bounding box filtering,
cross-border regional buffering (e.g. Plattsburgh NY and Mont Sutton QC within VT 20km buffer),
and packet stream ingestion for Meshtastic MQTT and Reticulum / MeshCore announcements.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from meshscout.web.app import create_web_app


@pytest.fixture()
def client(tmp_path: Path):
    """Provide a FastAPI TestClient configured with isolated SQLite cache pre-seeded with sample fixture."""
    db_path = tmp_path / "test_mesh_state.db"
    tower_db = tmp_path / "test_towers.db"
    telem_db = tmp_path / "test_telemetry.db"
    app = create_web_app(
        db_path=db_path,
        tower_db_path=tower_db,
        telemetry_db_path=telem_db,
    )
    with TestClient(app) as c:
        yield c


def test_get_telemetry_nodes_default_vt_buffered(client: TestClient) -> None:
    """Verify default query returns VT nodes buffered by 20km including cross-border nodes and both protocols."""
    resp = client.get("/api/telemetry/nodes")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    assert data["region"] == "VT"
    assert data["buffer_km"] == 20.0
    assert data["count"] > 0
    assert len(data["nodes"]) == data["count"]

    # Verify both protocols are represented
    protocols = {node["protocol"] for node in data["nodes"]}
    assert "meshtastic" in protocols
    assert "meshcore" in protocols

    # Verify protocol aggregation counts match
    counts_by_proto = data.get("counts_by_protocol", {})
    assert counts_by_proto.get("meshtastic", 0) > 0
    assert counts_by_proto.get("meshcore", 0) > 0
    assert sum(counts_by_proto.values()) == data["count"]

    # Verify cross-border nodes within 20km of VT border are returned
    short_names = {node["short_name"] for node in data["nodes"]}
    assert "PLAT-1" in short_names  # Plattsburgh, NY (across Lake Champlain within 20km buffer)
    assert "SUTT-1" in short_names  # Mont Sutton, QC (near Canadian border within 20km buffer)


def test_get_telemetry_nodes_filtered_meshtastic(client: TestClient) -> None:
    """Verify filtering by protocol=meshtastic returns only Meshtastic telemetry nodes."""
    resp = client.get("/api/telemetry/nodes?protocol=meshtastic")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    assert data["count"] > 0
    for node in data["nodes"]:
        assert node["protocol"] == "meshtastic"


def test_get_telemetry_nodes_filtered_meshcore(client: TestClient) -> None:
    """Verify filtering by protocol=meshcore returns only MeshCore / Reticulum telemetry nodes."""
    resp = client.get("/api/telemetry/nodes?protocol=meshcore")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    assert data["count"] > 0
    for node in data["nodes"]:
        assert node["protocol"] == "meshcore"


def test_get_telemetry_nodes_region_quebec(client: TestClient) -> None:
    """Verify querying region=CA_QC returns Canadian Quebec nodes."""
    resp = client.get("/api/telemetry/nodes?region=CA_QC")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    assert data["region"] == "CA_QC"
    assert data["count"] > 0

    short_names = {node["short_name"] for node in data["nodes"]}
    # Quebec fixture nodes
    assert any(name in short_names for name in ("MTLR-1", "SUTT-1", "SHER-1", "SJSR-1", "RNS-MTLR"))


def test_get_telemetry_nodes_spatial_bounding_box(client: TestClient) -> None:
    """Verify spatial bounding box filtering returns nodes strictly within coordinates."""
    # Burlington / Chittenden County bounding box
    min_lat, max_lat = 44.40, 44.60
    min_lon, max_lon = -73.30, -73.05

    resp = client.get(
        f"/api/telemetry/nodes?min_lat={min_lat}&max_lat={max_lat}&min_lon={min_lon}&max_lon={max_lon}"
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    assert data["count"] > 0
    for node in data["nodes"]:
        c = node["coordinate"]
        assert min_lat <= c["lat"] <= max_lat
        assert min_lon <= c["lon"] <= max_lon


def test_post_telemetry_ingest_meshtastic(client: TestClient) -> None:
    """Verify POST /api/telemetry/ingest correctly ingests Meshtastic MQTT JSON packets."""
    payload = {
        "raw_data": json.dumps([
            {
                "from_node_id": "!feedbeef01",
                "sender_short_name": "ING-1",
                "sender_long_name": "Ingested Meshtastic Test Node",
                "latitude": 44.4759,
                "longitude": -73.2121,
                "altitude": 105.0,
                "rssi": -82.0,
                "snr": 9.5,
                "channel": "LongFast",
            }
        ]),
        "protocol": "meshtastic",
        "apply_fuzz": False,
    }

    resp = client.post("/api/telemetry/ingest", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["ingested_count"] == 1

    # Verify node is queryable
    nodes_resp = client.get("/api/telemetry/nodes?protocol=meshtastic")
    assert nodes_resp.status_code == 200
    nodes_data = nodes_resp.json()
    node_ids = {n["node_id"] for n in nodes_data["nodes"]}
    assert "!feedbeef01" in node_ids


def test_post_telemetry_ingest_meshcore(client: TestClient) -> None:
    """Verify POST /api/telemetry/ingest correctly ingests Reticulum / MeshCore announcements."""
    payload = {
        "raw_data": json.dumps({
            "destination_hash": "deadbeefcafe00112233445566778899",
            "name": "RNS-TEST-NODE",
            "coordinate": {"lat": 44.481, "lon": -73.215, "elevation_m": 130.0},
            "hops": 2,
            "snr_db": 11.0,
            "rssi_dbm": -75.0,
        }),
        "protocol": "meshcore",
        "apply_fuzz": False,
    }

    resp = client.post("/api/telemetry/ingest", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["ingested_count"] == 1

    # Verify node is queryable
    nodes_resp = client.get("/api/telemetry/nodes?protocol=meshcore")
    assert nodes_resp.status_code == 200
    nodes_data = nodes_resp.json()
    node_ids = {n["node_id"] for n in nodes_data["nodes"]}
    assert "mcore:deadbeefcafe0011" in node_ids


def test_post_telemetry_ingest_invalid_protocol(client: TestClient) -> None:
    """Verify POST /api/telemetry/ingest rejects unknown protocols with 400 Bad Request."""
    payload = {
        "raw_data": "{}",
        "protocol": "lorawan",
        "apply_fuzz": True,
    }
    resp = client.post("/api/telemetry/ingest", json=payload)
    assert resp.status_code == 400
    assert "Unsupported protocol" in resp.json()["detail"]


def test_post_telemetry_ingest_invalid_meshtastic_payload(client: TestClient) -> None:
    """Verify POST /api/telemetry/ingest rejects malformed meshtastic payload with 400 Bad Request."""
    payload = {
        "raw_data": "{invalid json: true}",
        "protocol": "meshtastic",
        "apply_fuzz": True,
    }
    resp = client.post("/api/telemetry/ingest", json=payload)
    assert resp.status_code == 400
