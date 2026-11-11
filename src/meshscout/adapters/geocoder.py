"""Privacy-preserving geocoder, offline Vermont gazetteer, and Maidenhead grid locator.

Provides deterministic 200m grid fuzzing so home/rooftop coordinates are never exposed,
an instant (<10ms) offline Vermont ZIP/town/summit gazetteer, raw coordinate parsing,
SQLite caching, and rate-limited Nominatim fallback respecting ADR-024 jitter.
"""

from __future__ import annotations

import contextlib
import json
import math
import re
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple
from pydantic import BaseModel, Field

from meshscout.adapters.base import RateLimitBackoff, RateLimitConfig
from meshscout.core.contracts import Coordinate, Result


class GeocodedLocation(BaseModel):
    """Resolved and privacy-fuzzed location result."""

    query: str = Field(..., min_length=1, description="Original user search query")
    display_name: str = Field(..., min_length=1, description="Formatted location display name")
    coordinate: Coordinate = Field(..., description="Active coordinate (fuzzed when privacy_fuzzed=True)")
    raw_coordinate: Coordinate = Field(..., description="Exact un-fuzzed coordinate")
    fuzzed_coordinate: Coordinate = Field(..., description="Grid-snapped privacy-fuzzed coordinate")
    maidenhead_grid: str = Field(..., min_length=4, description="Amateur radio Maidenhead grid locator")
    privacy_fuzzed: bool = Field(..., description="Whether coordinate was snapped to privacy grid")
    source: str = Field(
        ...,
        description="Resolution source ('local_fixture', 'sqlite_cache', or 'nominatim')",
    )


