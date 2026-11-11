"""Unit and integration tests for Landowner Pitch Sheet REST API endpoints.

Tests GET /api/reports/landowner/{site_id} and POST /api/reports/landowner
against bundled fixtures, living registry nodes, and custom ad-hoc site candidates.
"""

from __future__ import annotations

from pathlib import Path
import pytest
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
