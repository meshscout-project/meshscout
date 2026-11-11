"""Unit and integration tests for Pack Client, CLI Commands, and CI Pack Builder (TASK-1135).

All network calls are hermetically intercepted; ZERO live network requests are made.
"""

from __future__ import annotations

import email
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request
import pytest

from meshscout.adapters.pack_builder import _find_fixture, build_region_packs
from meshscout.adapters.pack_client import (
    DEFAULT_ALLOWED_HOSTS,
    DEFAULT_MANIFEST_URL,
    AllowlistRedirectHandler,
    PackClient,
)
from meshscout.cli import main
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    Result,
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
    list_installed_packs,
)
from meshscout.core.tower_registry import SCHEMA_VERSION, UnifiedTowerRegistry

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
FCC_VT_SAMPLE_PATH = _find_fixture("fcc_asr_vt_sample.dat")
ISED_SAMPLE_PATH = _find_fixture("ised_sms_sample.csv")
CIVIC_SAMPLE_PATH = _find_fixture("civic_highsites_catalog.json")


def _make_dummy_site(site_id: str = "VT-TEST-01", region_code: str = "VT") -> SiteCandidate:
    """Helper to generate a valid test candidate."""
    return SiteCandidate(
        site_id=site_id,
        name="Test Hill",
        location=Coordinate(lat=44.4759, lon=-73.2121, elevation_m=120.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=25.0,
        has_grid_power=True,
        solar_exposure_pct=95.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
    )


class MockTransportHandler(urllib.request.BaseHandler):
    """Hermetic urllib BaseHandler for route-based testing with redirects."""

    handler_order = 100

    def __init__(self, routes: Dict[str, tuple[int, Dict[str, str], bytes]]) -> None:
        super().__init__()
        self.routes = routes

    def http_open(self, req: urllib.request.Request) -> Any:
        return self._handle(req)

    def https_open(self, req: urllib.request.Request) -> Any:
        return self._handle(req)

    def _handle(self, req: urllib.request.Request) -> Any:
        url = req.full_url
        if url in self.routes:
            status, headers_dict, body = self.routes[url]
            hdr_str = "".join(f"{k}: {v}\n" for k, v in headers_dict.items()) + "\n"
            headers = email.message_from_string(hdr_str)
            resp = urllib.response.addinfourl(io.BytesIO(body), headers, url, code=status)
            resp.msg = "Found" if status in (301, 302, 303, 307, 308) else "OK"
            return resp
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


class TestPackClientHermetic:
    """Hermetic unit tests for PackClient manifest fetching, caching, downloading, and verification."""

    def test_default_manifest_url_and_allowed_hosts(self) -> None:
        """Verify DEFAULT_ALLOWED_HOSTS and DEFAULT_MANIFEST_URL constants."""
        assert "release-assets.githubusercontent.com" in DEFAULT_ALLOWED_HOSTS
        assert "github.com" in DEFAULT_ALLOWED_HOSTS
        assert "objects.githubusercontent.com" in DEFAULT_ALLOWED_HOSTS
        assert "raw.githubusercontent.com" in DEFAULT_ALLOWED_HOSTS
        assert "manifest.json" in DEFAULT_MANIFEST_URL

    def test_disallowed_host_aborts_with_host_not_allowed(self, tmp_path: Path) -> None:
        """Disallowed domain names must immediately fail with HOST_NOT_ALLOWED."""
        client = PackClient(
            manifest_url="https://malicious-site.evil/manifest.json",
            cache_dir=tmp_path / "cache",
        )
        res = client.fetch_manifest()
        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "HOST_NOT_ALLOWED"
        assert "malicious-site.evil" in res.error.message

        # Test download_pack host allowlist gate
        bad_pack = RegionPackInfo(
            pack_id="towers-bad",
            region_code="VT",
            pack_version="1.0.0",
            schema_version=SCHEMA_VERSION,
            row_count=10,
            sha256="abc123def456",
            size_bytes=100,
            url="https://untrusted-storage.attacker.com/pack.sqlite.gz",
        )
        dl_res = client.download_pack(bad_pack)
        assert dl_res.ok is False
        assert dl_res.error is not None
        assert dl_res.error.code == "HOST_NOT_ALLOWED"

    def test_sha256_mismatch_aborts_with_pack_hash_mismatch(self, tmp_path: Path) -> None:
        """Corrupted or mismatched payload bytes must be rejected with PACK_HASH_MISMATCH."""
        corrupt_payload = b"FAKE_CORRUPTED_ARCHIVE_DATA"
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [corrupt_payload, b""]
        mock_resp.__enter__.return_value = mock_resp

        client = PackClient(
            manifest_url="http://127.0.0.1/manifest.json",
            allowed_hosts=["127.0.0.1"],
            cache_dir=tmp_path / "cache",
        )

        pack_info = RegionPackInfo(
            pack_id="towers-vt",
            region_code="VT",
            pack_version="1.0.0",
            schema_version=SCHEMA_VERSION,
            row_count=1,
            sha256="0000000000000000000000000000000000000000000000000000000000000000",
            size_bytes=len(corrupt_payload),
            url="http://127.0.0.1/towers-vt-1.0.0.sqlite.gz",
        )

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = client.download_pack(pack_info)

        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "PACK_HASH_MISMATCH"
        assert "mismatch" in res.error.message.lower()

        # Verify temporary file cleanup
        temp_files = list((tmp_path / "cache").glob("ms_pack_*.tmp"))
        assert len(temp_files) == 0

        # Verify aborting installation leaves registry untouched
        test_db = tmp_path / "abort_test.db"
        with UnifiedTowerRegistry(db_path=test_db) as reg:
            dummy_manifest = build_pack_manifest([pack_info])
            mock_resp2 = MagicMock()
            mock_resp2.read.side_effect = [corrupt_payload, b""]
            mock_resp2.__enter__.return_value = mock_resp2
            with patch("urllib.request.urlopen", return_value=mock_resp2):
                with patch.object(client, "fetch_manifest", return_value=Result.success(dummy_manifest)):
                    inst_res = client.install_pack(reg, "VT")
                    assert inst_res.ok is False
                    assert inst_res.error is not None
                    assert inst_res.error.code == "PACK_HASH_MISMATCH"
            assert len(list_installed_packs(reg)) == 0

    def test_redirect_to_allowed_host_succeeds(self, tmp_path: Path) -> None:
        """302 redirect from an allowed host to another allowed host succeeds."""
        pack_content = gzip.compress(b"HERMETIC_SQLITE_PACK_PAYLOAD")
        pack_hash = hashlib.sha256(pack_content).hexdigest()

        initial_url = (
            "https://github.com/meshscout-project/meshscout/releases/download/v1.0.0/towers-vt-1.0.0.sqlite.gz"
        )
        redirect_url = (
            "https://release-assets.githubusercontent.com/meshscout-project/meshscout/towers-vt-1.0.0.sqlite.gz"
        )

        routes = {
            initial_url: (302, {"Location": redirect_url}, b""),
            redirect_url: (200, {"Content-Type": "application/gzip"}, pack_content),
        }

        pack_info = RegionPackInfo(
            pack_id="towers-vt",
            region_code="VT",
            pack_version="1.0.0",
            schema_version=SCHEMA_VERSION,
            row_count=10,
            sha256=pack_hash,
            size_bytes=len(pack_content),
            url=initial_url,
        )

        client = PackClient(cache_dir=tmp_path / "cache")
        client.opener = client._build_opener(MockTransportHandler(routes))

        res = client.download_pack(pack_info)
        assert res.ok is True
        assert res.value is not None
        assert res.value.exists()
        assert compute_sha256(res.value) == pack_hash

    def test_redirect_to_unallowed_host_blocked_in_download(self, tmp_path: Path) -> None:
        """302 redirect to an unallowed host is intercepted and rejected with HOST_NOT_ALLOWED."""
        pack_content = gzip.compress(b"MALICIOUS_PAYLOAD")
        pack_hash = hashlib.sha256(pack_content).hexdigest()

        initial_url = (
            "https://github.com/meshscout-project/meshscout/releases/download/v1.0.0/towers-vt-1.0.0.sqlite.gz"
        )
        malicious_redirect_url = "https://evil-attacker.com/malicious-pack.sqlite.gz"

        routes = {
            initial_url: (302, {"Location": malicious_redirect_url}, b""),
            malicious_redirect_url: (200, {"Content-Type": "application/gzip"}, pack_content),
        }

        pack_info = RegionPackInfo(
            pack_id="towers-vt",
            region_code="VT",
            pack_version="1.0.0",
            schema_version=SCHEMA_VERSION,
            row_count=10,
            sha256=pack_hash,
            size_bytes=len(pack_content),
            url=initial_url,
        )

        cache_dir = tmp_path / "cache"
        client = PackClient(cache_dir=cache_dir)
        client.opener = client._build_opener(MockTransportHandler(routes))

        res = client.download_pack(pack_info)
        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "HOST_NOT_ALLOWED"
        assert "unallowed host" in res.error.message.lower() or "blocked" in res.error.message.lower()

        # Verify no temporary files remain
        temp_files = list(cache_dir.glob("ms_pack_*.tmp"))
        assert len(temp_files) == 0

    def test_redirect_to_unallowed_host_blocked_in_manifest_fetch(self, tmp_path: Path) -> None:
        """302 redirect in fetch_manifest to an unallowed host is rejected with HOST_NOT_ALLOWED."""
        manifest_url = "https://github.com/meshscout-project/meshscout/releases/latest/download/manifest.json"
        malicious_url = "https://evil-attacker.com/manifest.json"

        routes = {
            manifest_url: (302, {"Location": malicious_url}, b""),
            malicious_url: (200, {"Content-Type": "application/json"}, b"{}"),
        }

        client = PackClient(
            manifest_url=manifest_url,
            cache_dir=tmp_path / "cache",
        )
        client.opener = client._build_opener(MockTransportHandler(routes))

        res = client.fetch_manifest()
        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "HOST_NOT_ALLOWED"
        assert "unallowed host" in res.error.message.lower() or "blocked" in res.error.message.lower()

    def test_allowlist_redirect_handler_intercepts_unallowed_all_30x_codes(self) -> None:
        """AllowlistRedirectHandler must raise HTTPError(403) on 301, 302, 303, 307, 308."""
        client = PackClient(allowed_hosts=["github.com"])
        handler = AllowlistRedirectHandler(client)

        req = urllib.request.Request("https://github.com/source")
        headers = email.message_from_string("Location: https://evil-attacker.com/malicious\n\n")

        for code in (301, 302, 303, 307, 308):
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                handler.redirect_request(req, None, code, "Redirect", headers, "https://evil-attacker.com/malicious")
            assert exc_info.value.code == 403
            assert "evil-attacker.com" in str(exc_info.value)
            exc_info.value.close()

    def test_allowlist_redirect_handler_permits_allowed_destination(self) -> None:
        """AllowlistRedirectHandler must return Request when target host is allowed."""
        client = PackClient(allowed_hosts=["github.com", "release-assets.githubusercontent.com"])
        handler = AllowlistRedirectHandler(client)

        req = urllib.request.Request("https://github.com/source")
        dest_url = "https://release-assets.githubusercontent.com/pack.sqlite.gz"
        headers = email.message_from_string(f"Location: {dest_url}\n\n")

        new_req = handler.redirect_request(req, None, 302, "Found", headers, dest_url)
        assert new_req is not None
        assert new_req.full_url == dest_url

    def test_manifest_fallback_to_bundled_when_unreachable(self, tmp_path: Path) -> None:
        """When remote manifest endpoint is unreachable, fallback to bundled manifest."""
        client = PackClient(
            manifest_url="http://127.0.0.1:9999/manifest.json",
            allowed_hosts=["127.0.0.1"],
            cache_dir=tmp_path / "cache",
        )
        # Mock network failure via URLError
        mock_open = MagicMock(side_effect=urllib.error.URLError("Connection refused"))
        with patch.object(client.opener, "open", mock_open):
            res = client.fetch_manifest()
            assert res.ok is True
            assert res.value is not None
            assert "towers-vt" in res.value.packs

    def test_manifest_fetch_download_and_install_mocked(self, tmp_path: Path) -> None:
        """Test complete workflow: fetch manifest, download pack, verify, and install into registry."""
        origin_dir = tmp_path / "origin"
        origin_dir.mkdir(parents=True, exist_ok=True)

        # 1. Create a genuine, valid test pack archive
        build_db_path = origin_dir / "build.db"
        with UnifiedTowerRegistry(db_path=build_db_path) as build_reg:
            build_reg.upsert_tower(_make_dummy_site("VT-TEST-01"), region_code="VT")
            source_info = PackSourceInfo(
                dataset="fcc_asr",
                license="Public Domain",
                attribution="FCC",
            )
            real_pack_info = export_region_pack(
                registry=build_reg,
                region_code="VT",
                out_dir=origin_dir,
                pack_version="1.0.0",
                sources=[source_info],
            )

        pack_archive_path = origin_dir / f"towers-vt-{real_pack_info.pack_version}.sqlite.gz"
        assert pack_archive_path.exists()
        pack_bytes = pack_archive_path.read_bytes()

        # Update URL to mock host
        real_pack_info.url = "http://127.0.0.1:8080/towers-vt-1.0.0.sqlite.gz"
        manifest = build_pack_manifest([real_pack_info])
        manifest_json_bytes = manifest.to_json().encode("utf-8")

        # Mock urllib.request.urlopen dispatcher
        def mock_urlopen_handler(req: Any, timeout: float = 30.0) -> Any:
            url = req.full_url if hasattr(req, "full_url") else str(req)
            resp = MagicMock()
            if "manifest.json" in url:
                resp.read.side_effect = [manifest_json_bytes, b""]
            elif "towers-vt" in url:
                resp.read.side_effect = [pack_bytes, b""]
            else:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            resp.__enter__.return_value = resp
            return resp

        client = PackClient(
            manifest_url="http://127.0.0.1:8080/manifest.json",
            allowed_hosts=["127.0.0.1"],
            cache_dir=tmp_path / "client_cache",
        )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
            # Test manifest fetch
            m_res = client.fetch_manifest()
            assert m_res.ok is True
            assert m_res.value is not None
            assert "towers-vt" in m_res.value.packs

            # Test list available packs
            avail_res = client.list_available_packs()
            assert avail_res.ok is True
            assert len(avail_res.value or []) == 1

            # Test download
            dl_res = client.download_pack(real_pack_info)
            assert dl_res.ok is True
            assert dl_res.value is not None
            assert dl_res.value.exists()
            assert compute_sha256(dl_res.value) == real_pack_info.sha256

            # Test installation into clean registry
            target_db_path = tmp_path / "target_towers.db"
            with UnifiedTowerRegistry(db_path=target_db_path) as target_reg:
                inst_res = client.install_pack(target_reg, "VT")
                assert inst_res.ok is True
                assert inst_res.value is not None
                assert inst_res.value.pack_id == "towers-vt"

                installed_list = list_installed_packs(target_reg)
                assert len(installed_list) == 1
                assert installed_list[0]["pack_id"] == "towers-vt"

                # Check update_installed_packs reports up_to_date
                up_res = client.update_installed_packs(target_reg)
                assert up_res["ok"] is True
                assert len(up_res["up_to_date"]) == 1
                assert up_res["up_to_date"][0]["pack_id"] == "towers-vt"


class TestPackBuilder:
    """Verify offline fixture compiling, manifest generation, and artifact validity."""

    def test_build_region_packs_offline_fixtures(self, tmp_path: Path) -> None:
        """Test meshscout packs build --regions VT --offline-fixtures creates valid pack and manifest."""
        out_dir = tmp_path / "built_packs"

        manifest = build_region_packs(
            regions=["VT"],
            out_dir=out_dir,
            offline_fixtures=True,
            base_url="https://github.com/meshscout/meshscout/releases/download/v1.0.0",
        )

        assert manifest.manifest_version == "1.0.0"
        assert "towers-vt" in manifest.packs
        vt_pack = manifest.packs["towers-vt"]
        assert vt_pack.region_code == "VT"
        assert vt_pack.row_count > 0  # Sample fixtures provide ~60 sites for VT
        assert vt_pack.sha256
        assert vt_pack.size_bytes > 0
        assert vt_pack.url == "https://github.com/meshscout/meshscout/releases/download/v1.0.0/towers-vt-1.0.0.sqlite.gz"

        # Verify disk files
        manifest_file = out_dir / "manifest.json"
        assert manifest_file.exists()
        loaded_manifest = PackManifest.from_file(manifest_file)
        assert loaded_manifest.packs["towers-vt"].row_count == vt_pack.row_count

        pack_archive = out_dir / "towers-vt-1.0.0.sqlite.gz"
        assert pack_archive.exists()
        assert compute_sha256(pack_archive) == vt_pack.sha256

        # Verify the generated pack installs cleanly into a new registry
        test_db = tmp_path / "verify_install.db"
        with UnifiedTowerRegistry(db_path=test_db) as reg:
            from meshscout.core.packs import install_region_pack
            res = install_region_pack(reg, pack_archive, expected_sha256=vt_pack.sha256)
            assert res.ok is True
            assert res.value is not None
            assert res.value.row_count == vt_pack.row_count


class TestCLIIntegration:
    """End-to-end testing of regions, towers ingest, and packs build CLI commands."""

    def test_cli_packs_build_offline_fixtures(self, tmp_path: Path) -> None:
        """Verify CLI execution of 'meshscout packs build --regions VT --offline-fixtures'."""
        out_dir = tmp_path / "cli_dist_packs"
        argv = [
            "packs",
            "build",
            "--regions",
            "VT",
            "--out-dir",
            str(out_dir),
            "--offline-fixtures",
            "--json",
        ]
        ret = main(argv)
        assert ret == 0

        manifest_path = out_dir / "manifest.json"
        assert manifest_path.exists()
        pack_path = out_dir / "towers-vt-1.0.0.sqlite.gz"
        assert pack_path.exists()

    def test_cli_towers_ingest_all_sources(self, tmp_path: Path) -> None:
        """Verify CLI execution of 'towers ingest' across civic, fcc_asr, and ised_sms."""
        test_db = tmp_path / "towers_cli.db"

        # 1. Civic ingest
        ret_civic = main([
            "towers",
            "ingest",
            "--source",
            "civic",
            "--path",
            str(CIVIC_SAMPLE_PATH),
            "--region",
            "VT",
            "--db-path",
            str(test_db),
            "--json",
        ])
        assert ret_civic == 0

        # 2. FCC ASR ingest
        ret_fcc = main([
            "towers",
            "ingest",
            "--source",
            "fcc_asr",
            "--path",
            str(FCC_VT_SAMPLE_PATH),
            "--region",
            "VT",
            "--db-path",
            str(test_db),
            "--json",
        ])
        assert ret_fcc == 0

        # 3. ISED SMS ingest
        ret_ised = main([
            "towers",
            "ingest",
            "--source",
            "ised_sms",
            "--path",
            str(ISED_SAMPLE_PATH),
            "--db-path",
            str(test_db),
            "--json",
        ])
        assert ret_ised == 0

        # Verify sites exist in DB
        with UnifiedTowerRegistry(db_path=test_db) as reg:
            stats = reg.count_towers_by_category()
            total_towers = sum(cnt for k, cnt in stats.items() if k in ("tier_1", "tier_2", "tier_3"))
            assert total_towers > 50

    def test_cli_towers_ingest_missing_path_and_from_source(self) -> None:
        """Omitting both --path and --from-source must exit with return code 2."""
        ret = main(["towers", "ingest", "--source", "civic"])
        assert ret == 2

    def test_cli_regions_lifecycle(self, tmp_path: Path) -> None:
        """Verify CLI lifecycle: regions list, install, update, remove."""
        test_db = tmp_path / "regions_cli.db"
        out_packs = tmp_path / "test_packs"

        # Build local pack to act as mock server source
        manifest = build_region_packs(
            regions=["VT"],
            out_dir=out_packs,
            offline_fixtures=True,
            base_url="http://127.0.0.1:8080",
        )
        pack_archive = out_packs / "towers-vt-1.0.0.sqlite.gz"
        pack_bytes = pack_archive.read_bytes()
        manifest_bytes = (out_packs / "manifest.json").read_bytes()

        # 1. regions list initially empty
        ret_list_empty = main(["regions", "list", "--db-path", str(test_db), "--json"])
        assert ret_list_empty == 0

        # Mock network for client install
        def mock_urlopen_handler(req: Any, timeout: float = 30.0) -> Any:
            url = req.full_url if hasattr(req, "full_url") else str(req)
            resp = MagicMock()
            if "manifest.json" in url:
                resp.read.side_effect = [manifest_bytes, b""]
            elif "towers-vt" in url:
                resp.read.side_effect = [pack_bytes, b""]
            else:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            resp.__enter__.return_value = resp
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
            # 2. regions list --available
            ret_avail = main([
                "regions",
                "list",
                "--available",
                "--manifest-url",
                "http://127.0.0.1:8080/manifest.json",
                "--json",
            ])
            assert ret_avail == 0

            # 3. regions install VT
            ret_install = main([
                "regions",
                "install",
                "VT",
                "--manifest-url",
                "http://127.0.0.1:8080/manifest.json",
                "--db-path",
                str(test_db),
            ])
            assert ret_install == 0

            # 4. regions update
            ret_update = main([
                "regions",
                "update",
                "--manifest-url",
                "http://127.0.0.1:8080/manifest.json",
                "--db-path",
                str(test_db),
                "--json",
            ])
            assert ret_update == 0

        # 5. regions remove VT
        ret_remove = main([
            "regions",
            "remove",
            "VT",
            "--db-path",
            str(test_db),
        ])
        assert ret_remove == 0

        # 6. Verify removed
        with UnifiedTowerRegistry(db_path=test_db) as reg:
            assert len(list_installed_packs(reg)) == 0