# Offline Vermont gazetteer mapping normalized lowercase queries to (display_name, Coordinate)
_GAZETTEER_ENTRIES: Tuple[Tuple[Tuple[str, ...], str, float, float, float], ...] = (
    (
        ("05452", "essex junction", "essex junction, vt", "five corners", "essex jct", "essex jct, vt"),
        "Essex Junction, VT 05452",
        44.4906,
        -73.1112,
        108.0,
    ),
    (
        ("05401", "burlington", "burlington, vt"),
        "Burlington, VT 05401",
        44.4759,
        -73.2121,
        61.0,
    ),
    (
        ("05446", "colchester", "colchester, vt"),
        "Colchester, VT 05446",
        44.5439,
        -73.1479,
        95.0,
    ),
    (
        ("05477", "richmond", "richmond, vt"),
        "Richmond, VT 05477",
        44.4053,
        -72.9926,
        105.0,
    ),
    (
        ("05489", "underhill", "underhill, vt"),
        "Underhill, VT 05489",
        44.5275,
        -72.8950,
        215.0,
    ),
    (
        ("05495", "williston", "williston, vt"),
        "Williston, VT 05495",
        44.4375,
        -73.0685,
        132.0,
    ),
    (
        ("05602", "montpelier", "montpelier, vt"),
        "Montpelier, VT 05602",
        44.2601,
        -72.5754,
        160.0,
    ),
    (
        ("05672", "stowe", "stowe, vt"),
        "Stowe, VT 05672",
        44.4654,
        -72.6874,
        220.0,
    ),
    (
        ("mount mansfield", "mt mansfield", "mt. mansfield"),
        "Mount Mansfield Summit, VT",
        44.5437,
        -72.8143,
        1339.0,
    ),
    (
        ("camels hump", "camel's hump", "camels hump, vt", "camel's hump, vt"),
        "Camel's Hump Summit, VT",
        44.3195,
        -72.8863,
        1244.0,
    ),
    (
        ("05464", "cambridge", "cambridge, vt", "jeffersonville", "jeffersonville, vt", "cambridge vt", "jeffersonville vt"),
        "Jeffersonville / Cambridge, VT 05464",
        44.6436,
        -72.8270,
        145.0,
    ),
    (
        ("05465", "jericho", "jericho, vt", "jericho vt"),
        "Jericho, VT 05465",
        44.5042,
        -72.9996,
        175.0,
    ),
    (
        ("05468", "milton", "milton, vt", "milton vt"),
        "Milton, VT 05468",
        44.6225,
        -73.1118,
        107.0,
    ),
    (
        ("05482", "shelburne", "shelburne, vt", "shelburne vt"),
        "Shelburne, VT 05482",
        44.3789,
        -73.2273,
        62.0,
    ),
    (
        ("05445", "charlotte", "charlotte, vt", "charlotte vt"),
        "Charlotte, VT 05445",
        44.3098,
        -73.2607,
        75.0,
    ),
    (
        ("05458", "grand isle", "grand isle, vt", "grand isle vt"),
        "Grand Isle, VT 05458",
        44.7214,
        -73.2968,
        43.0,
    ),
    (
        ("05486", "south hero", "south hero, vt", "south hero vt"),
        "South Hero, VT 05486",
        44.6487,
        -73.3037,
        40.0,
    ),
    (
        ("05701", "rutland", "rutland, vt", "rutland vt"),
        "Rutland, VT 05701",
        43.6106,
        -72.9726,
        170.0,
    ),
    (
        ("05641", "barre", "barre, vt", "barre vt"),
        "Barre, VT 05641",
        44.1970,
        -72.5020,
        185.0,
    ),
    (
        ("05676", "waterbury", "waterbury, vt", "waterbury vt"),
        "Waterbury, VT 05676",
        44.3378,
        -72.7562,
        130.0,
    ),
    (
        ("05674", "waitsfield", "waitsfield, vt", "waitsfield vt"),
        "Waitsfield, VT 05674",
        44.1895,
        -72.8248,
        213.0,
    ),
    (
        ("05667", "plainfield", "plainfield, vt", "plainfield vt"),
        "Plainfield, VT 05667",
        44.2789,
        -72.4279,
        230.0,
    ),
    (
        ("05461", "hinesburg", "hinesburg, vt", "hinesburg vt"),
        "Hinesburg, VT 05461",
        44.3309,
        -73.1118,
        104.0,
    ),
    (
        ("05454", "fairfax", "fairfax, vt", "fairfax vt"),
        "Fairfax, VT 05454",
        44.6653,
        -73.0118,
        110.0,
    ),
    (
        ("05459", "highgate", "highgate, vt", "highgate vt", "highgate center", "highgate center, vt", "highgate center vt"),
        "Highgate, VT 05459",
        44.9317,
        -73.0487,
        85.0,
    ),
    (
        ("05478", "st albans", "st albans, vt", "st albans vt", "st. albans", "st. albans, vt", "st. albans vt", "saint albans", "saint albans, vt", "saint albans vt"),
        "St. Albans, VT 05478",
        44.8109,
        -73.0832,
        60.0,
    ),
    (
        ("05851", "morrisville", "morrisville, vt", "morrisville vt"),
        "Morrisville, VT 05851",
        44.5617,
        -72.5979,
        204.0,
    ),
    (
        ("05819", "st johnsbury", "st johnsbury, vt", "st johnsbury vt", "st. johnsbury", "st. johnsbury, vt", "st. johnsbury vt", "saint johnsbury", "saint johnsbury, vt", "saint johnsbury vt"),
        "St. Johnsbury, VT 05819",
        44.4206,
        -72.0151,
        210.0,
    ),
    (
        ("05855", "newport", "newport, vt", "newport vt"),
        "Newport, VT 05855",
        44.9364,
        -72.2051,
        208.0,
    ),
    (
        ("05301", "brattleboro", "brattleboro, vt", "brattleboro vt"),
        "Brattleboro, VT 05301",
        42.8509,
        -72.5579,
        90.0,
    ),
    (
        ("05201", "bennington", "bennington, vt", "bennington vt"),
        "Bennington, VT 05201",
        42.8781,
        -73.1968,
        205.0,
    ),
    (
        ("05091", "woodstock", "woodstock, vt", "woodstock vt"),
        "Woodstock, VT 05091",
        43.6248,
        -72.5184,
        215.0,
    ),
)

