"""End-to-end API and persistence tests for the MeshScout FastAPI Web Workbench."""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from meshscout.web.app import create_web_app


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated temporary SQLite database path per test."""
    return tmp_path / "test_mesh_state.db"


@pytest.fixture()
def client(temp_db_path: Path):
    """Create a FastAPI TestClient backed by an isolated SQLite database."""
    app = create_web_app(db_path=temp_db_path)
    with TestClient(app) as c:
        yield c


def test_serve_workbench_html_and_static_assets(client: TestClient) -> None:
    """Verify GET /, /static/styles.css, and /static/app.js serve the workbench UI."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "M E S H S C O U T //" in resp.text
    assert 'id="brand-version"' in resp.text
    assert "WORKBENCH" in resp.text
    assert "fresnel-svg" in resp.text
    assert "vector-map-svg" in resp.text
    assert "mode-backhaul-btn" in resp.text
    assert "backhaul-control-bar" in resp.text
    assert "toggle-layer-heatmap" in resp.text
    assert "toggle-layer-towers" in resp.text
    assert "Signal Quality Heatmap" in resp.text
    assert 'id="sidebar-toggle-icon">▶</span> <span id="sidebar-toggle-text">Collapse</span>' in resp.text
    assert "◀ Workbench" in resp.text
    assert "map-mode-vector-btn" in resp.text
    assert "map-mode-tiles-btn" in resp.text
    assert "backhaul-pick-a-btn" in resp.text
    assert "backhaul-pick-b-btn" in resp.text
    assert "backhaul-pick-indicator" in resp.text
    assert "INFRASTRUCTURE &amp; CIVIC HIGH-SITES" in resp.text
    assert "Prioritizing Low-Friction Municipal &amp; Civic Structures" in resp.text
    assert "layer-fire-lookouts" in resp.text
    assert "layer-water-towers" in resp.text
    assert "layer-research-towers" in resp.text
    assert "layer-silos" in resp.text
    assert "layer-commercial-towers" in resp.text
    assert "opt-include-civic-towers" in resp.text
    assert "tower-info-modal" in resp.text
    assert "layer-meshtastic-nodes" in resp.text
    assert "layer-meshcore-nodes" in resp.text
    assert "layer-coverage-gaps" in resp.text
    assert "telemetry-node-modal" in resp.text
    assert "drop-pin-btn" in resp.text
    assert "layer-active-coverage" in resp.text
    assert "layer-whatif-coverage" in resp.text
    assert "tactical-pin-card" in resp.text
    assert "whatif-scenario-panel" in resp.text
    assert "backhaul-corridor-section" in resp.text
    assert "corridor-eval-btn" in resp.text
    assert "corridor-clear-btn" in resp.text
    assert "corridor-chain-chips" in resp.text
    assert 'id="origin-mast-slider"' in resp.text
    assert 'id="target-mast-slider"' in resp.text
    assert "origin-mast-val" in resp.text
    assert "target-mast-val" in resp.text
    assert "mast-sliders-panel" in resp.text
    assert "mast-height-sliders-panel" in resp.text
    assert "fresnel-dynamic-badge" in resp.text

    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    assert "--brand-hue: 155" in css_resp.text
    assert "map-top-bar" in css_resp.text
    assert "backhaul-control-bar" in css_resp.text
    assert "mast-sliders-panel" in css_resp.text
    assert "mast-slider-row" in css_resp.text
    assert "mast-slider-label" in css_resp.text
    assert "brutal-slider" in css_resp.text
    assert "mast-clearance-indicator" in css_resp.text
    assert "backhaul-corridor-section" in css_resp.text
    assert "corridor-chain-chips" in css_resp.text
    assert "corridor-chip" in css_resp.text
    assert "corridor-results-card" in css_resp.text
    assert "bottleneck-row" in css_resp.text
    assert "heatmap-legend" in css_resp.text
    assert "--scrollbar-track: var(--bg-canvas);" in css_resp.text
    assert "scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);" in css_resp.text
    assert "*::-webkit-scrollbar" in css_resp.text
    assert "map-mode-segmented-group" in css_resp.text
    assert "backhaul-pick-btn" in css_resp.text
    assert "pick-indicator" in css_resp.text
    assert "civic-tower-layer-bar" in css_resp.text
    assert "tower-marker" in css_resp.text
    assert "badge-friction-tier-1" in css_resp.text
    assert "badge-friction-tier-2" in css_resp.text
    assert "badge-friction-tier-3" in css_resp.text
    assert "badge-meshtastic" in css_resp.text
    assert "badge-meshcore" in css_resp.text
    assert "telemetry-node-meshtastic" in css_resp.text
    assert "telemetry-node-meshcore" in css_resp.text
    assert "picking-active" in css_resp.text
    assert "tower-pick-node-a-btn" in css_resp.text
    assert "tower-pick-node-b-btn" in css_resp.text
    assert "leaflet-graticule-label" in css_resp.text
    assert "leaflet-summit-marker" in css_resp.text

    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "renderFresnelChart" in js_resp.text
    assert "backhaulNodeAId" in js_resp.text
    assert "signal-heatmap-grad" in js_resp.text
    assert "getHeatmapOrigin" in js_resp.text
    assert 'iconEl.textContent = nextCollapsed ? "◀" : "▶";' in js_resp.text
    assert "backhaulPickTarget" in js_resp.text
    assert "updateBackhaulPickUI" in js_resp.text
    assert "updateMapModeUI" in js_resp.text
    assert "setMapDisplayMode" in js_resp.text
    assert "fetchCivicTowers" in js_resp.text
    assert "TOWER_TYPE_CONFIG" in js_resp.text
    assert "resolveTowerFrictionTier" in js_resp.text
    assert "addTowerAsCandidate" in js_resp.text
    assert "fetchRegionalTelemetry" in js_resp.text
    assert "showMeshtasticNodes" in js_resp.text
    assert "showMeshCoreNodes" in js_resp.text
    assert "showCoverageGaps" in js_resp.text
    assert "buildTelemetryNodePopupHtml" in js_resp.text
    assert "addTelemetryNodeAsCandidate" in js_resp.text
    assert "handleUniversalMapPick" in js_resp.text
    assert "handlePopupPickNode" in js_resp.text
    assert "picking-active" in js_resp.text
    assert "tower-pick-node-a-btn" in js_resp.text
    assert "tower-pick-node-b-btn" in js_resp.text
    assert "addSiteToCorridor" in js_resp.text
    assert "evaluateCorridorRoute" in js_resp.text
    assert "corridorSiteIds" in js_resp.text
    assert "leafletGraticuleLayer" in js_resp.text
    assert "leafletCountiesLayer" in js_resp.text
    assert "leafletSummitsLayer" in js_resp.text
    assert "calcSquare" in js_resp.text


def test_workspace_state_persistence_across_restarts(temp_db_path: Path) -> None:
    """Verify GET /api/state and POST /api/state persist operator location and presets."""
    with TestClient(create_web_app(db_path=temp_db_path)) as client1:
        init_resp = client1.get("/api/state")
        assert init_resp.status_code == 200
        init_data = init_resp.json()
        assert init_data["ok"] is True
        assert init_data["maidenhead"] == "FN34jl"
        assert init_data["preferences"]["hardware_preset"] == "RAK4631_SOLAR"

        update_resp = client1.post(
            "/api/state",
            json={
                "home_name": "Stowe Mountain Cabin",
                "home_lat": 44.4654,
                "home_lon": -72.6874,
                "home_elev_m": 220.0,
                "home_height_agl_m": 14.5,
                "hardware_preset": "STATION_G2_BACKBONE",
                "protocol_profile": "MESHCORE_NARROW",
                "season_profile": "SUMMER_LEAF_ON",
            },
        )
        assert update_resp.status_code == 200
        upd_data = update_resp.json()
        assert upd_data["ok"] is True
        assert upd_data["preferences"]["home_name"] == "Stowe Mountain Cabin"
        assert upd_data["preferences"]["hardware_preset"] == "STATION_G2_BACKBONE"
        assert upd_data["preferences"]["protocol_profile"] == "MESHCORE_NARROW"
        assert upd_data["preferences"]["season_profile"] == "SUMMER_LEAF_ON"

    # Re-create web app pointing at the same SQLite file to verify persistence
    with TestClient(create_web_app(db_path=temp_db_path)) as client2:
        reload_resp = client2.get("/api/state")
        assert reload_resp.status_code == 200
    reloaded = reload_resp.json()["preferences"]
    assert reloaded["home_name"] == "Stowe Mountain Cabin"
    assert reloaded["home_lat"] == pytest.approx(44.4654, abs=1e-4)
    assert reloaded["home_height_agl_m"] == pytest.approx(14.5, abs=1e-4)
    assert reloaded["hardware_preset"] == "STATION_G2_BACKBONE"
    assert reloaded["protocol_profile"] == "MESHCORE_NARROW"
    assert reloaded["season_profile"] == "SUMMER_LEAF_ON"


def test_get_presets_catalog(client: TestClient) -> None:
    """Verify GET /api/presets returns hardware, protocol, and seasonal profiles."""
    resp = client.get("/api/presets")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "RAK4631_SOLAR" in data["hardware_presets"]
    assert "STATION_G2_BACKBONE" in data["hardware_presets"]
    assert "HELTEC_V3_HOME" in data["hardware_presets"]
    assert "SENSECAP_T1000E" in data["hardware_presets"]
    assert "MESHTASTIC_LONGFAST" in data["protocol_profiles"]
    assert "MESHCORE_NARROW" in data["protocol_profiles"]
    assert "WINTER_LEAF_OFF" in data["seasonal_profiles"]
    assert "SUMMER_LEAF_ON" in data["seasonal_profiles"]


