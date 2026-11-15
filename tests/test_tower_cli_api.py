"""Unit and integration tests for Tower Ingestion CLI and Web REST API (TASK-1094)."""

from __future__ import annotations

import io
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from meshscout.cli import build_parser, main
from meshscout.cli_tower_helpers import format_tower_ingest_summary, run_towers_subcommand
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


def test_format_tower_ingest_summary() -> None:
    """Verify pure human-readable summary formatting for tower ingestion results."""
    ingest_res = {
        "ok": True,
        "source": "fcc_asr",
        "ingested_count": 1295,
        "by_region": {"VT": 1250, "CA_QC": 45},
        "by_friction_tier": {
            "tier_1_civic": 200,
            "tier_2_agricultural": 95,
            "tier_3_commercial": 1000,
        },
    }
    summary = format_tower_ingest_summary(ingest_res, "fcc_asr")
    assert "Ingested 1295 towers from fcc_asr" in summary
    assert "Breakdown by Region:" in summary
    ca_idx = summary.index("   - CA_QC       : 45 towers")
    vt_idx = summary.index("   - VT          : 1,250 towers")
    assert ca_idx < vt_idx
    assert "   - Tier 1 Civic:        200 towers" in summary
    assert "   - Tier 2 Agricultural: 95 towers" in summary
    assert "   - Tier 3 Commercial:   1,000 towers" in summary
    assert summary.endswith("============================================================\n")


def test_cli_towers_ingest_civic_human_readable(
    temp_towers_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify 'towers ingest civic --path ...' human-readable output and DB persistence."""
    civic_path = Path(__file__).resolve().parent.parent / "fixtures" / "civic_highsites_catalog.json"
    out_buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", out_buf)

    exit_code = main(
        [
            "towers",
            "ingest",
            "civic",
            "--path",
            str(civic_path),
            "--db-path",
            str(temp_towers_db),
        ]
    )
    assert exit_code == 0
    output = out_buf.getvalue()
    assert "towers from civic" in output
    assert "Breakdown by Region:" in output
    assert "Breakdown by Friction Tier:" in output
    assert "Tier 1 Civic:" in output

    with UnifiedTowerRegistry(db_path=temp_towers_db) as registry:
        assert len(registry.query_towers(max_friction_tier=1)) > 0


def test_cli_towers_ingest_civic_json_mode(
    temp_towers_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify 'towers ingest civic --path ... --json' emits structured JSON summary."""
    civic_path = Path(__file__).resolve().parent.parent / "fixtures" / "civic_highsites_catalog.json"
    out_buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", out_buf)

    exit_code = main(
        [
            "towers",
            "ingest",
            "civic",
            "--path",
            str(civic_path),
            "--region",
            "VT",
            "--db-path",
            str(temp_towers_db),
            "--json",
        ]
    )
    assert exit_code == 0
    payload = json.loads(out_buf.getvalue())
    assert payload["ok"] is True
    assert payload["source"] == "civic"
    assert payload["ingested_count"] > 0
    assert "VT" in payload["by_region"]
    assert payload["by_friction_tier"]["tier_1_civic"] > 0


def test_cli_towers_ingest_validation_failures(
    temp_towers_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify POSIX exit codes 2 and 1 for validation and missing-path errors."""
    civic_path = Path(__file__).resolve().parent.parent / "fixtures" / "civic_highsites_catalog.json"
    err_buf = io.StringIO()
    monkeypatch.setattr("sys.stderr", err_buf)

    # 1. Missing source -> exit code 2
    code_no_source = main(["towers", "ingest", "--path", str(civic_path)])
    assert code_no_source == 2
    assert "Must specify source" in err_buf.getvalue()

    # 2. Missing both --path/--input and --from-source -> exit code 2
    err_buf.seek(0)
    err_buf.truncate(0)
    code_no_path = main(["towers", "ingest", "civic"])
    assert code_no_path == 2
    assert "Must specify either --path/--input <PATH> or --from-source" in err_buf.getvalue()

    # 3. Nonexistent path -> exit code 1
    err_buf.seek(0)
    err_buf.truncate(0)
    missing_file = tmp_path / "nonexistent_towers.json"
    code_missing_file = main(
        [
            "towers",
            "ingest",
            "civic",
            "--path",
            str(missing_file),
            "--db-path",
            str(temp_towers_db),
        ]
    )
    assert code_missing_file == 1
    assert f"Source file not found: {missing_file}" in err_buf.getvalue()

    # 4. Offline --from-source fetch failure -> exit code 1
    err_buf.seek(0)
    err_buf.truncate(0)

    def _fail_fetch(_src: str) -> Path:
        raise RuntimeError("simulated offline fetch error")

    monkeypatch.setattr("meshscout.adapters.source_fetch.fetch_source", _fail_fetch)
    parser = build_parser()
    parsed = parser.parse_args(
        ["towers", "ingest", "civic", "--from-source", "--db-path", str(temp_towers_db)]
    )
    code_fetch_err = run_towers_subcommand(parsed)
    assert code_fetch_err == 1
    assert "Error fetching source 'civic': simulated offline fetch error" in err_buf.getvalue()
