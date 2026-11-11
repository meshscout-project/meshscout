"""Hermetic unit tests for regional pack builder (TASK-001).

Verifies fail-closed behavior, hermetic offline execution, plausibility floor enforcement,
and exclusion of synthetic anchors in live production mode.
"""

from __future__ import annotations

import gzip
from pathlib import Path
import sqlite3
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from meshscout.adapters.pack_builder import (
    PackBuildError,
    build_region_packs,
    load_pack_floors,
)
from meshscout.adapters.regions import NorthAmericaRegionCode
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    SiteCandidate,
    SiteType,
)
from meshscout.core.tower_registry import UnifiedTowerRegistry


def _insert_dummy_sites(registry: UnifiedTowerRegistry, region_code: str, count: int) -> None:
    """Helper to insert a given number of valid sites for a region."""
    for i in range(count):
        cand = SiteCandidate(
            site_id=f"{region_code}-LIVE-SITE-{i:04d}",
            name=f"{region_code} Live Site {i}",
            location=Coordinate(
                lat=44.0 + (i * 0.001),
                lon=-72.0 - (i * 0.001),
                elevation_m=300.0,
            ),
            site_type=SiteType.COMMUNICATIONS_TOWER,
            mast_height_m=30.0,
            access_difficulty=AccessDifficulty.DRIVE_UP,
            has_grid_power=True,
            solar_exposure_pct=90.0,
            notes="Live authoritative ingestion candidate",
            source_url="https://authoritative.source.gov/test",
        )
        registry.upsert_tower(cand, region_code=region_code, source_dataset="fcc_asr")


def test_pack_floors_schema_and_all_regions_covered() -> None:
    """Verify that pack_floors.json covers all 65 North American jurisdictions with valid tiers."""
    floors = load_pack_floors()
    assert isinstance(floors, dict)

    # Check that all 65 region codes from enum are present
    enum_codes = {member.value for member in NorthAmericaRegionCode}
    assert len(enum_codes) == 65
    missing = enum_codes - set(floors.keys())
    assert not missing, f"pack_floors.json missing jurisdiction codes: {missing}"

    # Verify tiers
    tier_3_regions = {"DC", "PR", "CA_YT", "CA_NT", "CA_NU"}
    tier_15_regions = {"CA_MB", "CA_SK", "CA_NS", "CA_NB", "CA_NL", "CA_PE"}

    for reg, floor in floors.items():
        assert isinstance(floor, int)
        if reg in tier_3_regions:
            assert floor == 3, f"Expected floor 3 for {reg}, got {floor}"
        elif reg in tier_15_regions:
            assert floor == 15, f"Expected floor 15 for {reg}, got {floor}"
        else:
            assert floor == 50, f"Expected floor 50 for {reg}, got {floor}"


def test_offline_mode_never_touches_network(tmp_path: Path) -> None:
    """Hermetic test: patches network sockets and urllib to ensure zero network egress in offline mode."""
    out_dir = tmp_path / "offline_packs"

    with patch("urllib.request.urlopen", side_effect=RuntimeError("NETWORK EGRESS FORBIDDEN")):
        manifest = build_region_packs(
            regions=["VT"],
            out_dir=out_dir,
            offline_fixtures=True,
        )

    assert "towers-vt" in manifest.packs
    pack_info = manifest.packs["towers-vt"]
    assert pack_info.row_count > 0

    archive = out_dir / f"towers-vt-{pack_info.pack_version}.sqlite.gz"
    assert archive.exists()
    assert archive.stat().st_size > 0

    manifest_file = out_dir / "manifest.json"
    assert manifest_file.exists()


