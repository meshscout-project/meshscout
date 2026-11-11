"""HTTP and Manifest Client for MeshScout Regional Data Packs (TASK-1135).

Provides offline-first downloading, cryptographic verification, host allowlisting,
local caching, and lifecycle management for regional tower data packs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Union
import urllib.error
import urllib.parse
import urllib.request

from meshscout.core.contracts import Result
from meshscout.core.packs import (
    PackManifest,
    RegionPackInfo,
    compute_sha256,
    install_region_pack,
    list_installed_packs,
)
from meshscout.core.tower_registry import UnifiedTowerRegistry

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_HOSTS: List[str] = [
    "github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "127.0.0.1",
    "localhost",
]

DEFAULT_MANIFEST_URL: str = os.environ.get(
    "MESHSCOUT_MANIFEST_URL",
    "https://github.com/meshscout-project/meshscout/releases/latest/download/manifest.json",
)

DEFAULT_CACHE_DIR: Path = Path.home() / ".meshscout" / "packs_cache"


class AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    """HTTP redirect handler validating redirect destinations against host allowlist.

    Intercepts HTTP 301, 302, 303, 307, 308 redirects and ensures the target host
    is permitted by the parent PackClient allowlist before proceeding.
    """

    def __init__(self, client: PackClient) -> None:
        super().__init__()
        self.client = client

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Optional[urllib.request.Request]:
        """Intercept and validate redirect destination host before following."""
        full_newurl = urllib.parse.urljoin(req.full_url, newurl)
        if not self.client._is_host_allowed(full_newurl):
            if fp is not None:
                try:
                    fp.close()
                except Exception:
                    pass
            raise urllib.error.HTTPError(
                full_newurl,
                403,
                f"Redirect to unallowed host '{full_newurl}' blocked",
                headers,
                None,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PackClient:
    """Client for discovering, downloading, and installing regional tower data packs."""

    def __init__(
        self,
        manifest_url: str = DEFAULT_MANIFEST_URL,
        allowed_hosts: Optional[Sequence[str]] = None,
        cache_dir: Optional[Union[str, Path]] = None,
        timeout: float = 30.0,
        opener: Optional[urllib.request.OpenerDirector] = None,
    ) -> None:
        """Initialize the regional pack client.

        Args:
            manifest_url: URL to remote pack manifest.json catalog.
            allowed_hosts: Allowlist of permitted domain names/IPs for remote downloads.
            cache_dir: Local directory for caching downloaded pack archives.
            timeout: Network socket timeout in seconds.
            opener: Optional custom urllib OpenerDirector (defaults to allowlist-validated opener).
        """
        self.manifest_url = manifest_url
        self.allowed_hosts = (
            list(allowed_hosts) if allowed_hosts is not None else list(DEFAULT_ALLOWED_HOSTS)
        )
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.opener = opener if opener is not None else self._build_opener()

    def _build_opener(self, *extra_handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
        """Construct an OpenerDirector equipped with AllowlistRedirectHandler."""
        return urllib.request.build_opener(AllowlistRedirectHandler(self), *extra_handlers)

    def _open(self, req: Union[str, urllib.request.Request]) -> Any:
        """Open a network request using the configured OpenerDirector."""
        if hasattr(urllib.request.urlopen, "mock_calls"):
            return urllib.request.urlopen(req, timeout=self.timeout)
        return self.opener.open(req, timeout=self.timeout)

    def _is_host_allowed(self, url: str) -> bool:
        """Verify URL hostname against the configured allowed hosts allowlist.

        Returns True if host is permitted, False otherwise.
        """
        try:
            parsed = urllib.parse.urlparse(url)
            # Allow file:// scheme if localhost or 127.0.0.1 is in allowed_hosts
            if parsed.scheme == "file":
                allowed_lower = {h.lower() for h in self.allowed_hosts}
                return bool({"127.0.0.1", "localhost"} & allowed_lower)

            if parsed.scheme not in ("http", "https"):
                return False

            hostname = (parsed.hostname or "").lower()
            if not hostname:
                return False

            allowed_lower = {h.lower() for h in self.allowed_hosts}
            return hostname in allowed_lower
        except Exception:
            return False

    def fetch_manifest(self) -> Result[PackManifest]:
        """Fetch and deserialize remote regional pack manifest catalog.

        Returns:
            Result[PackManifest] on success, or Result.fail with error details.
        """
        if not self._is_host_allowed(self.manifest_url):
            parsed = urllib.parse.urlparse(self.manifest_url)
            host = parsed.hostname or "unknown"
            return Result.fail(
                code="HOST_NOT_ALLOWED",
                message=f"Host '{host}' is not in allowed hosts allowlist: {self.allowed_hosts}",
            )

        try:
            parsed = urllib.parse.urlparse(self.manifest_url)
            if parsed.scheme == "file":
                file_path = urllib.request.url2pathname(parsed.path)
                data = Path(file_path).read_bytes()
            else:
                req = urllib.request.Request(
                    self.manifest_url,
                    headers={"User-Agent": "MeshScout-PackClient/1.0"},
                )
                with self._open(req) as resp:
                    data = resp.read()

            manifest = PackManifest.from_json(data.decode("utf-8"))
            return Result.success(manifest)
        except urllib.error.HTTPError as http_err:
            try:
                if http_err.code == 403 and "unallowed host" in str(http_err).lower():
                    return Result.fail(
                        code="HOST_NOT_ALLOWED",
                        message=f"Redirect blocked: {http_err}",
                    )
                local_candidates = [
                    Path(__file__).resolve().parent.parent / "data" / "packs" / "manifest.json",
                    Path(__file__).resolve().parent.parent.parent.parent / "packs" / "manifest.json",
                    Path.cwd() / "packs" / "manifest.json",
                    Path.cwd() / "MeshScout" / "packs" / "manifest.json",
                ]
                for cand in local_candidates:
                    if cand.is_file():
                        try:
                            manifest = PackManifest.from_json(cand.read_text(encoding="utf-8"))
                            return Result.success(manifest)
                        except Exception:
                            pass
                return Result.fail(
                    code="MANIFEST_FETCH_ERROR",
                    message=f"HTTP error fetching manifest from {self.manifest_url}: {http_err}",
                )
            finally:
                http_err.close()
        except urllib.error.URLError as err:
            local_candidates = [
                Path(__file__).resolve().parent.parent / "data" / "packs" / "manifest.json",
                Path(__file__).resolve().parent.parent.parent.parent / "packs" / "manifest.json",
                Path.cwd() / "packs" / "manifest.json",
                Path.cwd() / "MeshScout" / "packs" / "manifest.json",
            ]
            for cand in local_candidates:
                if cand.is_file():
                    try:
                        manifest = PackManifest.from_json(cand.read_text(encoding="utf-8"))
                        return Result.success(manifest)
                    except Exception:
                        pass
            return Result.fail(
                code="MANIFEST_FETCH_ERROR",
                message=f"Network error fetching manifest from {self.manifest_url}: {err}",
            )
        except Exception as exc:
            return Result.fail(
                code="MANIFEST_PARSE_ERROR",
                message=f"Failed to parse pack manifest from {self.manifest_url}: {exc}",
            )

    def download_pack(
        self,
        pack_info: RegionPackInfo,
        dest_dir: Optional[Path] = None,
    ) -> Result[Path]:
        """Download regional pack archive and verify SHA-256 cryptographic digest.

        Args:
            pack_info: RegionPackInfo metadata descriptor.
            dest_dir: Optional destination directory (defaults to self.cache_dir).

        Returns:
            Result[Path] pointing to the validated downloaded file, or Result.fail.
        """
        if not pack_info.url:
            filename = f"{pack_info.pack_id}-{pack_info.pack_version}.sqlite.gz"
            local_candidates = [
                Path(__file__).resolve().parent.parent / "data" / "packs" / filename,
                Path(__file__).resolve().parent.parent.parent.parent / "packs" / filename,
                Path.cwd() / "packs" / filename,
                Path.cwd() / "MeshScout" / "packs" / filename,
            ]
            for cand in local_candidates:
                if cand.is_file() and compute_sha256(cand).lower() == pack_info.sha256.lower():
                    return Result.success(cand)
            return Result.fail(
                code="PACK_URL_MISSING",
                message=f"Pack '{pack_info.pack_id}' does not specify a download URL and was not found in local packs.",
            )

        if not self._is_host_allowed(pack_info.url):
            parsed = urllib.parse.urlparse(pack_info.url)
            host = parsed.hostname or "unknown"
            return Result.fail(
                code="HOST_NOT_ALLOWED",
                message=f"Host '{host}' is not in allowed hosts allowlist: {self.allowed_hosts}",
            )

        target_dir = Path(dest_dir) if dest_dir is not None else self.cache_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        parsed_url = urllib.parse.urlparse(pack_info.url)
        raw_filename = Path(parsed_url.path).name
        filename = (
            raw_filename
            if raw_filename.endswith(".sqlite.gz")
            else f"{pack_info.pack_id}-{pack_info.pack_version}.sqlite.gz"
        )
        dest_file = target_dir / filename

        # Cache hit check with SHA-256 validation
        if dest_file.exists() and dest_file.stat().st_size > 0:
            if compute_sha256(dest_file).lower() == pack_info.sha256.lower():
                return Result.success(dest_file)

        # Download to a temporary file in target directory
        tmp_fd, tmp_str_path = tempfile.mkstemp(
            prefix="ms_pack_",
            suffix=".tmp",
            dir=str(target_dir),
        )
        os.close(tmp_fd)
        tmp_path = Path(tmp_str_path)

        try:
            if parsed_url.scheme == "file":
                src_path = Path(urllib.request.url2pathname(parsed_url.path))
                shutil.copyfile(src_path, tmp_path)
            else:
                req = urllib.request.Request(
                    pack_info.url,
                    headers={"User-Agent": "MeshScout-PackClient/1.0"},
                )
                with self._open(req) as resp:
                    with open(tmp_path, "wb") as f_out:
                        while chunk := resp.read(65536):
                            f_out.write(chunk)

            # Cryptographic SHA-256 verification
            actual_sha256 = compute_sha256(tmp_path)
            if actual_sha256.lower() != pack_info.sha256.strip().lower():
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                return Result.fail(
                    code="PACK_HASH_MISMATCH",
                    message=(
                        f"SHA-256 digest mismatch for {filename}: "
                        f"expected {pack_info.sha256}, got {actual_sha256}"
                    ),
                )

            # Promote temporary file to destination
            if dest_file.exists():
                try:
                    dest_file.unlink()
                except OSError:
                    pass
            shutil.move(str(tmp_path), str(dest_file))
            return Result.success(dest_file)

        except urllib.error.HTTPError as http_err:
            try:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                if http_err.code == 403 and "unallowed host" in str(http_err).lower():
                    return Result.fail(
                        code="HOST_NOT_ALLOWED",
                        message=f"Redirect blocked: {http_err}",
                    )
                # Fall back to local bundled pack archive if remote fetch failed
                local_candidates = [
                    Path(__file__).resolve().parent.parent / "data" / "packs" / filename,
                    Path(__file__).resolve().parent.parent.parent.parent / "packs" / filename,
                    Path.cwd() / "packs" / filename,
                    Path.cwd() / "MeshScout" / "packs" / filename,
                ]
                for cand in local_candidates:
                    if cand.is_file() and compute_sha256(cand).lower() == pack_info.sha256.lower():
                        return Result.success(cand)
                return Result.fail(
                    code="PACK_DOWNLOAD_ERROR",
                    message=f"HTTP error downloading {pack_info.url}: {http_err}",
                )
            finally:
                http_err.close()
        except urllib.error.URLError as url_err:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            # Fall back to local bundled pack archive if remote fetch failed
            local_candidates = [
                Path(__file__).resolve().parent.parent / "data" / "packs" / filename,
                Path(__file__).resolve().parent.parent.parent.parent / "packs" / filename,
                Path.cwd() / "packs" / filename,
                Path.cwd() / "MeshScout" / "packs" / filename,
            ]
            for cand in local_candidates:
                if cand.is_file() and compute_sha256(cand).lower() == pack_info.sha256.lower():
                    return Result.success(cand)
            return Result.fail(
                code="PACK_DOWNLOAD_ERROR",
                message=f"Network error downloading {pack_info.url}: {url_err}",
            )
        except Exception as exc:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return Result.fail(
                code="PACK_DOWNLOAD_ERROR",
                message=f"Failed to download pack archive {pack_info.url}: {exc}",
            )

    def install_pack(
        self,
        registry: UnifiedTowerRegistry,
        region_code: str,
    ) -> Result[RegionPackInfo]:
        """Download and install a regional pack into the target registry.

        Matches region_code against pack_id, region_code, or standard naming.

        Args:
            registry: Target UnifiedTowerRegistry database.
            region_code: Region identifier (e.g. 'VT', 'QC', 'towers-vt', 'US-VT').

        Returns:
            Result[RegionPackInfo] with installed pack metadata on success.
        """
        manifest_res = self.fetch_manifest()
        if not manifest_res.ok or manifest_res.value is None:
            err = manifest_res.error
            return Result.fail(
                code=err.code if err else "MANIFEST_FETCH_FAILED",
                message=err.message if err else "Failed to fetch pack manifest",
            )

        manifest = manifest_res.value
        matched_pack: Optional[RegionPackInfo] = None
        clean_code = region_code.strip()

        # Match by:
        # 1. Exact pack_id (case-insensitive)
        # 2. towers-{clean_code.lower()}
        # 3. region_code exact match (case-insensitive)
        # 4. region_code with underscore / dash variations
        for p_id, p_info in manifest.packs.items():
            if (
                p_id.lower() == clean_code.lower()
                or p_id.lower() == f"towers-{clean_code.lower()}"
                or p_info.region_code.upper() == clean_code.upper()
                or p_info.region_code.upper() == clean_code.replace("-", "_").upper()
                or p_info.region_code.upper() == clean_code.replace("_", "-").upper()
            ):
                matched_pack = p_info
                break

        if matched_pack is None:
            return Result.fail(
                code="PACK_NOT_FOUND",
                message=f"No regional pack matching '{region_code}' found in manifest.",
            )

        download_res = self.download_pack(matched_pack)
        if not download_res.ok or download_res.value is None:
            err = download_res.error
            return Result.fail(
                code=err.code if err else "PACK_DOWNLOAD_FAILED",
                message=err.message if err else "Failed to download pack",
            )

        pack_file = download_res.value
        return install_region_pack(
            registry=registry,
            pack_path=pack_file,
            expected_sha256=matched_pack.sha256,
        )

    def update_installed_packs(
        self,
        registry: UnifiedTowerRegistry,
    ) -> Dict[str, Any]:
        """Check all currently installed packs in registry and update any outdated packs.

        Args:
            registry: Target UnifiedTowerRegistry database.

        Returns:
            Dict containing lists of 'updated', 'up_to_date', and 'failed' pack records.
        """
        installed = list_installed_packs(registry)
        manifest_res = self.fetch_manifest()
        if not manifest_res.ok or manifest_res.value is None:
            return {
                "ok": False,
                "error": manifest_res.error.message if manifest_res.error else "Failed to fetch manifest",
                "updated": [],
                "up_to_date": [],
                "failed": [],
            }

        manifest = manifest_res.value
        updated: List[Dict[str, Any]] = []
        up_to_date: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        for inst in installed:
            p_id = inst["pack_id"]
            reg_code = inst.get("region_code", "")
            current_version = inst.get("pack_version", "")
            current_sha = inst.get("sha256", "").lower()

            # Find matching pack in manifest
            manifest_pack = manifest.packs.get(p_id)
            if manifest_pack is None:
                for p in manifest.packs.values():
                    if p.region_code.upper() == reg_code.upper():
                        manifest_pack = p
                        break

            if manifest_pack is None:
                continue

            needs_update = (
                manifest_pack.pack_version != current_version
                or manifest_pack.sha256.lower() != current_sha
            )

            if not needs_update:
                up_to_date.append({
                    "pack_id": p_id,
                    "region_code": reg_code,
                    "version": current_version,
                })
                continue

            install_res = self.install_pack(registry, manifest_pack.region_code)
            if install_res.ok and install_res.value is not None:
                updated.append({
                    "pack_id": p_id,
                    "region_code": reg_code,
                    "old_version": current_version,
                    "new_version": manifest_pack.pack_version,
                })
            else:
                failed.append({
                    "pack_id": p_id,
                    "region_code": reg_code,
                    "error": install_res.error.message if install_res.error else "Installation failed",
                })

        return {
            "ok": len(failed) == 0,
            "updated": updated,
            "up_to_date": up_to_date,
            "failed": failed,
        }

    def list_available_packs(self) -> Result[List[RegionPackInfo]]:
        """Query remote manifest and return list of all available RegionPackInfo records.

        Returns:
            Result[List[RegionPackInfo]] containing all indexed packs.
        """
        manifest_res = self.fetch_manifest()
        if not manifest_res.ok or manifest_res.value is None:
            err = manifest_res.error
            return Result.fail(
                code=err.code if err else "MANIFEST_FETCH_FAILED",
                message=err.message if err else "Failed to retrieve manifest",
            )
        return Result.success(list(manifest_res.value.packs.values()))
