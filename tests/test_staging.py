"""Comprehensive test suite for offline Field Kit Staging Engine and CLI subcommand (TASK-1088)."""

from __future__ import annotations

from pathlib import Path
import contextlib
import sqlite3
import pytest

from meshscout.adapters.regions import resolve_regional_bounds
from meshscout.cli import build_parser, main
from meshscout.core.contracts import RegionalBounds
from meshscout.core.staging import (
    calculate_buffered_region_bounds,
    deg_to_tile,
    estimate_offline_tile_count,
    stage_offline_region,
)


def test_deg_to_tile_calculation() -> None:
    """Verify deg_to_tile produces accurate, clamped Slippy map tile coordinates."""
    # Origin at z=0 is tile (0, 0)
    assert deg_to_tile(0.0, 0.0, 0) == (0, 0)

    # Burlington, VT area (~44.47, -73.21) at z=10
    x, y = deg_to_tile(44.4759, -73.2121, 10)
    assert 0 <= x < 1024
    assert 0 <= y < 1024
    assert x == 303
    assert y == 370

    # Extreme latitudes clamped safely without math domain error
    x_north, y_north = deg_to_tile(89.9, 0.0, 5)
    assert y_north == 0
    x_south, y_south = deg_to_tile(-89.9, 0.0, 5)
    assert y_south == (1 << 5) - 1


def test_calculate_buffered_region_bounds_vt_and_qc() -> None:
    """Verify calculate_buffered_region_bounds correctly expands boundaries outward for VT and CA_QC."""
    # Test VT expansion
    base_vt = resolve_regional_bounds("VT").value
    assert base_vt is not None

    buffered_vt = calculate_buffered_region_bounds("VT", buffer_km=20.0)
    assert buffered_vt.min_lat < base_vt.min_lat
    assert buffered_vt.max_lat > base_vt.max_lat
    assert buffered_vt.min_lon < base_vt.min_lon
    assert buffered_vt.max_lon > base_vt.max_lon
    assert "buffered_20km" in buffered_vt.name

    # Test CA_QC expansion
    base_qc = resolve_regional_bounds("CA_QC").value
    assert base_qc is not None

    buffered_qc = calculate_buffered_region_bounds("CA_QC", buffer_km=15.0)
    assert buffered_qc.min_lat < base_qc.min_lat
    assert buffered_qc.max_lat > base_qc.max_lat
    assert buffered_qc.min_lon < base_qc.min_lon
    assert buffered_qc.max_lon > base_qc.max_lon


def test_calculate_buffered_region_bounds_validation() -> None:
    """Verify validation errors for negative buffer or unsupported region identifiers."""
    with pytest.raises(ValueError, match="buffer_km must be non-negative"):
        calculate_buffered_region_bounds("VT", buffer_km=-5.0)

    with pytest.raises(ValueError, match="Unsupported state"):
        calculate_buffered_region_bounds("NON_EXISTENT_STATE", buffer_km=20.0)


def test_estimate_offline_tile_count() -> None:
    """Verify estimate_offline_tile_count returns positive tile counts and proportional byte estimates."""
    bounds = RegionalBounds(
        name="Test_Bounds",
        min_lat=44.0,
        max_lat=45.0,
        min_lon=-73.5,
        max_lon=-72.5,
    )
    res = estimate_offline_tile_count(bounds, min_zoom=7, max_zoom=10)

    assert "total_tiles" in res
    assert "by_zoom" in res
    assert "est_bytes" in res

    assert isinstance(res["total_tiles"], int)
    assert res["total_tiles"] > 0
    assert len(res["by_zoom"]) == 4  # zooms 7, 8, 9, 10
    for z in range(7, 11):
        assert z in res["by_zoom"]
        assert res["by_zoom"][z] > 0

    assert res["est_bytes"] == res["total_tiles"] * 25000

    # Invalid zoom ranges
    with pytest.raises(ValueError, match="Invalid zoom range"):
        estimate_offline_tile_count(bounds, min_zoom=12, max_zoom=7)


