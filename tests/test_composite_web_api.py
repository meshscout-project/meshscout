"""End-to-end API tests for Composite Viewshed and Ad-Hoc Tactical Pins endpoints."""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from meshscout.web.app import create_web_app


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated temporary SQLite database path per test."""
    return tmp_path / "test_composite_mesh_state.db"


@pytest.fixture()
def client(temp_db_path: Path) -> TestClient:
    """Create a FastAPI TestClient backed by an isolated SQLite database."""
    app = create_web_app(db_path=temp_db_path)
    return TestClient(app)


def test_sample_elevation_returns_200_and_positive_elevation(client: TestClient) -> None:
    """Test POST /api/pins/sample-elevation with lat/lon returns 200 and positive elevation."""
    # Test Mount Mansfield summit coordinates
    resp = client.post(
        "/api/pins/sample-elevation",
        json={"lat": 44.5437, "lon": -72.8143},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["lat"] == 44.5437
    assert data["lon"] == -72.8143
    assert isinstance(data["elevation_m"], (int, float))
    assert data["elevation_m"] > 1000.0  # Mansfield summit is well above 1000m

    # Test Burlington waterfront coordinates
    resp_burl = client.post(
        "/api/pins/sample-elevation",
        json={"lat": 44.4759, "lon": -73.2200},
    )
    assert resp_burl.status_code == 200
    data_burl = resp_burl.json()
    assert data_burl["ok"] is True
    assert data_burl["elevation_m"] > 0.0

    # Test invalid coordinates validation
    resp_invalid = client.post(
        "/api/pins/sample-elevation",
        json={"lat": 195.0, "lon": -72.8143},
    )
    assert resp_invalid.status_code == 422


def test_composite_viewshed_include_active_nodes(client: TestClient) -> None:
    """Test POST /api/viewshed/composite with include_active_nodes=True returns composite footprint."""
    # Step 1: Promote/set a regional site to active_on_air
    status_resp = client.post(
        "/api/sites/status",
        json={"site_id": "VT-PEAK-01", "status": "active_on_air"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["ok"] is True

    # Step 2: Query composite viewshed with include_active_nodes=True
    resp = client.post(
        "/api/viewshed/composite",
        json={
            "include_active_nodes": True,
            "max_range_km": 40.0,
            "num_radials": 36,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] >= 1

    comp = data["composite"]
    assert "VT-PEAK-01" in comp["origin_site_ids"]
    assert "VT-PEAK-01" in comp["individual_polygons"]
    assert len(comp["composite_polygons"]) >= 1
    assert comp["total_illuminated_area_sq_km"] > 0.0
    assert isinstance(comp["illuminated_towns"], list)


def test_composite_viewshed_site_ids_mansfield_and_bolton(client: TestClient) -> None:
    """Test POST /api/viewshed/composite with site_ids returns individual polygons, composite polygons, area, and backhaul."""
    resp = client.post(
        "/api/viewshed/composite",
        json={
            "site_ids": ["VT-CHIT-MANS-01", "VT-CHIT-BOLT-01"],
            "max_range_km": 50.0,
            "num_radials": 72,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2

    comp = data["composite"]
    assert "VT-CHIT-MANS-01" in comp["origin_site_ids"]
    assert "VT-CHIT-BOLT-01" in comp["origin_site_ids"]

    # Verify individual polygons for both sites (closed rings: 72 radials + closing vertex)
    assert "VT-CHIT-MANS-01" in comp["individual_polygons"]
    assert "VT-CHIT-BOLT-01" in comp["individual_polygons"]
    assert len(comp["individual_polygons"]["VT-CHIT-MANS-01"]) == 73
    assert len(comp["individual_polygons"]["VT-CHIT-BOLT-01"]) == 73

    # Verify composite polygons and total area
    assert len(comp["composite_polygons"]) >= 1
    assert comp["total_illuminated_area_sq_km"] > 1000.0

    # Verify inter-site microwave/VHF backhaul link analysis
    links = comp["intersite_backhaul_links"]
    assert len(links) == 1
    link = links[0]
    assert link["site_a_id"] == "VT-CHIT-MANS-01"
    assert link["site_b_id"] == "VT-CHIT-BOLT-01"
    assert link["distance_km"] > 10.0
    assert link["has_line_of_sight"] is True
    assert link["link_margin_db"] > 10.0
    assert link["fresnel_clearance_ratio"] > 0.6


def test_composite_viewshed_with_ad_hoc_pin(client: TestClient) -> None:
    """Test POST /api/viewshed/composite with ad-hoc pin returns composite footprint including pin."""
    pin_payload = {
        "pin_id": "pin_tactical_42",
        "name": "Camel's Hump Tactical Drop",
        "lat": 44.3197,
        "lon": -72.8864,
        "elevation_m": 1244.0,
        "mast_height_m": 12.0,
        "site_type": "mountain_peak",
        "notes": "Emergency tactical repeater drop",
    }

    resp = client.post(
        "/api/viewshed/composite",
        json={
            "ad_hoc_pins": [pin_payload],
            "max_range_km": 40.0,
            "num_radials": 36,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 1

    comp = data["composite"]
    expected_site_id = "adhoc_pin_tactical_42"
    assert expected_site_id in comp["origin_site_ids"]
    assert expected_site_id in comp["individual_polygons"]
    assert len(comp["composite_polygons"]) >= 1
    assert comp["total_illuminated_area_sq_km"] > 0.0


def test_promote_pin_to_living_registry_and_verify_in_sites(client: TestClient) -> None:
    """Test POST /api/pins/promote promotes a pin to living registry and verifies it appears in GET /api/sites."""
    pin_payload = {
        "pin_id": "pin_promo_underhill",
        "name": "Underhill Community Tactical Site",
        "lat": 44.5200,
        "lon": -72.9500,
        "elevation_m": 350.0,
        "mast_height_m": 15.0,
        "site_type": "building_rooftop",
        "notes": "Community member roof access granted",
    }

    # Step 1: Promote the pin
    promote_resp = client.post(
        "/api/pins/promote",
        json={"pin": pin_payload, "status": "candidate"},
    )
    assert promote_resp.status_code == 200
    pdata = promote_resp.json()
    assert pdata["ok"] is True
    assert pdata["site_id"] == "adhoc_pin_promo_underhill"
    assert pdata["name"] == "Underhill Community Tactical Site"

    # Step 2: Query GET /api/sites and verify the promoted site appears
    sites_resp = client.get("/api/sites")
    assert sites_resp.status_code == 200
    sdata = sites_resp.json()
    assert sdata["ok"] is True

    promoted_matches = [
        s for s in sdata["sites"]
        if s["site_id"] == "adhoc_pin_promo_underhill"
    ]
    assert len(promoted_matches) == 1
    promoted = promoted_matches[0]
    assert promoted["name"] == "Underhill Community Tactical Site"
    assert promoted["lat"] == 44.5200
    assert promoted["lon"] == -72.9500
    assert promoted["elevation_m"] == 350.0
    assert promoted["mast_height_m"] == 15.0
    assert promoted["status"] == "candidate"


def test_composite_viewshed_directional_uplink_shrinkage_and_asymmetric_backhaul(
    client: TestClient,
) -> None:
    """Verify POST /api/viewshed/composite directional uplink vs downlink shrinkage, site_presets backhaul, and 400 validation."""
    # Legacy default keeps directional backhaul fields None
    legacy_resp = client.post(
        "/api/viewshed/composite",
        json={
            "site_ids": ["VT-CHIT-MANS-01", "VT-CHIT-BOLT-01"],
            "max_range_km": 50.0,
            "num_radials": 24,
        },
    )
    assert legacy_resp.status_code == 200
    legacy_comp = legacy_resp.json()["composite"]
    assert legacy_comp["direction"] == "downlink"
    assert legacy_comp["intersite_backhaul_links"][0]["forward_margin_db"] is None
    assert legacy_comp["intersite_backhaul_links"][0]["reverse_margin_db"] is None
    assert legacy_comp["intersite_backhaul_links"][0]["reachability_state"] is None

    # Directional evaluation with ad-hoc commercial tower + registered summit and weak client inside vehicle cabin
    comm_pin = {
        "pin_id": "comm_summit_01",
        "name": "Noisy Broadcast Ridge",
        "lat": 44.5437,
        "lon": -72.8143,
        "elevation_m": 1339.0,
        "mast_height_m": 20.0,
        "site_type": "communications_tower",
    }
    tank_pin = {
        "pin_id": "solar_tank_01",
        "name": "Foothill Municipal Water Tank",
        "lat": 44.4950,
        "lon": -73.0850,
        "elevation_m": 195.0,
        "mast_height_m": 18.0,
        "site_type": "water_tower",
    }
    base_payload = {
        "ad_hoc_pins": [comm_pin, tank_pin],
        "max_range_km": 130.0,
        "num_radials": 36,
        "client_preset": "SENSECAP_T1000E",
        "client_env": "VEHICLE_CABIN",
        "protocol_profile": "RETICULUM_RNODE_FAST",
        "season_profile": "SUMMER_LEAF_ON",
        "site_presets": {
            "adhoc_comm_summit_01": "STATION_G2_BACKBONE",
            "adhoc_solar_tank_01": "RAK4631_SOLAR",
        },
    }

    dl_resp = client.post("/api/viewshed/composite", json={**base_payload, "direction": "downlink"})
    ul_resp = client.post("/api/viewshed/composite", json={**base_payload, "direction": "uplink"})
    tw_resp = client.post("/api/viewshed/composite", json={**base_payload, "direction": "two_way"})
    assert dl_resp.status_code == 200
    assert ul_resp.status_code == 200
    assert tw_resp.status_code == 200

    dl_comp = dl_resp.json()["composite"]
    ul_comp = ul_resp.json()["composite"]
    tw_comp = tw_resp.json()["composite"]

    assert dl_comp["direction"] == "downlink"
    assert ul_comp["direction"] == "uplink"
    assert tw_comp["direction"] == "two_way"
    assert ul_comp["total_illuminated_area_sq_km"] < dl_comp["total_illuminated_area_sq_km"]
    assert tw_comp["total_illuminated_area_sq_km"] <= min(
        ul_comp["total_illuminated_area_sq_km"],
        dl_comp["total_illuminated_area_sq_km"],
    )

    # Intersite backhaul link populates asymmetric forward/reverse margins & reachability_state
    bh_link = tw_comp["intersite_backhaul_links"][0]
    assert bh_link["site_a_id"] == "adhoc_comm_summit_01"
    assert bh_link["site_b_id"] == "adhoc_solar_tank_01"
    assert bh_link["forward_margin_db"] is not None
    assert bh_link["reverse_margin_db"] is not None
    assert bh_link["reachability_state"] == "two_way"
    assert bh_link["forward_margin_db"] - bh_link["reverse_margin_db"] == pytest.approx(11.0, abs=0.05)
    assert bh_link["link_margin_db"] == pytest.approx(
        min(bh_link["forward_margin_db"], bh_link["reverse_margin_db"]), abs=0.05
    )

    # Validation: HTTP 400 on invalid direction, client_env, client_preset, and site_presets
    assert (
        client.post(
            "/api/viewshed/composite",
            json={"site_ids": ["VT-CHIT-MANS-01"], "direction": "sideways"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/viewshed/composite",
            json={"site_ids": ["VT-CHIT-MANS-01"], "client_env": "UNDERWATER"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/viewshed/composite",
            json={"site_ids": ["VT-CHIT-MANS-01"], "client_preset": "BAD_CLIENT_HW"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/viewshed/composite",
            json={
                "site_ids": ["VT-CHIT-MANS-01"],
                "site_presets": {"VT-CHIT-MANS-01": "BAD_SITE_HW"},
            },
        ).status_code
        == 400
    )

