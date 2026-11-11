"""Authoritative Source Catalog and Cached HTTPS Fetcher for MeshScout.

Provides offline-first downloading and local caching of external tower and
spatial datasets (FCC ASR bulk, Canadian ISED SMS, OpenStreetMap civic data),
with exponential backoff, rate limiting, and atomic cache storage.
"""

from __future__ import annotations

import importlib.resources
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, Optional, Union
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".meshscout" / "cache" / "sources"
_DEFAULT_SOURCES_JSON = Path(__file__).resolve().parent.parent / "data" / "sources.json"


def get_catalog_path() -> Path:
    """Resolve the filesystem path to authoritative sources.json catalog."""
    try:
        data_path = importlib.resources.files("meshscout").joinpath("data", "sources.json")
        resolved = Path(str(data_path))
        if resolved.exists():
            return resolved
    except Exception:
        pass
    return _DEFAULT_SOURCES_JSON


def load_source_catalog(catalog_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Load and parse the authoritative source metadata catalog.

    Args:
        catalog_path: Optional custom path to sources.json.

    Returns:
        Dictionary mapping source IDs to their respective metadata schemas.
    """
    path = Path(catalog_path) if catalog_path is not None else get_catalog_path()
    if not path.exists():
        raise FileNotFoundError(f"Source catalog not found at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "sources" in data and isinstance(data["sources"], dict):
        return data["sources"]
    return data


def get_source_metadata(
    source_id: str,
    catalog_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Retrieve metadata for a specific registered source.

    Args:
        source_id: Registered source identifier (e.g. 'fcc_asr', 'ised_sms', 'civic_osm').
        catalog_path: Optional path to sources.json.

    Returns:
        Metadata dictionary.

    Raises:
        KeyError: If source_id is not in catalog.
    """
    catalog = load_source_catalog(catalog_path=catalog_path)
    clean_id = source_id.strip().lower()
    if clean_id not in catalog:
        raise KeyError(
            f"Unknown source '{source_id}'. Available sources: {', '.join(sorted(catalog.keys()))}"
        )
    return catalog[clean_id]


def fetch_source_file(
    url: str,
    dest_path: Optional[Union[str, Path]] = None,
    cache_dir: Optional[Union[str, Path]] = None,
    force: bool = False,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    timeout: float = 30.0,
    rate_limit_delay: float = 0.0,
) -> Path:
    """Download an external data source file over HTTPS with caching, rate limiting, and backoff.

    Args:
        url: Direct download URL (must use HTTPS or HTTP).
        dest_path: Optional explicit destination file path.
        cache_dir: Optional cache directory to store file if dest_path is omitted.
        force: If True, bypass cache and re-download.
        max_retries: Maximum number of retry attempts upon transient network failures.
        backoff_factor: Base multiplier for exponential backoff (sleep = factor * 2^attempt).
        timeout: Socket timeout in seconds.
        rate_limit_delay: Minimum delay in seconds before issuing request.

    Returns:
        Path to the cached or downloaded file.

    Raises:
        ValueError: If URL schema is unsupported.
        RuntimeError: If download fails after exceeding max_retries.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'. Only HTTP and HTTPS are supported.")

    if dest_path is not None:
        target_path = Path(dest_path)
    else:
        cdir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        raw_name = Path(parsed.path).name
        filename = raw_name if raw_name else "download.dat"
        target_path = cdir / filename

    # Cache hit check
    if not force and target_path.exists() and target_path.stat().st_size > 0:
        logger.debug("Source file cache hit: %s", target_path)
        return target_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp.{time.time_ns()}")

    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        if rate_limit_delay > 0:
            time.sleep(rate_limit_delay)

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "MeshScout/0.13.0 (+https://github.com/meshscout)",
                    "Accept": "*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                with open(tmp_path, "wb") as f_out:
                    while chunk := resp.read(65536):
                        f_out.write(chunk)

            tmp_path.replace(target_path)
            logger.info("Successfully fetched %s -> %s", url, target_path)
            return target_path
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            last_error = err
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

            if attempt < max_retries:
                sleep_secs = backoff_factor * (2 ** attempt)
                logger.warning(
                    "Fetch attempt %d failed for %s (%s). Retrying in %.2fs...",
                    attempt + 1,
                    url,
                    err,
                    sleep_secs,
                )
                time.sleep(sleep_secs)
            else:
                break

    raise RuntimeError(
        f"Failed to fetch {url} after {max_retries + 1} attempts: {last_error}"
    ) from last_error


def fetch_source(
    source_id: str,
    dest_path: Optional[Union[str, Path]] = None,
    cache_dir: Optional[Union[str, Path]] = None,
    force: bool = False,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    timeout: float = 30.0,
    rate_limit_delay: float = 0.0,
    catalog_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Fetch a registered source dataset by source_id from the authoritative catalog.

    Args:
        source_id: Catalog source identifier (e.g. 'fcc_asr', 'ised_sms', 'civic_osm').
        dest_path: Optional destination file path.
        cache_dir: Optional local cache directory.
        force: If True, bypass cache and re-download.
        max_retries: Maximum number of retry attempts.
        backoff_factor: Base multiplier for exponential backoff.
        timeout: Socket timeout in seconds.
        rate_limit_delay: Minimum delay in seconds before request.
        catalog_path: Optional path to sources.json.

    Returns:
        Path to the cached or downloaded source file.
    """
    meta = get_source_metadata(source_id, catalog_path=catalog_path)
    url = meta.get("url")
    if not url:
        raise ValueError(f"Source '{source_id}' does not define a download 'url'.")

    return fetch_source_file(
        url=url,
        dest_path=dest_path,
        cache_dir=cache_dir,
        force=force,
        max_retries=max_retries,
        backoff_factor=backoff_factor,
        timeout=timeout,
        rate_limit_delay=rate_limit_delay,
    )