def test_stage_offline_region_dry_run(tmp_path: Path) -> None:
    """Verify dry_run=True returns valid estimates without modifying or creating filesystem paths."""
    out_dir = tmp_path / "simulated_field_kit"
    assert not out_dir.exists()

    res = stage_offline_region(
        state_code="VT",
        output_dir=out_dir,
        buffer_km=20.0,
        min_zoom=7,
        max_zoom=10,
        dry_run=True,
    )

    assert res.ok is True
    assert res.value is not None
    data = res.value

    assert data["dry_run"] is True
    assert data["state_code"] == "VT"
    assert data["total_tiles"] > 0
    assert len(data["planned_files"]) >= 2
    assert not out_dir.exists()


def test_stage_offline_region_execution_and_mbtiles(tmp_path: Path) -> None:
    """Verify dry_run=False creates directory structure, Living Mesh DB, and valid MBTiles SQLite archive."""
    out_dir = tmp_path / "actual_field_kit"
    res = stage_offline_region(
        state_code="VT",
        output_dir=out_dir,
        buffer_km=10.0,
        min_zoom=7,
        max_zoom=9,
        include_dem=True,
        dry_run=False,
    )

    assert res.ok is True
    assert res.value is not None
    data = res.value

    assert data["dry_run"] is False
    assert (out_dir / "tiles").is_dir()
    assert (out_dir / "data").is_dir()
    assert (out_dir / "dem").is_dir()

    mbtiles_path = out_dir / "tiles" / "vt_offline.mbtiles"
    assert mbtiles_path.is_file()

    # Validate MBTiles schema and content
    with contextlib.closing(sqlite3.connect(mbtiles_path)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name, value FROM metadata")
        meta = dict(cur.fetchall())

        assert meta.get("name") == "VT Offline Field Kit"
        assert meta.get("format") == "png"
        assert meta.get("minzoom") == "7"
        assert meta.get("maxzoom") == "9"
        assert "bounds" in meta

        cur.execute("SELECT count(*) FROM tiles")
        tile_count = cur.fetchone()[0]
        assert tile_count > 0

    # Validate Living Mesh DB
    mesh_db_path = out_dir / "data" / "mesh_state.db"
    assert mesh_db_path.is_file()

    with contextlib.closing(sqlite3.connect(mesh_db_path)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='workspace_prefs'")
        assert cur.fetchone() is not None


def test_stage_offline_region_with_custom_tile_fetcher(tmp_path: Path) -> None:
    """Verify custom tile_fetcher callable is invoked and its tile payloads are stored in MBTiles."""
    out_dir = tmp_path / "fetcher_field_kit"
    custom_bytes = b"\x89PNG\r\n\x1a\n\x00CUSTOM_MOCK_PAYLOAD"
    fetched_coords = []

    def mock_fetcher(z: int, x: int, y: int) -> bytes:
        fetched_coords.append((z, x, y))
        return custom_bytes

    res = stage_offline_region(
        state_code="VT",
        output_dir=out_dir,
        buffer_km=5.0,
        min_zoom=7,
        max_zoom=7,
        include_dem=False,
        dry_run=False,
        tile_fetcher=mock_fetcher,
    )

    assert res.ok is True
    assert len(fetched_coords) > 0

    mbtiles_path = out_dir / "tiles" / "vt_offline.mbtiles"
    with contextlib.closing(sqlite3.connect(mbtiles_path)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT tile_data FROM tiles LIMIT 1")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == custom_bytes


def test_cli_stage_parser_and_execution(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify CLI parser options for 'stage' and dry-run execution."""
    parser = build_parser()
    args = parser.parse_args(["stage", "--region", "VT", "--buffer-km", "25.0", "--dry-run"])

    assert args.command == "stage"
    assert args.region == "VT"
    assert args.buffer_km == 25.0
    assert args.dry_run is True
    assert args.output_dir == "./MeshScout-Field-Kit"
    assert args.min_zoom == 7
    assert args.max_zoom == 12
    assert args.no_dem is False

    # Execute main() dry-run and verify clean stdout table
    exit_code = main(["stage", "--region", "VT", "--dry-run"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "MeshScout Field Kit Staging: VT [DRY RUN (Simulated)]" in captured.out
    assert "Bounding Box:" in captured.out
    assert "Planned Assets:" in captured.out

    # Execute main() with JSON flag
    exit_code_json = main(["stage", "--region", "VT", "--dry-run", "--json"])
    assert exit_code_json == 0
    captured_json = capsys.readouterr()
    assert '"state_code": "VT"' in captured_json.out
    assert '"dry_run": true' in captured_json.out


def test_cli_stage_failure_unknown_region(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify non-zero exit code and error message when invalid region code is supplied to stage."""
    exit_code = main(["stage", "--region", "UNKNOWN_REGION", "--dry-run"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_stage_offline_region_required_hgt_tiles_and_pack_staging(tmp_path: Path) -> None:
    """Verify required_hgt_tiles calculation and regional pack file staging (TASK-1137)."""
    source_packs_dir = tmp_path / "custom_packs"
    source_packs_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy regional pack archive and manifest
    mock_pack_file = source_packs_dir / "towers-vt-1.0.0.sqlite.gz"
    mock_pack_file.write_bytes(b"\x1f\x8b\x08\x00MOCK_GZIP_CONTENT")

    manifest_json = (
        '{"manifest_version": "1.0.0", "packs": {'
        '"towers-vt": {"pack_id": "towers-vt", "region_code": "VT", "pack_version": "1.0.0", '
        '"row_count": 34, "sha256": "fake_hash", "size_bytes": 1024}'
        '}}'
    )
    (source_packs_dir / "manifest.json").write_text(manifest_json, encoding="utf-8")

    out_dir = tmp_path / "staged_kit"
    res = stage_offline_region(
        state_code="VT",
        output_dir=out_dir,
        buffer_km=10.0,
        min_zoom=7,
        max_zoom=8,
        include_dem=False,
        dry_run=False,
        packs_dir=source_packs_dir,
    )

    assert res.ok is True
    assert res.value is not None
    data = res.value

    # 1. Verify required_hgt_tiles calculation
    assert "required_hgt_tiles" in data
    assert isinstance(data["required_hgt_tiles"], list)
    assert len(data["required_hgt_tiles"]) > 0
    assert any("N44W073.hgt" in t for t in data["required_hgt_tiles"])

    # 2. Verify packs staged
    assert "packs_staged" in data
    assert "towers-vt-1.0.0.sqlite.gz" in data["packs_staged"]
    assert "manifest.json" in data["packs_staged"]

    staged_pack_path = out_dir / "packs" / "towers-vt-1.0.0.sqlite.gz"
    assert staged_pack_path.is_file()
    assert staged_pack_path.read_bytes() == b"\x1f\x8b\x08\x00MOCK_GZIP_CONTENT"

    staged_manifest_path = out_dir / "packs" / "manifest.json"
    assert staged_manifest_path.is_file()


def test_stage_offline_region_dry_run_includes_hgt_tiles(tmp_path: Path) -> None:
    """Verify dry_run result payload contains required_hgt_tiles and packs directory in planned_files."""
    out_dir = tmp_path / "sim_field_kit"
    res = stage_offline_region(
        state_code="VT",
        output_dir=out_dir,
        buffer_km=15.0,
        dry_run=True,
    )

    assert res.ok is True
    assert res.value is not None
    data = res.value

    assert "required_hgt_tiles" in data
    assert len(data["required_hgt_tiles"]) > 0
    assert "packs_staged" in data
    assert any("packs" in p for p in data["planned_files"])

