"""Unit and API integration tests for MBTilesReader and offline tile serving."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Generator

from fastapi.testclient import TestClient
import pytest

from meshscout.adapters.mbtiles import (
    MBTilesReader,
    generate_boundary_tile_svg,
)
from meshscout.web.app import create_web_app

EXPECTED_TILE_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR_FAKE_TILE_DATA"


@pytest.fixture()
def sample_mbtiles(tmp_path: Path) -> Path:
    """Create a synthetic MBTiles 1.3 SQLite database with metadata and a test tile."""
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    mbtiles_path = tiles_dir / "vt_offline.mbtiles"

    conn = sqlite3.connect(mbtiles_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE metadata (name text, value text);")
    cur.execute(
        "CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob);"
    )
    cur.execute("INSERT INTO metadata VALUES ('name', 'Vermont Offline Test');")
    cur.execute("INSERT INTO metadata VALUES ('format', 'png');")
    cur.execute("INSERT INTO metadata VALUES ('bounds', '-73.5,42.7,-71.5,45.1');")

    # Tile at z=10, x=303, y=374 -> TMS tile_row = (1 << 10) - 1 - 374 = 1023 - 374 = 649
    cur.execute(
        "INSERT INTO tiles VALUES (10, 303, 649, ?);",
        (sqlite3.Binary(EXPECTED_TILE_BYTES),),
    )
    conn.commit()
    conn.close()

    return mbtiles_path


def test_mbtiles_reader_metadata_and_tiles(sample_mbtiles: Path) -> None:
    """Verify MBTilesReader correctly queries metadata and transforms TMS tile coordinates."""
    with MBTilesReader(sample_mbtiles) as reader:
        meta = reader.get_metadata()
        assert meta.get("name") == "Vermont Offline Test"
        assert meta.get("format") == "png"

        # Present tile: z=10, x=303, y=374 -> TMS row 649
        assert reader.has_tile(10, 303, 374) is True
        retrieved_bytes = reader.get_tile_bytes(10, 303, 374)
        assert retrieved_bytes == EXPECTED_TILE_BYTES

        # Non-existent tile
        assert reader.has_tile(10, 999, 999) is False
        assert reader.get_tile_bytes(10, 999, 999) is None


def test_mbtiles_reader_nonexistent_file_raises() -> None:
    """Verify FileNotFoundError is raised when initializing with a missing file."""
    with pytest.raises(FileNotFoundError):
        MBTilesReader("non_existent_archive.mbtiles")


def test_generate_boundary_tile_svg() -> None:
    """Verify generate_boundary_tile_svg produces valid SVG bytes with required labels."""
    svg_bytes = generate_boundary_tile_svg("VERMONT")
    assert isinstance(svg_bytes, bytes)
    svg_text = svg_bytes.decode("utf-8")
    assert "<svg" in svg_text
    assert "</svg>" in svg_text
    assert "OFFLINE BOUNDARY" in svg_text
    assert "VERMONT" in svg_text
    assert "Switch Region Pack" in svg_text
    assert "#141917" in svg_text


def test_api_tiles_found(sample_mbtiles: Path, tmp_path: Path) -> None:
    """Verify GET /api/tiles/{region}/{z}/{x}/{y}.png serves raw PNG bytes when tile exists."""
    app = create_web_app(
        db_path=tmp_path / "test_mesh.db",
        tiles_dir=sample_mbtiles.parent,
    )
    client = TestClient(app)

    resp = client.get("/api/tiles/vt/10/303/374.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == EXPECTED_TILE_BYTES


def test_api_tiles_out_of_bounds_fallback(sample_mbtiles: Path, tmp_path: Path) -> None:
    """Verify GET /api/tiles/{region}/{z}/{x}/{y}.png returns SVG fallback when tile is missing."""
    app = create_web_app(
        db_path=tmp_path / "test_mesh.db",
        tiles_dir=sample_mbtiles.parent,
    )
    client = TestClient(app)

    resp = client.get("/api/tiles/vt/10/999/999.png")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers["content-type"]
    assert "OFFLINE BOUNDARY" in resp.text
    assert "VT" in resp.text
    assert "Switch Region Pack" in resp.text


def test_api_tiles_unknown_region_fallback(tmp_path: Path) -> None:
    """Verify GET /api/tiles/{region}/{z}/{x}/{y}.png returns SVG fallback when region mbtiles not found."""
    app = create_web_app(
        db_path=tmp_path / "test_mesh.db",
        tiles_dir=tmp_path / "empty_tiles",
    )
    client = TestClient(app)

    resp = client.get("/api/tiles/me/10/303/374.png")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers["content-type"]
    assert "OFFLINE BOUNDARY" in resp.text
    assert "ME" in resp.text
