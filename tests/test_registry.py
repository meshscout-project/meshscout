"""Unit tests for the Living Mesh SQLite Registry and 360-Degree Home Node Reach Analyzer."""

from __future__ import annotations

from pathlib import Path
import pytest

from meshscout.core.contracts import Coordinate, SiteCandidate, SiteType
from meshscout.core.registry import (
    DeploymentStatus,
    LivingMeshRegistry,
    RegisteredNode,
    WorkspacePreferences,
    compute_azimuth_bearing,
    evaluate_home_node_reach,
)


def test_workspace_preferences_default_and_persistence(tmp_path: Path) -> None:
    """Verify default Burlington preferences load and custom locations persist across instances."""
    db_file = tmp_path / "mesh_state.db"
    reg1 = LivingMeshRegistry(db_path=db_file)

    prefs = reg1.get_preferences()
    assert prefs.last_lat == pytest.approx(44.4759)
    assert prefs.last_lon == pytest.approx(-73.2121)
    assert prefs.home_name == "Burlington Home Node"
    assert prefs.last_region == "vt_chittenden"

    # Update to Montpelier, VT (or out-of-state) and save
    updated_prefs = prefs.model_copy(
        update={
            "last_lat": 44.2601,
            "last_lon": -72.5754,
            "last_elev_m": 160.0,
            "last_zoom": 13,
            "last_region": "vt_washington",
            "home_name": "Montpelier Capitol Base",
            "home_lat": 44.2601,
            "home_lon": -72.5754,
            "home_elev_m": 160.0,
            "home_height_agl_m": 12.0,
            "protocol_profile": "MESHCORE_REPEATER",
            "season_profile": "SUMMER_FOLIAGE",
        }
    )
    reg1.save_preferences(updated_prefs)

    # Re-open a fresh LivingMeshRegistry instance against the same SQLite DB
    reg2 = LivingMeshRegistry(db_path=db_file)
    reloaded = reg2.get_preferences()
    assert reloaded.last_lat == pytest.approx(44.2601)
    assert reloaded.last_lon == pytest.approx(-72.5754)
    assert reloaded.last_zoom == 13
    assert reloaded.last_region == "vt_washington"
    assert reloaded.home_name == "Montpelier Capitol Base"
    assert reloaded.home_height_agl_m == pytest.approx(12.0)
    assert reloaded.protocol_profile == "MESHCORE_REPEATER"
    assert reloaded.season_profile == "SUMMER_FOLIAGE"


def test_seed_candidates_preserves_user_modified_status_and_notes(tmp_path: Path) -> None:
    """Verify seed_candidates populates nodes and does not overwrite user-upgraded status/notes."""
    db_file = tmp_path / "mesh_state.db"
    registry = LivingMeshRegistry(db_path=db_file)

    candidates = [
        SiteCandidate(
            site_id="VT-MANS-01",
            name="Mount Mansfield Summit Ridge",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=10.0,
            notes="Initial seed note",
        ),
        SiteCandidate(
            site_id="VT-ESX-WT01",
            name="Essex Municipal Water Tower",
            location=Coordinate(lat=44.5021, lon=-73.0985, elevation_m=152.0),
            site_type=SiteType.WATER_TOWER,
            mast_height_m=28.0,
        ),
    ]

    count = registry.seed_candidates(candidates)
    assert count == 2

    # Upgrade Mount Mansfield to ACTIVE_ON_AIR with operator notes and custom preset
    res = registry.update_node_status(
        site_id="VT-MANS-01",
        status=DeploymentStatus.ACTIVE_ON_AIR,
        notes="Deployed 6dBi fiberglass omni + 30W vertical PV",
        hardware_preset="STATION_G2_CAVITY",
    )
    assert res.ok and res.value is not None
    assert res.value.status == DeploymentStatus.ACTIVE_ON_AIR

    # Re-seed with updated candidate metadata
    reseed_candidates = [
        SiteCandidate(
            site_id="VT-MANS-01",
            name="Mount Mansfield Summit Ridge",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=12.0,
            notes="Generic seed note that should not overwrite operator notes",
        ),
    ]
    registry.seed_candidates(reseed_candidates)

    nodes = {n.site_id: n for n in registry.list_nodes()}
    mansfield = nodes["VT-MANS-01"]
    assert mansfield.status == DeploymentStatus.ACTIVE_ON_AIR
    assert mansfield.notes == "Deployed 6dBi fiberglass omni + 30W vertical PV"
    assert mansfield.hardware_preset == "STATION_G2_CAVITY"
    assert mansfield.height_agl_m == pytest.approx(12.0)


