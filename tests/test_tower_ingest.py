"""Unit tests for MeshScout Source Catalog, HTTPS Fetcher, and Multi-Source Ingest Pipeline.

All fetcher tests strictly use local filesystem stubs or mocked network interfaces.
ZERO live network calls are made during test execution.
"""

from __future__ import annotations

import io
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from meshscout.adapters.source_fetch import (
    fetch_source,
    fetch_source_file,
    get_catalog_path,
    get_source_metadata,
    load_source_catalog,
)
from meshscout.adapters.tower_ingest import (
    FrictionTierCounts,
    ingest_tower_source,
)
from meshscout.core.tower_registry import UnifiedTowerRegistry

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
FCC_VT_SAMPLE_PATH = FIXTURES_DIR / "fcc_asr_vt_sample.dat"
ISED_SAMPLE_PATH = FIXTURES_DIR / "ised_sms_sample.csv"
CIVIC_SAMPLE_PATH = FIXTURES_DIR / "civic_highsites_catalog.json"


class TestSourceCatalogAndMetadata:
    """Verify sources.json schema, authoritative metadata, and loader functions."""

    def test_catalog_file_exists_and_loads(self) -> None:
        cat_path = get_catalog_path()
        assert cat_path.exists(), f"sources.json not found at {cat_path}"
        catalog = load_source_catalog()
        assert isinstance(catalog, dict)
        assert len(catalog) >= 3

    def test_authoritative_source_entries(self) -> None:
        catalog = load_source_catalog()

        # 1. FCC ASR
        assert "fcc_asr" in catalog
        fcc = catalog["fcc_asr"]
        assert fcc["license"] == "Public Domain"
        assert "Federal Communications Commission" in fcc["attribution"]
        assert fcc["country"] == "US"
        assert fcc["url"].startswith("https://")

        # 2. ISED SMS
        assert "ised_sms" in catalog
        ised = catalog["ised_sms"]
        assert ised["license"] == "Open Government Licence - Canada"
        assert "Innovation, Science and Economic Development Canada" in ised["attribution"]
        assert ised["country"] == "CA"
        assert ised["url"].startswith("https://")

        # 3. Civic OSM
        assert "civic_osm" in catalog
        civic = catalog["civic_osm"]
        assert civic["license"] == "ODbL 1.0"
        assert "OpenStreetMap" in civic["attribution"]

    def test_get_source_metadata_helpers(self) -> None:
        meta = get_source_metadata("fcc_asr")
        assert meta["id"] == "fcc_asr"

        with pytest.raises(KeyError, match="Unknown source"):
            get_source_metadata("nonexistent_telecom_feed")


