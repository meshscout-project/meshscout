"""Regional data pack format, manifest contracts, export and install engines.

Provides offline distribution capabilities for municipal and carrier infrastructure across
US states and Canadian provinces. Packs are packaged as gzip-compressed SQLite databases
carrying a towers table and pack_metadata table, stamped with PRAGMA user_version matching
the UnifiedTowerRegistry schema version.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel, Field

from meshscout.core.contracts import Result
from meshscout.core.tower_registry import SCHEMA_VERSION, UnifiedTowerRegistry


class PackSourceInfo(BaseModel):
    """Provenance and licensing metadata for a dataset included in a regional pack."""

    dataset: str = Field(..., description="Source dataset identifier, e.g. fcc_asr, vt_vcgi")
    license: str = Field(..., description="License name or identifier, e.g. Public Domain, CC-BY-4.0")
    attribution: str = Field(..., description="Attribution text or entity citation")
    retrieved_at: str = Field(default="", description="ISO-8601 timestamp when dataset was retrieved")
    source_url: str = Field(default="", description="Source origin URL")


class RegionPackInfo(BaseModel):
    """Metadata descriptor for a regional data pack archive."""

    pack_id: str = Field(..., description="Unique pack identifier, e.g. towers-vt")
    region_code: str = Field(..., description="Administrative region code, e.g. VT, US-VT, CA-QC")
    pack_version: str = Field(default="1.0.0", description="Semantic release version string")
    schema_version: int = Field(default=SCHEMA_VERSION, description="Database schema version (PRAGMA user_version)")
    row_count: int = Field(..., ge=0, description="Total number of tower records in pack")
    sha256: str = Field(..., description="Cryptographic SHA-256 digest of .sqlite.gz archive")
    size_bytes: int = Field(..., ge=0, description="File size of .sqlite.gz archive in bytes")
    url: Optional[str] = Field(default=None, description="Remote download URL if published")
    sources: List[PackSourceInfo] = Field(default_factory=list, description="Source dataset attributions")
    required_hgt_tiles: List[str] = Field(default_factory=list, description="SRTM/3DEP DEM tiles required for region")


class PackManifest(BaseModel):
    """Manifest catalog indexing available regional data packs."""

    manifest_version: str = Field(default="1.0.0", description="Manifest schema version")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 generation timestamp",
    )
    packs: Dict[str, RegionPackInfo] = Field(
        default_factory=dict,
        description="Map of pack_id to RegionPackInfo records",
    )

    def to_json(self, indent: int = 2) -> str:
        """Serialize manifest to JSON string."""
        return self.model_dump_json(indent=indent)

    def write_json(self, path: Union[str, Path], indent: int = 2) -> Path:
        """Write manifest JSON to disk."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(indent=indent), encoding="utf-8")
        return p

    @classmethod
    def from_json(cls, json_str: str) -> PackManifest:
        """Deserialize manifest from JSON string."""
        return cls.model_validate_json(json_str)

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> PackManifest:
        """Read and deserialize manifest from disk file."""
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


