"""Unit tests for UnifiedTowerRegistry and friction-tier resolution (TASK-1093)."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import pytest

from meshscout.core import (
    FrictionTier,
    SCHEMA_VERSION,
    UnifiedTowerRegistry,
    migrate_database,
    resolve_friction_tier,
)
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)


def test_resolve_friction_tier() -> None:
    """Verify friction tier resolution across civic, agricultural, and commercial site types and owners."""
    # Tier 1 Civic: inherently civic site types
    assert resolve_friction_tier(SiteType.FIRE_LOOKOUT) == FrictionTier.TIER_1_CIVIC
    assert resolve_friction_tier(SiteType.WATER_TOWER) == FrictionTier.TIER_1_CIVIC
    assert resolve_friction_tier(SiteType.RESEARCH_TOWER) == FrictionTier.TIER_1_CIVIC

    # Tier 1 Civic: owner category heuristics
    assert (
        resolve_friction_tier(SiteType.COMMUNICATIONS_TOWER, owner_category="Civic Public Safety")
        == FrictionTier.TIER_1_CIVIC
    )
    assert (
        resolve_friction_tier(SiteType.BUILDING_ROOFTOP, owner_category="municipal_civic")
        == FrictionTier.TIER_1_CIVIC
    )

    # Tier 2 Agricultural: silos and utility/coop/ag owners
    assert resolve_friction_tier(SiteType.SILO) == FrictionTier.TIER_2_AGRICULTURAL
    assert (
        resolve_friction_tier(SiteType.COMMUNICATIONS_TOWER, owner_category="Electric Coop")
        == FrictionTier.TIER_2_AGRICULTURAL
    )
    assert (
        resolve_friction_tier(SiteType.CUSTOM, owner_category="VT_Dairy_Ag")
        == FrictionTier.TIER_2_AGRICULTURAL
    )
    assert (
        resolve_friction_tier(SiteType.CUSTOM, owner_category="rural_utility_pole")
        == FrictionTier.TIER_2_AGRICULTURAL
    )

    # Tier 3 Commercial: commercial carriers and unclassified sites
    assert (
        resolve_friction_tier(SiteType.COMMUNICATIONS_TOWER, owner_category="American Tower Corp")
        == FrictionTier.TIER_3_COMMERCIAL
    )
    assert (
        resolve_friction_tier(SiteType.COMMUNICATIONS_TOWER, owner_category="Crown Castle")
        == FrictionTier.TIER_3_COMMERCIAL
    )
    assert resolve_friction_tier(SiteType.COMMUNICATIONS_TOWER) == FrictionTier.TIER_3_COMMERCIAL
    assert resolve_friction_tier(SiteType.CUSTOM) == FrictionTier.TIER_3_COMMERCIAL


def test_upsert_single_tower_and_bulk_upsert(tmp_path: Path) -> None:
    """Verify single upsert, bulk upsert, and update replacement in SQLite registry."""
    db_file = tmp_path / "test_towers.db"
    registry = UnifiedTowerRegistry(db_path=db_file)

    site1 = SiteCandidate(
        site_id="TOWER-001",
        name="Burlington Water Works",
        location=Coordinate(lat=44.4759, lon=-73.2121, elevation_m=65.0),
        site_type=SiteType.WATER_TOWER,
        mast_height_m=25.0,
        has_grid_power=True,
        solar_exposure_pct=90.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        notes="Municipal reservoir pump tower",
    )

    # Single upsert
    ok = registry.upsert_tower(
        site1,
        owner="City of Burlington",
        owner_category="municipal_water",
        source_dataset="vt_vcgi",
    )
    assert ok is True

    # Query single tower
    results = registry.query_towers()
    assert len(results) == 1
    t = results[0]
    assert t.site_id == "TOWER-001"
    assert t.name == "Burlington Water Works"
    assert t.location.lat == pytest.approx(44.4759)
    assert t.location.lon == pytest.approx(-73.2121)
    assert t.location.elevation_m == pytest.approx(65.0)
    assert t.mast_height_m == pytest.approx(25.0)
    assert t.site_type == SiteType.WATER_TOWER
    assert t.has_grid_power is True
    assert t.solar_exposure_pct == pytest.approx(90.0)
    assert t.access_difficulty == AccessDifficulty.DRIVE_UP
    assert t.notes == "Municipal reservoir pump tower"

    # Bulk upsert additional towers
    sites = [
        SiteCandidate(
            site_id="TOWER-002",
            name="Jericho Farm Silo",
            location=Coordinate(lat=44.5050, lon=-72.9980, elevation_m=210.0),
            site_type=SiteType.SILO,
            mast_height_m=18.0,
        ),
        SiteCandidate(
            site_id="TOWER-003",
            name="Williston Commercial Cell",
            location=Coordinate(lat=44.4370, lon=-73.0690, elevation_m=140.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
            mast_height_m=45.0,
        ),
    ]

    count = registry.bulk_upsert_towers(
        sites,
        owner_default="Various",
        owner_category_default="commercial",
        source_dataset="fcc_asr",
    )
    assert count == 2

    all_towers = registry.query_towers()
    assert len(all_towers) == 3

    # Test update existing tower
    site1_updated = SiteCandidate(
        site_id="TOWER-001",
        name="Burlington Water Works Upgraded",
        location=Coordinate(lat=44.4759, lon=-73.2121, elevation_m=65.0),
        site_type=SiteType.WATER_TOWER,
        mast_height_m=30.0,
        notes="Updated mast height",
    )
    registry.upsert_tower(site1_updated)
    all_towers_after_update = registry.query_towers()
    assert len(all_towers_after_update) == 3
    updated = next(t for t in all_towers_after_update if t.site_id == "TOWER-001")
    assert updated.name == "Burlington Water Works Upgraded"
    assert updated.mast_height_m == pytest.approx(30.0)

    registry.close()


def test_spatial_bounding_box_query(tmp_path: Path) -> None:
    """Verify spatial bounding box filtering returns only candidate sites inside the region."""
    db_file = tmp_path / "spatial_towers.db"
    registry = UnifiedTowerRegistry(db_path=db_file)

    chittenden_bounds = RegionalBounds(
        name="Chittenden County",
        min_lat=44.25,
        max_lat=44.65,
        min_lon=-73.35,
        max_lon=-72.80,
    )

    sites = [
        # Inside Chittenden
        SiteCandidate(
            site_id="IN-01",
            name="Essex Junction Water Tank",
            location=Coordinate(lat=44.4906, lon=-73.1112, elevation_m=108.0),
            site_type=SiteType.WATER_TOWER,
        ),
        SiteCandidate(
            site_id="IN-02",
            name="Burlington Rooftop",
            location=Coordinate(lat=44.4760, lon=-73.2120, elevation_m=60.0),
            site_type=SiteType.BUILDING_ROOFTOP,
        ),
        # Outside Chittenden (North near border, South in Rutland)
        SiteCandidate(
            site_id="OUT-01",
            name="Jay Peak Lookout",
            location=Coordinate(lat=44.9242, lon=-72.5255, elevation_m=1176.0),
            site_type=SiteType.FIRE_LOOKOUT,
        ),
        SiteCandidate(
            site_id="OUT-02",
            name="Killington Peak Mast",
            location=Coordinate(lat=43.6045, lon=-72.8208, elevation_m=1289.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
        ),
    ]

    registry.bulk_upsert_towers(sites)

    # Spatial query inside Chittenden
    inside_towers = registry.query_towers(bounds=chittenden_bounds)
    assert len(inside_towers) == 2
    inside_ids = {t.site_id for t in inside_towers}
    assert inside_ids == {"IN-01", "IN-02"}

    # Spatial query without bounds returns all 4
    all_towers = registry.query_towers()
    assert len(all_towers) == 4

    registry.close()


def test_friction_tier_query_filtering(tmp_path: Path) -> None:
    """Verify querying with max_friction_tier correctly isolates civic, agricultural, and commercial sites."""
    db_file = tmp_path / "tier_towers.db"
    registry = UnifiedTowerRegistry(db_path=db_file)

    sites = [
        SiteCandidate(
            site_id="CIVIC-01",
            name="Camels Hump Fire Lookout",
            location=Coordinate(lat=44.3197, lon=-72.8861, elevation_m=1244.0),
            site_type=SiteType.FIRE_LOOKOUT,
        ),
        SiteCandidate(
            site_id="CIVIC-02",
            name="Shelburne Water Tower",
            location=Coordinate(lat=44.3780, lon=-73.2260, elevation_m=80.0),
            site_type=SiteType.WATER_TOWER,
        ),
        SiteCandidate(
            site_id="AG-01",
            name="Charlotte Dairy Silo",
            location=Coordinate(lat=44.3100, lon=-73.2500, elevation_m=95.0),
            site_type=SiteType.SILO,
        ),
        SiteCandidate(
            site_id="COMM-01",
            name="SBA Monopole Tower",
            location=Coordinate(lat=44.4000, lon=-73.1500, elevation_m=110.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
        ),
    ]

    registry.bulk_upsert_towers(sites)

    # Query Tier 1 only (civic: fire lookout and water tower)
    tier1_towers = registry.query_towers(max_friction_tier=1)
    assert len(tier1_towers) == 2
    assert {t.site_id for t in tier1_towers} == {"CIVIC-01", "CIVIC-02"}

    # Query Tier 2 ceiling (civic + agricultural)
    tier2_towers = registry.query_towers(max_friction_tier=2)
    assert len(tier2_towers) == 3
    assert {t.site_id for t in tier2_towers} == {"CIVIC-01", "CIVIC-02", "AG-01"}

    # Query Tier 3 ceiling (all sites)
    tier3_towers = registry.query_towers(max_friction_tier=3)
    assert len(tier3_towers) == 4

    registry.close()


def test_ordering(tmp_path: Path) -> None:
    """Verify ordering by friction_tier ASC, then total height (elevation_m + mast_height_m) DESC."""
    db_file = tmp_path / "order_towers.db"
    registry = UnifiedTowerRegistry(db_path=db_file)

    # Even though Commercial Tower has highest elevation, Tier 1 civic towers must appear first!
    sites = [
        # Tier 3 commercial, very high elevation
        SiteCandidate(
            site_id="T3-HIGH",
            name="Commercial Mountain Mast",
            location=Coordinate(lat=44.50, lon=-72.80, elevation_m=1000.0),
            mast_height_m=50.0,  # Total 1050m
            site_type=SiteType.COMMUNICATIONS_TOWER,
        ),
        # Tier 1 civic, lower elevation
        SiteCandidate(
            site_id="T1-LOW",
            name="Civic Water Tank Low",
            location=Coordinate(lat=44.40, lon=-73.10, elevation_m=150.0),
            mast_height_m=20.0,  # Total 170m
            site_type=SiteType.WATER_TOWER,
        ),
        # Tier 1 civic, higher elevation
        SiteCandidate(
            site_id="T1-HIGH",
            name="Civic Mountain Lookout",
            location=Coordinate(lat=44.45, lon=-72.90, elevation_m=800.0),
            mast_height_m=15.0,  # Total 815m
            site_type=SiteType.FIRE_LOOKOUT,
        ),
        # Tier 2 agricultural, moderate elevation
        SiteCandidate(
            site_id="T2-MID",
            name="Farm Co-op Silo",
            location=Coordinate(lat=44.42, lon=-73.05, elevation_m=250.0),
            mast_height_m=25.0,  # Total 275m
            site_type=SiteType.SILO,
        ),
    ]

    registry.bulk_upsert_towers(sites)
    ordered = registry.query_towers()

    expected_id_order = ["T1-HIGH", "T1-LOW", "T2-MID", "T3-HIGH"]
    actual_id_order = [t.site_id for t in ordered]
    assert actual_id_order == expected_id_order

    registry.close()


def test_count_towers_by_category(tmp_path: Path) -> None:
    """Verify count_towers_by_category groups counts by site_type and friction_tier."""
    db_file = tmp_path / "count_towers.db"
    registry = UnifiedTowerRegistry(db_path=db_file)

    sites = [
        SiteCandidate(
            site_id="WT-01",
            name="Water Tower 1",
            location=Coordinate(lat=44.48, lon=-73.20, elevation_m=70.0),
            site_type=SiteType.WATER_TOWER,
        ),
        SiteCandidate(
            site_id="WT-02",
            name="Water Tower 2",
            location=Coordinate(lat=44.49, lon=-73.19, elevation_m=75.0),
            site_type=SiteType.WATER_TOWER,
        ),
        SiteCandidate(
            site_id="FL-01",
            name="Fire Lookout 1",
            location=Coordinate(lat=44.52, lon=-72.85, elevation_m=900.0),
            site_type=SiteType.FIRE_LOOKOUT,
        ),
        SiteCandidate(
            site_id="SILO-01",
            name="Silo 1",
            location=Coordinate(lat=44.44, lon=-73.05, elevation_m=180.0),
            site_type=SiteType.SILO,
        ),
        SiteCandidate(
            site_id="COMM-01",
            name="Commercial Tower 1",
            location=Coordinate(lat=44.45, lon=-73.12, elevation_m=120.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
        ),
        SiteCandidate(
            site_id="COMM-02",
            name="Commercial Tower 2",
            location=Coordinate(lat=44.46, lon=-73.14, elevation_m=130.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
        ),
        # Out-of-region site
        SiteCandidate(
            site_id="COMM-OUT",
            name="Distant Tower",
            location=Coordinate(lat=45.50, lon=-71.00, elevation_m=500.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
        ),
    ]

    registry.bulk_upsert_towers(sites)

    # Unbounded counts
    counts = registry.count_towers_by_category()
    assert counts["water_tower"] == 2
    assert counts["fire_lookout"] == 1
    assert counts["silo"] == 1
    assert counts["communications_tower"] == 3
    assert counts["tier_1"] == 3
    assert counts["tier_2"] == 1
    assert counts["tier_3"] == 3

    # Bounded counts
    vt_bounds = RegionalBounds(
        name="VT Region",
        min_lat=44.20,
        max_lat=44.60,
        min_lon=-73.30,
        max_lon=-72.80,
    )
    bounded_counts = registry.count_towers_by_category(bounds=vt_bounds)
    assert bounded_counts["water_tower"] == 2
    assert bounded_counts["fire_lookout"] == 1
    assert bounded_counts["silo"] == 1
    assert bounded_counts["communications_tower"] == 2
    assert bounded_counts["tier_1"] == 3
    assert bounded_counts["tier_2"] == 1
    assert bounded_counts["tier_3"] == 2
    assert "COMM-OUT" not in [t.site_id for t in registry.query_towers(bounds=vt_bounds)]

    registry.close()


def test_site_types_filtering(tmp_path: Path) -> None:
    """Verify querying towers with specific site_types filters correctly."""
    db_file = tmp_path / "filter_types.db"
    with UnifiedTowerRegistry(db_path=db_file) as registry:
        sites = [
            SiteCandidate(
                site_id="WT-01",
                name="Water Tower",
                location=Coordinate(lat=44.48, lon=-73.20, elevation_m=70.0),
                site_type=SiteType.WATER_TOWER,
            ),
            SiteCandidate(
                site_id="FL-01",
                name="Fire Lookout",
                location=Coordinate(lat=44.52, lon=-72.85, elevation_m=900.0),
                site_type=SiteType.FIRE_LOOKOUT,
            ),
            SiteCandidate(
                site_id="SILO-01",
                name="Silo",
                location=Coordinate(lat=44.44, lon=-73.05, elevation_m=180.0),
                site_type=SiteType.SILO,
            ),
        ]
        registry.bulk_upsert_towers(sites)

        res = registry.query_towers(site_types=[SiteType.WATER_TOWER, SiteType.SILO])
        assert len(res) == 2
        assert {t.site_id for t in res} == {"WT-01", "SILO-01"}


def test_v1_to_v2_migration(tmp_path: Path) -> None:
    """Verify clean idempotent migration from v1 legacy schema to v2."""
    db_file = tmp_path / "legacy_v1.db"

    # 1. Create a pure v1 database manually
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE towers (
            site_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            elevation_m REAL NOT NULL,
            mast_height_m REAL NOT NULL,
            site_type TEXT NOT NULL,
            owner TEXT NOT NULL,
            owner_category TEXT NOT NULL,
            friction_tier INTEGER NOT NULL,
            source_dataset TEXT NOT NULL,
            access_difficulty TEXT NOT NULL,
            has_grid_power INTEGER NOT NULL,
            solar_exposure_pct REAL NOT NULL,
            notes TEXT,
            source_url TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute("CREATE INDEX idx_towers_spatial ON towers(lat, lon);")
    conn.execute("PRAGMA user_version = 1;")

    # Insert two v1 candidate sites
    conn.execute(
        """
        INSERT INTO towers (
            site_id, name, lat, lon, elevation_m, mast_height_m,
            site_type, owner, owner_category, friction_tier, source_dataset,
            access_difficulty, has_grid_power, solar_exposure_pct
        ) VALUES (
            'V1-01', 'Legacy Tower 1', 44.4750, -73.2120, 100.0, 20.0,
            'water_tower', 'City', 'civic', 1, 'vt_legacy', 'drive_up', 1, 95.0
        );
        """
    )
    conn.execute(
        """
        INSERT INTO towers (
            site_id, name, lat, lon, elevation_m, mast_height_m,
            site_type, owner, owner_category, friction_tier, source_dataset,
            access_difficulty, has_grid_power, solar_exposure_pct
        ) VALUES (
            'V1-02', 'Legacy Tower 2', 44.5000, -73.1000, 250.0, 30.0,
            'silo', 'Farm', 'ag', 2, 'vt_legacy', 'moderate', 0, 80.0
        );
        """
    )
    conn.commit()

    # Pre-migration assertions
    cols_pre = [r[1] for r in conn.execute("PRAGMA table_info(towers);").fetchall()]
    assert "region_code" not in cols_pre
    assert "source_record_id" not in cols_pre
    rtree_pre = conn.execute("SELECT 1 FROM sqlite_master WHERE name='towers_rtree';").fetchone()
    assert rtree_pre is None
    assert conn.execute("PRAGMA user_version;").fetchone()[0] == 1
    conn.close()

    # 2. Open via UnifiedTowerRegistry (triggers migrate_database)
    with UnifiedTowerRegistry(db_path=db_file) as registry:
        # Check user_version updated to 2
        assert registry.conn.execute("PRAGMA user_version;").fetchone()[0] == SCHEMA_VERSION

        # Check new columns exist
        cols_post = [r[1] for r in registry.conn.execute("PRAGMA table_info(towers);").fetchall()]
        assert "region_code" in cols_post
        assert "source_record_id" in cols_post

        # Check auxiliary tables exist
        tables = [r[0] for r in registry.conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
        assert "tower_packs" in tables
        assert "installed_packs" in tables
        if registry.has_rtree:
            assert "towers_rtree" in tables
            # Check existing rows were cleanly backfilled into towers_rtree
            rtree_count = registry.conn.execute("SELECT COUNT(*) FROM towers_rtree;").fetchone()[0]
            assert rtree_count == 2

        # Check existing towers are queryable
        queried = registry.query_towers()
        assert len(queried) == 2
        assert {t.site_id for t in queried} == {"V1-01", "V1-02"}

        # 3. Verify running migration a second time is an idempotent no-op
        v = migrate_database(registry.conn)
        assert v == SCHEMA_VERSION
        assert registry.conn.execute("PRAGMA user_version;").fetchone()[0] == SCHEMA_VERSION


def test_upsert_three_times_leaves_single_rtree_row(tmp_path: Path) -> None:
    """Verify upserting the same site_id 3 times leaves exactly 1 towers_rtree row."""
    db_file = tmp_path / "dedup_test.db"
    with UnifiedTowerRegistry(db_path=db_file) as registry:
        site_v1 = SiteCandidate(
            site_id="SITE-DEDUP",
            name="Mount Philo Mast v1",
            location=Coordinate(lat=44.2797, lon=-73.2167, elevation_m=295.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
            mast_height_m=15.0,
        )
        registry.upsert_tower(
            site_v1,
            owner="State of VT",
            owner_category="civic_park",
            region_code="VT",
            source_record_id="VCGI-001",
            pack_id="pack-vt-2026",
        )

        site_v2 = SiteCandidate(
            site_id="SITE-DEDUP",
            name="Mount Philo Mast v2 (Upgraded)",
            location=Coordinate(lat=44.2797, lon=-73.2167, elevation_m=295.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
            mast_height_m=25.0,
        )
        registry.upsert_tower(
            site_v2,
            owner="State of VT",
            owner_category="civic_park",
            region_code="VT",
            source_record_id="VCGI-001",
            pack_id="pack-vt-2026",
        )

        site_v3 = SiteCandidate(
            site_id="SITE-DEDUP",
            name="Mount Philo Mast v3 (Final)",
            location=Coordinate(lat=44.2797, lon=-73.2167, elevation_m=295.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
            mast_height_m=30.0,
        )
        registry.upsert_tower(
            site_v3,
            owner="State of VT",
            owner_category="civic_park",
            region_code="VT",
            source_record_id="VCGI-001",
            pack_id="pack-vt-2026",
        )

        towers_count = registry.conn.execute("SELECT COUNT(*) FROM towers;").fetchone()[0]
        assert towers_count == 1

        if registry.has_rtree:
            rtree_count = registry.conn.execute("SELECT COUNT(*) FROM towers_rtree;").fetchone()[0]
            assert rtree_count == 1

        packs_count = registry.conn.execute("SELECT COUNT(*) FROM tower_packs;").fetchone()[0]
        assert packs_count == 1

        results = registry.query_towers()
        assert len(results) == 1
        assert results[0].name == "Mount Philo Mast v3 (Final)"
        assert results[0].mast_height_m == pytest.approx(30.0)


def test_10000_synthetic_towers_decimation(tmp_path: Path) -> None:
    """10,000-tower synthetic test asserting decimated results never exceed one tower per grid cell."""
    db_file = tmp_path / "synthetic_10k.db"
    with UnifiedTowerRegistry(db_path=db_file) as registry:
        # Generate 10,000 synthetic sites in a 1.0 x 1.0 degree box [44.0..45.0, -73.5..-72.5]
        # with varying friction tiers and heights
        sites: list[SiteCandidate] = []
        owner_cats: list[str] = []
        types_cycle = [
            SiteType.WATER_TOWER,
            SiteType.FIRE_LOOKOUT,
            SiteType.SILO,
            SiteType.COMMUNICATIONS_TOWER,
            SiteType.BUILDING_ROOFTOP,
        ]
        cats_cycle = ["civic_water", "civic_safety", "farm_ag", "carrier", "municipal"]

        # Deterministic generation using linear congruential arithmetic
        seed = 42
        for i in range(10_000):
            seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
            lat_offset = (seed % 10000) / 10000.0  # 0.0 to 1.0
            seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
            lon_offset = (seed % 10000) / 10000.0  # 0.0 to 1.0
            seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
            elev = 50.0 + (seed % 800)
            mast = 10.0 + (i % 40)

            st = types_cycle[i % len(types_cycle)]
            cat = cats_cycle[i % len(cats_cycle)]

            sites.append(
                SiteCandidate(
                    site_id=f"SYNTH-{i:05d}",
                    name=f"Synthetic Tower {i}",
                    location=Coordinate(
                        lat=44.0 + lat_offset,
                        lon=-73.5 + lon_offset,
                        elevation_m=float(elev),
                    ),
                    site_type=st,
                    mast_height_m=float(mast),
                )
            )
            owner_cats.append(cat)

        registry.bulk_upsert_towers(
            sites,
            owner_default="Synth Corp",
            owner_categories=owner_cats,
            source_dataset="synth_10k",
            pack_id="pack-synth-10k",
        )

        assert registry.conn.execute("SELECT COUNT(*) FROM towers;").fetchone()[0] == 10_000

        # Test Decimation Zoom 7 (cell_size = 0.25 deg)
        # Across a 1.0x1.0 box, max cells is (1.0/0.25 + 1)^2 = 25 cells max
        cell_size_z7 = 0.25
        results_z7 = registry.query_towers(zoom=7, limit=0)
        assert len(results_z7) > 0
        assert len(results_z7) <= 25

        cell_keys_z7 = [
            (
                int((t.location.lat + 90.0) / cell_size_z7),
                int((t.location.lon + 180.0) / cell_size_z7),
            )
            for t in results_z7
        ]
        # Crucial invariant: never exceed one tower per grid cell!
        assert len(cell_keys_z7) == len(set(cell_keys_z7)), "Zoom 7: Duplicate cell detected in decimated results"

        # Test Decimation Zoom 9 (cell_size = 0.10 deg)
        cell_size_z9 = 0.10
        results_z9 = registry.query_towers(zoom=9, limit=0)
        assert len(results_z9) > len(results_z7)
        assert len(results_z9) <= 121

        cell_keys_z9 = [
            (
                int((t.location.lat + 90.0) / cell_size_z9),
                int((t.location.lon + 180.0) / cell_size_z9),
            )
            for t in results_z9
        ]
        assert len(cell_keys_z9) == len(set(cell_keys_z9)), "Zoom 9: Duplicate cell detected in decimated results"

        # Test Decimation Zoom 10 (cell_size = 0.04 deg)
        cell_size_z10 = 0.04
        results_z10 = registry.query_towers(zoom=10, limit=0)
        assert len(results_z10) > len(results_z9)
        assert len(results_z10) <= 729

        cell_keys_z10 = [
            (
                int((t.location.lat + 90.0) / cell_size_z10),
                int((t.location.lon + 180.0) / cell_size_z10),
            )
            for t in results_z10
        ]
        assert len(cell_keys_z10) == len(set(cell_keys_z10)), "Zoom 10: Duplicate cell detected in decimated results"

        # Test Zoom > 10 (no decimation)
        results_z11 = registry.query_towers(zoom=11, limit=500)
        assert len(results_z11) == 500

        # Test with RegionalBounds and Zoom 7
        bounds = RegionalBounds(
            name="Sub-region",
            min_lat=44.25,
            max_lat=44.75,
            min_lon=-73.25,
            max_lon=-72.75,
        )
        bounded_z7 = registry.query_towers(bounds=bounds, zoom=7, limit=0)
        for t in bounded_z7:
            assert bounds.min_lat <= t.location.lat <= bounds.max_lat
            assert bounds.min_lon <= t.location.lon <= bounds.max_lon

        cell_keys_bounded = [
            (
                int((t.location.lat + 90.0) / cell_size_z7),
                int((t.location.lon + 180.0) / cell_size_z7),
            )
            for t in bounded_z7
        ]
        assert len(cell_keys_bounded) == len(set(cell_keys_bounded))


def test_pack_provenance_and_region_filtering(tmp_path: Path) -> None:
    """Verify pack metadata tracking and region_code query filtering."""
    db_file = tmp_path / "pack_provenance.db"
    with UnifiedTowerRegistry(db_path=db_file) as registry:
        # Record installed packs
        registry.record_installed_pack(
            pack_id="pack-vt-vcgi-2026",
            region_code="VT",
            pack_version="1.0.0",
            schema_version=2,
            sha256="abc123def456",
            licenses_json='[{"license": "CC0-1.0", "origin": "VCGI"}]',
        )
        registry.record_installed_pack(
            pack_id="pack-nh-granit-2026",
            region_code="NH",
            pack_version="1.1.0",
            schema_version=2,
            sha256="789xyz",
        )

        installed = registry.list_installed_packs()
        assert len(installed) == 2
        pack_ids = {p["pack_id"] for p in installed}
        assert pack_ids == {"pack-vt-vcgi-2026", "pack-nh-granit-2026"}

        # Upsert towers with region_code and pack_id
        vt_sites = [
            SiteCandidate(
                site_id="VT-01",
                name="Vermont Tower",
                location=Coordinate(lat=44.47, lon=-73.21, elevation_m=100.0),
                site_type=SiteType.WATER_TOWER,
            )
        ]
        nh_sites = [
            SiteCandidate(
                site_id="NH-01",
                name="New Hampshire Peak",
                location=Coordinate(lat=44.27, lon=-71.30, elevation_m=1900.0),
                site_type=SiteType.FIRE_LOOKOUT,
            )
        ]

        registry.bulk_upsert_towers(
            vt_sites,
            region_codes=["VT"],
            source_record_ids=["VCGI-T1"],
            pack_id="pack-vt-vcgi-2026",
        )
        registry.bulk_upsert_towers(
            nh_sites,
            region_codes=["NH"],
            source_record_ids=["GRANIT-T1"],
            pack_id="pack-nh-granit-2026",
        )

        # Query by region_code
        vt_results = registry.query_towers(region_code="VT")
        assert len(vt_results) == 1
        assert vt_results[0].site_id == "VT-01"

        nh_results = registry.query_towers(region_code="NH")
        assert len(nh_results) == 1
        assert nh_results[0].site_id == "NH-01"

        # Check tower_packs association
        rows = registry.conn.execute("SELECT site_id, pack_id FROM tower_packs ORDER BY site_id;").fetchall()
        assert [(r[0], r[1]) for r in rows] == [
            ("NH-01", "pack-nh-granit-2026"),
            ("VT-01", "pack-vt-vcgi-2026"),
        ]
