"""Unit and integration tests for MeshScout Community Hosted Mode and Coordinator Guard."""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from meshscout.web.app import create_web_app


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated SQLite database path per test."""
    return tmp_path / "test_hosted_mesh_state.db"


def test_hosted_mode_blocks_unauthenticated_mutations(temp_db_path: Path) -> None:
    """Verify hosted mode blocks unauthenticated topology mutation endpoints with HTTP 403."""
    app = create_web_app(
        db_path=temp_db_path,
        hosted_mode=True,
        club_token="correct-club-secret",
    )
    client = TestClient(app)

    # 1. POST /api/sites/status without auth
    resp = client.post(
        "/api/sites/status",
        json={"site_id": "VT-PEAK-01", "status": "active_on_air"},
    )
    assert resp.status_code == 403
    assert "coordinator authentication required" in resp.json()["detail"]

    # 1b. POST /api/sites/status with invalid token
    resp_bad = client.post(
        "/api/sites/status",
        json={"site_id": "VT-PEAK-01", "status": "active_on_air"},
        headers={"X-Club-Token": "wrong-token"},
    )
    assert resp_bad.status_code == 403

    # 2. POST /api/sites/custom without auth
    resp = client.post(
        "/api/sites/custom",
        json={
            "name": "Unauthorized Site",
            "lat": 44.5,
            "lon": -73.0,
            "mast_height_m": 10.0,
        },
    )
    assert resp.status_code == 403
    assert "coordinator authentication required" in resp.json()["detail"]

    # 3. POST /api/sites/propose without auth
    resp = client.post(
        "/api/sites/propose",
        json={
            "name": "Community Tower Proposal",
            "lat": 44.5,
            "lon": -73.0,
            "height_agl_m": 12.0,
            "site_type": "tower",
        },
    )
    assert resp.status_code == 403
    assert "coordinator authentication required" in resp.json()["detail"]

    # 4. POST /api/import/snapshot without auth
    resp = client.post(
        "/api/import/snapshot",
        json={"nodes": []},
    )
    assert resp.status_code == 403
    assert "coordinator authentication required" in resp.json()["detail"]


def test_hosted_mode_valid_token_allows_mutations(temp_db_path: Path) -> None:
    """Verify valid X-Club-Token and Bearer Authorization headers permit topology mutations."""
    club_token = "secret-coordinator-key-xyz"
    app = create_web_app(
        db_path=temp_db_path,
        hosted_mode=True,
        club_token=club_token,
    )
    client = TestClient(app)

    # 1. POST /api/sites/status with X-Club-Token
    status_resp = client.post(
        "/api/sites/status",
        json={
            "site_id": "VT-PEAK-01",
            "status": "active_on_air",
            "notes": "Verified active by coordinator",
        },
        headers={"X-Club-Token": club_token},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["ok"] is True
    assert status_resp.json()["node"]["status"] == "active_on_air"

    # 2. POST /api/sites/custom with Bearer Authorization
    custom_resp = client.post(
        "/api/sites/custom",
        json={
            "name": "Authorized Summit Repeater",
            "lat": 44.4500,
            "lon": -72.9500,
            "elevation_m": 850.0,
            "mast_height_m": 15.0,
            "site_type": "commercial_tower",
            "hardware_preset": "STATION_G2_BACKBONE",
            "notes": "Coordinator approved",
        },
        headers={"Authorization": f"Bearer {club_token}"},
    )
    assert custom_resp.status_code == 200
    assert custom_resp.json()["ok"] is True
    assert custom_resp.json()["site"]["name"] == "Authorized Summit Repeater"

    # 3. POST /api/sites/propose with X-Club-Token
    prop_resp = client.post(
        "/api/sites/propose",
        json={
            "name": "Authorized Community Proposal",
            "lat": 44.5200,
            "lon": -72.9800,
            "elevation_m": 320.0,
            "height_agl_m": 12.0,
            "site_type": "water_tank",
            "owner": "Water District",
            "notes": "Coordinator added proposal",
            "source_url": "https://example.com/site",
        },
        headers={"X-Club-Token": club_token},
    )
    assert prop_resp.status_code == 200
    assert prop_resp.json()["ok"] is True
    assert prop_resp.json()["node"]["site_id"].startswith("COMM-")

    # 4. POST /api/import/snapshot with X-Club-Token
    valid_node = {
        "site_id": "COMM-SNAP-01",
        "name": "Imported Backbone Node",
        "coordinate": {"lat": 44.40, "lon": -73.10, "elevation_m": 150.0},
        "height_agl_m": 10.0,
        "site_type": "custom",
        "status": "candidate",
        "hardware_preset": "RAK4631_SOLAR",
        "owner": "Club",
        "is_public_land": False,
        "notes": "Verified snapshot node",
        "privacy_fuzzed": False,
        "source_url": "https://vermontmesh.org/nodes/01",
        "updated_at": "2026-10-29T12:00:00Z",
    }
    snap_resp = client.post(
        "/api/import/snapshot",
        json={"nodes": [valid_node]},
        headers={"X-Club-Token": club_token},
    )
    assert snap_resp.status_code == 200
    assert snap_resp.json()["ok"] is True
    assert snap_resp.json()["imported_count"] == 1


def test_public_reads_remain_open_without_auth(temp_db_path: Path) -> None:
    """Verify public read endpoints and link evaluations remain fully accessible without auth."""
    app = create_web_app(
        db_path=temp_db_path,
        hosted_mode=True,
        club_token="locked-token",
    )
    client = TestClient(app)

    # 1. GET /api/status
    from meshscout import __version__
    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["ok"] is True
    assert status_data["hosted_mode"] is True
    assert status_data["version"] == __version__

    # 2. GET /api/sites
    sites_resp = client.get("/api/sites")
    assert sites_resp.status_code == 200
    assert sites_resp.json()["ok"] is True
    assert sites_resp.json()["count"] > 0

    # 3. GET /api/presets
    presets_resp = client.get("/api/presets")
    assert presets_resp.status_code == 200
    assert presets_resp.json()["ok"] is True
    assert "hardware_presets" in presets_resp.json()

    # 4. GET /api/regions
    regions_resp = client.get("/api/regions")
    assert regions_resp.status_code == 200
    assert regions_resp.json()["ok"] is True
    assert len(regions_resp.json()["states"]) > 0

    # 5. POST /api/link
    link_resp = client.post(
        "/api/link",
        json={
            "target_site_id": "VT-PEAK-01",
            "hardware_preset": "RAK4631_SOLAR",
            "protocol_profile": "MESHTASTIC_LONGFAST",
            "season_profile": "WINTER_LEAF_OFF",
        },
    )
    assert link_resp.status_code == 200
    assert link_resp.json()["ok"] is True
    assert "link_budget" in link_resp.json()


def test_geocode_set_as_home_hosted_mode_does_not_mutate_server_prefs(temp_db_path: Path) -> None:
    """Verify geocoding with set_as_home=True in hosted mode does not mutate server workspace_prefs."""
    app = create_web_app(
        db_path=temp_db_path,
        hosted_mode=True,
        club_token="hosted-token",
    )
    client = TestClient(app)

    # Record initial server state
    init_state = client.get("/api/state").json()["preferences"]
    init_home_lat = init_state["home_lat"]
    init_home_lon = init_state["home_lon"]

    # Perform geocode with set_as_home=True
    geocode_resp = client.post(
        "/api/geocode",
        json={
            "query": "Stowe, VT",
            "apply_privacy_fuzz": True,
            "offline_only": False,
            "set_as_home": True,
        },
    )
    assert geocode_resp.status_code == 200
    geo_data = geocode_resp.json()
    assert geo_data["ok"] is True
    assert geo_data["client_local_home"] is True
    assert "Home location set locally in browser (hosted community mode)." in geo_data["message"]

    # Verify server database preferences remain unchanged
    after_state = client.get("/api/state").json()["preferences"]
    assert after_state["home_lat"] == init_home_lat
    assert after_state["home_lon"] == init_home_lon
    assert after_state["home_name"] == init_state["home_name"]

    # Contrast: with hosted_mode=False, set_as_home DOES mutate server preferences
    unhosted_app = create_web_app(db_path=temp_db_path, hosted_mode=False)
    unhosted_client = TestClient(unhosted_app)
    unhosted_resp = unhosted_client.post(
        "/api/geocode",
        json={
            "query": "Burlington, VT",
            "apply_privacy_fuzz": True,
            "offline_only": False,
            "set_as_home": True,
        },
    )
    assert unhosted_resp.status_code == 200
    unhosted_data = unhosted_resp.json()
    assert "client_local_home" not in unhosted_data
    unhosted_state = unhosted_client.get("/api/state").json()["preferences"]
    assert unhosted_state["home_name"] != init_state["home_name"]


def test_request_scoped_home_coordinates_on_link(temp_db_path: Path) -> None:
    """Verify /api/link evaluates against request-supplied home coordinates instead of server prefs."""
    app = create_web_app(db_path=temp_db_path, hosted_mode=True)
    client = TestClient(app)

    # 1. Link evaluation with specific custom home coordinates (Middlebury area)
    custom_lat = 44.0150
    custom_lon = -73.1670
    custom_elev = 110.0

    resp = client.post(
        "/api/link",
        json={
            "home_lat": custom_lat,
            "home_lon": custom_lon,
            "home_elev_m": custom_elev,
            "target_site_id": "VT-PEAK-01",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    src = data["source"]
    assert pytest.approx(src["location"]["lat"], rel=1e-4) == custom_lat
    assert pytest.approx(src["location"]["lon"], rel=1e-4) == custom_lon
    assert pytest.approx(src["location"]["elevation_m"], rel=1e-4) == custom_elev
    dist_1 = data["fresnel_analysis"]["total_distance_m"]

    # 2. Link evaluation with different home coordinates (Waterbury area)
    custom_lat_2 = 44.3370
    custom_lon_2 = -72.7560
    resp_2 = client.post(
        "/api/link",
        json={
            "home_lat": custom_lat_2,
            "home_lon": custom_lon_2,
            "target_site_id": "VT-PEAK-01",
        },
    )
    assert resp_2.status_code == 200
    data_2 = resp_2.json()
    assert pytest.approx(data_2["source"]["location"]["lat"], rel=1e-4) == custom_lat_2
    assert pytest.approx(data_2["source"]["location"]["lon"], rel=1e-4) == custom_lon_2
    dist_2 = data_2["fresnel_analysis"]["total_distance_m"]

    # Distances must differ because the sources are in different locations
    assert abs(dist_1 - dist_2) > 5000.0


def test_hosted_mode_env_vars(monkeypatch: pytest.MonkeyPatch, temp_db_path: Path) -> None:
    """Verify hosted mode and club token are correctly picked up from environment variables."""
    monkeypatch.setenv("MESHSCOUT_HOSTED_MODE", "1")
    monkeypatch.setenv("MESHSCOUT_CLUB_TOKEN", "env-secret-token")

    app = create_web_app(db_path=temp_db_path)
    client = TestClient(app)

    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["hosted_mode"] is True

    # Mutation blocked without token
    blocked = client.post(
        "/api/sites/status",
        json={"site_id": "VT-PEAK-01", "status": "testing"},
    )
    assert blocked.status_code == 403

    # Mutation allowed with env token
    allowed = client.post(
        "/api/sites/status",
        json={"site_id": "VT-PEAK-01", "status": "testing"},
        headers={"X-Club-Token": "env-secret-token"},
    )
    assert allowed.status_code == 200
