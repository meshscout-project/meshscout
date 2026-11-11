"""Unit tests for regional pack format, manifest contract, and local install engine (TASK-1133)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
import sqlite3
import pytest

from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    SiteCandidate,
    SiteType,
)
from meshscout.core.packs import (
    PackManifest,
    PackSourceInfo,
    RegionPackInfo,
    build_pack_manifest,
    compute_sha256,
    export_region_pack,
    install_region_pack,
    list_installed_packs,
    uninstall_region_pack,
)
from meshscout.core.tower_registry import SCHEMA_VERSION, UnifiedTowerRegistry


def make_site(
    site_id: str,
    name: str = "Test Tower",
    lat: float = 44.5,
    lon: float = -73.0,
    elevation_m: float = 150.0,
    mast_height_m: float = 20.0,
    site_type: SiteType = SiteType.WATER_TOWER,
) -> SiteCandidate:
    """Helper to generate a valid SiteCandidate."""
    return SiteCandidate(
        site_id=site_id,
        name=name,
        location=Coordinate(lat=lat, lon=lon, elevation_m=elevation_m),
        site_type=site_type,
        mast_height_m=mast_height_m,
        has_grid_power=True,
        solar_exposure_pct=90.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
    )


def test_pack_source_and_manifest_contracts(tmp_path: Path) -> None:
    """Verify Pydantic models serialization, schema defaults, and file round-trips."""
    source1 = PackSourceInfo(
        dataset="fcc_asr",
        license="Public Domain",
        attribution="Federal Communications Commission",
        retrieved_at="2026-11-06T12:00:00Z",
        source_url="https://wireless2.fcc.gov/UlsApp/AsrSearch/asrRegistrationSearch.jsp",
    )
    source2 = PackSourceInfo(
        dataset="vt_vcgi",
        license="CC-BY-4.0",
        attribution="VCGI Open Geodata",
    )

    pack_info = RegionPackInfo(
        pack_id="towers-vt",
        region_code="VT",
        pack_version="1.0.0",
        schema_version=SCHEMA_VERSION,
        row_count=42,
        sha256="abc123def456",
        size_bytes=1024,
        url="https://github.com/example/meshscout/releases/towers-vt-1.0.0.sqlite.gz",
        sources=[source1, source2],
        required_hgt_tiles=["N44W073", "N44W072"],
    )

    manifest = build_pack_manifest([pack_info], manifest_version="1.0.0")
    assert manifest.manifest_version == "1.0.0"
    assert "towers-vt" in manifest.packs
    assert manifest.packs["towers-vt"].row_count == 42
    assert len(manifest.packs["towers-vt"].sources) == 2

    # Test JSON round-trip
    manifest_path = tmp_path / "manifest.json"
    manifest.write_json(manifest_path)
    assert manifest_path.is_file()

    loaded = PackManifest.from_file(manifest_path)
    assert loaded.manifest_version == "1.0.0"
    assert "towers-vt" in loaded.packs
    assert loaded.packs["towers-vt"].required_hgt_tiles == ["N44W073", "N44W072"]


def test_export_install_and_reinstall_idempotent(tmp_path: Path) -> None:
    """Verify export, install, and re-install produce identical row counts (idempotence)."""
    src_db = tmp_path / "src_towers.db"
    dest_db = tmp_path / "dest_towers.db"
    out_dir = tmp_path / "packs"

    src_reg = UnifiedTowerRegistry(db_path=src_db)
    dest_reg = UnifiedTowerRegistry(db_path=dest_db)

    # Insert 3 VT towers and 1 NH tower in source registry
    s1 = make_site("VT-01", name="Burlington Water Tower", lat=44.47, lon=-73.21)
    s2 = make_site("VT-02", name="Mount Mansfield Mast", lat=44.54, lon=-72.81)
    s3 = make_site("VT-03", name="Stowe Silo", lat=44.46, lon=-72.68, site_type=SiteType.SILO)
    s_nh = make_site("NH-01", name="Mt Washington Tower", lat=44.27, lon=-71.30)

    src_reg.upsert_tower(s1, region_code="VT", source_dataset="vt_vcgi")
    src_reg.upsert_tower(s2, region_code="VT", source_dataset="fcc_asr")
    src_reg.upsert_tower(s3, region_code="VT", source_dataset="osm")
    src_reg.upsert_tower(s_nh, region_code="NH", source_dataset="fcc_asr")

    sources = [
        PackSourceInfo(
            dataset="vt_vcgi",
            license="CC-BY-4.0",
            attribution="State of Vermont",
            retrieved_at="2026-11-06T00:00:00Z",
            source_url="https://geodata.vermont.gov",
        )
    ]
    hgt_tiles = ["N44W073", "N44W072"]

    # 1. Export VT pack
    pack_info = export_region_pack(
        src_reg,
        region_code="VT",
        out_dir=out_dir,
        pack_version="1.0.0",
        sources=sources,
        required_hgt_tiles=hgt_tiles,
    )

    assert pack_info.pack_id == "towers-vt"
    assert pack_info.region_code == "VT"
    assert pack_info.pack_version == "1.0.0"
    assert pack_info.row_count == 3
    assert pack_info.schema_version == SCHEMA_VERSION
    assert len(pack_info.sha256) == 64
    assert pack_info.size_bytes > 0
    assert pack_info.required_hgt_tiles == hgt_tiles

    pack_file = out_dir / "towers-vt-1.0.0.sqlite.gz"
    assert pack_file.is_file()

    # 2. First install into clean destination registry
    res1 = install_region_pack(dest_reg, pack_file, expected_sha256=pack_info.sha256)
    assert res1.ok is True
    assert res1.value is not None
    assert res1.value.row_count == 3
    assert res1.value.pack_id == "towers-vt"

    dest_towers_1 = dest_reg.query_towers(limit=0)
    assert len(dest_towers_1) == 3
    site_ids_1 = {t.site_id for t in dest_towers_1}
    assert site_ids_1 == {"VT-01", "VT-02", "VT-03"}

    packs_1 = list_installed_packs(dest_reg)
    assert len(packs_1) == 1
    assert packs_1[0]["pack_id"] == "towers-vt"
    assert packs_1[0]["pack_version"] == "1.0.0"

    # 3. Re-install identical pack into destination registry (idempotent test)
    res2 = install_region_pack(dest_reg, pack_file, expected_sha256=pack_info.sha256)
    assert res2.ok is True
    assert res2.value is not None
    assert res2.value.row_count == 3

    dest_towers_2 = dest_reg.query_towers(limit=0)
    assert len(dest_towers_2) == 3
    site_ids_2 = {t.site_id for t in dest_towers_2}
    assert site_ids_2 == {"VT-01", "VT-02", "VT-03"}

    packs_2 = list_installed_packs(dest_reg)
    assert len(packs_2) == 1


def test_shared_tower_survives_uninstall(tmp_path: Path) -> None:
    """Verify a tower shared by two installed packs survives uninstalling one of them."""
    src_db = tmp_path / "src_shared.db"
    dest_db = tmp_path / "dest_shared.db"
    out_dir = tmp_path / "packs"

    src_reg = UnifiedTowerRegistry(db_path=src_db)
    dest_reg = UnifiedTowerRegistry(db_path=dest_db)

    # T1: VT exclusive
    # T_SHARED: Shared border high-site (in both VT and NH packs)
    # T3: NH exclusive
    s_vt = make_site("VT-ONLY", name="Burlington Civic Mast", lat=44.47, lon=-73.21)
    s_shared = make_site("BORDER-SHARED", name="Connecticut River Bluff", lat=44.30, lon=-71.95)
    s_nh = make_site("NH-ONLY", name="Concord Water Tower", lat=43.20, lon=-71.53)

    # Export VT pack containing VT-ONLY and BORDER-SHARED
    src_reg.upsert_tower(s_vt, region_code="VT")
    src_reg.upsert_tower(s_shared, region_code="VT")
    vt_pack = export_region_pack(src_reg, "VT", out_dir=out_dir)
    assert vt_pack.row_count == 2

    # Export NH pack containing NH-ONLY and BORDER-SHARED
    # Update shared site region_code to NH in src_reg to export NH pack
    src_reg.upsert_tower(s_shared, region_code="NH")
    src_reg.upsert_tower(s_nh, region_code="NH")
    nh_pack = export_region_pack(src_reg, "NH", out_dir=out_dir)
    assert nh_pack.row_count == 2

    vt_file = out_dir / "towers-vt-1.0.0.sqlite.gz"
    nh_file = out_dir / "towers-nh-1.0.0.sqlite.gz"

    # Add an unmanaged local user tower to destination registry
    s_local = make_site("USER-CUSTOM-01", name="Private Farm Repeater", lat=44.0, lon=-72.0)
    dest_reg.upsert_tower(s_local, owner="Self", source_dataset="manual_local")

    # Install VT and NH packs into destination
    install_region_pack(dest_reg, vt_file)
    install_region_pack(dest_reg, nh_file)

    initial_towers = dest_reg.query_towers(limit=0)
    assert len(initial_towers) == 4
    initial_ids = {t.site_id for t in initial_towers}
    assert initial_ids == {"VT-ONLY", "BORDER-SHARED", "NH-ONLY", "USER-CUSTOM-01"}

    # 1. Uninstall VT pack: BORDER-SHARED must survive because NH pack also references it!
    removed_vt = uninstall_region_pack(dest_reg, "towers-vt")
    assert removed_vt == 1  # Only VT-ONLY removed

    towers_after_vt = dest_reg.query_towers(limit=0)
    assert len(towers_after_vt) == 3
    ids_after_vt = {t.site_id for t in towers_after_vt}
    assert ids_after_vt == {"BORDER-SHARED", "NH-ONLY", "USER-CUSTOM-01"}
    assert "BORDER-SHARED" in ids_after_vt
    assert "USER-CUSTOM-01" in ids_after_vt

    # 2. Uninstall NH pack: BORDER-SHARED now has 0 remaining packs, so it is removed
    removed_nh = uninstall_region_pack(dest_reg, "towers-nh")
    assert removed_nh == 2  # BORDER-SHARED and NH-ONLY removed

    final_towers = dest_reg.query_towers(limit=0)
    assert len(final_towers) == 1
    assert final_towers[0].site_id == "USER-CUSTOM-01"


def test_tampered_pack_hash_mismatch(tmp_path: Path) -> None:
    """Verify tampered pack fails install with PACK_HASH_MISMATCH and alters no rows."""
    src_db = tmp_path / "src_tamper.db"
    dest_db = tmp_path / "dest_tamper.db"
    out_dir = tmp_path / "packs"

    src_reg = UnifiedTowerRegistry(db_path=src_db)
    dest_reg = UnifiedTowerRegistry(db_path=dest_db)

    src_reg.upsert_tower(make_site("VT-T1"), region_code="VT")
    pack_info = export_region_pack(src_reg, "VT", out_dir=out_dir)
    pack_file = out_dir / "towers-vt-1.0.0.sqlite.gz"

    # Mismatch with incorrect expected_sha256
    bogus_hash = "0" * 64
    res1 = install_region_pack(dest_reg, pack_file, expected_sha256=bogus_hash)
    assert res1.ok is False
    assert res1.error is not None
    assert res1.error.code == "PACK_HASH_MISMATCH"
    assert len(dest_reg.query_towers(limit=0)) == 0

    # Tamper with the archive bytes directly on disk
    raw_bytes = pack_file.read_bytes()
    tampered_bytes = bytearray(raw_bytes)
    tampered_bytes[-10] = (tampered_bytes[-10] + 1) % 256
    pack_file.write_bytes(tampered_bytes)

    # Attempt install with original valid expected hash
    res2 = install_region_pack(dest_reg, pack_file, expected_sha256=pack_info.sha256)
    assert res2.ok is False
    assert res2.error is not None
    assert res2.error.code == "PACK_HASH_MISMATCH"
    assert len(dest_reg.query_towers(limit=0)) == 0


def test_newer_schema_pack_unsupported(tmp_path: Path) -> None:
    """Verify pack with future schema_version fails install with PACK_SCHEMA_UNSUPPORTED."""
    dest_db = tmp_path / "dest_future.db"
    dest_reg = UnifiedTowerRegistry(db_path=dest_db)

    # Construct a pack SQLite database with future PRAGMA user_version = 99
    future_db_path = tmp_path / "future.sqlite"
    future_gz_path = tmp_path / "towers-future-1.0.0.sqlite.gz"

    conn = sqlite3.connect(str(future_db_path))
    conn.execute("PRAGMA user_version = 99;")
    conn.execute(
        """
        CREATE TABLE towers (
            site_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            elevation_m REAL NOT NULL,
            mast_height_m REAL NOT NULL,
            site_type TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE pack_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO towers VALUES ('FUT-01', 'Future Quantum Mast', 45.0, -73.0, 200.0, 50.0, 'custom');"
    )
    conn.execute("INSERT INTO pack_metadata VALUES ('pack_id', 'towers-future');")
    conn.execute("INSERT INTO pack_metadata VALUES ('region_code', 'FUTURE');")
    conn.commit()
    conn.close()

    with open(future_db_path, "rb") as f_in, gzip.GzipFile(future_gz_path, "wb", mtime=0.0) as f_out:
        import shutil

        shutil.copyfileobj(f_in, f_out)

    res = install_region_pack(dest_reg, future_gz_path)
    assert res.ok is False
    assert res.error is not None
    assert res.error.code == "PACK_SCHEMA_UNSUPPORTED"
    assert "exceeds registry supported schema version" in res.error.message

    # Ensure no rows were merged
    assert len(dest_reg.query_towers(limit=0)) == 0


def test_missing_and_corrupt_pack_handling(tmp_path: Path) -> None:
    """Verify error reporting for non-existent and non-gzip corrupt archives."""
    reg = UnifiedTowerRegistry(db_path=tmp_path / "towers.db")

    # Non-existent file
    res_missing = install_region_pack(reg, tmp_path / "does_not_exist.sqlite.gz")
    assert res_missing.ok is False
    assert res_missing.error is not None
    assert res_missing.error.code == "PACK_NOT_FOUND"

    # Corrupt non-gzip file
    corrupt_file = tmp_path / "corrupt.sqlite.gz"
    corrupt_file.write_bytes(b"NOT_A_VALID_GZIP_STREAM")
    res_corrupt = install_region_pack(reg, corrupt_file)
    assert res_corrupt.ok is False
    assert res_corrupt.error is not None
    assert res_corrupt.error.code == "PACK_CORRUPT"


def test_uninstall_nonexistent_pack(tmp_path: Path) -> None:
    """Verify uninstalling an unknown pack returns 0 removed towers without errors."""
    reg = UnifiedTowerRegistry(db_path=tmp_path / "towers.db")
    removed = uninstall_region_pack(reg, "towers-unknown")
    assert removed == 0