LOCAL_GAZETTEER: Dict[str, Tuple[str, Coordinate]] = {}
for _aliases, _display, _lat, _lon, _elev in _GAZETTEER_ENTRIES:
    _coord = Coordinate(lat=_lat, lon=_lon, elevation_m=_elev)
    for _alias in _aliases:
        LOCAL_GAZETTEER[_alias] = (_display, _coord)


def fuzz_coordinate(coord: Coordinate, grid_m: float = 200.0) -> Coordinate:
    """Deterministically snap latitude and longitude to a ~`grid_m` meter privacy cell.

    Uses `lat_step = grid_m / 111_320.0` and evaluates `lon_step` at the snapped cell
    latitude (`grid_m / (111_320.0 * max(0.2, math.cos(math.radians(snapped_lat))))`)
    so any two points inside the same ~200m cell snap to the exact same 4-decimal
    coordinate while preserving `elevation_m`.
    """
    if grid_m <= 0.0:
        return Coordinate(
            lat=round(coord.lat, 4),
            lon=round(coord.lon, 4),
            elevation_m=coord.elevation_m,
        )

    lat_step = grid_m / 111_320.0
    snapped_lat = math.floor(coord.lat / lat_step) * lat_step
    fuzzed_lat = round(snapped_lat, 4)

    # Compute lon_step using snapped_lat so all points in the same lat cell share identical lon_step
    lon_step = grid_m / (111_320.0 * max(0.2, math.cos(math.radians(snapped_lat))))
    snapped_lon = math.floor(coord.lon / lon_step) * lon_step
    fuzzed_lon = round(snapped_lon, 4)

    return Coordinate(
        lat=fuzzed_lat,
        lon=fuzzed_lon,
        elevation_m=coord.elevation_m,
    )


def to_maidenhead(coord: Coordinate, precision: int = 6) -> str:
    """Convert a `Coordinate` into a standard 4, 6, or 8 character Maidenhead grid locator."""
    if precision not in (4, 6, 8):
        raise ValueError(f"precision must be 4, 6, or 8, got {precision}")

    lon_deg = max(0.0, min(359.999999, coord.lon + 180.0))
    lat_deg = max(0.0, min(179.999999, coord.lat + 90.0))

    field_lon = min(17, int(lon_deg / 20.0))
    field_lat = min(17, int(lat_deg / 10.0))
    c1 = chr(ord("A") + field_lon)
    c2 = chr(ord("A") + field_lat)

    rem_lon = lon_deg - (field_lon * 20.0)
    rem_lat = lat_deg - (field_lat * 10.0)
    sq_lon = min(9, int(rem_lon / 2.0))
    sq_lat = min(9, int(rem_lat / 1.0))
    c3 = str(sq_lon)
    c4 = str(sq_lat)

    if precision == 4:
        return f"{c1}{c2}{c3}{c4}"

    rem_lon_sub = rem_lon - (sq_lon * 2.0)
    rem_lat_sub = rem_lat - (sq_lat * 1.0)
    sub_lon = min(23, max(0, int(rem_lon_sub * 12.0)))
    sub_lat = min(23, max(0, int(rem_lat_sub * 24.0)))
    c5 = chr(ord("a") + sub_lon)
    c6 = chr(ord("a") + sub_lat)

    if precision == 6:
        return f"{c1}{c2}{c3}{c4}{c5}{c6}"

    rem_lon_ext = rem_lon_sub - (sub_lon / 12.0)
    rem_lat_ext = rem_lat_sub - (sub_lat / 24.0)
    ext_lon = min(9, max(0, int(rem_lon_ext * 120.0)))
    ext_lat = min(9, max(0, int(rem_lat_ext * 240.0)))
    return f"{c1}{c2}{c3}{c4}{c5}{c6}{ext_lon}{ext_lat}"


def _try_parse_raw_coordinate(query: str) -> Optional[Coordinate]:
    """Parse raw 'LAT,LON' or 'LAT,LON,ELEV' strings if present."""
    parts = [p.strip() for p in query.split(",")]
    if len(parts) not in (2, 3):
        return None
    try:
        lat = float(parts[0])
        lon = float(parts[1])
        elev = float(parts[2]) if len(parts) == 3 else 0.0
        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
            return Coordinate(lat=lat, lon=lon, elevation_m=elev)
    except ValueError:
        return None
    return None