def test_geocode_05452_privacy_fuzz_and_maidenhead(client: TestClient) -> None:
    """Verify POST /api/geocode resolves 05452 with privacy fuzzing and FN34ll locator."""
    resp = client.post(
        "/api/geocode",
        json={
            "query": "05452",
            "apply_privacy_fuzz": True,
            "offline_only": True,
            "set_as_home": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    loc = data["location"]
    assert loc["maidenhead_grid"] == "FN34kl"
    assert loc["privacy_fuzzed"] is True
    assert "Essex Junction" in loc["display_name"]
    # Verify fuzzed coordinate differs from raw exact coordinate or is snapped to 4 decimals
    assert loc["coordinate"] == loc["fuzzed_coordinate"]
    assert data["preferences"]["home_lat"] == pytest.approx(loc["coordinate"]["lat"], abs=1e-5)


def test_evaluate_link_profile_points_and_seasonal_foliage(client: TestClient) -> None:
    """Verify POST /api/link returns 25 profile_points and SUMMER_LEAF_ON lowers margin vs WINTER_LEAF_OFF."""
    winter_resp = client.post(
        "/api/link",
        json={
            "target_site_id": "VT-PEAK-01",
            "hardware_preset": "RAK4631_SOLAR",
            "protocol_profile": "MESHTASTIC_LONGFAST",
            "season_profile": "WINTER_LEAF_OFF",
        },
    )
    assert winter_resp.status_code == 200
    winter_data = winter_resp.json()
    assert winter_data["ok"] is True
    assert "link_budget" in winter_data
    assert "fresnel_analysis" in winter_data
    assert len(winter_data["profile_points"]) == 25

    sample_pt = winter_data["profile_points"][12]
    for required_key in (
        "distance_km",
        "terrain_elev_m",
        "earth_bulge_m",
        "effective_terrain_m",
        "los_height_m",
        "fresnel_radius_m",
        "fresnel_60pct_lower_m",
        "clearance_m",
    ):
        assert required_key in sample_pt

    summer_resp = client.post(
        "/api/link",
        json={
            "target_site_id": "VT-PEAK-01",
            "hardware_preset": "RAK4631_SOLAR",
            "protocol_profile": "MESHTASTIC_LONGFAST",
            "season_profile": "SUMMER_LEAF_ON",
        },
    )
    assert summer_resp.status_code == 200
    summer_data = summer_resp.json()

    winter_margin = winter_data["link_budget"]["link_margin_db"]
    summer_margin = summer_data["link_budget"]["link_margin_db"]
    assert summer_margin < winter_margin
    assert (winter_margin - summer_margin) == pytest.approx(8.5, abs=0.2)


def test_evaluate_site_to_site_backhaul_link(client: TestClient) -> None:
    """Verify POST /api/link between two candidate high sites (Mount Mansfield <-> Killington Peak)."""
    resp = client.post(
        "/api/link",
        json={
            "source_site_id": "VT-PEAK-01",
            "target_site_id": "VT-RUT-01",
            "hardware_preset": "STATION_G2_BACKBONE",
            "protocol_profile": "MESHCORE_STANDARD",
            "season_profile": "WINTER_LEAF_OFF",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source"]["site_id"] == "VT-PEAK-01"
    assert "Mount Mansfield" in data["source"]["name"]
    assert data["target"]["site_id"] == "VT-RUT-01"
    assert "Killington" in data["target"]["name"]

    budget = data["link_budget"]
    assert budget["distance_km"] == pytest.approx(104.4, abs=2.0)
    assert budget["free_space_loss_db"] > 120.0
    assert "link_margin_db" in budget

    fa = data["fresnel_analysis"]
    assert "has_line_of_sight" in fa
    assert "fresnel_60pct_clear" in fa
    assert len(data["profile_points"]) == 25

    # Verify swapped direction returns symmetrical distance and valid profile
    swap_resp = client.post(
        "/api/link",
        json={
            "source_site_id": "VT-RUT-01",
            "target_site_id": "VT-PEAK-01",
            "hardware_preset": "STATION_G2_BACKBONE",
            "protocol_profile": "MESHCORE_STANDARD",
            "season_profile": "WINTER_LEAF_OFF",
        },
    )
    assert swap_resp.status_code == 200
    swap_data = swap_resp.json()
    assert swap_data["ok"] is True
    assert swap_data["source"]["site_id"] == "VT-RUT-01"
    assert swap_data["target"]["site_id"] == "VT-PEAK-01"
    assert swap_data["link_budget"]["distance_km"] == pytest.approx(budget["distance_km"], abs=0.1)


def test_home_check_360_reach_for_essex_junction(client: TestClient) -> None:
    """Verify POST /api/home-check returns best azimuth, cardinal direction, and ranked towers."""
    resp = client.post(
        "/api/home-check",
        json={
            "home_lat": 44.4906,
            "home_lon": -73.1112,
            "home_elev_m": 108.0,
            "home_height_agl_m": 10.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["best_azimuth_deg"] is not None
    assert 0.0 <= data["best_azimuth_deg"] < 360.0
    assert data["best_cardinal_direction"] in (
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    )
    assert data["reachable_candidate_count"] > 0
    assert len(data["ranked_towers"]) == 33


def test_site_status_update_persists_across_sites_snapshot_and_optimizer(
    client: TestClient,
) -> None:
    """Verify POST /api/sites/status updates node to active_on_air and persists across endpoints."""
    sites_init = client.get("/api/sites").json()
    assert sites_init["ok"] is True
    assert sites_init["count"] == 33

    target_id = "VT-PEAK-01"
    upd_resp = client.post(
        "/api/sites/status",
        json={
            "site_id": target_id,
            "status": "active_on_air",
            "notes": "Deployed solar RAK4631 on summit ridge",
            "hardware_preset": "STATION_G2_BACKBONE",
        },
    )
    assert upd_resp.status_code == 200
    upd_json = upd_resp.json()
    assert upd_json["ok"] is True
    assert upd_json["node"]["status"] == "active_on_air"
    assert upd_json["node"]["notes"] == "Deployed solar RAK4631 on summit ridge"

    # Verify in GET /api/sites
    active_sites = client.get("/api/sites?status=active_on_air").json()
    assert active_sites["count"] == 1
    assert active_sites["sites"][0]["site_id"] == target_id

    # Verify in GET /api/export/snapshot
    snap_resp = client.get("/api/export/snapshot")
    assert snap_resp.status_code == 200
    snap_data = snap_resp.json()
    assert snap_data["ok"] is True
    matched_snap = [n for n in snap_data["nodes"] if n["site_id"] == target_id]
    assert len(matched_snap) == 1
    assert matched_snap[0]["status"] == "active_on_air"

    # Verify POST /api/optimize prioritizes the active_on_air site and pitch-sheet / html export work
    opt_resp = client.post("/api/optimize", json={"min_coverage": 0.90, "max_repeaters": 5})
    assert opt_resp.status_code == 200
    opt_data = opt_resp.json()
    assert opt_data["ok"] is True
    assert opt_data["active_on_air_count"] == 1
    selected_ids = [s["site_id"] for s in opt_data["selected_repeaters"]]
    assert target_id in selected_ids

    pitch_resp = client.get(f"/api/pitch-sheet/{target_id}")
    assert pitch_resp.status_code == 200
    assert "text/html" in pitch_resp.headers["content-type"]
    assert target_id in pitch_resp.text

    html_export = client.get("/api/export/html")
    assert html_export.status_code == 200
    assert "text/html" in html_export.headers["content-type"]
    assert target_id in html_export.text


def test_get_vermont_counties(client: TestClient) -> None:
    """Verify GET /api/counties returns all 14 Vermont counties."""
    resp = client.get("/api/counties")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    counties = data["counties"]
    assert len(counties) == 14
    for c in (
        "Addison", "Bennington", "Caledonia", "Chittenden", "Essex",
        "Franklin", "Grand Isle", "Lamoille", "Orange", "Orleans",
        "Rutland", "Washington", "Windham", "Windsor",
    ):
        assert c in counties


def test_switch_county_populates_sites(client: TestClient) -> None:
    """Verify POST /api/counties/switch switches to rutland and washington and populates sites."""
    # Switch to Rutland
    resp_rutland = client.post("/api/counties/switch", json={"county": "rutland"})
    assert resp_rutland.status_code == 200
    data_rutland = resp_rutland.json()
    assert data_rutland["ok"] is True
    assert data_rutland["county"].lower() == "rutland"
    assert data_rutland["sites_count"] == 4
    assert "bounds" in data_rutland
    assert len(data_rutland["sites"]) == 4

    sites_resp = client.get("/api/sites?county=rutland")
    assert sites_resp.status_code == 200
    sites_rutland = sites_resp.json()
    assert sites_rutland["ok"] is True
    assert any("RUT" in s["site_id"] or s.get("county") == "Rutland" for s in sites_rutland["sites"])

    # Switch to Washington
    resp_wash = client.post("/api/counties/switch", json={"county": "washington"})
    assert resp_wash.status_code == 200
    data_wash = resp_wash.json()
    assert data_wash["ok"] is True
    assert data_wash["county"].lower() == "washington"
    assert data_wash["sites_count"] == 4
    assert len(data_wash["sites"]) == 4


def test_get_regions_returns_supported_states(client: TestClient) -> None:
    """Verify GET /api/regions returns VT, NH, NY, ME, MA, CA_QC state catalog."""
    resp = client.get("/api/regions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "states" in data
    state_codes = [s["state_code"] for s in data["states"]]
    assert "VT" in state_codes
    assert "NH" in state_codes
    assert "NY" in state_codes
    assert "CA_QC" in state_codes
    assert "ME" in state_codes

    qc_state = next(s for s in data["states"] if s["state_code"] == "CA_QC")
    assert qc_state["country"] == "CA"
    assert qc_state["is_province"] is True

    me_state = next(s for s in data["states"] if s["state_code"] == "ME")
    assert me_state["country"] == "US"
    assert me_state["is_province"] is False


def test_switch_region_ca_qc_seeds_quebec_sites_and_bounds(client: TestClient) -> None:
    """Verify POST /api/regions/switch with state='CA_QC' switches region, seeds Quebec sites, and returns Quebec bounds."""
    resp = client.post("/api/regions/switch", json={"state": "CA_QC"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["state"] == "CA_QC"
    assert data["sites_count"] > 0
    assert "bounds" in data
    bounds = data["bounds"]
    assert bounds["name"] == "Quebec_Southern"
    assert bounds["min_lat"] < bounds["max_lat"]
    assert bounds["min_lon"] < bounds["max_lon"]

    # Verify QC sites are seeded and queryable in LivingMeshRegistry
    sites_resp = client.get("/api/sites")
    assert sites_resp.status_code == 200
    sites_data = sites_resp.json()
    assert sites_data["ok"] is True
    qc_sites = [s for s in sites_data["sites"] if s["site_id"].startswith("QC-")]
    assert len(qc_sites) >= 4
    sutt_site = next((s for s in qc_sites if "SUTT" in s["site_id"]), None)
    assert sutt_site is not None
    assert "Sutton" in sutt_site["name"]


def test_switch_region_me_seeds_maine_sites_and_bounds(client: TestClient) -> None:
    """Verify POST /api/regions/switch with state='ME' switches region and seeds Maine sites."""
    resp = client.post("/api/regions/switch", json={"state": "ME"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["state"] == "ME"
    assert data["sites_count"] > 0
    assert "bounds" in data
    bounds = data["bounds"]
    assert bounds["name"] == "Maine_Statewide"
    assert bounds["min_lat"] < bounds["max_lat"]
    assert bounds["min_lon"] < bounds["max_lon"]

    # Verify ME sites are seeded and queryable in LivingMeshRegistry
    sites_resp = client.get("/api/sites")
    assert sites_resp.status_code == 200
    sites_data = sites_resp.json()
    assert sites_data["ok"] is True
    me_sites = [s for s in sites_data["sites"] if s["site_id"].startswith("ME-")]
    assert len(me_sites) >= 2
    suga_site = next((s for s in me_sites if "SUGA" in s["site_id"]), None)
    assert suga_site is not None
    assert "Sugarloaf" in suga_site["name"]


def test_switch_region_nh_seeds_candidates_and_bounds(client: TestClient) -> None:
    """Verify POST /api/regions/switch with state='NH' switches state, seeds NH sites, and returns NH bounds."""
    resp = client.post("/api/regions/switch", json={"state": "NH"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["state"] == "NH"
    assert data["sites_count"] > 0
    assert "bounds" in data
    bounds = data["bounds"]
    assert bounds["name"] == "New_Hampshire_Statewide"
    assert bounds["min_lat"] < bounds["max_lat"]
    assert bounds["min_lon"] < bounds["max_lon"]

    # Verify NH sites are seeded and queryable in LivingMeshRegistry
    sites_resp = client.get("/api/sites")
    assert sites_resp.status_code == 200
    sites_data = sites_resp.json()
    assert sites_data["ok"] is True
    nh_sites = [s for s in sites_data["sites"] if s["site_id"].startswith("NH-")]
    assert len(nh_sites) >= 5
    wash_site = next((s for s in nh_sites if "WASH" in s["site_id"]), None)
    assert wash_site is not None
    assert "Washington" in wash_site["name"]


def test_switch_region_ny_seeds_adirondack_sites(client: TestClient) -> None:
    """Verify POST /api/regions/switch with state='NY' switches state and seeds Adirondack sites."""
    resp = client.post("/api/regions/switch", json={"state": "NY"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["state"] == "NY"
    assert data["sites_count"] > 0
    assert "bounds" in data
    bounds = data["bounds"]
    assert bounds["name"] == "New_York_Adirondack_Champlain"

    # Verify NY Adirondack sites are seeded and queryable in LivingMeshRegistry
    sites_resp = client.get("/api/sites")
    assert sites_resp.status_code == 200
    sites_data = sites_resp.json()
    assert sites_data["ok"] is True
    ny_sites = [s for s in sites_data["sites"] if s["site_id"].startswith("NY-")]
    assert len(ny_sites) >= 3
    whit_site = next((s for s in ny_sites if "WHIT" in s["site_id"]), None)
    assert whit_site is not None
    assert "Whiteface" in whit_site["name"]


def test_telemetry_calibrate_route15_sample(client: TestClient) -> None:
    """Verify POST /api/telemetry/calibrate with Route 15 sample returns ClutterCalibrationResult."""
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "wardriving_sample.json"
    assert fixture_path.exists(), f"Missing wardriving sample fixture at {fixture_path}"
    raw_log = fixture_path.read_text(encoding="utf-8")

    resp = client.post(
        "/api/telemetry/calibrate",
        json={
            "raw_log": raw_log,
            "format_hint": "json",
            "transmitter_site_id": "VT-MANS-01",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    calib = data["calibration"]
    assert calib["total_packets_ingested"] == 18
    assert calib["matched_packets_count"] == 18
    assert "mean_error_db" in calib
    assert "rmse_db" in calib
    assert calib["rmse_db"] > 0.0
    assert "recommended_canopy_adjustment_db" in calib
    assert "recommended_clutter_db_per_km" in calib
    assert len(calib["matches"]) == 18

    # Verify GET /api/telemetry/sample endpoint
    sample_resp = client.get("/api/telemetry/sample")
    assert sample_resp.status_code == 200
    sample_data = sample_resp.json()
    assert sample_data["ok"] is True
    assert "VT-MANS-01" in sample_data["sample"]


def test_solar_simulation_lto_vs_lifepo4_cold_charging(client: TestClient) -> None:
    """Verify POST /api/solar/simulate returns WinterSurvivalReport with LTO vs LiFePO4 cold differences."""
    lat = 44.5437
    lon = -72.8143

    # LTO Simulation (-30°C cold charging)
    resp_lto = client.post(
        "/api/solar/simulate",
        json={
            "site_id": "VT-MANS-01",
            "lat": lat,
            "lon": lon,
            "panel_watts": 10.0,
            "battery_chemistry": "lto",
            "battery_capacity_wh": 24.0,
            "radio_power_mw": 45.0,
            "consecutive_cloudy_days": 5,
        },
    )
    assert resp_lto.status_code == 200
    lto_data = resp_lto.json()
    assert lto_data["ok"] is True
    rep_lto = lto_data["report"]
    assert rep_lto["simulation_days"] == 30
    assert rep_lto["total_generation_wh"] > 0.0
    assert rep_lto["survived_winter_streak"] is True
    assert len(rep_lto["daily_timeline"]) == 30

    # LiFePO4 Simulation (0°C cold charge lockout)
    resp_lifepo4 = client.post(
        "/api/solar/simulate",
        json={
            "site_id": "VT-MANS-01",
            "lat": lat,
            "lon": lon,
            "panel_watts": 10.0,
            "battery_chemistry": "lifepo4",
            "battery_capacity_wh": 24.0,
            "radio_power_mw": 45.0,
            "consecutive_cloudy_days": 5,
        },
    )
    assert resp_lifepo4.status_code == 200
    lifepo4_data = resp_lifepo4.json()
    assert lifepo4_data["ok"] is True
    rep_lifepo4 = lifepo4_data["report"]

    # Verify LTO harvests significantly more energy than LiFePO4 due to zero-temp lockout
    assert rep_lto["total_generation_wh"] > rep_lifepo4["total_generation_wh"]
    assert rep_lto["min_state_of_charge_pct"] > rep_lifepo4["min_state_of_charge_pct"]


def test_get_sites_bounding_box_filtering_and_dynamic_fuzzy_loading(
    client: TestClient,
) -> None:
    """Verify GET /api/sites filters by bounding box and fuzzy-loads regional candidates."""
    # 1. Query bounding box in Chittenden County
    resp = client.get(
        "/api/sites?min_lat=44.4&max_lat=44.7&min_lon=-73.3&max_lon=-72.7"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] > 0
    assert data["count"] == len(data["sites"])
    for site in data["sites"]:
        assert 44.4 <= site["lat"] <= 44.7
        assert -73.3 <= site["lon"] <= -72.7

    # 2. Query bounding box in Washington County (initially 0 candidates in registry)
    # The registry has < 5 candidates, so it should dynamically fuzzy-load from 14-county fixtures
    wash_resp = client.get(
        "/api/sites?min_lat=44.1&max_lat=44.4&min_lon=-72.7&max_lon=-72.4"
    )
    assert wash_resp.status_code == 200
    wash_data = wash_resp.json()
    assert wash_data["ok"] is True
    assert wash_data["count"] >= 1
    wash_site_ids = {s["site_id"] for s in wash_data["sites"]}
    assert "VT-WAS-02" in wash_site_ids or any(
        s["site_id"].startswith("VT-WAS") for s in wash_data["sites"]
    )
    for site in wash_data["sites"]:
        assert 44.1 <= site["lat"] <= 44.4
        assert -72.7 <= site["lon"] <= -72.4

    # 3. Verify newly seeded sites are persisted in LivingMeshRegistry
    all_sites = client.get("/api/sites").json()
    all_ids = {s["site_id"] for s in all_sites["sites"]}
    for site_id in wash_site_ids:
        assert site_id in all_ids


def test_get_map_layers_statewide(client: TestClient) -> None:
    """Verify GET /api/map/layers statewide returns all vector layers and null bounds."""
    resp = client.get("/api/map/layers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    layers = data["layers"]

    assert layers["bounds"] is None
    for key in (
        "lake_champlain",
        "lakes",
        "rivers",
        "highways",
        "county_borders",
        "summits",
        "reference_towns",
        "state_border",
    ):
        assert key in layers

    assert len(layers["county_borders"]) > 0
    assert len(layers["summits"]) > 0
    assert len(layers["reference_towns"]) > 0
    assert len(layers["rivers"]) > 0
    assert len(layers["lakes"]) > 0
    assert layers["lake_champlain"] is not None

    # Partial bounding box query parameters should fall back to statewide (bounds=None)
    partial_resp = client.get("/api/map/layers?min_lat=44.0&max_lat=45.0")
    assert partial_resp.status_code == 200
    assert partial_resp.json()["layers"]["bounds"] is None


def test_get_map_layers_with_bounding_box(client: TestClient) -> None:
    """Verify GET /api/map/layers with bounding box query parameters filters to active bbox."""
    statewide_resp = client.get("/api/map/layers")
    statewide_layers = statewide_resp.json()["layers"]

    min_lat, max_lat = 44.4, 44.6
    min_lon, max_lon = -73.3, -73.0

    resp = client.get(
        f"/api/map/layers?min_lat={min_lat}&max_lat={max_lat}&min_lon={min_lon}&max_lon={max_lon}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    layers = data["layers"]

    assert layers["bounds"] is not None
    assert layers["bounds"]["min_lat"] == min_lat
    assert layers["bounds"]["max_lat"] == max_lat
    assert layers["bounds"]["min_lon"] == min_lon
    assert layers["bounds"]["max_lon"] == max_lon

    # Filtered collections should be a subset of statewide
    assert len(layers["summits"]) < len(statewide_layers["summits"])
    assert len(layers["reference_towns"]) < len(statewide_layers["reference_towns"])

    # All filtered summits must lie strictly within the active bounding box
    for summit in layers["summits"].values():
        assert min_lat <= summit["lat"] <= max_lat
        assert min_lon <= summit["lon"] <= max_lon

    # All filtered reference towns must lie strictly within the active bounding box
    for town in layers["reference_towns"].values():
        assert min_lat <= town["lat"] <= max_lat
        assert min_lon <= town["lon"] <= max_lon


def test_get_map_minimap(client: TestClient) -> None:
    """Verify GET /api/map/minimap returns 200 with the 55-point state border and Vermont bounds."""
    resp = client.get("/api/map/minimap")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    # Validate state_border structure and 55-point vertex count
    border = data["state_border"]
    assert border["type"] == "Feature"
    assert border["id"] == "vermont_state_border"
    coordinates = border["coordinates"]
    assert len(coordinates) == 55
    # Verify polygon is closed (first vertex matches last vertex)
    assert coordinates[0] == coordinates[-1]

    # Validate state bounding box coordinates
    bounds = data["bounds"]
    assert bounds["min_lat"] == pytest.approx(42.7269, abs=1e-4)
    assert bounds["max_lat"] == pytest.approx(45.0131, abs=1e-4)
    assert bounds["min_lon"] == pytest.approx(-73.4379, abs=1e-4)
    assert bounds["max_lon"] == pytest.approx(-71.5033, abs=1e-4)


def test_post_viewshed_radial_polygon(client: TestClient) -> None:
    """Verify POST /api/viewshed returns elevation-occluded polygon with 360-degree radials."""
    resp = client.post(
        "/api/viewshed",
        json={
            "site_id": "VT-PEAK-01",
            "num_radials": 36,
            "max_range_km": 40.0,
            "hardware_preset": "RAK4631_SOLAR",
            "protocol_profile": "MESHTASTIC_LONGFAST",
            "season_profile": "WINTER_LEAF_OFF",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    vs = data["viewshed"]
    assert vs["origin_site_id"] == "VT-PEAK-01"
    assert vs["num_radials"] == 36
    assert len(vs["los_polygon"]) == 37
    assert len(vs["diffracted_polygon"]) == 37
    assert vs["los_polygon"][0] == vs["los_polygon"][-1]
    assert vs["diffracted_polygon"][0] == vs["diffracted_polygon"][-1]
    assert vs["los_area_sq_km"] > 0.0
    assert vs["diffracted_area_sq_km"] >= vs["los_area_sq_km"]


def test_export_gpx_and_kml_endpoints(client: TestClient) -> None:
    """Verify GET /api/export/gpx and /api/export/kml return valid XML documents."""
    resp_gpx = client.get("/api/export/gpx")
    assert resp_gpx.status_code == 200
    assert resp_gpx.headers["content-type"].startswith("application/gpx+xml")
    assert "<gpx" in resp_gpx.text
    assert "</gpx>" in resp_gpx.text

    resp_kml = client.get("/api/export/kml")
    assert resp_kml.status_code == 200
    assert "kml" in resp_kml.headers["content-type"]
    assert "<kml" in resp_kml.text
    assert "</kml>" in resp_kml.text


def test_post_mesh_route_endpoint(client: TestClient) -> None:
    """Verify POST /api/mesh/route computes optimal multi-hop mesh packet route."""
    resp = client.post(
        "/api/mesh/route",
        json={
            "origin_site_id": "VT-PEAK-01",
            "destination_site_id": "VT-RUT-01",
            "max_hops": 3,
            "min_link_margin_db": 0.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    route = data["route"]
    assert route["route_found"] is True
    assert route["origin_id"] == "VT-PEAK-01"
    assert route["destination_id"] == "VT-RUT-01"
    assert len(route["legs"]) >= 1


def test_create_custom_site_endpoint(client: TestClient) -> None:
    """Verify POST /api/sites/custom creates a user node and appears in site list and snapshots."""
    resp = client.post(
        "/api/sites/custom",
        json={
            "name": "Shelburne Hill Silo",
            "lat": 44.3850,
            "lon": -73.2100,
            "elevation_m": 120.0,
            "mast_height_m": 14.0,
            "site_type": "silo",
            "hardware_preset": "RAK4631_SOLAR",
            "notes": "Farm silo rooftop clamp",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    site = data["site"]
    assert site["name"] == "Shelburne Hill Silo"
    assert site["site_type"] == "silo"
    assert site["elevation_m"] == 120.0
    assert site["mast_height_m"] == 14.0
    assert site["site_id"].startswith("USER-")

    # Verify site appears in /api/sites
    sites_resp = client.get("/api/sites")
    assert sites_resp.status_code == 200
    all_sites = sites_resp.json()["sites"]
    assert any(s["site_id"] == site["site_id"] for s in all_sites)


def test_get_link_survey_dossier_endpoint(client: TestClient) -> None:
    """Verify GET /api/survey/{source_id}/{target_id} returns printable link survey HTML."""
    resp = client.get("/api/survey/HOME/VT-PEAK-01")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "RF Link Engineering Survey Dossier" in resp.text
    assert "Mount Mansfield" in resp.text
    assert "Free Space (FSPL)" in resp.text
    assert "Field Deployment Pre-Flight Checklist" in resp.text


def test_advisor_role_airtime_endpoint(client: TestClient) -> None:
    """Verify POST /api/advisor/role-airtime returns recommendation, airtime, and isolation."""
    # 1. High summit site gets ROUTER
    resp_summit = client.post(
        "/api/advisor/role-airtime",
        json={
            "site_id": "VT-PEAK-01",
            "exposed_population": 15000,
            "overlapping_router_count": 0,
            "protocol_family": "Meshtastic",
        },
    )
    assert resp_summit.status_code == 200
    data_summit = resp_summit.json()
    assert data_summit["ok"] is True
    assert data_summit["recommendation"]["recommended_role"] == "ROUTER"
    assert data_summit["forecast"]["expected_nodes"] >= 0
    assert data_summit["isolation_db"] > 0

    # 2. Residential low-mast custom location gets demoted to CLIENT
    resp_home = client.post(
        "/api/advisor/role-airtime",
        json={
            "lat": 44.4900,
            "lon": -73.1100,
            "elevation_m": 105.0,
            "mast_height_m": 4.0,
            "exposed_population": 3000,
            "overlapping_router_count": 1,
            "protocol_family": "Meshtastic",
        },
    )
    assert resp_home.status_code == 200
    data_home = resp_home.json()
    assert data_home["ok"] is True
    assert data_home["recommendation"]["recommended_role"] == "CLIENT"


def test_advisor_backhaul_endpoint(client: TestClient) -> None:
    """Verify POST /api/advisor/backhaul recommends backhaul architecture and RF decoupling."""
    resp = client.post(
        "/api/advisor/backhaul",
        json={
            "source_site_id": "VT-PEAK-01",
            "target_site_id": "VT-PEAK-05",
            "channel_utilization_pct": 12.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    rec = data["recommendation"]
    assert rec["architecture"] in ("direct_lora", "dual_radio_pi_bridge", "microwave_ip_5_8ghz")
    assert rec["required_vertical_isolation_m"] >= 3.0
    assert len(rec["notes"]) >= 1


def test_site_provisioning_endpoints(client: TestClient) -> None:
    """Verify GET and POST /api/provision/{site_id} generate configurations and protect secret PSK."""
    # 1. GET meshtastic provisioning
    resp_get = client.get("/api/provision/VT-PEAK-01?target=meshtastic&channel_name=MeshScout")
    assert resp_get.status_code == 200
    data_get = resp_get.json()
    assert data_get["ok"] is True
    payload_get = data_get["payload"]
    assert payload_get["target"] == "meshtastic"
    assert payload_get["channel_name"] == "MeshScout"
    assert "<svg" in payload_get["inline_svg_qr"]
    assert len(payload_get["cli_commands"]) >= 1

    # 2. GET meshcore provisioning
    resp_mc = client.get("/api/provision/VT-PEAK-01?target=meshcore&channel_name=CoreNet")
    assert resp_mc.status_code == 200
    assert resp_mc.json()["payload"]["target"] == "meshcore"

    # 3. POST provisioning with private PSK
    secret_psk = "TopSecretOperatorKey987654321"
    resp_post = client.post(
        "/api/provision/VT-PEAK-01",
        json={
            "target": "meshtastic",
            "channel_name": "EmergencyOps",
            "psk": secret_psk,
        },
    )
    assert resp_post.status_code == 200
    data_post = resp_post.json()
    assert data_post["ok"] is True
    payload_post = data_post["payload"]
    assert payload_post["channel_name"] == "EmergencyOps"
    assert "<svg" in payload_post["inline_svg_qr"]

    # Invariant: Secret PSK must never appear in raw text of API response
    assert secret_psk not in resp_post.text


def test_mqtt_gap_analysis_endpoint(client: TestClient) -> None:
    """Verify POST /api/mqtt/gap-analysis parses telemetry and identifies unobserved town gaps."""
    resp = client.post(
        "/api/mqtt/gap-analysis",
        json={
            "coverage_radius_km": 8.0,
            "use_fixture": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    report = data["report"]
    assert report["total_towns_checked"] > 0
    assert report["observed_towns_count"] > 0
    assert report["unobserved_towns_count"] > 0
    assert isinstance(report["unobserved_gaps"], list)
    assert isinstance(report["ranked_solution_sites"], list)


def test_community_site_proposal_success_and_url_validation(client: TestClient) -> None:
    """Verify POST /api/sites/propose creates COMM- candidate node with source_url."""
    resp = client.post(
        "/api/sites/propose",
        json={
            "name": "Jericho Hill Research Tower",
            "lat": 44.5020,
            "lon": -72.9980,
            "elevation_m": 310.0,
            "height_agl_m": 15.0,
            "site_type": "research_tower",
            "owner": "VT Mesh Research Group",
            "notes": "Panoramic ridge candidate",
            "source_url": "https://wireless2.fcc.gov/example",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    node = data["node"]
    assert node["site_id"].startswith("COMM-")
    assert node["name"] == "Jericho Hill Research Tower"
    assert node["status"] == "candidate"
    assert node["site_type"] == "research_tower"
    assert node["owner"] == "VT Mesh Research Group"
    assert node["source_url"] == "https://wireless2.fcc.gov/example"

    # Verify site appears in /api/sites
    sites_resp = client.get("/api/sites")
    assert sites_resp.status_code == 200
    all_sites = sites_resp.json()["sites"]
    found = [s for s in all_sites if s["site_id"] == node["site_id"]]
    assert len(found) == 1
    assert found[0]["source_url"] == "https://wireless2.fcc.gov/example"


def test_community_site_proposal_rejects_javascript_and_invalid_urls(client: TestClient) -> None:
    """Verify POST /api/sites/propose rejects javascript: and non-http(s) source_url."""
    # javascript: scheme
    resp_js = client.post(
        "/api/sites/propose",
        json={
            "name": "XSS Probe Site",
            "lat": 44.5020,
            "lon": -72.9980,
            "source_url": "javascript:alert('pwned')",
        },
    )
    assert resp_js.status_code == 400
    assert "Invalid source_url" in resp_js.json()["detail"]

    # JAVASCRIPT: mixed case
    resp_js_upper = client.post(
        "/api/sites/propose",
        json={
            "name": "XSS Upper Probe Site",
            "lat": 44.5020,
            "lon": -72.9980,
            "source_url": "JAVASCRIPT:void(0)",
        },
    )
    assert resp_js_upper.status_code == 400

    # ftp:// scheme
    resp_ftp = client.post(
        "/api/sites/propose",
        json={
            "name": "FTP Probe Site",
            "lat": 44.5020,
            "lon": -72.9980,
            "source_url": "ftp://files.example.com/site",
        },
    )
    assert resp_ftp.status_code == 400


def test_site_status_accepts_dismantled_and_formats_error_message(client: TestClient) -> None:
    """Verify POST /api/sites/status accepts 'dismantled' and mentions dismantled on invalid status."""
    # 1. Update site to dismantled
    resp = client.post(
        "/api/sites/status",
        json={
            "site_id": "VT-PEAK-01",
            "status": "dismantled",
            "notes": "Decommissioned mountain summit node",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["node"]["status"] == "dismantled"

    # 2. Invalid status error message
    bad_resp = client.post(
        "/api/sites/status",
        json={
            "site_id": "VT-PEAK-01",
            "status": "demolished",
        },
    )
    assert bad_resp.status_code == 400
    assert (
        bad_resp.json()["detail"]
        == "Invalid status 'demolished'. Expected candidate, testing, active_on_air, blocked, or dismantled."
    )


def test_optimize_backbone_excludes_dismantled_towers(client: TestClient) -> None:
    """Verify POST /api/optimize excludes towers marked as dismantled alongside blocked."""
    target_id = "VT-PEAK-01"

    # Set VT-PEAK-01 to dismantled
    upd = client.post(
        "/api/sites/status",
        json={"site_id": target_id, "status": "dismantled"},
    )
    assert upd.status_code == 200
    assert upd.json()["node"]["status"] == "dismantled"

    # Run optimizer
    opt_resp = client.post("/api/optimize", json={"min_coverage": 0.90, "max_repeaters": 5})
    assert opt_resp.status_code == 200
    opt_data = opt_resp.json()
    assert opt_data["ok"] is True
    selected_ids = [s["site_id"] for s in opt_data["selected_repeaters"]]
    assert target_id not in selected_ids


def test_import_snapshot_enforces_500_node_cap_and_url_validation(client: TestClient) -> None:
    """Verify POST /api/import/snapshot rejects >500 nodes and javascript: source_url."""
    # 1. Exceed 500 node cap (501 nodes)
    nodes_501 = [
        {
            "site_id": f"TEST-{i:04d}",
            "name": f"Node {i}",
            "coordinate": {"lat": 44.4 + (i * 0.0001), "lon": -73.1, "elevation_m": 100.0},
            "height_agl_m": 10.0,
            "site_type": "custom",
            "status": "candidate",
            "hardware_preset": "RAK4631_SOLAR",
            "owner": "User",
            "is_public_land": False,
            "notes": "",
            "privacy_fuzzed": False,
        }
        for i in range(501)
    ]
    resp_501 = client.post("/api/import/snapshot", json={"nodes": nodes_501})
    assert resp_501.status_code == 400
    assert "exceeding maximum limit of 500 nodes" in resp_501.json()["detail"]

    # 2. Reject javascript: URL in snapshot node
    bad_url_node = [
        {
            "site_id": "XSS-SNAP-01",
            "name": "XSS Snapshot Node",
            "coordinate": {"lat": 44.5, "lon": -73.2, "elevation_m": 100.0},
            "height_agl_m": 10.0,
            "site_type": "custom",
            "status": "candidate",
            "hardware_preset": "RAK4631_SOLAR",
            "owner": "User",
            "is_public_land": False,
            "notes": "",
            "privacy_fuzzed": False,
            "source_url": "javascript:alert(1)",
        }
    ]
    resp_xss = client.post("/api/import/snapshot", json={"nodes": bad_url_node})
    assert resp_xss.status_code == 400
    assert "Invalid source_url" in resp_xss.json()["detail"]

    # 3. Valid import under 500 nodes with valid http/https URLs
    valid_nodes = [
        {
            "site_id": "COMM-SNAP-01",
            "name": "Valid Community Node",
            "coordinate": {"lat": 44.51, "lon": -73.18, "elevation_m": 150.0},
            "height_agl_m": 12.0,
            "site_type": "custom",
            "status": "candidate",
            "hardware_preset": "RAK4631_SOLAR",
            "owner": "Community",
            "is_public_land": False,
            "notes": "Verified snapshot import node",
            "privacy_fuzzed": False,
            "source_url": "https://vermontmesh.org/nodes/01",
            "updated_at": "2026-10-29T15:00:00Z",
        }
    ]
    resp_good = client.post("/api/import/snapshot", json={"nodes": valid_nodes})
    assert resp_good.status_code == 200
    assert resp_good.json()["ok"] is True
    assert resp_good.json()["imported_count"] == 1


def test_workbench_ui_community_proposal_and_dismantled_elements(client: TestClient) -> None:
    """Verify HTML, CSS, and JS include community proposal, import pack, and dismantled elements."""
    html_resp = client.get("/")
    assert html_resp.status_code == 200
    assert "propose-site-btn" in html_resp.text
    assert "import-pack-btn" in html_resp.text
    assert "proposal-modal" in html_resp.text
    assert "import-pack-modal" in html_resp.text
    assert "filter-status-select" in html_resp.text
    assert "dismantled" in html_resp.text

    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    assert "status-dismantled" in css_resp.text
    assert "#proposal-modal" in css_resp.text
    assert "#import-pack-modal" in css_resp.text

    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert 'dismantled: "oklch(0.50 0.04 30)"' in js_resp.text
    assert "[DISMANTLED]" in js_resp.text
    assert "/api/sites/propose" in js_resp.text


def test_airgap_vendor_assets_and_no_external_resources(client: TestClient) -> None:
    """Verify index.html contains no external script/link tags and vendor assets are served."""
    resp = client.get("/")
    assert resp.status_code == 200
    html_content = resp.text

    import re
    script_sources = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    link_hrefs = re.findall(r'<link[^>]+href=["\']([^"\']+)["\']', html_content, re.IGNORECASE)

    external_domains = ["unpkg.com", "cdnjs", "jsdelivr.net", "googleapis.com", "cloudflare.com"]
    for src in script_sources:
        for domain in external_domains:
            assert domain not in src.lower(), f"External script detected: {src}"
        assert not src.startswith("http://") and not src.startswith("https://") and not src.startswith("//"), (
            f"External script protocol detected: {src}"
        )

    for href in link_hrefs:
        for domain in external_domains:
            assert domain not in href.lower(), f"External link detected: {href}"
        assert not href.startswith("http://") and not href.startswith("https://") and not href.startswith("//"), (
            f"External link protocol detected: {href}"
        )

    leaflet_js_resp = client.get("/static/vendor/leaflet/leaflet.js")
    assert leaflet_js_resp.status_code == 200
    assert "javascript" in leaflet_js_resp.headers.get("content-type", "").lower()
    assert "Leaflet" in leaflet_js_resp.text
    assert len(leaflet_js_resp.text) > 10000


def test_stage_field_kit_dry_run_estimates(client: TestClient) -> None:
    """Verify POST /api/stage/field-kit with dry_run=True returns 200 with size and tile estimates."""
    payload = {
        "state": "VT",
        "buffer_km": 20.0,
        "min_zoom": 7,
        "max_zoom": 12,
        "include_dem": True,
        "dry_run": True,
    }
    resp = client.post("/api/stage/field-kit", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert "summary" in data
    assert "output_dir" in data
    summary = data["summary"]
    assert "total_tiles" in summary or "estimated_tiles" in summary or "estimates" in summary
    assert "est_bytes" in summary or "estimated_size_mb" in summary or "total_estimated_mb" in summary or "estimates" in summary


def test_stage_field_kit_full_staging_launchers(client: TestClient, tmp_path: Path) -> None:
    """Verify POST /api/stage/field-kit with dry_run=False creates launchers and docs in target directory."""
    target_dir = tmp_path / "field_kit_usb"
    payload = {
        "state": "VT",
        "target_directory": str(target_dir),
        "buffer_km": 15.0,
        "min_zoom": 7,
        "max_zoom": 10,
        "include_dem": True,
        "dry_run": False,
    }
    resp = client.post("/api/stage/field-kit", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["dry_run"] is False
    assert data["output_dir"] == str(target_dir)

    bat_file = target_dir / "Start_MeshScout.bat"
    sh_file = target_dir / "Start_MeshScout.sh"
    readme_file = target_dir / "README_FIELD_OPS.txt"

    assert bat_file.is_file(), f"Expected launcher missing: {bat_file}"
    assert sh_file.is_file(), f"Expected launcher missing: {sh_file}"
    assert readme_file.is_file(), f"Expected doc missing: {readme_file}"

    bat_content = bat_file.read_text(encoding="utf-8")
    assert "MeshScout Tactical Field Kit" in bat_content
    assert "python -m meshscout.cli serve" in bat_content
    assert "8080" in bat_content

    sh_content = sh_file.read_text(encoding="utf-8")
    assert "#!/usr/bin/env bash" in sh_content
    assert "python3 -m meshscout.cli serve" in sh_content
    assert "8080" in sh_content

    readme_content = readme_file.read_text(encoding="utf-8")
    assert "OFFLINE TACTICAL FIELD KIT" in readme_content


def test_workbench_ui_fieldkit_modal_and_controls(client: TestClient) -> None:
    """Verify index.html and app.js contain the Field Kit USB provisioner button, modal, and event hooks."""
    html_resp = client.get("/")
    assert html_resp.status_code == 200
    html_text = html_resp.text

    assert 'id="fieldkit-open-btn"' in html_text
    assert "header-actions" in html_text
    assert 'id="fieldkit-modal"' in html_text
    assert "modal hidden" in html_text
    assert "STAGE OFFLINE FIELD KIT // USB PROVISIONER" in html_text
    assert 'id="fieldkit-drive-select"' in html_text
    assert 'id="fieldkit-custom-path"' in html_text
    assert 'id="fieldkit-state-select"' in html_text
    assert 'id="fieldkit-buffer"' in html_text
    assert 'id="fieldkit-zoom"' in html_text
    assert 'id="fieldkit-dem"' in html_text
    assert 'id="fieldkit-calc-btn"' in html_text
    assert 'id="fieldkit-stage-btn"' in html_text
    assert 'id="fieldkit-close-btn"' in html_text
    assert 'id="fieldkit-log"' in html_text

    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    js_text = js_resp.text
    assert "fieldkit-open-btn" in js_text
    assert "/api/system/drives" in js_text
    assert "/api/stage/field-kit" in js_text
    assert "fieldkit-drive-select" in js_text
    assert "fieldkit-custom-path" in js_text
    assert "fieldkit-calc-btn" in js_text
    assert "fieldkit-stage-btn" in js_text


def test_civic_tower_layers_and_search_endpoint(client: TestClient) -> None:
    """Verify HTML tower controls render and GET /api/towers/search returns expected results (TASK-1095)."""
    # 1. Verify HTML controls render in workbench root
    html_resp = client.get("/")
    assert html_resp.status_code == 200
    html = html_resp.text

    # Tower Layer Section headers and subtitle
    assert "INFRASTRUCTURE &amp; CIVIC HIGH-SITES" in html
    assert "Prioritizing Low-Friction Municipal &amp; Civic Structures" in html

    # Layer checkboxes with exact IDs and defaults
    assert 'id="layer-fire-lookouts" checked' in html or 'id="layer-fire-lookouts"' in html
    assert 'id="layer-water-towers" checked' in html or 'id="layer-water-towers"' in html
    assert 'id="layer-research-towers" checked' in html or 'id="layer-research-towers"' in html
    assert 'id="layer-silos" checked' in html or 'id="layer-silos"' in html
    assert 'id="layer-commercial-towers"' in html

    # Commercial tower should NOT be checked by default to eliminate carrier noise
    assert 'id="layer-commercial-towers" checked' not in html

    # Optimizer tab checkbox
    assert 'id="opt-include-civic-towers" checked' in html or 'id="opt-include-civic-towers"' in html
    assert "Include Civic High-Sites in Solver Candidate Pool" in html

    # Detail modal container
    assert 'id="tower-info-modal"' in html
    assert 'id="tower-info-body"' in html

    # 2. Verify GET /api/towers/search
    search_resp = client.get("/api/towers/search")
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    assert search_data["ok"] is True
    assert "towers" in search_data
    assert "count" in search_data
    assert search_data["count"] == len(search_data["towers"])
    assert search_data["count"] > 0

    # Categorical filter by types
    fire_resp = client.get("/api/towers/search?types=fire_lookout")
    assert fire_resp.status_code == 200
    fire_data = fire_resp.json()
    assert fire_data["ok"] is True
    assert fire_data["count"] > 0
    assert all(t["site_type"] == "fire_lookout" for t in fire_data["towers"])

    water_resp = client.get("/api/towers/search?types=water_tower")
    assert water_resp.status_code == 200
    water_data = water_resp.json()
    assert water_data["ok"] is True
    assert water_data["count"] > 0
    assert all(t["site_type"] == "water_tower" for t in water_data["towers"])

    # Friction tier filter
    tier1_resp = client.get("/api/towers/search?max_friction=1")
    assert tier1_resp.status_code == 200
    tier1_data = tier1_resp.json()
    assert tier1_data["ok"] is True
    assert tier1_data["count"] > 0

    # Bounding box filter
    bbox_resp = client.get(
        "/api/towers/search?min_lat=44.0&max_lat=45.0&min_lon=-73.5&max_lon=-72.0"
    )
    assert bbox_resp.status_code == 200
    bbox_data = bbox_resp.json()
    assert bbox_data["ok"] is True
    for t in bbox_data["towers"]:
        loc = t.get("location") or {}
        lat = loc.get("lat", t.get("lat"))
        lon = loc.get("lon", t.get("lon"))
        assert 44.0 <= lat <= 45.0
        assert -73.5 <= lon <= -72.0

    # 3. Verify promoting a tower to Living Mesh Registry via POST /api/sites/custom
    sample_tower = search_data["towers"][0]
    loc = sample_tower.get("location") or {}
    post_resp = client.post(
        "/api/sites/custom",
        json={
            "name": f"Civic Candidate: {sample_tower['name']}",
            "lat": loc.get("lat", 44.5),
            "lon": loc.get("lon", -73.0),
            "elevation_m": loc.get("elevation_m", 250.0),
            "mast_height_m": sample_tower.get("mast_height_m", 15.0),
            "site_type": sample_tower.get("site_type", "fire_lookout"),
            "notes": "Added from Civic High-Sites test",
            "status": "candidate",
        },
    )
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    assert post_data["ok"] is True
    assert "site" in post_data or "site_id" in post_data

    # Verify candidate appears in living registry
    sites_resp = client.get("/api/sites")
    assert sites_resp.status_code == 200
    living_sites = sites_resp.json()["sites"]
    assert any(
        s["name"] == f"Civic Candidate: {sample_tower['name']}" for s in living_sites
    )


def test_workbench_ui_telemetry_layers_and_toggles(client: TestClient) -> None:
    """Verify workbench serves Meshtastic & MeshCore multi-layer controls and modal markup (TASK-1101)."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="layer-meshtastic-nodes"' in html
    assert 'id="layer-meshcore-nodes"' in html
    assert 'id="layer-coverage-gaps"' in html
    assert 'id="telemetry-node-modal"' in html
    assert 'id="telemetry-node-title"' in html
    assert 'id="close-telemetry-node-modal-btn"' in html


def test_version_dynamic_status_and_commercial_towers_seeded(client: TestClient) -> None:
    """Verify /api/status returns active version 0.12.1 and commercial towers are seeded."""
    from meshscout import __version__

    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["ok"] is True
    assert status_data["version"] == __version__
    assert status_data["version"] == "0.14.0"

    # Verify commercial towers (communications_tower) are present for layer toggle
    comm_resp = client.get("/api/towers/search?types=communications_tower")
    assert comm_resp.status_code == 200
    comm_data = comm_resp.json()
    assert comm_data["ok"] is True
    assert comm_data["count"] >= 50
    assert all(t["site_type"] == "communications_tower" for t in comm_data["towers"])


def test_workbench_ui_tactical_pin_and_whatif_controls(client: TestClient) -> None:
    """TASK-1106: Verify drop pin button, coverage layers, tactical pin modal, and what-if drawer."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Drop Pin button
    assert 'id="drop-pin-btn"' in html
    assert "📍 Drop Pin" in html

    # 2. Topographic coverage toggles
    assert 'id="layer-active-coverage"' in html
    assert "Active Network Coverage" in html
    assert 'id="layer-whatif-coverage"' in html
    assert "What-If Coverage" in html

    # 3. Tactical Pin Modal / Floating Card
    assert 'id="tactical-pin-card"' in html
    assert "TACTICAL AD-HOC PIN // COMMUNITY LOCATION" in html
    assert 'id="pin-name"' in html
    assert 'id="pin-coords"' in html
    assert 'id="pin-elevation"' in html
    assert 'id="pin-mast-height"' in html
    assert 'id="pin-site-type"' in html
    assert 'id="pin-include-whatif"' in html
    assert 'id="pin-simulate-btn"' in html
    assert 'id="pin-save-btn"' in html
    assert 'id="pin-remove-btn"' in html
    assert 'id="pin-close-btn"' in html

    # 4. What-If Scenario Floating Drawer & Universal Clear Buttons
    assert 'id="whatif-scenario-panel"' in html
    assert 'id="whatif-site-count"' in html
    assert 'id="whatif-total-area"' in html
    assert 'id="whatif-towns-count"' in html
    assert 'id="whatif-backhaul-status"' in html
    assert 'id="whatif-clear-btn"' in html
    assert 'id="clear-selection-btn"' in html
    assert 'id="map-corner-clear-btn"' in html

    # 5. CSS and JS Verification
    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    assert "#drop-pin-btn.active" in css_resp.text
    assert ".crosshair-cursor" in css_resp.text
    assert "#tactical-pin-card" in css_resp.text
    assert "#whatif-scenario-panel" in css_resp.text
    assert ".whatif-badge" in css_resp.text
    assert ".map-corner-clear-btn" in css_resp.text
    assert "leaflet-coveragePane-pane" in css_resp.text

    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "whatIfSiteIds" in js_resp.text
    assert "adHocPins" in js_resp.text
    assert "toggleDropPinMode" in js_resp.text
    assert "runWhatIfCompositeViewshed" in js_resp.text
    assert "runActiveNetworkViewshed" in js_resp.text
    assert "clearAllSelectionsAndPlanning" in js_resp.text
    assert "coveragePane" in js_resp.text


def test_workbench_ui_backhaul_map_pick_and_crosshair(client: TestClient) -> None:
    """TASK-1110: Verify unified backhaul map pick interceptor, crosshair cursor cue, and interactive popup actions."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "backhaul-pick-a-btn" in resp.text
    assert "backhaul-pick-b-btn" in resp.text
    assert "backhaul-pick-indicator" in resp.text

    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    assert ".picking-active" in css_resp.text
    assert "cursor: crosshair !important;" in css_resp.text
    assert ".tower-pick-node-a-btn" in css_resp.text
    assert ".tower-pick-node-b-btn" in css_resp.text

    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "handleUniversalMapPick" in js_resp.text
    assert "handlePopupPickNode" in js_resp.text
    assert "picking-active" in js_resp.text
    assert "tower-pick-node-a-btn" in js_resp.text
    assert "tower-pick-node-b-btn" in js_resp.text
    assert "addSiteToCorridor" in js_resp.text
    assert "evaluateCorridorRoute" in js_resp.text
    assert "corridorSiteIds" in js_resp.text
    assert "Adopted via Map Pick" in js_resp.text


def test_workbench_ui_multi_hop_corridor_builder(client: TestClient) -> None:
    """TASK-1111: Verify multi-hop trunk corridor builder UI controls, styles, and route evaluation."""
    # 1. HTML Markup verification
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="backhaul-corridor-section"' in html
    assert "MULTI-HOP TRUNK CORRIDOR BUILDER" in html
    assert 'id="corridor-chain-chips"' in html
    assert 'id="corridor-eval-btn"' in html
    assert 'id="corridor-clear-btn"' in html
    assert 'id="corridor-results-card"' in html
    assert 'id="corridor-hops-tbody"' in html

    # 2. CSS Styles verification
    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    assert "#backhaul-corridor-section" in css_resp.text
    assert ".corridor-chain-chips" in css_resp.text
    assert ".corridor-chip" in css_resp.text
    assert '.corridor-chip[draggable="true"]' in css_resp.text
    assert ".corridor-chip-grip" in css_resp.text
    assert ".corridor-chip-move-btn" in css_resp.text
    assert ".corridor-results-card" in css_resp.text
    assert ".bottleneck-row" in css_resp.text
    assert ".bottleneck-tag" in css_resp.text

    # 3. JavaScript Wiring verification
    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "addSiteToCorridor" in js_resp.text
    assert "removeSiteFromCorridor" in js_resp.text
    assert "moveCorridorSite" in js_resp.text
    assert 'draggable="true"' in js_resp.text
    assert "corridor-chip-grip" in js_resp.text
    assert "corridor-chip-move-btn" in js_resp.text
    assert "renderCorridorChainChips" in js_resp.text
    assert "evaluateCorridorRoute" in js_resp.text
    assert "corridorSiteIds" in js_resp.text
    assert "leafletCorridorLines" in js_resp.text
    assert "tower-add-chain-btn" in js_resp.text
    assert "telemetry-add-chain-btn" in js_resp.text
    assert "corridor-chain-btn" in js_resp.text

    # 4. API Backend endpoint verification
    corridor_req = {
        "site_ids": ["ASR_1010001", "ASR_1010002"],
    }
    api_resp = client.post("/api/backhaul/corridor", json=corridor_req)
    assert api_resp.status_code == 200
    data = api_resp.json()
    assert data["ok"] is True
    assert "corridor" in data
    corridor = data["corridor"]
    assert corridor["total_hops"] == 1
    assert corridor["total_distance_km"] > 0
    assert len(corridor["hops"]) == 1
    assert corridor["hops"][0]["origin_site_id"] == "ASR_1010001"
    assert corridor["hops"][0]["target_site_id"] == "ASR_1010002"


def test_workbench_ui_corridor_chain_reorder_and_dnd(client: TestClient) -> None:
    """TASK-1121: Verify multi-hop corridor drag & drop and manual chain reordering."""
    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    assert '.corridor-chip[draggable="true"]' in css_resp.text
    assert ".corridor-chip.dragging" in css_resp.text
    assert ".corridor-chip.drag-over" in css_resp.text
    assert ".corridor-chip-grip" in css_resp.text
    assert ".corridor-chip-nav" in css_resp.text
    assert ".corridor-chip-move-btn" in css_resp.text

    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "moveCorridorSite" in js_resp.text
    assert 'draggable="true"' in js_resp.text
    assert "corridor-chip-grip" in js_resp.text
    assert "corridor-chip-move-btn" in js_resp.text
    assert "btn-chip-left" in js_resp.text
    assert "btn-chip-right" in js_resp.text
    assert "corridor-chip-remove" in js_resp.text


def test_workbench_ui_dedicated_chain_map_picker(client: TestClient) -> None:
    """TASK-1122: Verify dedicated [🎯 Pick on Map] chain picker mode and selection state isolation."""
    # 1. HTML button
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="corridor-pick-btn"' in resp.text
    assert "Pick on Map" in resp.text

    # 2. CSS styles
    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    assert "#corridor-pick-btn.active-picking" in css_resp.text

    # 3. JavaScript wiring
    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "corridor-pick-btn" in js_resp.text
    assert 'state.backhaulPickTarget === "chain"' in js_resp.text
    assert "Adding to Chain... (Done)" in js_resp.text
    assert "CLICK ANY TOWER/SITE ON MAP TO APPEND TO CHAIN" in js_resp.text


def test_workbench_ui_site_click_disambiguation(client: TestClient) -> None:
    """TASK-1123: Verify site click disambiguation, site popovers, and quick endpoint assignment."""
    # 1. HTML quick buttons on Selected Site Bar
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="sel-chain-btn"' in resp.text
    assert 'id="sel-node-a-btn"' in resp.text
    assert 'id="sel-node-b-btn"' in resp.text

    # 2. JavaScript wiring
    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "buildSitePopupHtml" in js_resp.text
    assert "sel-chain-btn" in js_resp.text
    assert "sel-node-a-btn" in js_resp.text
    assert "sel-node-b-btn" in js_resp.text
    assert "handleUniversalMapPick" in js_resp.text


def test_workbench_ui_leaflet_vector_overlays(client: TestClient) -> None:
    """TASK-1113: Verify Leaflet vector overlays (Graticule, County borders, Mountain Summits) in app.js and styles.css."""
    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    js = js_resp.text

    # 1. State variable declarations
    assert "leafletGraticuleLayer: null" in js or "leafletGraticuleLayer" in js
    assert "leafletCountiesLayer: null" in js or "leafletCountiesLayer" in js
    assert "leafletSummitsLayer: null" in js or "leafletSummitsLayer" in js

    # 2. Cleanup in syncLeafletMap()
    assert "if (state.leafletGraticuleLayer) {" in js
    assert "state.leafletGraticuleLayer.remove();" in js
    assert "if (state.leafletCountiesLayer) {" in js
    assert "state.leafletCountiesLayer.remove();" in js
    assert "if (state.leafletSummitsLayer) {" in js
    assert "state.leafletSummitsLayer.remove();" in js

    # 3. Maidenhead graticule rendering & calculation
    assert "state.layerVisibility.graticule" in js
    assert "state.leafletGraticuleLayer = window.L.layerGroup();" in js
    assert "function calcSquare(" in js
    assert "leaflet-graticule-label" in js
    assert "stepLat = 2.5 / 60" in js
    assert "stepLon = 5.0 / 60" in js

    # 4. County borders rendering
    assert "state.layerVisibility.counties && state.mapLayers && state.mapLayers.county_borders" in js
    assert "state.leafletCountiesLayer = window.L.layerGroup();" in js
    assert "window.L.polygon(latLngs" in js
    assert "County" in js

    # 5. Mountain summits rendering
    assert "state.layerVisibility.spine" in js
    assert "state.leafletSummitsLayer = window.L.layerGroup();" in js
    assert "leaflet-summit-marker" in js
    assert "summit-badge" in js
    assert "Mountain Summit:" in js

    # 6. CSS styles
    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    css = css_resp.text
    assert ".leaflet-graticule-label" in css
    assert "#38bdf8" in css
    assert ".leaflet-summit-marker" in css
    assert ".summit-badge" in css
    assert "#f59e0b" in css


def test_workbench_ui_layer_groups_and_collapsible_drawer(client: TestClient) -> None:
    """TASK-1114: Verify collapsible layer groups drawer, badges, vector dimming, and all 18 toggles."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Header and Collapsible Button
    assert 'id="toggle-all-layers-btn"' in html
    assert "[▾ Layers Panel]" in html
    assert "map-layer-header" in html
    assert 'id="layer-groups-container"' in html
    assert "layer-group" in html
    assert "group-title" in html

    # 2. Group Headers and Count Badges
    assert 'id="layer-group-rf"' in html
    assert 'id="rf-group-count"' in html
    assert "📡 RF &amp; TOPOLOGY" in html

    assert 'id="layer-group-tactical"' in html
    assert 'id="tactical-group-count"' in html
    assert "🎯 TACTICAL OVERLAYS" in html

    assert 'id="layer-group-vector"' in html
    assert 'id="vector-group-count"' in html
    assert "🗺️ VECTOR BASEMAP" in html
    assert "vector-only-pill" in html

    # 3. All 18 layer checkboxes verified
    expected_checkboxes = [
        "toggle-layer-towers",
        "toggle-layer-heatmap",
        "layer-active-coverage",
        "layer-whatif-coverage",
        "layer-meshtastic-nodes",
        "layer-meshcore-nodes",
        "layer-coverage-gaps",
        "layer-fire-lookouts",
        "layer-water-towers",
        "layer-research-towers",
        "layer-silos",
        "layer-commercial-towers",
        "toggle-layer-graticule",
        "toggle-layer-counties",
        "toggle-layer-spine",
        "toggle-layer-water",
        "toggle-layer-corridors",
        "toggle-layer-towns",
    ]
    assert len(expected_checkboxes) == 18
    for cb_id in expected_checkboxes:
        assert f'id="{cb_id}"' in html, f"Missing checkbox #{cb_id}"

    # 4. CSS Verification
    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    css = css_resp.text
    assert ".layer-groups-container" in css
    assert ".layer-group" in css
    assert ".layer-group-header" in css
    assert ".layer-group-body" in css
    assert ".group-count-badge" in css
    assert ".vector-only-pill" in css
    assert "#layer-group-vector.tile-overlay-active" in css
    assert ".btn-layer-collapse" in css

    # 5. JS Verification
    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    js = js_resp.text
    assert "layerGroupCollapsed" in js
    assert "updateLayerGroupCounts" in js
    assert "toggleLayerGroup" in js
    assert "toggleAllLayerGroups" in js
    assert "handleTileToggle" in js
    assert "meshscout_layers_all_collapsed" in js
    assert "meshscout_layers_rf_collapsed" in js


def test_workbench_ui_mast_height_sliders(client: TestClient) -> None:
    """Verify TASK-1116 interactive mast height sliders markup, styles, JS bindings, and API."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Markup verification
    assert 'id="mast-height-sliders-panel"' in html
    assert 'class="mast-sliders-panel"' in html
    assert 'id="origin-mast-slider"' in html
    assert 'id="target-mast-slider"' in html
    assert 'id="origin-mast-val"' in html
    assert 'id="target-mast-val"' in html
    assert 'id="fresnel-dynamic-badge"' in html
    assert 'min="3"' in html
    assert 'max="45"' in html
    assert 'step="1"' in html
    assert "ORIGIN MAST (AGL):" in html
    assert "TARGET MAST (AGL):" in html
    assert "60% FRESNEL CLEAR" in html

    # 2. CSS verification
    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    css = css_resp.text
    assert ".mast-sliders-panel" in css
    assert ".mast-slider-row" in css
    assert ".mast-slider-label" in css
    assert ".brutal-slider" in css
    assert ".mast-clearance-indicator" in css
    assert ".badge-fresnel-clear" in css
    assert ".badge-fresnel-obstructed" in css
    assert "::-webkit-slider-thumb" in css

    # 3. JavaScript state and event listeners verification
    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    js = js_resp.text
    assert "originMastHeight" in js
    assert "targetMastHeight" in js
    assert "origin-mast-slider" in js
    assert "target-mast-slider" in js
    assert "origin-mast-val" in js
    assert "target-mast-val" in js
    assert "fresnel-dynamic-badge" in js
    assert "source_mast_m" in js
    assert "target_mast_m" in js
    assert "updateMastSliders" in js
    assert "badge-fresnel-clear" in js
    assert "badge-fresnel-obstructed" in js

    # 4. API functional verification with source_mast_m and target_mast_m
    low_mast_resp = client.post(
        "/api/link",
        json={
            "source_site_id": "VT-PEAK-01",
            "target_site_id": "VT-RUT-01",
            "source_mast_m": 5.0,
            "target_mast_m": 5.0,
        },
    )
    assert low_mast_resp.status_code == 200
    low_data = low_mast_resp.json()
    assert low_data["source"]["mast_height_m"] == 5.0
    assert low_data["target"]["mast_height_m"] == 5.0

    high_mast_resp = client.post(
        "/api/link",
        json={
            "source_site_id": "VT-PEAK-01",
            "target_site_id": "VT-RUT-01",
            "source_mast_m": 35.0,
            "target_mast_m": 35.0,
        },
    )
    assert high_mast_resp.status_code == 200
    high_data = high_mast_resp.json()
    assert high_data["source"]["mast_height_m"] == 35.0
    assert high_data["target"]["mast_height_m"] == 35.0


def test_viewshed_concurrency_semaphore() -> None:
    """Verify _VIEWSHED_SEMAPHORE is configured with concurrency limit of 2 (TASK-1119)."""
    import asyncio
    from meshscout.web.app import _VIEWSHED_SEMAPHORE

    assert isinstance(_VIEWSHED_SEMAPHORE, asyncio.Semaphore)
    assert _VIEWSHED_SEMAPHORE._value == 2


def test_workbench_ui_landowner_and_solar_autonomy_modals(client: TestClient) -> None:
    """Verify TASK-1119: Landowner dossier and winter solar autonomy calculator UI elements and handlers."""
    # 1. HTML structure
    html_resp = client.get("/")
    assert html_resp.status_code == 200
    html_text = html_resp.text

    assert 'id="landowner-dossier-modal"' in html_text
    assert "[📄 LANDOWNER HOST BRIEF & EQUIPMENT MOU]" in html_text
    assert 'id="landowner-dossier-body"' in html_text
    assert 'id="print-landowner-brief-btn"' in html_text
    assert "[🖨️ Print / Save PDF]" in html_text
    assert 'id="close-landowner-modal-btn"' in html_text

    assert 'id="solar-autonomy-modal"' in html_text
    assert "[☀️ WINTER SOLAR & BATTERY AUTONOMY CALCULATOR]" in html_text
    assert 'id="solar-autonomy-body"' in html_text
    assert 'id="close-solar-modal-btn"' in html_text

    assert 'id="sel-landowner-brief-btn"' in html_text
    assert 'id="sel-solar-sizing-btn"' in html_text
    assert 'id="pin-landowner-brief-btn"' in html_text
    assert 'id="pin-solar-sizing-btn"' in html_text

    # 2. JavaScript logic
    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    js_text = js_resp.text

    assert "openLandownerModal" in js_text
    assert "openSolarModal" in js_text
    assert "closeLandownerModal" in js_text
    assert "closeSolarModal" in js_text
    assert "/api/reports/landowner" in js_text
    assert "/api/solar/site" in js_text
    assert "tower-landowner-brief-btn" in js_text
    assert "tower-solar-sizing-btn" in js_text
    assert "sel-landowner-brief-btn" in js_text
    assert "sel-solar-sizing-btn" in js_text
    assert "pin-landowner-brief-btn" in js_text
    assert "pin-solar-sizing-btn" in js_text
    assert "window.open('/api/reports/landowner/' + siteId + '?format=html', '_blank')" in js_text
    assert "Recommended Panel (W)" in js_text
    assert "Recommended Battery (Wh)" in js_text
    assert "Winter Survival Verdict" in js_text
    assert "Cold Charging Lockout Threshold" in js_text
    assert "0°C (32°F)" in js_text
    assert "-30°C (-22°F)" in js_text

    # 3. CSS styling
    css_resp = client.get("/static/styles.css")
    assert css_resp.status_code == 200
    css_text = css_resp.text

    assert "#landowner-dossier-modal" in css_text
    assert "#solar-autonomy-modal" in css_text
    assert ".solar-comparison-grid" in css_text
    assert ".solar-chem-card" in css_text
    assert ".chem-badge-lifepo4" in css_text
    assert ".chem-badge-lto" in css_text

    # 4. Backend endpoints backing the modals
    lo_resp = client.get("/api/reports/landowner/VT-PEAK-01")
    assert lo_resp.status_code == 200
    lo_data = lo_resp.json()
    assert lo_data["ok"] is True
    assert "Mount Mansfield" in lo_data["site_name"]
    assert "html" in lo_data

    solar_resp = client.get("/api/solar/site/VT-PEAK-01")
    assert solar_resp.status_code == 200
    solar_data = solar_resp.json()
    assert solar_data["ok"] is True
    assert "lifepo4" in solar_data
    assert "lto" in solar_data
    assert "recommended_panel_watts" in solar_data["lifepo4"]
    assert "recommended_battery_wh" in solar_data["lto"]


def test_web_api_towers_search_zoom_and_region(client: TestClient) -> None:
    """Verify GET /api/towers/search accepts zoom and region query parameters (TASK-1136)."""
    resp = client.get("/api/towers/search?zoom=9&region=VT")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "count" in data
    assert "towers" in data


def test_web_api_towers_ingest_ised_sms(client: TestClient) -> None:
    """Verify POST /api/towers/ingest supports Canadian ISED SMS source dataset (TASK-1136)."""
    resp = client.post("/api/towers/ingest", json={"source": "ised_sms"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source"] in ("ised_sms", "ised")
    assert data["ingested_count"] > 0
    assert "by_friction_tier" in data


def test_web_api_attribution_endpoint(client: TestClient) -> None:
    """Verify GET /api/v1/attribution serves licenses and dataset provenance (TASK-1136)."""
    resp = client.get("/api/v1/attribution")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "sources" in data
    assert "fcc_asr" in data["sources"]
    assert "ised_sms" in data["sources"]
    assert data["count"] >= 3


def test_web_api_regions_north_america_endpoint(client: TestClient) -> None:
    """Verify GET /api/v1/regions/north-america lists all 65 states/provinces (TASK-1136)."""
    resp_all = client.get("/api/v1/regions/north-america")
    assert resp_all.status_code == 200
    data_all = resp_all.json()
    assert data_all["ok"] is True
    assert data_all["count"] >= 65
    assert len(data_all["regions"]) == data_all["count"]

    # Filter by country=CA
    resp_ca = client.get("/api/v1/regions/north-america?country=CA")
    assert resp_ca.status_code == 200
    data_ca = resp_ca.json()
    assert data_ca["ok"] is True
    assert data_ca["count"] == 13
    assert all(r["country"] == "CA" for r in data_ca["regions"])


def test_web_api_regulatory_eirp_endpoint(client: TestClient) -> None:
    """Verify GET /api/v1/regulatory/eirp computes conducted power and EIRP limits (TASK-1136)."""
    # 1. High-gain omni triggering dB-for-dB reduction warning
    resp = client.get("/api/v1/regulatory/eirp?tx_power_dbm=30.0&antenna_gain_dbi=8.0&cable_loss_db=1.2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["conducted_power_dbm"] == 28.8
    assert data["eirp_dbm"] == 36.8
    assert data["recommended_max_tx_dbm"] == 28.0
    assert len(data["warnings"]) == 1

    # 2. Canadian domain detection
    resp_ca = client.get("/api/v1/regulatory/eirp?tx_power_dbm=20.0&antenna_gain_dbi=3.0&region=CA_QC")
    assert resp_ca.status_code == 200
    data_ca = resp_ca.json()
    assert data_ca["ok"] is True
    assert data_ca["domain"] == "CA_ISED_RSS247"


def test_web_api_packs_lifecycle_and_install_stubbed_manifest(
    client: TestClient, tmp_path: Path
) -> None:
    """Verify POST /api/v1/packs/install against a stubbed manifest installs a fixture pack

    and returns row_count > 0, followed by listing and deletion (TASK-1136 Acceptance Criteria).
    """
    from unittest.mock import MagicMock, patch
    import urllib.error
    from meshscout.core.contracts import Coordinate, SiteCandidate, SiteType
    from meshscout.core.packs import build_pack_manifest, export_region_pack
    from meshscout.core.tower_registry import UnifiedTowerRegistry

    origin_dir = tmp_path / "packs_origin"
    origin_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create a genuine, valid test pack archive
    build_db_path = origin_dir / "build_tower.db"
    dummy_site = SiteCandidate(
        site_id="VT-PACK-TEST-01",
        name="Mount Philo Test Highsite",
        location=Coordinate(lat=44.2780, lon=-73.2198, elevation_m=295.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=30.0,
    )
    with UnifiedTowerRegistry(db_path=build_db_path) as build_reg:
        build_reg.upsert_tower(dummy_site, region_code="VT")
        real_pack_info = export_region_pack(
            registry=build_reg,
            region_code="VT",
            out_dir=origin_dir,
            pack_version="1.0.0",
        )

    pack_archive_path = origin_dir / f"towers-vt-{real_pack_info.pack_version}.sqlite.gz"
    assert pack_archive_path.exists()
    pack_bytes = pack_archive_path.read_bytes()

    real_pack_info.url = "http://127.0.0.1:8999/towers-vt-1.0.0.sqlite.gz"
    manifest = build_pack_manifest([real_pack_info])
    manifest_bytes = manifest.to_json().encode("utf-8")

    def mock_urlopen_handler(req: Any, timeout: float = 30.0) -> Any:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        resp = MagicMock()
        if "manifest.json" in url:
            resp.read.side_effect = [manifest_bytes, b""]
        elif "towers-vt" in url:
            resp.read.side_effect = [pack_bytes, b""]
        else:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        resp.__enter__.return_value = resp
        return resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        # 2. POST /api/v1/packs/install
        install_resp = client.post(
            "/api/v1/packs/install",
            json={
                "region_codes": ["VT"],
                "manifest_url": "http://127.0.0.1:8999/manifest.json",
                "cache_dir": str(tmp_path / "cache"),
            },
        )
        assert install_resp.status_code == 200
        install_data = install_resp.json()
        assert install_data["ok"] is True
        assert install_data["row_count"] > 0
        assert len(install_data["installed"]) == 1
        assert install_data["installed"][0]["pack_id"] == "towers-vt"

        # 3. GET /api/v1/packs
        list_resp = client.get("/api/v1/packs")
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["ok"] is True
        assert len(list_data["installed"]) >= 1
        assert any(p["pack_id"] == "towers-vt" for p in list_data["installed"])

        # 4. DELETE /api/v1/packs/{pack_id}
        del_resp = client.delete("/api/v1/packs/towers-vt")
        assert del_resp.status_code == 200
        del_data = del_resp.json()
        assert del_data["ok"] is True
        assert del_data["pack_id"] == "towers-vt"
        assert del_data["removed_rows"] > 0


def test_web_api_switch_national_region_colorado(client: TestClient) -> None:
    """Verify switching to national state outside pilot fixtures succeeds with full bounds."""
    # 1. GET /api/regions returns north_america catalog with 65 entries
    regions_resp = client.get("/api/regions")
    assert regions_resp.status_code == 200
    regions_data = regions_resp.json()
    assert "north_america" in regions_data
    assert len(regions_data["north_america"]) >= 65

    # 2. Switch to Colorado (CO)
    switch_resp = client.post("/api/regions/switch", json={"state": "CO"})
    assert switch_resp.status_code == 200
    switch_data = switch_resp.json()
    assert switch_data["ok"] is True
    assert switch_data["state"] == "CO"
    assert switch_data["bounds"]["name"] == "Colorado_Statewide"
    assert switch_data["bounds"]["min_lat"] == 36.99
    assert switch_data["bounds"]["max_lat"] == 41.01


def test_tutorial_walkthrough_covers_all_eight_tabs(client: TestClient) -> None:
    """Verify that interactive walkthrough tutorial includes steps for all 8 workbench tabs."""
    html_resp = client.get("/")
    assert html_resp.status_code == 200
    html = html_resp.text
    assert "STEP 1 OF 8" in html
    assert 'aria-valuemax="8"' in html

    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    js = js_resp.text

    assert "total: 8" in js
    assert "Regional Packs & Offline Expansion (Tab 8)" in js
    assert "RF Best Practices & MQTT Gaps (Tabs 6 & 7)" in js
    assert "Core Planning Engines (Tabs 1–5)" in js
    assert "#tab-packs-btn" in js
    assert '[data-tab="tab-advisor"]' in js









