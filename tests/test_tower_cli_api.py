"""Unit and integration tests for Tower Ingestion CLI and Web REST API (TASK-1094)."""

from __future__ import annotations

import io
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from meshscout.cli import build_parser, main
from meshscout.core.contracts import SiteType
from meshscout.core.tower_registry import FrictionTier, UnifiedTowerRegistry
from meshscout.web.app import create_web_app


@pytest.fixture()
def temp_towers_db(tmp_path: Path) -> Path:
    """Provide an isolated SQLite database path for CLI ingestion tests."""
    return tmp_path / "towers_test.db"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Provide a FastAPI TestClient with an isolated database pre-seeded with civic towers."""
    db_path = tmp_path / "test_mesh_state.db"
    tower_db = tmp_path / "test_towers.db"
    app = create_web_app(db_path=db_path, tower_db_path=tower_db)
    return TestClient(app)


def test_cli_parser_ingest_towers_options() -> None:
    """Verify build_parser registers 'ingest-towers' subcommand and supported flags."""
    parser = build_parser()
    args = parser.parse_args(["ingest-towers", "--source", "civic", "--batch-size", "500"])
    assert args.command == "ingest-towers"
    assert args.source == "civic"
    assert args.batch_size == 500


def test_cli_ingest_towers_civic(temp_towers_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify CLI 'ingest-towers --source civic' populates database with Tier 1 civic towers."""
    out_buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", out_buf)

    exit_code = main(["ingest-towers", "--source", "civic", "--db-path", str(temp_towers_db)])
    assert exit_code == 0
    output = out_buf.getvalue()
    assert "MeshScout Tower Ingestion Summary" in output
    assert "Tier 1 Civic" in output

    # Verify SQLite database content directly
    registry = UnifiedTowerRegistry(db_path=temp_towers_db)
    civic_towers = registry.query_towers(max_friction_tier=1)
    assert len(civic_towers) > 0
    for t in civic_towers:
        assert t.site_type in (
            SiteType.FIRE_LOOKOUT,
            SiteType.WATER_TOWER,
            SiteType.RESEARCH_TOWER,
            SiteType.COMMUNICATIONS_TOWER,
        )


def test_cli_ingest_towers_json_output(
    temp_towers_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify CLI 'ingest-towers --json' emits well-formed JSON summary."""
    out_buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", out_buf)

    exit_code = main(
        ["ingest-towers", "--source", "civic", "--db-path", str(temp_towers_db), "--json"]
    )
    assert exit_code == 0
    payload = json.loads(out_buf.getvalue())
    assert payload["ok"] is True
    assert payload["source"] == "civic"
    assert payload["total_ingested"] > 0
    assert payload["by_friction_tier"]["tier_1_civic"] > 0
    assert "civic" in payload["by_source"]


def test_cli_ingest_towers_fcc_and_region(
    temp_towers_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify CLI ingestion with FCC fixture file and regional bounds filter."""
    fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures"
    fcc_path = fixtures_dir / "fcc_asr_vt_sample.dat"

    out_buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", out_buf)

    exit_code = main(
        [
            "ingest-towers",
            "--source",
            "fcc",
            "--region",
            "VT",
            "--ant-path",
            str(fcc_path),
            "--db-path",
            str(temp_towers_db),
            "--json",
        ]
    )
    assert exit_code == 0
    payload = json.loads(out_buf.getvalue())
    assert payload["ok"] is True
    assert payload["source"] == "fcc"
    assert payload["region"] == "VT"
    assert payload["total_ingested"] > 0


def test_cli_ingest_towers_validation_errors(
    temp_towers_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify CLI errors on missing required input files or invalid regional identifiers."""
    err_buf = io.StringIO()
    monkeypatch.setattr("sys.stderr", err_buf)

    # Missing ant-path when source=fcc
    code_fcc = main(["ingest-towers", "--source", "fcc", "--db-path", str(temp_towers_db)])
    assert code_fcc == 1
    assert "--ant-path is required" in err_buf.getvalue()

    # Missing ised-path when source=ised
    err_buf.seek(0)
    err_buf.truncate(0)
    code_ised = main(["ingest-towers", "--source", "ised", "--db-path", str(temp_towers_db)])
    assert code_ised == 1
    assert "--ised-path is required" in err_buf.getvalue()

    # Invalid regional bounding filter
    err_buf.seek(0)
    err_buf.truncate(0)
    code_reg = main(
        [
            "ingest-towers",
            "--source",
            "civic",
            "--region",
            "INVALID_REGION_XYZ",
            "--db-path",
            str(temp_towers_db),
        ]
    )
    assert code_reg == 1
    assert "Error:" in err_buf.getvalue()


def test_api_towers_search_unbounded(client: TestClient) -> None:
    """Verify GET /api/towers/search without params returns 200 and auto-seeded civic towers."""
    resp = client.get("/api/towers/search")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] > 0
    assert len(data["towers"]) == data["count"]

    first = data["towers"][0]
    assert "site_id" in first
    assert "name" in first
    assert "location" in first
    assert "lat" in first["location"]
    assert "lon" in first["location"]
    assert "site_type" in first


def test_api_towers_search_type_filtering(client: TestClient) -> None:
    """Verify GET /api/towers/search filters by comma-separated SiteType values."""
    resp = client.get("/api/towers/search?types=water_tower,fire_lookout")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] > 0
    for tower in data["towers"]:
        assert tower["site_type"] in ("water_tower", "fire_lookout")


def test_api_towers_search_max_friction_filter(client: TestClient) -> None:
    """Verify GET /api/towers/search with max_friction=1 returns only Tier 1 infrastructure."""
    resp = client.get("/api/towers/search?max_friction=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] > 0


def test_api_towers_search_spatial_bbox(client: TestClient) -> None:
    """Verify GET /api/towers/search restricts results within spatial bounding box coordinates."""
    min_lat, max_lat = 44.0, 45.0
    min_lon, max_lon = -73.5, -72.0

    resp = client.get(
        f"/api/towers/search?min_lat={min_lat}&max_lat={max_lat}&min_lon={min_lon}&max_lon={max_lon}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    for tower in data["towers"]:
        loc = tower["location"]
        assert min_lat <= loc["lat"] <= max_lat
        assert min_lon <= loc["lon"] <= max_lon


def test_api_towers_search_limit(client: TestClient) -> None:
    """Verify GET /api/towers/search respects limit query parameter."""
    resp = client.get("/api/towers/search?limit=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] <= 3


def test_api_towers_ingest_civic(client: TestClient) -> None:
    """Verify POST /api/towers/ingest successfully ingests civic high-sites."""
    resp = client.post("/api/towers/ingest", json={"source": "civic"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source"] == "civic"
    assert data["ingested_count"] > 0
    assert data["by_friction_tier"]["tier_1_civic"] > 0


def test_api_towers_ingest_all_with_region(client: TestClient) -> None:
    """Verify POST /api/towers/ingest with region filter and all sources."""
    resp = client.post("/api/towers/ingest", json={"source": "all", "region": "VT"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["region"] == "VT"
    assert data["ingested_count"] > 0


def test_api_towers_ingest_invalid_region(client: TestClient) -> None:
    """Verify POST /api/towers/ingest returns 400 for unknown regional bounds."""
    resp = client.post("/api/towers/ingest", json={"source": "civic", "region": "UNKNOWN_REGION_123"})
    assert resp.status_code == 400
    assert "Invalid region" in resp.json()["detail"]