def compute_sha256(path: Union[str, Path]) -> str:
    """Calculate SHA-256 hex digest for a file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def export_region_pack(
    registry: UnifiedTowerRegistry,
    region_code: str,
    out_dir: Union[str, Path],
    pack_version: str = "1.0.0",
    sources: Optional[List[PackSourceInfo]] = None,
    required_hgt_tiles: Optional[List[str]] = None,
    pack_id: Optional[str] = None,
    filename: Optional[str] = None,
    include_datasets: Optional[Sequence[str]] = None,
    exclude_datasets: Optional[Sequence[str]] = None,
) -> RegionPackInfo:
    """Export regional tower data from registry into a gzip-compressed SQLite pack archive.

    Creates gzip-compressed SQLite archive named `towers-{region_code.lower()}-{pack_version}.sqlite.gz`
    (or custom filename if provided).
    Holds table `towers` (v2 columns) and table `pack_metadata(key TEXT PRIMARY KEY, value TEXT)`.
    PRAGMA user_version = SCHEMA_VERSION.

    Args:
        registry: Source UnifiedTowerRegistry.
        region_code: Administrative region code (e.g. 'VT', 'NH', 'US-VT').
        out_dir: Output directory for the generated .sqlite.gz archive.
        pack_version: Release semantic version string.
        sources: Optional dataset provenance citations.
        required_hgt_tiles: Optional list of DEM tile names needed for terrain coverage.
        pack_id: Optional pack identifier; defaults to towers-{region_code.lower()}.
        filename: Optional custom output archive filename.
        include_datasets: Optional sequence of source datasets to include exclusively.
        exclude_datasets: Optional sequence of source datasets to exclude (e.g. ODbL datasets).

    Returns:
        RegionPackInfo descriptor with computed SHA-256 digest and file size.
    """
    out_path_dir = Path(out_dir)
    out_path_dir.mkdir(parents=True, exist_ok=True)

    clean_region = region_code.strip()
    effective_pack_id = pack_id or f"towers-{clean_region.lower()}"
    archive_filename = filename or f"{effective_pack_id}-{pack_version}.sqlite.gz"
    out_file = out_path_dir / archive_filename

    sources_list = sources or []
    hgt_list = required_hgt_tiles or []

    where_parts = [
        """(UPPER(COALESCE(t.region_code, '')) = UPPER(?)
           OR UPPER(COALESCE(tp.pack_id, '')) = UPPER(?)
           OR UPPER(COALESCE(tp.pack_id, '')) = UPPER(?))"""
    ]
    query_params: List[Any] = [clean_region.upper(), clean_region, effective_pack_id, clean_region]

    if include_datasets:
        placeholders = ",".join("?" for _ in include_datasets)
        where_parts.append(f"LOWER(t.source_dataset) IN ({placeholders})")
        query_params.extend([d.lower() for d in include_datasets])

    if exclude_datasets:
        placeholders = ",".join("?" for _ in exclude_datasets)
        where_parts.append(f"LOWER(t.source_dataset) NOT IN ({placeholders})")
        query_params.extend([d.lower() for d in exclude_datasets])

    cursor = registry.conn.cursor()
    cursor.execute(
        f"""
        SELECT DISTINCT t.site_id, t.name, t.lat, t.lon, t.elevation_m, t.mast_height_m,
               t.site_type, t.owner, t.owner_category, t.friction_tier, t.source_dataset,
               t.access_difficulty, t.has_grid_power, t.solar_exposure_pct,
               t.notes, t.source_url, COALESCE(t.region_code, ?) AS region_code,
               t.source_record_id, t.updated_at
        FROM towers t
        LEFT JOIN tower_packs tp ON t.site_id = tp.site_id
        WHERE {" AND ".join(where_parts)}
        ORDER BY t.site_id ASC;
        """,
        query_params,
    )
    rows = cursor.fetchall()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_db_path = Path(tmp_dir) / "export.sqlite"
        with contextlib.closing(sqlite3.connect(str(tmp_db_path))) as tmp_conn:
            tmp_conn.execute(f"PRAGMA user_version = {registry.SCHEMA_VERSION};")
            tmp_conn.execute(
                """
                CREATE TABLE towers (
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
                    region_code TEXT,
                    source_record_id TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            tmp_conn.execute("CREATE INDEX idx_towers_spatial ON towers(lat, lon);")
            tmp_conn.execute("CREATE INDEX idx_towers_type ON towers(site_type);")
            tmp_conn.execute("CREATE INDEX idx_towers_friction ON towers(friction_tier);")
            tmp_conn.execute("CREATE INDEX idx_towers_region ON towers(region_code);")
            tmp_conn.execute(
                """
                CREATE TABLE pack_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )

            if rows:
                insert_tuples = [
                    (
                        r[0],
                        r[1],
                        r[2],
                        r[3],
                        r[4],
                        r[5],
                        r[6],
                        r[7],
                        r[8],
                        r[9],
                        r[10],
                        r[11],
                        r[12],
                        r[13],
                        r[14],
                        r[15],
                        r[16] or clean_region.upper(),
                        r[17],
                        r[18],
                    )
                    for r in rows
                ]
                tmp_conn.executemany(
                    """
                    INSERT INTO towers (
                        site_id, name, lat, lon, elevation_m, mast_height_m,
                        site_type, owner, owner_category, friction_tier, source_dataset,
                        access_difficulty, has_grid_power, solar_exposure_pct,
                        notes, source_url, region_code, source_record_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP));
                    """,
                    insert_tuples,
                )

            meta_entries = [
                ("pack_id", effective_pack_id),
                ("region_code", clean_region.upper()),
                ("pack_version", pack_version),
                ("schema_version", str(registry.SCHEMA_VERSION)),
                ("row_count", str(len(rows))),
                ("sources", json.dumps([s.model_dump() for s in sources_list])),
                ("required_hgt_tiles", json.dumps(hgt_list)),
            ]
            tmp_conn.executemany("INSERT INTO pack_metadata (key, value) VALUES (?, ?);", meta_entries)
            tmp_conn.commit()

        with open(tmp_db_path, "rb") as f_in, gzip.GzipFile(out_file, "wb", mtime=0.0) as f_out:
            shutil.copyfileobj(f_in, f_out)

    sha256_digest = compute_sha256(out_file)
    size_bytes = out_file.stat().st_size

    return RegionPackInfo(
        pack_id=effective_pack_id,
        region_code=clean_region.upper(),
        pack_version=pack_version,
        schema_version=registry.SCHEMA_VERSION,
        row_count=len(rows),
        sha256=sha256_digest,
        size_bytes=size_bytes,
        url=None,
        sources=sources_list,
        required_hgt_tiles=hgt_list,
    )


def install_region_pack(
    registry: UnifiedTowerRegistry,
    pack_path: Union[str, Path],
    expected_sha256: Optional[str] = None,
) -> Result[RegionPackInfo]:
    """Verify, decompress, and merge a regional pack archive into the local registry.

    Args:
        registry: Target UnifiedTowerRegistry.
        pack_path: Path to the .sqlite.gz archive.
        expected_sha256: Optional expected SHA-256 hash. If provided and does not match,
            installation is aborted with PACK_HASH_MISMATCH.

    Returns:
        Result containing RegionPackInfo on success, or MeshScoutError on failure.
    """
    p_path = Path(pack_path)
    if not p_path.is_file():
        return Result.fail(
            code="PACK_NOT_FOUND",
            message=f"Regional pack file not found: {p_path}",
        )

    actual_sha256 = compute_sha256(p_path)
    size_bytes = p_path.stat().st_size

    if expected_sha256 is not None:
        if actual_sha256.lower() != expected_sha256.strip().lower():
            return Result.fail(
                code="PACK_HASH_MISMATCH",
                message=(
                    f"SHA-256 digest mismatch for {p_path.name}: "
                    f"expected {expected_sha256}, got {actual_sha256}"
                ),
            )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_db_path = Path(tmp_dir) / "pack.sqlite"
        try:
            with gzip.open(p_path, "rb") as gz_in, open(tmp_db_path, "wb") as f_out:
                shutil.copyfileobj(gz_in, f_out)
        except Exception as exc:
            return Result.fail(
                code="PACK_CORRUPT",
                message=f"Failed to decompress gzip archive {p_path.name}: {exc}",
            )

        try:
            with contextlib.closing(sqlite3.connect(str(tmp_db_path))) as pack_conn:
                pack_conn.row_factory = sqlite3.Row
                cur = pack_conn.cursor()

                pack_schema_version = cur.execute("PRAGMA user_version;").fetchone()[0]
                if pack_schema_version > registry.SCHEMA_VERSION:
                    return Result.fail(
                        code="PACK_SCHEMA_UNSUPPORTED",
                        message=(
                            f"Pack schema version {pack_schema_version} exceeds registry "
                            f"supported schema version {registry.SCHEMA_VERSION}. Please upgrade MeshScout."
                        ),
                    )

                meta_dict: Dict[str, str] = {}
                try:
                    for row in cur.execute("SELECT key, value FROM pack_metadata;").fetchall():
                        meta_dict[str(row[0])] = str(row[1])
                except sqlite3.OperationalError:
                    pass

                cols = {
                    row[1] if isinstance(row, (tuple, list)) else row["name"]
                    for row in cur.execute("PRAGMA table_info(towers);").fetchall()
                }
                cur.execute("SELECT * FROM towers;")
                tower_rows = cur.fetchall()
                row_count = len(tower_rows)
        except sqlite3.Error as db_exc:
            return Result.fail(
                code="PACK_SQLITE_ERROR",
                message=f"Corrupt or invalid SQLite pack database {p_path.name}: {db_exc}",
            )

    region_code = meta_dict.get("region_code", "")
    if not region_code:
        parts = p_path.name.replace(".sqlite.gz", "").split("-")
        if len(parts) >= 2 and parts[0] == "towers":
            region_code = parts[1].upper()
        else:
            region_code = "UNKNOWN"

    pack_version = meta_dict.get("pack_version", "1.0.0")
    pack_id = meta_dict.get("pack_id", f"towers-{region_code.lower()}")

    sources: List[PackSourceInfo] = []
    if "sources" in meta_dict:
        try:
            for item in json.loads(meta_dict["sources"]):
                sources.append(PackSourceInfo(**item))
        except Exception:
            pass

    required_hgt_tiles: List[str] = []
    if "required_hgt_tiles" in meta_dict:
        try:
            required_hgt_tiles = json.loads(meta_dict["required_hgt_tiles"])
        except Exception:
            pass

    with registry.conn:
        reg_cur = registry.conn.cursor()

        tuples = []
        for r in tower_rows:
            tuples.append(
                (
                    r["site_id"],
                    r["name"],
                    float(r["lat"]),
                    float(r["lon"]),
                    float(r["elevation_m"]),
                    float(r["mast_height_m"]),
                    r["site_type"],
                    r["owner"] if "owner" in cols else "",
                    r["owner_category"] if "owner_category" in cols else "",
                    int(r["friction_tier"]) if "friction_tier" in cols else 3,
                    r["source_dataset"] if "source_dataset" in cols else "generic",
                    r["access_difficulty"] if "access_difficulty" in cols else "moderate",
                    int(r["has_grid_power"]) if "has_grid_power" in cols else 0,
                    float(r["solar_exposure_pct"]) if "solar_exposure_pct" in cols else 100.0,
                    r["notes"] if "notes" in cols else None,
                    r["source_url"] if "source_url" in cols else None,
                    r["region_code"] if ("region_code" in cols and r["region_code"]) else region_code,
                    r["source_record_id"] if "source_record_id" in cols else None,
                    r["updated_at"] if "updated_at" in cols else None,
                )
            )

        if tuples:
            reg_cur.executemany(
                """
                INSERT OR REPLACE INTO towers (
                    site_id, name, lat, lon, elevation_m, mast_height_m,
                    site_type, owner, owner_category, friction_tier, source_dataset,
                    access_difficulty, has_grid_power, solar_exposure_pct,
                    notes, source_url, region_code, source_record_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP));
                """,
                tuples,
            )

            reg_cur.executemany(
                """
                INSERT OR REPLACE INTO tower_packs (site_id, pack_id)
                VALUES (?, ?);
                """,
                [(t[0], pack_id) for t in tuples],
            )

        licenses_json = json.dumps([s.model_dump() for s in sources])
        reg_cur.execute(
            """
            INSERT OR REPLACE INTO installed_packs (
                pack_id, region_code, pack_version, schema_version, sha256, licenses_json
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (pack_id, region_code, pack_version, pack_schema_version, actual_sha256, licenses_json),
        )

    pack_info = RegionPackInfo(
        pack_id=pack_id,
        region_code=region_code,
        pack_version=pack_version,
        schema_version=pack_schema_version,
        row_count=row_count,
        sha256=actual_sha256,
        size_bytes=size_bytes,
        url=None,
        sources=sources,
        required_hgt_tiles=required_hgt_tiles,
    )
    return Result.success(pack_info)


