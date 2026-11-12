"""Unit and integration tests for Landowner Pitch Sheet REST API endpoints.

Tests GET /api/reports/landowner/{site_id} and POST /api/reports/landowner
against bundled fixtures, living registry nodes, and custom ad-hoc site candidates.
"""

from __future__ import annotations

from pathlib import Path
import warnings
import pytest

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*BlockingPortal.*", category=DeprecationWarning)
    from fastapi.testclient import TestClient

from meshscout.web.app import create_web_app


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated temporary SQLite database path per test."""
    return tmp_path / "test_reporting_mesh_state.db"


@pytest.fixture()
def client(temp_db_path: Path) -> TestClient:
    """Create a FastAPI TestClient backed by an isolated SQLite database."""
    app = create_web_app(db_path=temp_db_path)
    return TestClient(app)


def test_get_landowner_report_json(client: TestClient) -> None:
    """Test GET /api/reports/landowner/VT-CHIT-MANS-01 returns 200 with HTML string and expected specs."""
    resp = client.get("/api/reports/landowner/VT-CHIT-MANS-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["site_id"] == "VT-CHIT-MANS-01"
    assert "Mount Mansfield" in data["site_name"]

    html_content = data["html"]
    assert isinstance(html_content, str)
    assert "<!DOCTYPE html>" in html_content
    # Site name presence
    assert "Mount Mansfield" in html_content
    # RF safety statement and RF cleanliness specs
    assert "RF" in html_content
    assert "FCC Part 15" in html_content
    assert "1 Watt" in html_content
    assert "RF Cleanliness" in html_content
    # Zero grid power specs
    assert "Zero Grid Power" in html_content


def test_get_landowner_report_html_format(client: TestClient) -> None:
    """Test GET /api/reports/landowner/VT-CHIT-MANS-01?format=html returns 200 with text/html content type."""
    resp = client.get("/api/reports/landowner/VT-CHIT-MANS-01?format=html")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/html")
    body = resp.text
    assert "<!DOCTYPE html>" in body
    assert "Mount Mansfield" in body
    assert "Zero Grid Power" in body


def test_get_landowner_report_not_found(client: TestClient) -> None:
    """Test GET /api/reports/landowner/NONEXISTENT returns 404 with error payload."""
    resp = client.get("/api/reports/landowner/NONEXISTENT")
    assert resp.status_code == 404
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "Site not found"


def test_post_landowner_report_custom_candidate(client: TestClient) -> None:
    """Test POST /api/reports/landowner with custom ad-hoc candidate data returns 200 and valid HTML brief."""
    payload = {
        "name": "Underhill Hilltop Barn",
        "lat": 44.5200,
        "lon": -72.9500,
        "elevation_m": 280.0,
        "mast_height_m": 12.0,
        "site_type": "custom",
        "contact_org": "Green Mountain Mesh Collective",
    }
    resp = client.post("/api/reports/landowner", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["site_name"] == "Underhill Hilltop Barn"
    assert "CUSTOM-" in data["site_id"]

    html_content = data["html"]
    assert "<!DOCTYPE html>" in html_content
    assert "Underhill Hilltop Barn" in html_content
    assert "Green Mountain Mesh Collective" in html_content
    assert "Zero Grid Power" in html_content
    assert "FCC Part 15" in html_content


def test_post_landowner_report_validation_error(client: TestClient) -> None:
    """Test POST /api/reports/landowner with invalid coordinates returns 422 Unprocessable Entity."""
    invalid_payload = {
        "name": "Invalid Site",
        "lat": 95.0,  # ge=-90.0, le=90.0 constraint
        "lon": -72.9500,
    }
    resp = client.post("/api/reports/landowner", json=invalid_payload)
    assert resp.status_code == 422


def test_portable_workbench_html_with_client_reach_fields(client: TestClient) -> None:
    """Verify portable HTML snapshot renders cleanly in both legacy symmetric and asymmetric client reach modes."""
    from meshscout.core.registry import WorkspacePreferences
    from meshscout.web.app import _fallback_portable_workbench_html

    # 1. HTTP endpoint in legacy symmetric mode
    sym_resp = client.get("/api/export/html")
    assert sym_resp.status_code == 200
    assert "text/html" in sym_resp.headers.get("content-type", "")
    assert "M E S H S C O U T // Portable Club Snapshot" in sym_resp.text

    # 2. HTTP endpoint with asymmetric client reach query parameters
    asym_resp = client.get("/api/export/html?client_preset=SENSECAP_T1000E&client_env=INDOOR_WINDOW")
    assert asym_resp.status_code == 200
    assert "DL " in asym_resp.text
    assert "UL " in asym_resp.text

    # 3. Direct fallback helper with explicit hear_only_alligator tower reach item
    prefs = WorkspacePreferences()
    html_snapshot = _fallback_portable_workbench_html(
        prefs=prefs,
        sites=[
            {
                "site_id": "VT-PEAK-01",
                "name": "Mount Mansfield",
                "site_type": "mountain_peak",
                "status": "active_on_air",
                "elevation_m": 1339.0,
                "composite_score": 88.5,
                "desense_risk": "moderate",
                "notes": "Summit repeater",
            }
        ],
        home_report={
            "best_azimuth_deg": 72.4,
            "best_cardinal_direction": "ENE",
            "ranked_towers": [
                {
                    "recommended_rank": 1,
                    "site_id": "VT-PEAK-01",
                    "name": "Mount Mansfield",
                    "azimuth_deg": 72.4,
                    "cardinal_direction": "ENE",
                    "distance_km": 24.8,
                    "rx_power_dbm": -121.5,
                    "link_margin_db": -3.2,
                    "downlink_margin_db": 7.8,
                    "uplink_margin_db": -3.2,
                    "reachability_state": "hear_only_alligator",
                    "has_line_of_sight": True,
                }
            ],
        },
    )
    assert "<!DOCTYPE html>" in html_snapshot
    assert "DL 7.8 / UL -3.2" in html_snapshot
    assert "[HEAR_ONLY_ALLIGATOR]" in html_snapshot
