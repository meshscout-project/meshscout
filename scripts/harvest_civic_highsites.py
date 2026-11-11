#!/usr/bin/env python3
"""Tiled Overpass Civic Harvester for MeshScout (TASK-004).

Queries OpenStreetMap Overpass API for authentic municipal water towers,
communications towers, masts, silos, and fire lookouts across North American
jurisdictions. Subdivides regional bounding boxes into <= 2.0 x 2.0 degree tiles,
enforces polite 5s egress rate-limiting with exponential backoff on HTTP 429 and 504,
and caches per-region GeoJSON archives.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
import urllib.error
import urllib.parse
import urllib.request

# Ensure meshscout source tree is importable when run directly
_repo_src = Path(__file__).resolve().parent.parent / "src"
if str(_repo_src) not in sys.path:
    sys.path.insert(0, str(_repo_src))

from meshscout.adapters.civic_highsites import (
    build_overpass_query,
    overpass_json_to_geojson,
    subdivide_bounding_box,
)
from meshscout.adapters.regions import NORTH_AMERICA_CATALOG

logger = logging.getLogger("meshscout.harvest_civic")

DEFAULT_CACHE_DIR = Path.home() / ".meshscout" / "cache" / "overpass"
DEFAULT_OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
DEFAULT_MAX_TILE_DEG = 2.0
DEFAULT_RATE_LIMIT_DELAY = 5.0
DEFAULT_TIMEOUT_S = 90


class OverpassRateLimiter:
    """Enforces polite rate limiting with minimum delay between live Overpass queries."""

    def __init__(self, min_delay_s: float = DEFAULT_RATE_LIMIT_DELAY) -> None:
        self.min_delay_s = max(0.0, float(min_delay_s))
        self.last_request_time: float = 0.0

    def wait(self) -> float:
        """Wait if needed to satisfy min_delay_s between consecutive requests."""
        sleep_s = 0.0
        if self.last_request_time > 0.0 and self.min_delay_s > 0.0:
            elapsed = time.monotonic() - self.last_request_time
            if elapsed < self.min_delay_s:
                sleep_s = self.min_delay_s - elapsed
                time.sleep(sleep_s)
        return sleep_s

    def record_request(self) -> None:
        """Record the timestamp of a dispatched request."""
        self.last_request_time = time.monotonic()


def query_overpass(
    query: str,
    endpoint: str = DEFAULT_OVERPASS_ENDPOINT,
    rate_limiter: Optional[OverpassRateLimiter] = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    max_retries: int = 4,
    initial_backoff_s: float = 5.0,
) -> Dict[str, Any]:
    """Execute Overpass QL query with polite rate limiting and retry on HTTP 429/504.

    Args:
        query: Overpass QL query string.
        endpoint: Target Overpass interpreter URL.
        rate_limiter: OverpassRateLimiter instance enforcing delay between queries.
        timeout_s: Timeout in seconds for HTTP request.
        max_retries: Maximum number of retries on 429/504 errors.
        initial_backoff_s: Starting backoff delay in seconds on transient HTTP errors.

    Returns:
        Parsed JSON dictionary with "elements" array.
    """
    if rate_limiter is None:
        rate_limiter = OverpassRateLimiter()

    post_data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=post_data,
        headers={
            "User-Agent": "MeshScout-CivicHarvester/1.0 (https://github.com/meshscout-project/meshscout)",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    backoff = initial_backoff_s
    for attempt in range(max_retries + 1):
        rate_limiter.wait()
        rate_limiter.record_request()
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                content = resp.read().decode("utf-8")
                return json.loads(content)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 504) and attempt < max_retries:
                logger.warning(
                    "Overpass HTTP %d (%s). Retrying in %.1f s (attempt %d/%d)...",
                    exc.code,
                    exc.reason,
                    backoff,
                    attempt + 1,
                    max_retries,
                )
                exc.close()
                time.sleep(backoff)
                backoff *= 2.0
                continue
            exc.close()
            raise


def harvest_region_civic(
    region_code: str,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    max_tile_deg: float = DEFAULT_MAX_TILE_DEG,
    offline: bool = False,
    force: bool = False,
    mock_fetcher: Optional[Callable[[str, Tuple[float, float, float, float]], Dict[str, Any]]] = None,
    rate_limiter: Optional[OverpassRateLimiter] = None,
    rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY,
    endpoint: str = DEFAULT_OVERPASS_ENDPOINT,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> Path:
    """Harvest authentic civic infrastructure for a single jurisdiction using tiled Overpass queries.

    Args:
        region_code: North American jurisdiction code (e.g. 'VT', 'NH', 'CA_QC').
        cache_dir: Target directory for storing regional GeoJSON cache files.
        max_tile_deg: Maximum bounding box tile width/height in degrees (<= 2.0).
        offline: If True, operates without live network egress.
        force: If True, ignores existing cached GeoJSON and queries Overpass afresh.
        mock_fetcher: Optional mock callable (query, tile_bbox) -> overpass_dict for hermetic testing.
        rate_limiter: Optional OverpassRateLimiter instance.
        rate_limit_delay: Delay in seconds between queries if creating a new rate limiter.
        endpoint: Overpass API endpoint URL.
        timeout_s: Query timeout in seconds.

    Returns:
        Path to the saved or cached regional GeoJSON file.
    """
    reg_key = region_code.strip().upper()
    if reg_key not in NORTH_AMERICA_CATALOG:
        raise ValueError(f"Unknown region code '{region_code}'. Not found in NORTH_AMERICA_CATALOG.")

    region_info = NORTH_AMERICA_CATALOG[reg_key]
    out_dir = Path(cache_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_file = out_dir / f"{reg_key.lower()}_civic.geojson"

    # Cache hit bypass: if already cached and not forcing re-harvest, skip Overpass
    if cache_file.exists() and not force:
        logger.info(
            "Cache hit for region %s at %s. Bypassing Overpass harvest.",
            reg_key,
            cache_file,
        )
        return cache_file

    # Offline mode without mock fetcher: write empty FeatureCollection
    if offline and mock_fetcher is None:
        logger.info("Offline mode active for %s: skipping Overpass network queries.", reg_key)
        empty_fc: Dict[str, Any] = {
            "type": "FeatureCollection",
            "region_code": reg_key,
            "features": [],
        }
        cache_file.write_text(json.dumps(empty_fc, indent=2), encoding="utf-8")
        return cache_file

    if rate_limiter is None:
        rate_limiter = OverpassRateLimiter(min_delay_s=rate_limit_delay)

    tiles = subdivide_bounding_box(region_info.bounds, max_tile_deg=max_tile_deg)
    logger.info(
        "Harvesting region %s (%s) partitioned into %d tile(s) (<= %.1f deg)...",
        reg_key,
        region_info.name,
        len(tiles),
        max_tile_deg,
    )

    seen_elements: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    for idx, (min_lat, min_lon, max_lat, max_lon) in enumerate(tiles):
        query_str = build_overpass_query(min_lat, min_lon, max_lat, max_lon, timeout_s=timeout_s)
        logger.debug(
            "Executing Overpass query for tile %d/%d of %s: (%.2f, %.2f, %.2f, %.2f)",
            idx + 1,
            len(tiles),
            reg_key,
            min_lat,
            min_lon,
            max_lat,
            max_lon,
        )

        if mock_fetcher is not None:
            raw_data = mock_fetcher(query_str, (min_lat, min_lon, max_lat, max_lon))
        else:
            raw_data = query_overpass(
                query_str,
                endpoint=endpoint,
                rate_limiter=rate_limiter,
                timeout_s=timeout_s,
            )

        elements = raw_data.get("elements", [])
        for elem in elements:
            elem_key = (str(elem.get("type", "node")), elem.get("id"))
            if elem_key not in seen_elements:
                seen_elements[elem_key] = elem

    merged_data = {"elements": list(seen_elements.values())}
    geojson_doc = overpass_json_to_geojson(merged_data, region_code=reg_key)

    cache_file.write_text(json.dumps(geojson_doc, indent=2), encoding="utf-8")
    logger.info(
        "Saved %d civic infrastructure features for %s to %s",
        len(geojson_doc.get("features", [])),
        reg_key,
        cache_file,
    )
    return cache_file


def harvest_all_regions(
    regions: Optional[Sequence[str]] = None,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    max_tile_deg: float = DEFAULT_MAX_TILE_DEG,
    offline: bool = False,
    force: bool = False,
    mock_fetcher: Optional[Callable[[str, Tuple[float, float, float, float]], Dict[str, Any]]] = None,
    rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY,
) -> List[Path]:
    """Harvest civic infrastructure across multiple regions."""
    if not regions or any(r.strip().upper() in ("ALL", "*") for r in regions):
        reg_list = list(NORTH_AMERICA_CATALOG.keys())
    else:
        reg_list = [r.strip().upper() for r in regions]

    rate_limiter = OverpassRateLimiter(min_delay_s=rate_limit_delay)
    saved_paths: List[Path] = []
    for reg in reg_list:
        try:
            path = harvest_region_civic(
                region_code=reg,
                cache_dir=cache_dir,
                max_tile_deg=max_tile_deg,
                offline=offline,
                force=force,
                mock_fetcher=mock_fetcher,
                rate_limiter=rate_limiter,
                rate_limit_delay=rate_limit_delay,
            )
            saved_paths.append(path)
        except Exception as exc:
            logger.error("Failed to harvest region %s: %s", reg, exc)
            raise
    return saved_paths


def main() -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Harvest civic high-sites from Overpass API into per-region GeoJSON archives."
    )
    parser.add_argument(
        "--regions",
        nargs="+",
        default=["all"],
        help="Region code(s) to harvest (e.g. VT NH CA_QC) or 'all' for entire North America catalog.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"Directory to save cached GeoJSON files (default: {DEFAULT_CACHE_DIR}).",
    )
    parser.add_argument(
        "--max-tile-deg",
        type=float,
        default=DEFAULT_MAX_TILE_DEG,
        help=f"Maximum bounding box tile size in degrees (default: {DEFAULT_MAX_TILE_DEG}).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run in offline mode without making live network requests.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-harvesting even if cache files already exist.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_RATE_LIMIT_DELAY,
        help=f"Minimum rate-limit delay in seconds between Overpass queries (default: {DEFAULT_RATE_LIMIT_DELAY}).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging.",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        paths = harvest_all_regions(
            regions=args.regions,
            cache_dir=args.cache_dir,
            max_tile_deg=args.max_tile_deg,
            offline=args.offline,
            force=args.force,
            rate_limit_delay=args.delay,
        )
        print(f"Successfully harvested {len(paths)} regional civic GeoJSON pack(s).")
        return 0
    except Exception as exc:
        print(f"Harvester failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
