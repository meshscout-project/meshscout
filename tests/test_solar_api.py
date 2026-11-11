"""Unit and integration tests for Solar Autonomy and Winter Survival API endpoints.

Tests:
- POST /api/solar/simulate (standard LiFePO4 parameters, LTO winter survival)
- GET /api/solar/site/{site_id} (VT-CHIT-MANS-01 side-by-side comparison, 404 for unknown site)
"""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from meshscout.web.app import create_web_app


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated temporary SQLite database path per test."""
    return tmp_path / "test_solar_mesh_state.db"


@pytest.fixture()
def client(temp_db_path: Path) -> TestClient:
    """Create a FastAPI TestClient backed by an isolated SQLite database."""
    app = create_web_app(db_path=temp_db_path)
    return TestClient(app)


def test_post_solar_simulate_lifepo4_standard(client: TestClient) -> None:
    """Test POST /api/solar/simulate with standard LiFePO4 parameters returns 200, valid report, and recommended panel watts > 0."""
    payload = {
        "lat": 44.5437,
        "lon": -72.8143,
        "elevation_m": 1339.0,
        "battery_chemistry": "lifepo4",
        "panel_watts": 10.0,
        "battery_capacity_wh": 50.0,
        "daily_consumption_wh": 19.2,
        "panel_tilt_deg": 60.0,
        "consecutive_cloudy_days": 5,
        "simulation_days": 30,
    }
    resp = client.post("/api/solar/simulate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "report" in data
    report = data["report"]
    assert report["simulation_days"] == 30
    assert report["recommended_panel_watts"] > 0
    assert report["recommended_battery_wh"] > 0
    assert isinstance(report["survived_winter_streak"], bool)
    assert len(report["daily_timeline"]) == 30


def test_post_solar_simulate_lto_survived_winter(client: TestClient) -> None:
    """Test POST /api/solar/simulate with LTO battery returns 200 and survived_winter_streak True."""
    payload = {
        "lat": 44.5437,
        "lon": -72.8143,
        "elevation_m": 1339.0,
        "battery_chemistry": "lto",
        "panel_watts": 20.0,
        "battery_capacity_wh": 150.0,
        "daily_consumption_wh": 19.2,
        "panel_tilt_deg": 60.0,
        "consecutive_cloudy_days": 5,
        "simulation_days": 30,
    }
    resp = client.post("/api/solar/simulate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "report" in data
    report = data["report"]
    assert report["survived_winter_streak"] is True
    assert report["brownout_hours"] == 0.0


def test_get_solar_site_mansfield_side_by_side(client: TestClient) -> None:
    """Test GET /api/solar/site/VT-CHIT-MANS-01 returns 200 with side-by-side lifepo4 and lto reports."""
    resp = client.get("/api/solar/site/VT-CHIT-MANS-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["site_id"] == "VT-CHIT-MANS-01"
    assert "Mount Mansfield" in data["site_name"]

    assert "lifepo4" in data
    assert "lto" in data

    lifepo4_rep = data["lifepo4"]
    lto_rep = data["lto"]

    # Recommended panel watts and battery Wh
    assert lifepo4_rep["recommended_panel_watts"] > 0
    assert lto_rep["recommended_panel_watts"] > 0
    assert lifepo4_rep["recommended_battery_wh"] > 0
    assert lto_rep["recommended_battery_wh"] > 0

    # Sub-zero survival verdicts
    assert isinstance(lifepo4_rep["survived_winter_streak"], bool)
    assert isinstance(lto_rep["survived_winter_streak"], bool)


def test_get_solar_site_nonexistent_returns_404(client: TestClient) -> None:
    """Test GET /api/solar/site/NONEXISTENT returns 404."""
    resp = client.get("/api/solar/site/NONEXISTENT")
    assert resp.status_code == 404