def test_update_node_status_lifecycle_transitions(tmp_path: Path) -> None:
    """Verify node lifecycle transitions candidate -> testing -> active_on_air -> blocked."""
    db_file = tmp_path / "mesh_state.db"
    registry = LivingMeshRegistry(db_path=db_file)

    registry.seed_candidates(
        [
            SiteCandidate(
                site_id="VT-BOLT-01",
                name="Bolton Valley Fire Lookout",
                location=Coordinate(lat=44.4215, lon=-72.8495, elevation_m=960.0),
                site_type=SiteType.FIRE_LOOKOUT,
                mast_height_m=8.0,
            )
        ]
    )

    for next_status in (
        DeploymentStatus.TESTING,
        DeploymentStatus.ACTIVE_ON_AIR,
        DeploymentStatus.BLOCKED,
    ):
        update_res = registry.update_node_status("VT-BOLT-01", status=next_status)
        assert update_res.ok and update_res.value is not None
        assert update_res.value.status == next_status
        filtered = registry.list_nodes(status=next_status)
        assert len(filtered) == 1
        assert filtered[0].site_id == "VT-BOLT-01"

    missing_res = registry.update_node_status("NON-EXISTENT", status=DeploymentStatus.TESTING)
    assert not missing_res.ok
    assert missing_res.error is not None
    assert missing_res.error.code == "NODE_NOT_FOUND"


def test_export_and_import_snapshot_with_privacy_fuzzing(tmp_path: Path) -> None:
    """Verify club snapshot round-trip into a fresh DB and ~200m coordinate fuzzing for private sites."""
    db_source = tmp_path / "source.db"
    reg_source = LivingMeshRegistry(db_path=db_source)

    reg_source.seed_candidates(
        [
            SiteCandidate(
                site_id="VT-PUB-01",
                name="Camel's Hump State Park",
                location=Coordinate(lat=44.3195, lon=-72.8863, elevation_m=1244.0),
                site_type=SiteType.MOUNTAIN_PEAK,  # public land
                mast_height_m=4.0,
            ),
            SiteCandidate(
                site_id="VT-PRIV-01",
                name="Private Barn Silo Host",
                location=Coordinate(lat=44.481234, lon=-73.078912, elevation_m=142.6),
                site_type=SiteType.SILO,  # private land (is_public_land=False)
                mast_height_m=18.0,
            ),
        ]
    )
    reg_source.update_node_status(
        "VT-PRIV-01",
        status=DeploymentStatus.ACTIVE_ON_AIR,
        notes="Hosted on private dairy silo",
    )

    snapshot = reg_source.export_snapshot(fuzz_private_nodes=True)
    assert snapshot["fuzz_private_nodes"] is True
    assert len(snapshot["nodes"]) == 2

    db_target = tmp_path / "target.db"
    reg_target = LivingMeshRegistry(db_path=db_target)
    imp_res = reg_target.import_snapshot(snapshot)
    assert imp_res.ok and imp_res.value == 2

    imported = {n.site_id: n for n in reg_target.list_nodes()}
    pub_node = imported["VT-PUB-01"]
    priv_node = imported["VT-PRIV-01"]

    # Public land coordinates remain exact and unfuzzed
    assert pub_node.privacy_fuzzed is False
    assert pub_node.coordinate.lat == pytest.approx(44.3195)
    assert pub_node.coordinate.lon == pytest.approx(-72.8863)

    # Private silo node is snapped to 0.002-deg grid (~200m) and marked privacy_fuzzed
    assert priv_node.privacy_fuzzed is True
    assert priv_node.status == DeploymentStatus.ACTIVE_ON_AIR
    assert priv_node.coordinate.lat != 44.481234
    assert priv_node.coordinate.lat == pytest.approx(44.482, abs=1e-4)
    assert priv_node.coordinate.lon == pytest.approx(-73.078, abs=1e-4)


