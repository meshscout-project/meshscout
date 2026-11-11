"""Field Kit Staging Engine for Offline Disaster Response Operations.

Provides deterministic regional bounding calculation, tile count and storage estimation,
offline MBTiles map archive compilation, DEM raster synchronization, and Living Mesh
database seeding for zero-dependency field deployment (TASK-1088).
"""

from __future__ import annotations

import contextlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from meshscout.adapters.elevation import get_required_hgt_tiles_for_bounds
from meshscout.adapters.regions import resolve_regional_bounds
from meshscout.core.contracts import RegionalBounds, Result
from meshscout.core.registry import LivingMeshRegistry

# Minimal 1x1 transparent PNG payload used for synthetic tile caching
SAMPLE_TILE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def deg_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Convert geodetic coordinates to standard Web Mercator Slippy map tile indices (x, y).

    Clamps latitude to the Web Mercator projection bounds (~[-85.0511, 85.0511])
    and ensures tile indices remain within [0, 2^zoom - 1].
    """
    n = 1 << zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_clamped = max(-85.05112878, min(85.05112878, lat))
    lat_rad = math.radians(lat_clamped)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def calculate_buffered_region_bounds(
    state_code: str,
    buffer_km: float = 20.0,
) -> RegionalBounds:
    """Calculate expanded regional bounding box buffered by outward geodesic distance in kilometers.

    Args:
        state_code: State or province identifier (e.g. 'VT', 'CA_QC', 'NH').
        buffer_km: Distance in km to expand all four boundary cardinal directions (default: 20.0).

    Returns:
        RegionalBounds with expanded min/max latitude and longitude.

    Raises:
        ValueError: If state_code cannot be resolved or buffer_km is negative.
    """
    if buffer_km < 0.0:
        raise ValueError(f"buffer_km must be non-negative, got {buffer_km}")

    res = resolve_regional_bounds(state_code)
    if not res.ok or res.value is None:
        msg = res.error.message if res.error else f"Unsupported region or state '{state_code}'"
        raise ValueError(msg)

    base_bounds = res.value
    d_lat = buffer_km / 111.0
    mid_lat = (base_bounds.min_lat + base_bounds.max_lat) / 2.0
    d_lon = buffer_km / (111.0 * max(0.1, math.cos(math.radians(mid_lat))))

    min_lat = max(-90.0, round(base_bounds.min_lat - d_lat, 4))
    max_lat = min(90.0, round(base_bounds.max_lat + d_lat, 4))
    min_lon = max(-180.0, round(base_bounds.min_lon - d_lon, 4))
    max_lon = min(180.0, round(base_bounds.max_lon + d_lon, 4))

    return RegionalBounds(
        name=f"{base_bounds.name}_buffered_{int(buffer_km)}km",
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )


def estimate_offline_tile_count(
    bounds: RegionalBounds,
    min_zoom: int = 7,
    max_zoom: int = 12,
) -> Dict[str, Any]:
    """Estimate total slippy tile count and storage size across zoom levels for a bounding box.

    Returns:
        Dictionary containing:
            total_tiles: Total tile count summed across zoom levels
            by_zoom: Mapping of zoom level to tile count
            est_bytes: Estimated uncompressed storage footprint (25 KB per raster tile)
    """
    if min_zoom < 0 or max_zoom < min_zoom or max_zoom > 22:
        raise ValueError(f"Invalid zoom range: min_zoom={min_zoom}, max_zoom={max_zoom}")

    by_zoom: Dict[int, int] = {}
    total_tiles = 0

    for z in range(min_zoom, max_zoom + 1):
        x_min, y_min = deg_to_tile(bounds.max_lat, bounds.min_lon, z)
        x_max, y_max = deg_to_tile(bounds.min_lat, bounds.max_lon, z)
        x_start = min(x_min, x_max)
        x_end = max(x_min, x_max)
        y_start = min(y_min, y_max)
        y_end = max(y_min, y_max)
        count_z = (x_end - x_start + 1) * (y_end - y_start + 1)
        by_zoom[z] = count_z
        total_tiles += count_z

    est_bytes = total_tiles * 25000
    return {
        "total_tiles": total_tiles,
        "by_zoom": by_zoom,
        "est_bytes": est_bytes,
    }


def stage_offline_region(
    state_code: str,
    output_dir: Union[str, Path],
    buffer_km: float = 20.0,
    min_zoom: int = 7,
    max_zoom: int = 12,
    include_dem: bool = True,
    dry_run: bool = False,
    tile_fetcher: Optional[Callable[[int, int, int], Optional[bytes]]] = None,
    packs_dir: Optional[Union[str, Path]] = None,
) -> Result[Dict[str, Any]]:
    """Stage a self-contained offline field kit directory for a given regional state or province.

    Args:
        state_code: Target state or provincial identifier (e.g. 'VT', 'CA_QC', 'NH').
        output_dir: Target destination path for the field kit.
        buffer_km: Buffer boundary expansion distance in km.
        min_zoom: Minimum tile zoom level (default: 7).
        max_zoom: Maximum tile zoom level (default: 12).
        include_dem: If True, check and synchronize local DEM raster tiles.
        dry_run: If True, calculate bounds and estimates without modifying filesystem.
        tile_fetcher: Optional callable `(z, x, y) -> Optional[bytes]` to pull raster tiles.
                      If None, synthetic raster tiles are generated.
        packs_dir: Optional custom path to search for regional data pack archives.

    Returns:
        Result containing staging summary metrics or MeshScoutError.
    """
    if buffer_km < 0.0:
        return Result.fail(
            code="INVALID_BUFFER",
            message=f"buffer_km must be non-negative, got {buffer_km}",
            details={"buffer_km": buffer_km},
        )

    if min_zoom < 0 or max_zoom < min_zoom or max_zoom > 22:
        return Result.fail(
            code="INVALID_ZOOM_RANGE",
            message=f"Invalid zoom range: min_zoom={min_zoom}, max_zoom={max_zoom}",
            details={"min_zoom": min_zoom, "max_zoom": max_zoom},
        )

    try:
        bounds = calculate_buffered_region_bounds(state_code=state_code, buffer_km=buffer_km)
    except ValueError as exc:
        return Result.fail(
            code="REGION_RESOLUTION_FAILED",
            message=str(exc),
            details={"state_code": state_code},
        )

    estimates = estimate_offline_tile_count(
        bounds=bounds,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
    )

    required_hgt_tiles = get_required_hgt_tiles_for_bounds(bounds)

    output_path = Path(output_dir)

    if dry_run:
        planned_files = [
            str(output_path / "tiles" / f"{state_code.lower()}_offline.mbtiles"),
            str(output_path / "data" / "mesh_state.db"),
        ]
        if include_dem:
            planned_files.append(str(output_path / "dem"))
        planned_files.append(str(output_path / "packs"))

        return Result.success(
            {
                "state_code": state_code.upper(),
                "dry_run": True,
                "output_dir": str(output_path),
                "buffer_km": buffer_km,
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
                "include_dem": include_dem,
                "bounds": bounds.model_dump(),
                "estimates": estimates,
                "total_tiles": estimates["total_tiles"],
                "est_bytes": estimates["est_bytes"],
                "by_zoom": estimates["by_zoom"],
                "planned_files": planned_files,
                "required_hgt_tiles": required_hgt_tiles,
                "packs_staged": [],
            }
        )

    # 1. Create directory structure
    tiles_dir = output_path / "tiles"
    dem_dir = output_path / "dem"
    data_dir = output_path / "data"
    packs_dest_dir = output_path / "packs"

    tiles_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    packs_dest_dir.mkdir(parents=True, exist_ok=True)
    if include_dem:
        dem_dir.mkdir(parents=True, exist_ok=True)

    # 2. Write MBTiles SQLite archive
    mbtiles_path = tiles_dir / f"{state_code.lower()}_offline.mbtiles"
    if mbtiles_path.exists():
        mbtiles_path.unlink()

    tiles_written = 0
    with contextlib.closing(sqlite3.connect(str(mbtiles_path))) as conn:
        conn.execute("PRAGMA synchronous = OFF;")
        conn.execute("CREATE TABLE metadata (name text, value text);")
        conn.execute(
            "CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob);"
        )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS name ON metadata (name);")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles (zoom_level, tile_column, tile_row);"
        )

        metadata_records = [
            ("name", f"{state_code.upper()} Offline Field Kit"),
            ("type", "baselayer"),
            ("version", "1.0.0"),
            ("description", f"Offline regional tiles for {state_code.upper()}"),
            ("format", "png"),
            ("bounds", f"{bounds.min_lon},{bounds.min_lat},{bounds.max_lon},{bounds.max_lat}"),
            ("minzoom", str(min_zoom)),
            ("maxzoom", str(max_zoom)),
        ]
        conn.executemany("INSERT INTO metadata (name, value) VALUES (?, ?);", metadata_records)
        conn.commit()

        # 3. Populate tiles (using TMS tile_row coordinate transformation)
        batch: List[Tuple[int, int, int, bytes]] = []

        if tile_fetcher is not None:
            for z in range(min_zoom, max_zoom + 1):
                x_min, y_min = deg_to_tile(bounds.max_lat, bounds.min_lon, z)
                x_max, y_max = deg_to_tile(bounds.min_lat, bounds.max_lon, z)
                x_start, x_end = min(x_min, x_max), max(x_min, x_max)
                y_start, y_end = min(y_min, y_max), max(y_min, y_max)
                for x in range(x_start, x_end + 1):
                    for y in range(y_start, y_end + 1):
                        data = tile_fetcher(z, x, y)
                        if data is not None:
                            tms_y = (1 << z) - 1 - y
                            batch.append((z, x, tms_y, data))
                            if len(batch) >= 500:
                                conn.executemany(
                                    "INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?);",
                                    batch,
                                )
                                tiles_written += len(batch)
                                batch.clear()
            if batch:
                conn.executemany("INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?);", batch)
                tiles_written += len(batch)
                batch.clear()
        else:
            # Synthetic / sample tiles
            if estimates["total_tiles"] <= 500:
                for z in range(min_zoom, max_zoom + 1):
                    x_min, y_min = deg_to_tile(bounds.max_lat, bounds.min_lon, z)
                    x_max, y_max = deg_to_tile(bounds.min_lat, bounds.max_lon, z)
                    x_start, x_end = min(x_min, x_max), max(x_min, x_max)
                    y_start, y_end = min(y_min, y_max), max(y_min, y_max)
                    for x in range(x_start, x_end + 1):
                        for y in range(y_start, y_end + 1):
                            tms_y = (1 << z) - 1 - y
                            batch.append((z, x, tms_y, SAMPLE_TILE_PNG))
            else:
                c_lat = (bounds.min_lat + bounds.max_lat) / 2.0
                c_lon = (bounds.min_lon + bounds.max_lon) / 2.0
                for z in range(min_zoom, max_zoom + 1):
                    tx, ty = deg_to_tile(c_lat, c_lon, z)
                    tms_y = (1 << z) - 1 - ty
                    batch.append((z, tx, tms_y, SAMPLE_TILE_PNG))

            if batch:
                conn.executemany("INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?);", batch)
                tiles_written += len(batch)
                batch.clear()

        conn.commit()

    # 4. Seed Living Mesh DB
    mesh_db_path = data_dir / "mesh_state.db"
    LivingMeshRegistry(db_path=mesh_db_path)

    # 5. DEM Tiles handling
    copied_dem: List[str] = []
    if include_dem:
        home_dem = Path.home() / ".meshscout" / "dem"
        if home_dem.is_dir():
            for f in home_dem.glob("*.hgt"):
                shutil.copy2(f, dem_dir / f.name)
                copied_dem.append(f.name)

        fixtures_dir = Path(__file__).resolve().parent.parent.parent.parent / "fixtures"
        if fixtures_dir.is_dir():
            for f in fixtures_dir.glob("*.hgt"):
                dest_file = dem_dir / f.name
                if not dest_file.exists():
                    shutil.copy2(f, dest_file)
                    copied_dem.append(f.name)

    # 6. Regional Data Packs staging
    packs_staged: List[str] = []
    clean_code = state_code.strip().lower()
    code_tokens = {clean_code, clean_code.replace("-", "_"), clean_code.replace("_", "-")}
    if "-" in clean_code:
        code_tokens.add(clean_code.split("-")[-1])
    if "_" in clean_code:
        code_tokens.add(clean_code.split("_")[-1])

    search_dirs: List[Path] = []
    if packs_dir is not None:
        search_dirs.append(Path(packs_dir))
    search_dirs.extend([
        Path.home() / ".meshscout" / "packs",
        Path.home() / ".meshscout" / "packs_cache",
        Path("dist/packs"),
        Path.cwd() / "dist" / "packs",
        packs_dest_dir,
    ])

    staged_set: set[str] = set()

    for s_dir in search_dirs:
        if not s_dir.is_dir():
            continue
        # Direct glob matching for .sqlite.gz and .sqlite
        candidate_files = sorted(list(s_dir.glob("*.sqlite.gz")) + list(s_dir.glob("*.sqlite")))
        for p_file in candidate_files:
            p_name = p_file.name.lower()
            matches = any(
                f"towers-{token}" in p_name
                or f"-{token}-" in p_name
                or f"_{token}_" in p_name
                or p_name.startswith(f"{token}-")
                or p_name.startswith(f"{token}_")
                or p_name.startswith(f"towers_{token}")
                or p_name == f"{token}.sqlite.gz"
                for token in code_tokens
            )
            if matches and p_file.name not in staged_set:
                dest_file = packs_dest_dir / p_file.name
                try:
                    if dest_file.resolve() != p_file.resolve():
                        shutil.copy2(p_file, dest_file)
                except Exception:
                    pass
                staged_set.add(p_file.name)
                packs_staged.append(p_file.name)

        # Manifest check if present in s_dir
        manifest_file = s_dir / "manifest.json"
        if manifest_file.is_file():
            try:
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                packs_dict = manifest_data.get("packs", {})
                has_matching_pack = False
                for pid, pinfo in packs_dict.items():
                    p_reg = str(pinfo.get("region_code", "")).lower()
                    if p_reg in code_tokens or any(t in pid.lower() for t in code_tokens):
                        has_matching_pack = True
                        p_ver = pinfo.get("pack_version", "1.0.0")
                        for cand_name in [f"{pid}-{p_ver}.sqlite.gz", f"{pid}.sqlite.gz", f"towers-{p_reg}-{p_ver}.sqlite.gz"]:
                            cand_path = s_dir / cand_name
                            if cand_path.is_file() and cand_name not in staged_set:
                                dest_f = packs_dest_dir / cand_name
                                try:
                                    if dest_f.resolve() != cand_path.resolve():
                                        shutil.copy2(cand_path, dest_f)
                                except Exception:
                                    pass
                                staged_set.add(cand_name)
                                packs_staged.append(cand_name)
                if has_matching_pack and "manifest.json" not in staged_set:
                    dest_manifest = packs_dest_dir / "manifest.json"
                    try:
                        if dest_manifest.resolve() != manifest_file.resolve():
                            shutil.copy2(manifest_file, dest_manifest)
                    except Exception:
                        pass
                    staged_set.add("manifest.json")
                    packs_staged.append("manifest.json")
            except Exception:
                pass

    return Result.success(
        {
            "state_code": state_code.upper(),
            "dry_run": False,
            "output_dir": str(output_path),
            "buffer_km": buffer_km,
            "min_zoom": min_zoom,
            "max_zoom": max_zoom,
            "include_dem": include_dem,
            "bounds": bounds.model_dump(),
            "estimates": estimates,
            "total_tiles": estimates["total_tiles"],
            "tiles_written": tiles_written,
            "mbtiles_path": str(mbtiles_path),
            "mesh_db_path": str(mesh_db_path),
            "dem_tiles_copied": len(copied_dem),
            "dem_dir": str(dem_dir) if include_dem else None,
            "required_hgt_tiles": required_hgt_tiles,
            "packs_staged": packs_staged,
        }
    )