def uninstall_region_pack(registry: UnifiedTowerRegistry, pack_id: str) -> int:
    """Uninstall a regional pack and remove unreferenced towers.

    Deletes from tower_packs where pack_id = ?.
    For candidate site_ids, deletes from towers ONLY IF they have no remaining links in tower_packs.
    Deletes from installed_packs.
    Returns count of removed towers.

    Args:
        registry: Target UnifiedTowerRegistry.
        pack_id: Unique pack identifier to remove.

    Returns:
        Number of towers removed from the registry.
    """
    with registry.conn:
        cur = registry.conn.cursor()

        cur.execute(
            """
            DELETE FROM towers
            WHERE site_id IN (
                SELECT tp.site_id
                FROM tower_packs tp
                WHERE tp.pack_id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM tower_packs other
                      WHERE other.site_id = tp.site_id
                        AND other.pack_id != ?
                  )
            );
            """,
            (pack_id, pack_id),
        )
        removed_towers = cur.rowcount

        cur.execute("DELETE FROM tower_packs WHERE pack_id = ?;", (pack_id,))
        cur.execute("DELETE FROM installed_packs WHERE pack_id = ?;", (pack_id,))

    return max(0, removed_towers)


def list_installed_packs(registry: UnifiedTowerRegistry) -> List[Dict[str, Any]]:
    """List all installed regional packs with provenance metadata.

    Args:
        registry: UnifiedTowerRegistry instance.

    Returns:
        List of dictionaries containing pack metadata from installed_packs table.
    """
    return registry.list_installed_packs()


def build_pack_manifest(
    pack_infos: Sequence[RegionPackInfo],
    manifest_version: str = "1.0.0",
) -> PackManifest:
    """Build a PackManifest catalog indexing multiple regional packs.

    Args:
        pack_infos: Sequence of RegionPackInfo metadata models.
        manifest_version: Manifest specification version string.

    Returns:
        PackManifest mapping pack_id to RegionPackInfo.
    """
    packs_map = {p.pack_id: p for p in pack_infos}
    return PackManifest(
        manifest_version=manifest_version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        packs=packs_map,
    )
