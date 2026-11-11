"""Unified SQLite Tower and High-Site Registry.

Provides unified persistent storage, spatial indexing, categorical filtering, and administrative
friction-tier ranking across municipal water towers, fire lookouts, agricultural silos, and
commercial carrier infrastructure for disaster mesh planning.
"""

from __future__ import annotations

from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Union

from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)

SCHEMA_VERSION: int = 2


class FrictionTier(int, Enum):
    """Administrative and financial friction tier for site acquisition and deployment.

    - TIER_1_CIVIC: Municipal water towers, fire lookouts, research masts, university canopy towers,
      civic public-safety. Low lease cost / high partnership friendliness.
    - TIER_2_AGRICULTURAL: Farm silos, co-op utility poles, private bluffs. Direct landowner negotiation,
      low-to-moderate friction.
    - TIER_3_COMMERCIAL: Leased carrier towers (American Tower, Crown Castle, SBA). High monthly rent,
      complex structural engineering review, strict insurance.
    """

    TIER_1_CIVIC = 1
    TIER_2_AGRICULTURAL = 2
    TIER_3_COMMERCIAL = 3


def resolve_friction_tier(
    site_type: Union[SiteType, str],
    owner_category: str = "",
) -> FrictionTier:
    """Resolve administrative friction tier based on physical site type and ownership metadata.

    Classification heuristics:
      - TIER_1_CIVIC: FIRE_LOOKOUT, WATER_TOWER, RESEARCH_TOWER, or owner category with 'civic'
        or 'public_safety'.
      - TIER_2_AGRICULTURAL: SILO, or owner category with 'ag', 'utility', or 'coop'.
      - TIER_3_COMMERCIAL: Commercial carrier towers, leased telecommunications masts, or
        unspecified private infrastructure.
    """
    st_val = site_type.value if hasattr(site_type, "value") else str(site_type)
    cat_lower = owner_category.lower() if owner_category else ""
    cat_norm = re.sub(r"[_\W]+", " ", cat_lower)

    if (
        st_val in (SiteType.FIRE_LOOKOUT.value, SiteType.WATER_TOWER.value, SiteType.RESEARCH_TOWER.value)
        or "civic" in cat_lower
        or "public_safety" in cat_lower
    ):
        return FrictionTier.TIER_1_CIVIC

    if (
        st_val == SiteType.SILO.value
        or bool(re.search(r"\b(ag|agri|agriculture|agricultural)\b", cat_norm))
        or "utility" in cat_lower
        or "coop" in cat_lower
    ):
        return FrictionTier.TIER_2_AGRICULTURAL

    return FrictionTier.TIER_3_COMMERCIAL


