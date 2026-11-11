"""Integration and unit tests for Multi-Hop Corridor Evaluation REST API endpoint.

Tests POST /api/backhaul/corridor against LivingMeshRegistry, bundled fixtures,
and inline custom sites.
"""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from meshscout.web.app import create_web_app


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated temporary SQLite database path per test."""
    return tmp_path / "test_corridor_mesh_state.db"


@pytest.fixture()
def client(temp_db_path: Path) -> TestClient:
    """Create a FastAPI TestClient backed by an isolated SQLite database."""
    app = create_web_app(db_path=temp_db_path)
    return TestClient(app)


def test_corridor_empty_site_ids(client: TestClient) -> None:
    """Test POST /api/backhaul/corridor with empty site_ids returns 200 and 0 hops."""
    resp = client.post(
        "/api/backhaul/corridor",
        json={"site_ids": []},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 0
    corridor = data["corridor"]
    assert corridor["total_hops"] == 0
    assert corridor["hops"] == []
    assert corridor["total_distance_km"] == 0.0
    assert corridor["all_clear_los"] is True
    assert corridor["bottleneck_hop_index"] is None


def test_corridor_two_valid_sites(client: TestClient) -> None:
    """Test POST /api/backhaul/corridor with 2 valid site IDs returns status 200, 1 hop, clear LOS."""
    resp = client.post(
        "/api/backhaul/corridor",
        json={"site_ids": ["VT-CHIT-MANS-01", "VT-CHIT-BOLT-01"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2
    corridor = data["corridor"]
    assert corridor["total_hops"] == 1
    assert corridor["all_clear_los"] is True
    assert corridor["total_distance_km"] > 0
    assert len(corridor["hops"]) == 1

    hop = corridor["hops"][0]
    assert hop["hop_index"] == 0
    assert hop["origin_site_id"] == "VT-CHIT-MANS-01"
    assert hop["target_site_id"] == "VT-CHIT-BOLT-01"
    assert hop["has_line_of_sight"] is True
    assert hop["link_margin_db"] is not None
    assert hop["distance_km"] > 0.0


def test_corridor_three_sites(client: TestClient) -> None:
    """Test POST /api/backhaul/corridor with 3 site IDs returns status 200, 2 hops, distance > 0, bottleneck."""
    resp = client.post(
        "/api/backhaul/corridor",
        json={"site_ids": ["VT-CHIT-MANS-01", "VT-CHIT-BOLT-01", "VT-CHIT-UVM-PMRC"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 3
    corridor = data["corridor"]
    assert corridor["total_hops"] == 2
    assert corridor["total_distance_km"] > 0
    assert corridor["bottleneck_hop_index"] is not None
    assert 0 <= corridor["bottleneck_hop_index"] < 2
    assert len(corridor["hops"]) == 2
    assert corridor["worst_link_margin_db"] is not None


def test_corridor_custom_sites_inline(client: TestClient) -> None:
    """Test POST /api/backhaul/corridor with custom inline SiteCandidate objects in custom_sites."""
    custom_a = {
        "site_id": "CUSTOM-ALPHA",
        "name": "Custom Alpha Summit",
        "location": {
            "lat": 44.5437,
            "lon": -72.8143,
            "elevation_m": 1339.0,
        },
        "mast_height_m": 12.0,
        "has_grid_power": False,
        "solar_exposure_pct": 95.0,
    }
    custom_b = {
        "site_id": "CUSTOM-BETA",
        "name": "Custom Beta Ridge",
        "location": {
            "lat": 44.4200,
            "lon": -72.8600,
            "elevation_m": 950.0,
        },
        "mast_height_m": 10.0,
        "has_grid_power": True,
        "solar_exposure_pct": 80.0,
    }

    # Evaluate with purely custom sites in custom_sites list
    resp = client.post(
        "/api/backhaul/corridor",
        json={
            "custom_sites": [custom_a, custom_b],
            "frequency_mhz": 915.0,
            "tx_power_dbm": 22.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2
    corridor = data["corridor"]
    assert corridor["total_hops"] == 1
    assert corridor["hops"][0]["origin_site_id"] == "CUSTOM-ALPHA"
    assert corridor["hops"][0]["target_site_id"] == "CUSTOM-BETA"
    assert corridor["total_distance_km"] > 0.0


def test_corridor_mixed_registry_and_custom_sites(client: TestClient) -> None:
    """Test POST /api/backhaul/corridor combining existing fixture/registry sites with custom sites."""
    custom_node = {
        "site_id": "CUSTOM-RELAY-1",
        "name": "Custom Relay Node",
        "location": {
            "lat": 44.4759,
            "lon": -73.2200,
            "elevation_m": 100.0,
        },
        "mast_height_m": 15.0,
    }
    resp = client.post(
        "/api/backhaul/corridor",
        json={
            "site_ids": ["VT-CHIT-MANS-01", "CUSTOM-RELAY-1"],
            "custom_sites": [custom_node],
            "frequency_mhz": 433.0,
            "tx_power_dbm": 17.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2
    corridor = data["corridor"]
    assert corridor["total_hops"] == 1
    assert corridor["hops"][0]["origin_site_id"] == "VT-CHIT-MANS-01"
    assert corridor["hops"][0]["target_site_id"] == "CUSTOM-RELAY-1"