def test_azimuth_and_evaluate_home_node_reach_essex_to_mansfield() -> None:
    """Verify azimuth (~75 deg ENE) and 360-degree home reach from Essex Junction to Mount Mansfield."""
    essex_home = Coordinate(lat=44.4906, lon=-73.1112, elevation_m=108.0)
    mansfield_coord = Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0)

    az_deg, cardinal = compute_azimuth_bearing(essex_home, mansfield_coord)
    assert 72.0 <= az_deg <= 79.0
    assert cardinal == "ENE"

    nodes = [
        RegisteredNode(
            site_id="VT-CAND-HILL",
            name="Candidate Foothill Relay",
            coordinate=Coordinate(lat=44.5100, lon=-73.0200, elevation_m=260.0),
            height_agl_m=10.0,
            site_type=SiteType.WATER_TOWER,
            status=DeploymentStatus.CANDIDATE,
            updated_at="2026-10-26T00:00:00Z",
        ),
        RegisteredNode(
            site_id="VT-MANS-ACTIVE",
            name="Mount Mansfield Active Repeater",
            coordinate=mansfield_coord,
            height_agl_m=12.0,
            site_type=SiteType.MOUNTAIN_PEAK,
            status=DeploymentStatus.ACTIVE_ON_AIR,
            updated_at="2026-10-26T00:00:00Z",
        ),
        RegisteredNode(
            site_id="VT-BLOCKED-01",
            name="Decommissioned Site",
            coordinate=Coordinate(lat=44.4950, lon=-73.1000, elevation_m=200.0),
            height_agl_m=15.0,
            site_type=SiteType.COMMUNICATIONS_TOWER,
            status=DeploymentStatus.BLOCKED,
            updated_at="2026-10-26T00:00:00Z",
        ),
    ]

    reach_res = evaluate_home_node_reach(
        home_coord=essex_home,
        home_height_agl_m=8.0,
        nodes=nodes,
    )
    assert reach_res.ok and reach_res.value is not None
    report = reach_res.value

    # Blocked node is excluded; active repeater is ranked #1
    assert len(report.ranked_towers) == 2
    assert report.reachable_active_count == 1
    assert report.reachable_candidate_count == 1

    top_tower = report.ranked_towers[0]
    assert top_tower.site_id == "VT-MANS-ACTIVE"
    assert top_tower.recommended_rank == 1
    assert top_tower.link_margin_db > 0.0
    assert top_tower.has_line_of_sight is True
    assert top_tower.cardinal_direction == "ENE"
    assert report.best_cardinal_direction == "ENE"
    assert report.best_azimuth_deg == pytest.approx(az_deg)


def test_insert_custom_node(tmp_path: Path) -> None:
    """Verify inserting a custom user-defined site persists and can be queried and updated."""
    db_file = tmp_path / "mesh_state.db"
    registry = LivingMeshRegistry(db_path=db_file)

    custom_node = RegisteredNode(
        site_id="CUSTOM-USER-01",
        name="Barn Silo Repeater",
        coordinate=Coordinate(lat=44.5200, lon=-73.0500, elevation_m=180.0),
        height_agl_m=12.0,
        site_type=SiteType.SILO,
        status=DeploymentStatus.CANDIDATE,
        hardware_preset="RAK4631_SOLAR",
        notes="Non-penetrating mast clamp on north silo band",
        updated_at="2026-10-28T12:00:00Z",
    )

    ins_res = registry.insert_node(custom_node)
    assert ins_res.ok is True
    assert ins_res.value is not None
    assert ins_res.value.site_id == "CUSTOM-USER-01"
    assert ins_res.value.name == "Barn Silo Repeater"

    nodes = registry.list_nodes()
    assert any(n.site_id == "CUSTOM-USER-01" for n in nodes)

