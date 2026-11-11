"""Unit and integration tests for FCC ASR status reconciliation and source_url provenance."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import pytest

from meshscout.adapters.fcc_asr import (
    DEFAULT_FCC_ASR_FIXTURE_PATH,
    extract_dismantled_site_ids,
)
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    RadioConfig,
    SiteCandidate,
    SiteType,
)
from meshscout.core.optimizer import solve_minimum_set_cover
from meshscout.core.registry import (
    DeploymentStatus,
    LivingMeshRegistry,
    RegisteredNode,
    evaluate_home_node_reach,
)
from meshscout.core.viewshed import TargetCoveragePoint, ViewshedResult


def test_extract_dismantled_site_ids_fixture() -> None:
    """Verify extract_dismantled_site_ids against the VT sample fixture returns ASR_1010008."""
    ids = extract_dismantled_site_ids()
    assert ids == ["ASR_1010008"]

    # Explicit fixture path call
    ids_explicit = extract_dismantled_site_ids(fixture_path=DEFAULT_FCC_ASR_FIXTURE_PATH)
    assert ids_explicit == ["ASR_1010008"]


def test_extract_dismantled_site_ids_custom_buffer() -> None:
    """Verify various dismantled/cancelled/terminated tokens and fallback rows are parsed."""
    sample_data = """