def migrate_database(conn: sqlite3.Connection) -> int:
    """Run idempotent schema migrations under PRAGMA user_version.

    Migration path:
      v0 -> v1: Base schema creation (towers table + spatial/type/friction indexes).
      v1 -> v2: Add region_code and source_record_id columns, idx_towers_region,
                tower_packs table and index, installed_packs table, R*Tree index (towers_rtree)
                with auto-sync triggers and backfill.

    Args:
        conn: Open SQLite database connection.

    Returns:
        Current schema user_version after migration.
    """
    conn.execute("PRAGMA recursive_triggers = ON;")
    user_version = conn.execute("PRAGMA user_version;").fetchone()[0]

    if user_version < 1:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS towers (
                site_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                elevation_m REAL NOT NULL,
                mast_height_m REAL NOT NULL,
                site_type TEXT NOT NULL,
                owner TEXT NOT NULL,
                owner_category TEXT NOT NULL,
                friction_tier INTEGER NOT NULL,
                source_dataset TEXT NOT NULL,
                access_difficulty TEXT NOT NULL,
                has_grid_power INTEGER NOT NULL,
                solar_exposure_pct REAL NOT NULL,
                notes TEXT,
                source_url TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_towers_spatial ON towers(lat, lon);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_towers_type ON towers(site_type);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_towers_friction ON towers(friction_tier);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_towers_source ON towers(source_dataset);")
        conn.execute("PRAGMA user_version = 1;")
        conn.commit()
        user_version = 1

    if user_version < 2:
        # Check and add columns safely if missing
        cols = {
            row[1] if isinstance(row, (tuple, list)) else row["name"]
            for row in conn.execute("PRAGMA table_info(towers);").fetchall()
        }
        if "region_code" not in cols:
            conn.execute("ALTER TABLE towers ADD COLUMN region_code TEXT;")
        if "source_record_id" not in cols:
            conn.execute("ALTER TABLE towers ADD COLUMN source_record_id TEXT;")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_towers_region ON towers(region_code);")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tower_packs (site_id TEXT, pack_id TEXT, PRIMARY KEY(site_id, pack_id));"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tower_packs_pack ON tower_packs(pack_id);")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS installed_packs (
                pack_id TEXT PRIMARY KEY,
                region_code TEXT,
                pack_version TEXT,
                schema_version INTEGER,
                sha256 TEXT,
                installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                licenses_json TEXT
            );
            """
        )

        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS towers_rtree USING rtree(id, min_lat, max_lat, min_lon, max_lon);"
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_towers_ai AFTER INSERT ON towers BEGIN
                    INSERT OR REPLACE INTO towers_rtree(id, min_lat, max_lat, min_lon, max_lon)
                    VALUES (new.rowid, new.lat, new.lat, new.lon, new.lon);
                END;
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_towers_ad AFTER DELETE ON towers BEGIN
                    DELETE FROM towers_rtree WHERE id = old.rowid;
                END;
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_towers_au AFTER UPDATE ON towers BEGIN
                    DELETE FROM towers_rtree WHERE id = old.rowid;
                    INSERT OR REPLACE INTO towers_rtree(id, min_lat, max_lat, min_lon, max_lon)
                    VALUES (new.rowid, new.lat, new.lat, new.lon, new.lon);
                END;
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO towers_rtree(id, min_lat, max_lat, min_lon, max_lon) SELECT rowid, lat, lat, lon, lon FROM towers;"
            )
        except sqlite3.OperationalError:
            pass

        conn.execute("PRAGMA user_version = 2;")
        conn.commit()
        user_version = 2

    return user_version


class UnifiedTowerRegistry:
    """Unified SQLite Tower and High-Site Registry backed by WAL mode storage."""

    SCHEMA_VERSION = SCHEMA_VERSION

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        """Initialize the unified tower registry database.

        Args:
            db_path: Path to the SQLite database file. Defaults to ~/.meshscout/towers.db.
        """
        if db_path is None:
            self.db_path = Path.home() / ".meshscout" / "towers.db"
        else:
            self.db_path = Path(db_path)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Open a new SQLite connection with WAL journal mode and row factory."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA recursive_triggers=ON;")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        """Active SQLite connection instance."""
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    @property
    def has_rtree(self) -> bool:
        """Check if R*Tree spatial virtual table index is available."""
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='towers_rtree';"
        ).fetchone()
        return row is not None

    def _init_db(self) -> None:
        """Initialize towers schema and execute versioned migrations."""
        migrate_database(self.conn)

    def upsert_tower(
        self,
        site: SiteCandidate,
        owner: str = "",
        owner_category: str = "",
        source_dataset: str = "generic",
        friction_tier: Optional[FrictionTier] = None,
        region_code: Optional[str] = None,
        source_record_id: Optional[str] = None,
        pack_id: Optional[str] = None,
    ) -> bool:
        """Insert or replace a high-site candidate in the registry.

        Args:
            site: SiteCandidate contract model.
            owner: Name of site owner or managing entity.
            owner_category: Descriptive category (e.g. 'municipal_water', 'commercial_carrier').
            source_dataset: Dataset provenance origin (e.g. 'vt_vcgi', 'fcc_asr', 'osm').
            friction_tier: Explicit friction tier, or None to auto-resolve from type and owner.
            region_code: Optional administrative region code (e.g. 'VT', 'NH', 'US-VT').
            source_record_id: Optional identifier within the source dataset.
            pack_id: Optional pack provenance identifier to register in tower_packs.

        Returns:
            True if upsert succeeded.
        """
        if friction_tier is None:
            tier = resolve_friction_tier(site.site_type, owner_category)
        else:
            tier = friction_tier

        tier_val = int(tier.value if hasattr(tier, "value") else tier)
        st_val = site.site_type.value if hasattr(site.site_type, "value") else str(site.site_type)
        acc_val = (
            site.access_difficulty.value
            if hasattr(site.access_difficulty, "value")
            else str(site.access_difficulty)
        )

        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO towers (
                    site_id, name, lat, lon, elevation_m, mast_height_m,
                    site_type, owner, owner_category, friction_tier, source_dataset,
                    access_difficulty, has_grid_power, solar_exposure_pct,
                    notes, source_url, region_code, source_record_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    site.site_id,
                    site.name,
                    site.location.lat,
                    site.location.lon,
                    site.location.elevation_m,
                    site.mast_height_m,
                    st_val,
                    owner,
                    owner_category,
                    tier_val,
                    source_dataset,
                    acc_val,
                    1 if site.has_grid_power else 0,
                    float(site.solar_exposure_pct),
                    site.notes,
                    site.source_url,
                    region_code,
                    source_record_id,
                ),
            )
            if pack_id:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO tower_packs (site_id, pack_id)
                    VALUES (?, ?);
                    """,
                    (site.site_id, pack_id),
                )
        return True

    def bulk_upsert_towers(
        self,
        sites: Sequence[SiteCandidate],
        owner_default: str = "",
        owner_category_default: str = "",
        source_dataset: str = "generic",
        owner_categories: Optional[Sequence[str]] = None,
        region_codes: Optional[Sequence[str]] = None,
        source_record_ids: Optional[Sequence[str]] = None,
        pack_id: Optional[str] = None,
        owners: Optional[Sequence[str]] = None,
    ) -> int:
        """Bulk upsert high-site candidates in a single transaction.

        Args:
            sites: Sequence of SiteCandidate records.
            owner_default: Default owner identifier if not specified.
            owner_category_default: Default owner category used for friction tier resolution.
            source_dataset: Source dataset origin tag.
            owner_categories: Optional sequence of per-site owner categories.
            region_codes: Optional sequence of per-site region codes.
            source_record_ids: Optional sequence of per-site source dataset record IDs.
            pack_id: Optional pack identifier to associate all inserted sites with.
            owners: Optional sequence of per-site owner names or licensee strings.

        Returns:
            Total count of rows upserted.
        """
        if not sites:
            return 0

        rows = []
        for i, site in enumerate(sites):
            owner_val = (
                owners[i]
                if (owners is not None and i < len(owners))
                else owner_default
            )
            owner_cat = (
                owner_categories[i]
                if (owner_categories is not None and i < len(owner_categories))
                else owner_category_default
            )
            reg_code = (
                region_codes[i]
                if (region_codes is not None and i < len(region_codes))
                else None
            )
            src_rec_id = (
                source_record_ids[i]
                if (source_record_ids is not None and i < len(source_record_ids))
                else None
            )

            tier = resolve_friction_tier(site.site_type, owner_cat)
            tier_val = int(tier.value if hasattr(tier, "value") else tier)
            st_val = site.site_type.value if hasattr(site.site_type, "value") else str(site.site_type)
            acc_val = (
                site.access_difficulty.value
                if hasattr(site.access_difficulty, "value")
                else str(site.access_difficulty)
            )
            rows.append(
                (
                    site.site_id,
                    site.name,
                    site.location.lat,
                    site.location.lon,
                    site.location.elevation_m,
                    site.mast_height_m,
                    st_val,
                    owner_val,
                    owner_cat,
                    tier_val,
                    source_dataset,
                    acc_val,
                    1 if site.has_grid_power else 0,
                    float(site.solar_exposure_pct),
                    site.notes,
                    site.source_url,
                    reg_code,
                    src_rec_id,
                )
            )

        with self.conn:
            cursor = self.conn.cursor()
            cursor.executemany(
                """
                INSERT OR REPLACE INTO towers (
                    site_id, name, lat, lon, elevation_m, mast_height_m,
                    site_type, owner, owner_category, friction_tier, source_dataset,
                    access_difficulty, has_grid_power, solar_exposure_pct,
                    notes, source_url, region_code, source_record_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                rows,
            )
            if pack_id:
                pack_rows = [(site.site_id, pack_id) for site in sites]
                cursor.executemany(
                    """
                    INSERT OR REPLACE INTO tower_packs (site_id, pack_id)
                    VALUES (?, ?);
                    """,
                    pack_rows,
                )
        return len(rows)

    def query_towers(
        self,
        bounds: Optional[RegionalBounds] = None,
        site_types: Optional[Sequence[SiteType]] = None,
        max_friction_tier: Optional[int] = None,
        limit: int = 500,
        zoom: Optional[int] = None,
        region_code: Optional[str] = None,
    ) -> List[SiteCandidate]:
        """Query tower registry with dynamic spatial, categorical, and friction tier filters.

        Results are ordered by `friction_tier ASC, (elevation_m + mast_height_m) DESC`.

        Args:
            bounds: Optional RegionalBounds bounding box.
            site_types: Optional sequence of SiteType categories to match.
            max_friction_tier: Optional maximum friction tier ceiling (e.g. 1 for civic only).
            limit: Maximum number of rows to return (default 500). Set to 0 or negative for unlimited.
            zoom: Optional web map zoom level (<= 10 triggers grid-cell decimation).
            region_code: Optional administrative region code filter.

        Returns:
            List of reconstructed SiteCandidate models.
        """
        where_clauses: List[str] = []
        params: List[Any] = []
        use_rtree = bounds is not None and self.has_rtree

        if use_rtree:
            from_clause = "towers JOIN towers_rtree ON towers.rowid = towers_rtree.id"
            where_clauses.append(
                "towers_rtree.min_lat >= ? AND towers_rtree.max_lat <= ? "
                "AND towers_rtree.min_lon >= ? AND towers_rtree.max_lon <= ?"
            )
            params.extend([bounds.min_lat, bounds.max_lat, bounds.min_lon, bounds.max_lon])
            # Re-verify exact bounds on REAL columns to eliminate float32 precision bleed
            where_clauses.append(
                "towers.lat >= ? AND towers.lat <= ? AND towers.lon >= ? AND towers.lon <= ?"
            )
            params.extend([bounds.min_lat, bounds.max_lat, bounds.min_lon, bounds.max_lon])
        else:
            from_clause = "towers"
            if bounds is not None:
                where_clauses.append(
                    "towers.lat >= ? AND towers.lat <= ? AND towers.lon >= ? AND towers.lon <= ?"
                )
                params.extend([bounds.min_lat, bounds.max_lat, bounds.min_lon, bounds.max_lon])

        if region_code is not None:
            where_clauses.append("towers.region_code = ?")
            params.append(region_code)

        if site_types:
            placeholders = ", ".join("?" for _ in site_types)
            where_clauses.append(f"towers.site_type IN ({placeholders})")
            params.extend(
                [st.value if hasattr(st, "value") else str(st) for st in site_types]
            )

        if max_friction_tier is not None:
            tier_val = (
                int(max_friction_tier.value)
                if hasattr(max_friction_tier, "value")
                else int(max_friction_tier)
            )
            where_clauses.append("towers.friction_tier <= ?")
            params.append(tier_val)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        apply_decimation = zoom is not None and zoom <= 10
        if apply_decimation:
            cell_size = 0.25 if zoom <= 7 else (0.10 if zoom <= 9 else 0.04)
            query_sql = f"""
                WITH decimated AS (
                    SELECT towers.site_id, towers.name, towers.lat, towers.lon,
                           towers.elevation_m, towers.mast_height_m, towers.site_type,
                           towers.owner, towers.owner_category, towers.friction_tier,
                           towers.source_dataset, towers.access_difficulty,
                           towers.has_grid_power, towers.solar_exposure_pct,
                           towers.notes, towers.source_url, towers.updated_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY CAST((towers.lat + 90.0) / {cell_size} AS INT),
                                            CAST((towers.lon + 180.0) / {cell_size} AS INT)
                               ORDER BY towers.friction_tier ASC, (towers.elevation_m + towers.mast_height_m) DESC
                           ) as row_num
                    FROM {from_clause}
                    {where_sql}
                )
                SELECT site_id, name, lat, lon, elevation_m, mast_height_m,
                       site_type, owner, owner_category, friction_tier, source_dataset,
                       access_difficulty, has_grid_power, solar_exposure_pct,
                       notes, source_url, updated_at
                FROM decimated
                WHERE row_num = 1
                ORDER BY friction_tier ASC, (elevation_m + mast_height_m) DESC
            """
        else:
            query_sql = f"""
                SELECT towers.site_id, towers.name, towers.lat, towers.lon,
                       towers.elevation_m, towers.mast_height_m, towers.site_type,
                       towers.owner, towers.owner_category, towers.friction_tier,
                       towers.source_dataset, towers.access_difficulty,
                       towers.has_grid_power, towers.solar_exposure_pct,
                       towers.notes, towers.source_url, towers.updated_at
                FROM {from_clause}
                {where_sql}
                ORDER BY towers.friction_tier ASC, (towers.elevation_m + towers.mast_height_m) DESC
            """

        if limit > 0:
            query_sql += f" LIMIT {int(limit)}"

        candidates: List[SiteCandidate] = []
        cursor = self.conn.cursor()
        cursor.execute(query_sql, params)
        for row in cursor.fetchall():
            raw_type = row["site_type"]
            try:
                st = SiteType(raw_type)
            except ValueError:
                st = SiteType.CUSTOM

            raw_acc = row["access_difficulty"]
            try:
                ad = AccessDifficulty(raw_acc)
            except ValueError:
                ad = AccessDifficulty.MODERATE

            candidates.append(
                SiteCandidate(
                    site_id=row["site_id"],
                    name=row["name"],
                    location=Coordinate(
                        lat=float(row["lat"]),
                        lon=float(row["lon"]),
                        elevation_m=float(row["elevation_m"]),
                    ),
                    site_type=st,
                    mast_height_m=float(row["mast_height_m"]),
                    has_grid_power=bool(row["has_grid_power"]),
                    solar_exposure_pct=float(row["solar_exposure_pct"]),
                    access_difficulty=ad,
                    notes=row["notes"],
                    source_url=row["source_url"],
                )
            )
        return candidates

    def count_towers_by_category(
        self, bounds: Optional[RegionalBounds] = None
    ) -> Dict[str, int]:
        """Return counts of registered towers grouped by site_type and friction_tier.

        Provides category counts for:
          - Each site_type (e.g. 'water_tower', 'fire_lookout')
          - Each friction tier (e.g. 'tier_1', 'tier_2', 'tier_3')
          - Joint categories (e.g. 'water_tower:tier_1' and 'water_tower:1')

        Args:
            bounds: Optional RegionalBounds to restrict count calculations.

        Returns:
            Dictionary mapping category labels to integer counts.
        """
        where_clauses: List[str] = []
        params: List[Any] = []

        if bounds is not None:
            where_clauses.append("lat >= ? AND lat <= ? AND lon >= ? AND lon <= ?")
            params.extend([bounds.min_lat, bounds.max_lat, bounds.min_lon, bounds.max_lon])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query_sql = f"""
            SELECT site_type, friction_tier, COUNT(*) as cnt
            FROM towers
            {where_sql}
            GROUP BY site_type, friction_tier
            ORDER BY site_type, friction_tier
        """

        counts: Dict[str, int] = {}
        cursor = self.conn.cursor()
        cursor.execute(query_sql, params)
        for row in cursor.fetchall():
            st = str(row[0])
            tier = int(row[1])
            cnt = int(row[2])

            counts[st] = counts.get(st, 0) + cnt
            counts[f"tier_{tier}"] = counts.get(f"tier_{tier}", 0) + cnt
            counts[f"{st}:tier_{tier}"] = cnt
            counts[f"{st}:{tier}"] = cnt

        return counts

    def record_installed_pack(
        self,
        pack_id: str,
        region_code: str,
        pack_version: str,
        schema_version: int,
        sha256: str,
        licenses_json: str = "[]",
    ) -> None:
        """Record or update an installed tower pack manifest entry.

        Args:
            pack_id: Unique identifier for the regional pack.
            region_code: ISO or FIPS regional geographic code.
            pack_version: Semantic release version string.
            schema_version: Database schema compatibility version.
            sha256: SHA-256 cryptographic digest of the source archive.
            licenses_json: JSON string representing open-data license attributions.
        """
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO installed_packs (
                    pack_id, region_code, pack_version, schema_version, sha256, licenses_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pack_id, region_code, pack_version, schema_version, sha256, licenses_json),
            )

    def list_installed_packs(self) -> List[Dict[str, Any]]:
        """List all installed packs with provenance metadata, tower counts, licenses, and bounds."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT p.pack_id, p.region_code, p.pack_version, p.schema_version, p.sha256, p.installed_at, p.licenses_json,
                   COUNT(tp.site_id) AS row_count,
                   MIN(t.lat) AS min_lat, MAX(t.lat) AS max_lat, MIN(t.lon) AS min_lon, MAX(t.lon) AS max_lon
            FROM installed_packs p
            LEFT JOIN tower_packs tp ON p.pack_id = tp.pack_id
            LEFT JOIN towers t ON tp.site_id = t.site_id
            GROUP BY p.pack_id
            ORDER BY p.installed_at DESC;
            """
        )
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            # Parse licenses if present
            licenses = []
            if d.get("licenses_json"):
                try:
                    lic_data = json.loads(d["licenses_json"])
                    if isinstance(lic_data, list):
                        licenses = [
                            s.get("license") for s in lic_data
                            if isinstance(s, dict) and s.get("license")
                        ]
                except Exception:
                    pass
            d["licenses"] = list(dict.fromkeys(licenses))
            d["site_count"] = d.get("row_count", 0)

            # Compute bounding box
            if (
                d.get("min_lat") is not None
                and d.get("max_lat") is not None
                and d.get("min_lon") is not None
                and d.get("max_lon") is not None
            ):
                d["bounds"] = {
                    "min_lat": float(d["min_lat"]),
                    "max_lat": float(d["max_lat"]),
                    "min_lon": float(d["min_lon"]),
                    "max_lon": float(d["max_lon"]),
                }
            elif d.get("region_code"):
                try:
                    from meshscout.adapters.regions import get_state_info
                    st = get_state_info(d["region_code"], include_national=True)
                    if st and st.bounds:
                        d["bounds"] = {
                            "min_lat": float(st.bounds.min_lat),
                            "max_lat": float(st.bounds.max_lat),
                            "min_lon": float(st.bounds.min_lon),
                            "max_lon": float(st.bounds.max_lon),
                        }
                    else:
                        d["bounds"] = None
                except Exception:
                    d["bounds"] = None
            else:
                d["bounds"] = None
            results.append(d)
        return results

    def close(self) -> None:
        """Close the underlying SQLite connection if open."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            finally:
                self._conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self) -> UnifiedTowerRegistry:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