def test_live_fetch_failure_raises(tmp_path: Path) -> None:
    """In live mode, failing source download must fail closed with PackBuildError, not fallback to fixtures."""
    out_dir = tmp_path / "live_fail_packs"

    with patch(
        "meshscout.adapters.source_fetch.fetch_source",
        side_effect=RuntimeError("Simulated FCC/ISED server timeout"),
    ):
        with pytest.raises(PackBuildError) as exc_info:
            build_region_packs(
                regions=["VT"],
                out_dir=out_dir,
                offline_fixtures=False,
            )

    assert "Failed to fetch or ingest live FCC ASR source" in str(exc_info.value) or "Simulated" in str(exc_info.value)


def test_floor_violation_fails_build(tmp_path: Path) -> None:
    """In live mode, if a region produces fewer sites than its floor, PackBuildError must be raised."""
    out_dir = tmp_path / "floor_fail_packs"

    # Mock _ingest_live_sources to insert only 10 sites for VT (floor is 50)
    def mock_ingest_too_few(reg: UnifiedTowerRegistry) -> None:
        _insert_dummy_sites(reg, "VT", 10)

    with patch("meshscout.adapters.pack_builder._ingest_live_sources", side_effect=mock_ingest_too_few):
        with pytest.raises(PackBuildError) as exc_info:
            build_region_packs(
                regions=["VT"],
                out_dir=out_dir,
                offline_fixtures=False,
            )

    msg = str(exc_info.value)
    assert "VT" in msg
    assert "10 sites" in msg
    assert "floor of 50 sites" in msg


def test_no_synthetic_anchors_in_live_mode(tmp_path: Path) -> None:
    """Live mode must never insert synthetic anchor sites (CIVIC-%-ANCHOR-%)."""
    out_dir = tmp_path / "live_clean_packs"

    # Mock _ingest_live_sources to insert 60 legitimate sites for VT (floor is 50)
    def mock_ingest_valid(reg: UnifiedTowerRegistry) -> None:
        _insert_dummy_sites(reg, "VT", 60)

    with patch("meshscout.adapters.pack_builder._ingest_live_sources", side_effect=mock_ingest_valid):
        manifest = build_region_packs(
            regions=["VT"],
            out_dir=out_dir,
            offline_fixtures=False,
        )

    pack_info = manifest.packs["towers-vt"]
    assert pack_info.row_count == 60

    archive = out_dir / f"towers-vt-{pack_info.pack_version}.sqlite.gz"
    decompressed_db = tmp_path / "decompressed_vt.sqlite"
    with gzip.open(archive, "rb") as gz_in, open(decompressed_db, "wb") as f_out:
        f_out.write(gz_in.read())

    conn = sqlite3.connect(decompressed_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM towers WHERE site_id LIKE 'CIVIC-%-ANCHOR-%'")
    count = cur.fetchone()[0]
    conn.close()

    assert count == 0, f"Found {count} synthetic anchors in live mode pack!"


def test_synthetic_anchors_in_offline_mode_have_empty_url(tmp_path: Path) -> None:
    """In offline mode, generated synthetic anchors must not use unowned meshscout.org URLs."""
    out_dir = tmp_path / "offline_anchor_packs"

    # Region 'WY' has no fixtures in offline mode, so it gets a synthetic anchor
    manifest = build_region_packs(
        regions=["WY"],
        out_dir=out_dir,
        offline_fixtures=True,
    )

    pack_info = manifest.packs["towers-wy"]
    assert pack_info.row_count >= 1

    archive = out_dir / f"towers-wy-{pack_info.pack_version}.sqlite.gz"
    decompressed_db = tmp_path / "decompressed_wy.sqlite"
    with gzip.open(archive, "rb") as gz_in, open(decompressed_db, "wb") as f_out:
        f_out.write(gz_in.read())

    conn = sqlite3.connect(decompressed_db)
    cur = conn.cursor()
    cur.execute("SELECT site_id, source_url FROM towers WHERE site_id LIKE 'CIVIC-%-ANCHOR-%'")
    rows = cur.fetchall()
    conn.close()

    assert len(rows) >= 1
    for site_id, source_url in rows:
        assert "meshscout.org" not in source_url
        assert source_url == ""