# Header comment
ANT|2000001|A0200001|44-28-33.0 N|073-12-45.0 W|TOWER|195.0|320.0|515.0|Burlington|VT|Chittenden|CONSTRUCTED
ANT|2000002|A0200002|44-27-15.0 N|073-10-50.0 W|POLE|140.0|350.0|490.0|South Burlington|VT|Chittenden|DISMANTLED
ANT|2000003|A0200003|44-29-24.0 N|073-06-36.0 W|TOWER|150.0|360.0|510.0|Essex Junction|VT|Chittenden|CANCELLED
ANT|2000004|A0200004|44-32-15.0 N|073-11-20.0 W|MTOWER|220.0|210.0|430.0|Colchester|VT|Chittenden|TERMINATED
ANT|2000005|A0200005|44-26-05.0 N|073-04-12.0 W|TOWER|180.0|480.0|660.0|Williston|VT|Chittenden|EXPIRED
ANT|2000006|A0200006|44-24-13.3 N|072-59-30.0 W|TOWER|130.0|420.0|550.0|Richmond|VT|Chittenden|DISMANTLE
# Fallback format row
3000001|44-29-30.0 N|073-11-15.0 W|110.0|CANCEL
"""
    result = extract_dismantled_site_ids(content=sample_data)
    assert result == [
        "ASR_2000002",
        "ASR_2000003",
        "ASR_2000004",
        "ASR_2000005",
        "ASR_2000006",
        "ASR_3000001",
    ]


def test_living_mesh_registry_status_reconciliation(tmp_path: Path) -> None:
    """Verify LivingMeshRegistry reconciliation updates dismantled nodes and leaves others intact."""
    db_file = tmp_path / "mesh_reconcile.db"
    registry = LivingMeshRegistry(db_path=db_file)

    source_url_uvm = (
        "https://wireless2.fcc.gov/UlsApp/AsrSearch/asrRegistration.jsp?regKey=98924"
    )
    candidates = [
        SiteCandidate(
            site_id="ASR_1010008",
            name="University of Vermont Underhill Mast",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            site_type=SiteType.RESEARCH_TOWER,
            mast_height_m=30.0,
            source_url=source_url_uvm,
            notes="FCC ASR: 1010008",
        ),
        SiteCandidate(
            site_id="ASR_1010001",
            name="American Tower Burlington",
            location=Coordinate(lat=44.4759, lon=-73.2121, elevation_m=95.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
            mast_height_m=60.0,
            notes="FCC ASR: 1010001",
        ),
    ]

    registry.seed_candidates(candidates)

    nodes_before = registry.list_nodes()
    uvm_before = next(n for n in nodes_before if n.site_id == "ASR_1010008")
    assert uvm_before.status == DeploymentStatus.CANDIDATE
    assert uvm_before.source_url == source_url_uvm

    # Reconcile dismantled sites
    updated_rows = registry.reconcile_dismantled_sites(["ASR_1010008", "NON_EXISTENT_999"])
    assert updated_rows == 1

    nodes_after = registry.list_nodes()
    uvm_after = next(n for n in nodes_after if n.site_id == "ASR_1010008")
    assert uvm_after.status == DeploymentStatus.DISMANTLED

    amt_after = next(n for n in nodes_after if n.site_id == "ASR_1010001")
    assert amt_after.status == DeploymentStatus.CANDIDATE

    # Subsequent reconciliation call returns 0 because ASR_1010008 is already dismantled
    second_run = registry.reconcile_dismantled_sites(["ASR_1010008"])
    assert second_run == 0


def test_evaluate_home_node_reach_ignores_dismantled(tmp_path: Path) -> None:
    """Verify evaluate_home_node_reach excludes nodes with DeploymentStatus.DISMANTLED."""
    db_file = tmp_path / "mesh_reach.db"
    registry = LivingMeshRegistry(db_path=db_file)

    candidates = [
        SiteCandidate(
            site_id="ASR_1010008",
            name="Dismantled UVM Mast",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            mast_height_m=30.0,
        ),
        SiteCandidate(
            site_id="VT-ACTIVE-01",
            name="Active Summit Repeater",
            location=Coordinate(lat=44.5000, lon=-73.0000, elevation_m=800.0),
            mast_height_m=15.0,
        ),
    ]
    registry.seed_candidates(candidates)
    registry.reconcile_dismantled_sites(["ASR_1010008"])

    all_nodes = registry.list_nodes()
    assert any(n.site_id == "ASR_1010008" and n.status == DeploymentStatus.DISMANTLED for n in all_nodes)

    home_coord = Coordinate(lat=44.4906, lon=-73.1112, elevation_m=108.0)
    report_res = evaluate_home_node_reach(
        home_coord=home_coord,
        home_height_agl_m=8.0,
        nodes=all_nodes,
        radio=RadioConfig(),
    )

    assert report_res.ok
    assert report_res.value is not None

    ranked_ids = [t.site_id for t in report_res.value.ranked_towers]
    assert "ASR_1010008" not in ranked_ids
    assert "VT-ACTIVE-01" in ranked_ids


def test_source_url_persistence_and_snapshot_roundtrip(tmp_path: Path) -> None:
    """Verify source_url persists across insert_node, export_snapshot, and import_snapshot."""
    db_file1 = tmp_path / "mesh_source.db"
    reg1 = LivingMeshRegistry(db_path=db_file1)

    url = "https://wireless2.fcc.gov/UlsApp/AsrSearch/asrRegistration.jsp?regKey=98924"
    node = RegisteredNode(
        site_id="ASR_1010008",
        name="University of Vermont Underhill Mast",
        coordinate=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        height_agl_m=30.48,
        site_type=SiteType.RESEARCH_TOWER,
        status=DeploymentStatus.DISMANTLED,
        hardware_preset="RAK4631_SOLAR",
        source_url=url,
        updated_at="2026-10-29T12:00:00Z",
    )

    ins_res = reg1.insert_node(node)
    assert ins_res.ok and ins_res.value is not None
    assert ins_res.value.source_url == url

    # Export snapshot
    snapshot = reg1.export_snapshot(fuzz_private_nodes=False)
    assert "nodes" in snapshot
    snap_node = next(n for n in snapshot["nodes"] if n["site_id"] == "ASR_1010008")
    assert snap_node["source_url"] == url

    # Import into fresh database
    db_file2 = tmp_path / "mesh_dest.db"
    reg2 = LivingMeshRegistry(db_path=db_file2)
    imp_res = reg2.import_snapshot(snapshot)
    assert imp_res.ok
    assert imp_res.value == 1

    imported_nodes = reg2.list_nodes()
    assert len(imported_nodes) == 1
    assert imported_nodes[0].site_id == "ASR_1010008"
    assert imported_nodes[0].source_url == url
    assert imported_nodes[0].status == DeploymentStatus.DISMANTLED


def test_db_bak_v05_migration_backup(tmp_path: Path) -> None:
    """Verify existing database without source_url is backed up to .db.bak-v05 and migrated."""
    legacy_db = tmp_path / "legacy_mesh.db"
    # Create legacy table without source_url column
    conn = sqlite3.connect(str(legacy_db))
    conn.execute(
        """
        CREATE TABLE mesh_nodes (
            site_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            elevation_m REAL NOT NULL,
            height_agl_m REAL NOT NULL,
            site_type TEXT NOT NULL,
            status TEXT NOT NULL,
            hardware_preset TEXT NOT NULL,
            owner TEXT,
            is_public_land INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            privacy_fuzzed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO mesh_nodes VALUES (
            'VT-OLD-01', 'Old Tower', 44.5, -73.0, 300.0, 20.0,
            'communications_tower', 'candidate', 'RAK4631_SOLAR', NULL,
            0, 'Old notes', 0, '2026-01-01T00:00:00Z'
        );
        """
    )
    conn.commit()
    conn.close()

    # Now open with LivingMeshRegistry
    reg = LivingMeshRegistry(db_path=legacy_db)

    # Check that backup file was created
    bak_file = legacy_db.with_suffix(".db.bak-v05")
    assert bak_file.exists()

    # Check that source_url column now exists and data is preserved
    nodes = reg.list_nodes()
    assert len(nodes) == 1
    assert nodes[0].site_id == "VT-OLD-01"
    assert nodes[0].source_url == ""


def test_optimizer_filters_dismantled_and_blocked() -> None:
    """Verify set-cover optimizer excludes repeaters marked dismantled or blocked."""
    all_targets = ["T-01", "T-02", "T-03", "T-04"]

    # Dismantled repeater covers all targets
    dismantled_site = SiteCandidate(
        site_id="ASR_DISMANTLED_01",
        name="Dismantled Mast",
        location=Coordinate(lat=44.50, lon=-72.90, elevation_m=1000.0),
        site_type=SiteType.RESEARCH_TOWER,
        mast_height_m=20.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        notes="Status: DISMANTLED",
    )
    # Active repeater covers all targets
    active_site = SiteCandidate(
        site_id="VT-ACTIVE-01",
        name="Active Tower",
        location=Coordinate(lat=44.50, lon=-72.90, elevation_m=900.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=20.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
    )

    def make_vs(site: SiteCandidate) -> ViewshedResult:
        return ViewshedResult(
            repeater=site,
            total_targets=len(all_targets),
            covered_targets=len(all_targets),
            coverage_fraction=1.0,
            weighted_coverage_fraction=1.0,
            target_results=[
                TargetCoveragePoint(
                    target_id=tid,
                    coordinate=Coordinate(lat=44.48, lon=-73.05, elevation_m=110.0),
                    distance_km=10.0,
                    has_line_of_sight=True,
                    fresnel_clearance_ratio=1.0,
                    estimated_rx_dbm=-100.0,
                    link_margin_db=25.0,
                    is_covered=True,
                )
                for tid in all_targets
            ],
            covered_target_ids=list(all_targets),
            shadowed_target_ids=[],
        )

    vs_dismantled = make_vs(dismantled_site)
    vs_active = make_vs(active_site)

    opt_res = solve_minimum_set_cover(
        viewsheds=[vs_dismantled, vs_active],
        target_coverage_fraction=0.90,
    )

    assert opt_res.ok
    assert opt_res.value is not None
    selected_ids = [s.site_id for s in opt_res.value.selected_sites]
    assert "ASR_DISMANTLED_01" not in selected_ids
    assert "VT-ACTIVE-01" in selected_ids