class PrivacyGeocoder:
    """Offline-first geocoder with 200m privacy fuzzing, SQLite cache, and Nominatim fallback."""

    def __init__(
        self,
        cache_db_path: Optional[Path | str] = None,
        no_delay: bool = False,
        user_agent: str = "MeshScout/1.0 (Vermont Community Mesh Planning)",
    ) -> None:
        self.cache_db_path: Optional[Path] = Path(cache_db_path) if cache_db_path else None
        self.user_agent = user_agent
        self.rate_limiter = RateLimitBackoff(
            RateLimitConfig(
                min_delay=1.0,
                max_delay=1.8,
                jitter=True,
                disabled=no_delay,
            )
        )
        if self.cache_db_path is not None:
            self._init_cache_db()

    def _init_cache_db(self) -> None:
        if self.cache_db_path is None:
            return
        self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(sqlite3.connect(self.cache_db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS geocode_cache (
                    query_key TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    elevation_m REAL NOT NULL
                )
                """
            )
            conn.commit()

    def _lookup_cache(self, query_key: str) -> Optional[Tuple[str, Coordinate]]:
        if self.cache_db_path is None or not self.cache_db_path.exists():
            return None
        with contextlib.closing(sqlite3.connect(self.cache_db_path)) as conn:
            row = conn.execute(
                "SELECT display_name, lat, lon, elevation_m FROM geocode_cache WHERE query_key = ?",
                (query_key,),
            ).fetchone()
            if row:
                return (
                    str(row[0]),
                    Coordinate(lat=float(row[1]), lon=float(row[2]), elevation_m=float(row[3])),
                )
        return None

    def _store_cache(self, query_key: str, display_name: str, coord: Coordinate) -> None:
        if self.cache_db_path is None:
            return
        with contextlib.closing(sqlite3.connect(self.cache_db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO geocode_cache (query_key, display_name, lat, lon, elevation_m)
                VALUES (?, ?, ?, ?, ?)
                """,
                (query_key, display_name, coord.lat, coord.lon, coord.elevation_m),
            )
            conn.commit()

    def _build_location(
        self,
        query: str,
        display_name: str,
        raw_coord: Coordinate,
        apply_privacy_fuzz: bool,
        grid_m: float,
        source: str,
    ) -> GeocodedLocation:
        fuzzed = fuzz_coordinate(raw_coord, grid_m=grid_m)
        active = fuzzed if apply_privacy_fuzz else raw_coord
        return GeocodedLocation(
            query=query,
            display_name=display_name,
            coordinate=active,
            raw_coordinate=raw_coord,
            fuzzed_coordinate=fuzzed,
            maidenhead_grid=to_maidenhead(active, precision=6),
            privacy_fuzzed=apply_privacy_fuzz,
            source=source,
        )

    def geocode(
        self,
        query: str,
        apply_privacy_fuzz: bool = True,
        grid_m: float = 200.0,
        offline_only: bool = False,
    ) -> Result[GeocodedLocation]:
        """Resolve a ZIP code, town name, landmark, or 'LAT,LON[,ELEV]' string."""
        cleaned = query.strip()
        if not cleaned:
            return Result.fail(code="EMPTY_GEOCODE_QUERY", message="Search query must not be empty.")

        # 1. Check raw coordinate syntax ('LAT,LON' or 'LAT,LON,ELEV')
        raw_parsed = _try_parse_raw_coordinate(cleaned)
        if raw_parsed is not None:
            display = f"Coordinate ({raw_parsed.lat:.4f}, {raw_parsed.lon:.4f})"
            return Result.success(
                self._build_location(
                    query=cleaned,
                    display_name=display,
                    raw_coord=raw_parsed,
                    apply_privacy_fuzz=apply_privacy_fuzz,
                    grid_m=grid_m,
                    source="local_fixture",
                )
            )

        norm_key = " ".join(cleaned.lower().split())
        # Also allow stripping trailing ' vt' / ', vt' for gazetteer lookup if needed
        lookup_candidates = [norm_key]
        if norm_key.endswith(" vt") and not norm_key.endswith(", vt"):
            lookup_candidates.append(norm_key[:-3].strip() + ", vt")
            lookup_candidates.append(norm_key[:-3].strip())
        elif norm_key.endswith(", vt"):
            lookup_candidates.append(norm_key[:-4].strip() + " vt")
            lookup_candidates.append(norm_key[:-4].strip())

        # 2. Built-in offline Vermont gazetteer
        for cand in lookup_candidates:
            if cand in LOCAL_GAZETTEER:
                display_name, raw_coord = LOCAL_GAZETTEER[cand]
                return Result.success(
                    self._build_location(
                        query=cleaned,
                        display_name=display_name,
                        raw_coord=raw_coord,
                        apply_privacy_fuzz=apply_privacy_fuzz,
                        grid_m=grid_m,
                        source="local_fixture",
                    )
                )

        # 3. Optional SQLite cache
        for cand in lookup_candidates:
            cached = self._lookup_cache(cand)
            if cached is not None:
                display_name, raw_coord = cached
                return Result.success(
                    self._build_location(
                        query=cleaned,
                        display_name=display_name,
                        raw_coord=raw_coord,
                        apply_privacy_fuzz=apply_privacy_fuzz,
                        grid_m=grid_m,
                        source="sqlite_cache",
                    )
                )

        if offline_only:
            return Result.fail(
                code="LOCATION_NOT_FOUND_OFFLINE",
                message=f"Location '{cleaned}' not found in offline Vermont gazetteer or local SQLite cache.",
            )

        # 4. Rate-limited Nominatim fallback when offline_only=False
        try:
            params = urllib.parse.urlencode({"q": cleaned, "format": "json", "limit": 1})
            url = f"https://nominatim.openstreetmap.org/search?{params}"

            def _fetch() -> list:
                req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            payload = self.rate_limiter.execute(_fetch)
            if not payload:
                # Intelligent Vermont municipal alias retry (e.g. 'Essex Junction' postal address -> 'Essex' town)
                alt_cleaned = re.sub(r"(?i)\bessex\s+j(?:un)?ct(?:ion)?\b", "Essex", cleaned)
                if alt_cleaned != cleaned:
                    alt_params = urllib.parse.urlencode({"q": alt_cleaned, "format": "json", "limit": 1})
                    alt_url = f"https://nominatim.openstreetmap.org/search?{alt_params}"

                    def _fetch_alt() -> list:
                        alt_req = urllib.request.Request(alt_url, headers={"User-Agent": self.user_agent})
                        with urllib.request.urlopen(alt_req, timeout=10.0) as resp:
                            return json.loads(resp.read().decode("utf-8"))

                    payload = self.rate_limiter.execute(_fetch_alt)

            if not payload:
                return Result.fail(
                    code="LOCATION_NOT_FOUND",
                    message=f"No geocoding results found for '{cleaned}'.",
                )

            first = payload[0]
            raw_coord = Coordinate(
                lat=float(first["lat"]),
                lon=float(first["lon"]),
                elevation_m=0.0,
            )
            display_name = str(first.get("display_name", cleaned))
            coord_to_store = fuzz_coordinate(raw_coord, grid_m=grid_m) if apply_privacy_fuzz else raw_coord
            self._store_cache(norm_key, display_name, coord_to_store)
            return Result.success(
                self._build_location(
                    query=cleaned,
                    display_name=display_name,
                    raw_coord=raw_coord,
                    apply_privacy_fuzz=apply_privacy_fuzz,
                    grid_m=grid_m,
                    source="nominatim",
                )
            )
        except Exception as exc:
            return Result.fail(
                code="GEOCODER_HTTP_ERROR",
                message=f"Nominatim geocoding failed for '{cleaned}': {exc}",
            )