class TestSourceFetcherHermetic:
    """Hermetic tests for HTTPS source file fetching, caching, rate limiting, and backoff."""

    def test_fetch_cache_hit_avoids_network(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache_file = Path(td) / "existing_dataset.dat"
            cache_file.write_text("CACHED_PAYLOAD_NO_NETWORK", encoding="utf-8")

            with patch("urllib.request.urlopen") as mock_urlopen:
                result_path = fetch_source_file(
                    url="https://example.gov/telecom/asr.zip",
                    dest_path=cache_file,
                    force=False,
                )
                assert result_path == cache_file
                assert result_path.read_text(encoding="utf-8") == "CACHED_PAYLOAD_NO_NETWORK"
                mock_urlopen.assert_not_called()

    def test_fetch_mocked_network_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "downloaded.dat"
            mock_payload = b"MOCKED_TOWER_RECORDS_DATA"

            mock_resp = MagicMock()
            mock_resp.read.side_effect = [mock_payload, b""]
            mock_resp.__enter__.return_value = mock_resp

            with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                res = fetch_source_file(
                    url="https://example.gov/telecom/towers.dat",
                    dest_path=dest_file,
                )
                assert res == dest_file
                assert res.exists()
                assert res.read_bytes() == mock_payload
                mock_urlopen.assert_called_once()

    def test_fetch_retry_and_exponential_backoff(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "recovered.dat"
            mock_payload = b"SUCCESS_ON_THIRD_ATTEMPT"

            mock_resp = MagicMock()
            mock_resp.read.side_effect = [mock_payload, b""]
            mock_resp.__enter__.return_value = mock_resp

            attempts = [
                urllib.error.URLError("Connection refused"),
                urllib.error.URLError("Gateway timeout"),
                mock_resp,
            ]

            with patch("urllib.request.urlopen", side_effect=attempts), \
                 patch("time.sleep") as mock_sleep:
                res = fetch_source_file(
                    url="https://example.gov/telecom/flaky.dat",
                    dest_path=dest_file,
                    max_retries=3,
                    backoff_factor=0.1,
                )
                assert res.read_bytes() == mock_payload
                assert mock_sleep.call_count == 2

    def test_fetch_exceeded_retries_raises_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "failed.dat"

            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")), \
                 patch("time.sleep"):
                with pytest.raises(RuntimeError, match="Failed to fetch"):
                    fetch_source_file(
                        url="https://example.gov/telecom/down.dat",
                        dest_path=dest_file,
                        max_retries=2,
                        backoff_factor=0.01,
                    )
            assert not dest_file.exists()

    def test_fetch_unsupported_url_scheme(self) -> None:
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            fetch_source_file("ftp://example.com/files/towers.zip")


class TestTowerIngestPipeline:
    """Validate unified ingestion of FCC ASR, Canadian ISED SMS, and Civic high-sites."""

    @pytest.fixture
    def test_registry(self) -> Any:
        td = tempfile.TemporaryDirectory()
        db_path = Path(td.name) / "test_ingest_towers.db"
        registry = UnifiedTowerRegistry(db_path=db_path)
        yield registry
        registry.close()
        td.cleanup()

    def test_ingest_fcc_asr_vt_sample(self, test_registry: UnifiedTowerRegistry) -> None:
        assert FCC_VT_SAMPLE_PATH.exists()

        res = ingest_tower_source(
            registry=test_registry,
            source="fcc_asr",
            path=FCC_VT_SAMPLE_PATH,
        )

        assert res["ok"] is True
        assert res["source"] == "fcc_asr"
        assert res["ingested_count"] == 53
        assert res["by_region"]["VT"] == 53

        # Check friction tier distribution
        tier_stats = res["by_friction_tier"]
        assert tier_stats["tier_1_civic"] == 5
        assert tier_stats["tier_2_agricultural"] == 1
        assert tier_stats["tier_3_commercial"] == 47

        # Dual access (by int and string)
        assert tier_stats[1] == 5
        assert tier_stats[2] == 1
        assert tier_stats[3] == 47

    def test_ingest_ised_sms_sample(self, test_registry: UnifiedTowerRegistry) -> None:
        assert ISED_SAMPLE_PATH.exists()

        res = ingest_tower_source(
            registry=test_registry,
            source="ised_sms",
            path=ISED_SAMPLE_PATH,
        )

        assert res["ok"] is True
        assert res["source"] == "ised_sms"
        assert res["ingested_count"] == 6

        # Cross-province normalization
        assert "CA_QC" in res["by_region"]
        assert "CA_ON" in res["by_region"]
        assert res["by_region"]["CA_QC"] == 5
        assert res["by_region"]["CA_ON"] == 1

        # Friction tiers: Reservoir McTavish + Observatory + Parliament Hill = Tier 1 (3)
        # Hydro-Quebec = Tier 2 (1)
        # Bell + Telecommunications de l'Est = Tier 3 (2)
        tier_stats = res["by_friction_tier"]
        assert tier_stats["tier_1_civic"] == 3
        assert tier_stats["tier_2_agricultural"] == 1
        assert tier_stats["tier_3_commercial"] == 2

    def test_ingest_civic_sample(self, test_registry: UnifiedTowerRegistry) -> None:
        assert CIVIC_SAMPLE_PATH.exists()

        res = ingest_tower_source(
            registry=test_registry,
            source="civic",
            path=CIVIC_SAMPLE_PATH,
        )

        assert res["ok"] is True
        assert res["source"] == "civic"
        assert res["ingested_count"] == 16
        assert res["by_friction_tier"]["tier_1_civic"] >= 14

    def test_ingest_with_region_filter(self, test_registry: UnifiedTowerRegistry) -> None:
        assert CIVIC_SAMPLE_PATH.exists()

        # Ingest only Vermont sites from the multi-state civic catalog
        res = ingest_tower_source(
            registry=test_registry,
            source="civic",
            path=CIVIC_SAMPLE_PATH,
            region_code="VT",
        )

        assert res["ok"] is True
        assert res["ingested_count"] == 7
        assert res["by_region"] == {"VT": 7}

    def test_ingest_with_pack_id(self, test_registry: UnifiedTowerRegistry) -> None:
        assert ISED_SAMPLE_PATH.exists()

        res = ingest_tower_source(
            registry=test_registry,
            source="ised_sms",
            path=ISED_SAMPLE_PATH,
            pack_id="pack_ca_quebec_south_v1",
        )
        assert res["ok"] is True
        assert res["ingested_count"] == 6

        cur = test_registry.conn.cursor()
        pack_rows = cur.execute(
            "SELECT site_id FROM tower_packs WHERE pack_id = ?",
            ("pack_ca_quebec_south_v1",),
        ).fetchall()
        assert len(pack_rows) == 6

    def test_ingest_idempotency(self, test_registry: UnifiedTowerRegistry) -> None:
        # Run 1
        res1 = ingest_tower_source(
            registry=test_registry,
            source="fcc_asr",
            path=FCC_VT_SAMPLE_PATH,
        )
        cur = test_registry.conn.cursor()
        cnt1 = cur.execute("SELECT COUNT(*) FROM towers").fetchone()[0]
        assert cnt1 == res1["ingested_count"] == 53

        # Run 2 with identical source and dataset
        res2 = ingest_tower_source(
            registry=test_registry,
            source="fcc_asr",
            path=FCC_VT_SAMPLE_PATH,
        )
        cnt2 = cur.execute("SELECT COUNT(*) FROM towers").fetchone()[0]
        assert cnt2 == cnt1, "Re-running ingest must leave database tower row count unchanged"
        assert res2["ingested_count"] == 53

    def test_ingest_unsupported_source_raises(self, test_registry: UnifiedTowerRegistry) -> None:
        with pytest.raises(ValueError, match="Unsupported tower source"):
            ingest_tower_source(
                registry=test_registry,
                source="unsupported_source_type",
                path=FCC_VT_SAMPLE_PATH,
            )

    def test_ingest_nonexistent_file_raises(self, test_registry: UnifiedTowerRegistry) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            ingest_tower_source(
                registry=test_registry,
                source="fcc_asr",
                path=Path("nonexistent_path_to_data.dat"),
            )
