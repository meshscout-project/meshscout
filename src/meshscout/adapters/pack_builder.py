"""CI Regional Data Pack Builder for MeshScout (TASK-1135).

Coordinates multi-source data ingestion (FCC ASR, ISED SMS, Civic Infrastructure),
compilation into per-region SQLite archives, and cryptographic manifest generation.
Supports hermetic, zero-network generation via local offline test fixtures.
"""

from __future__ import annotations

import importlib.resources
import json
import logging
import math
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Union
import zipfile

from meshscout.adapters.source_fetch import load_source_catalog
from meshscout.adapters.tower_ingest import ingest_tower_source
from meshscout.core.packs import (
    PackManifest,
    PackSourceInfo,
    RegionPackInfo,
    build_pack_manifest,
    export_region_pack,
)
from meshscout.core.tower_registry import UnifiedTowerRegistry

logger = logging.getLogger(__name__)

_DEFAULT_PACK_FLOORS_JSON = Path(__file__).resolve().parent.parent / "data" / "pack_floors.json"


class PackBuildError(Exception):
    """Raised when regional pack building fails due to fetch, parse, or quality floor violations."""


def get_pack_floors_path() -> Path:
    """Resolve the filesystem path to pack_floors.json."""
    try:
        data_path = importlib.resources.files("meshscout").joinpath("data", "pack_floors.json")
        resolved = Path(str(data_path))
        if resolved.exists():
            return resolved
    except Exception:
        pass
    return _DEFAULT_PACK_FLOORS_JSON


def load_pack_floors(floors_path: Optional[Union[str, Path]] = None) -> Dict[str, int]:
    """Load regional pack tower count floors.

    Args:
        floors_path: Optional custom path to pack_floors.json.

    Returns:
        Dictionary mapping region code to minimum site count floor.
    """
    path = Path(floors_path) if floors_path is not None else get_pack_floors_path()
    if not path.exists():
        raise FileNotFoundError(f"Pack floors config not found at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k.upper(): int(v) for k, v in data.items()}


def _find_fixture(filename: str) -> Path:
    """Locate a sample fixture file across standard project locations."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / filename,
        Path.cwd() / "fixtures" / filename,
        Path.cwd() / "MeshScout" / "fixtures" / filename,
        Path(__file__).resolve().parent.parent / "fixtures" / filename,
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(f"Fixture '{filename}' not found. Searched paths: {candidates}")


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract zip archive safely preventing Zip Slip directory traversal vulnerabilities."""
    target_resolved = target_dir.resolve()
    for member in zf.infolist():
        member_path = target_dir / member.filename
        try:
            resolved_dest = member_path.resolve()
        except Exception as exc:
            raise ValueError(f"Illegal zip member path: {member.filename}") from exc
        if not resolved_dest.is_relative_to(target_resolved):
            raise ValueError(f"Zip Slip path traversal attempt detected: {member.filename}")
    zf.extractall(target_dir)


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two coordinates in meters."""
    earth_radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return earth_radius_m * c


def is_spatially_suppressed(
    candidate: Any,
    registry: UnifiedTowerRegistry,
    radius_m: float = 50.0,
) -> bool:
    """Check if an authoritative fcc_asr or ised_sms tower exists within radius_m.

    Uses a RegionalBounds query on registry.query_towers() followed by exact geodetic distance.
    If an FCC or ISED tower is within radius_m, returns True (candidate should be dropped).
    """
    from meshscout.core.contracts import RegionalBounds

    lat = candidate.location.lat
    lon = candidate.location.lon

    earth_radius_m = 6371000.0
    # Safe bounding box buffer (~1.5x)
    delta_lat = (radius_m / earth_radius_m) * (180.0 / math.pi) * 1.5
    cos_lat = max(abs(math.cos(math.radians(lat))), 0.01)
    delta_lon = (radius_m / (earth_radius_m * cos_lat)) * (180.0 / math.pi) * 1.5

    min_lat = max(-89.9, lat - delta_lat)
    max_lat = min(89.9, lat + delta_lat)
    min_lon = max(-179.9, lon - delta_lon)
    max_lon = min(179.9, lon + delta_lon)

    search_bounds = RegionalBounds(
        name="spatial_suppression_check",
        min_lat=round(min_lat, 6),
        max_lat=round(max_lat, 6),
        min_lon=round(min_lon, 6),
        max_lon=round(max_lon, 6),
    )

    nearby = registry.query_towers(bounds=search_bounds, limit=0)
    if not nearby:
        return False

    cursor = registry.conn.cursor()
    for existing in nearby:
        dist = haversine_distance_m(lat, lon, existing.location.lat, existing.location.lon)
        if dist <= radius_m:
            row = cursor.execute(
                "SELECT source_dataset FROM towers WHERE site_id = ?",
                (existing.site_id,),
            ).fetchone()
            if row:
                src = row[0] if isinstance(row, (tuple, list)) else row["source_dataset"]
                if src in ("fcc_asr", "ised_sms"):
                    return True
    return False


def ingest_civic_candidates_with_suppression(
    registry: UnifiedTowerRegistry,
    candidates: Sequence[Any],
    region_code: Optional[str] = None,
    suppression_radius_m: float = 50.0,
) -> int:
    """Ingest civic candidates into registry, dropping any candidate within suppression_radius_m of an FCC or ISED tower.

    Preserves ODbL isolation: does not touch or copy attributes to existing FCC/ISED sites.
    """
    from meshscout.core.contracts import SiteType

    inserted = 0
    for cand in candidates:
        if is_spatially_suppressed(cand, registry, radius_m=suppression_radius_m):
            logger.debug(
                "Spatially suppressed civic candidate %s (%s) within %.1fm of existing FCC/ISED tower",
                cand.site_id,
                cand.name,
                suppression_radius_m,
            )
            continue

        owner = "Civic / Public Safety"
        owner_cat = "civic_public_safety"
        if cand.site_type == SiteType.SILO:
            owner_cat = "coop_utility_ag"

        if cand.notes:
            for part in cand.notes.split(" | "):
                if part.startswith("Owner: ") or part.startswith("Licensee: "):
                    owner = part.split(": ", 1)[1].strip()
                elif part.startswith("Owner Category: "):
                    owner_cat = part.split(": ", 1)[1].strip()

        reg = region_code
        if not reg:
            parts = cand.site_id.split("-")
            if len(parts) >= 2 and len(parts[1]) in (2, 5):
                reg = parts[1]

        registry.upsert_tower(
            site=cand,
            owner=owner,
            owner_category=owner_cat,
            source_dataset="civic",
            region_code=reg,
            source_record_id=cand.site_id,
        )
        inserted += 1

    return inserted


def ingest_cached_civic_geojson(
    registry: UnifiedTowerRegistry,
    geojson_path: Union[str, Path],
    region_code: Optional[str] = None,
    suppression_radius_m: float = 50.0,
) -> int:
    """Ingest a cached civic GeoJSON file into the registry with spatial suppression."""
    from meshscout.adapters.civic_highsites import harvest_civic_features_from_geojson

    p = Path(geojson_path)
    if not p.is_file():
        raise FileNotFoundError(f"Civic GeoJSON file not found: {p}")

    candidates = harvest_civic_features_from_geojson(p)
    return ingest_civic_candidates_with_suppression(
        registry=registry,
        candidates=candidates,
        region_code=region_code,
        suppression_radius_m=suppression_radius_m,
    )


def _ingest_live_sources(
    registry: UnifiedTowerRegistry,
    civic_cache_dir: Optional[Union[str, Path]] = None,
) -> None:
    """Attempt live download and ingest of FCC, ISED, and Civic data; fail closed if sources fail."""
    from meshscout.adapters.source_fetch import fetch_source
    from meshscout.adapters.civic_highsites import load_civic_highsites

    # 1. FCC ASR
    try:
        fcc_file = fetch_source("fcc_asr")
        if fcc_file.suffix.lower() == ".zip":
            with zipfile.ZipFile(fcc_file, "r") as zf:
                extract_dir = fcc_file.parent / "fcc_extracted"
                extract_dir.mkdir(parents=True, exist_ok=True)
                _safe_extract_zip(zf, extract_dir)
                dat_files = [p for p in extract_dir.rglob("*") if p.suffix.lower() == ".dat"]
                if dat_files:
                    ingest_tower_source(registry, "fcc_asr", dat_files[0])
        else:
            ingest_tower_source(registry, "fcc_asr", fcc_file)
    except Exception as exc:
        raise PackBuildError(f"Failed to fetch or ingest live FCC ASR source: {exc}") from exc

    # 2. ISED SMS
    try:
        ised_file = fetch_source("ised_sms")
        if ised_file.suffix.lower() == ".zip":
            with zipfile.ZipFile(ised_file, "r") as zf:
                extract_dir = ised_file.parent / "ised_extracted"
                extract_dir.mkdir(parents=True, exist_ok=True)
                _safe_extract_zip(zf, extract_dir)
                csv_files = [p for p in extract_dir.rglob("*") if p.suffix.lower() == ".csv"]
                if csv_files:
                    ingest_tower_source(registry, "ised_sms", csv_files[0])
        else:
            ingest_tower_source(registry, "ised_sms", ised_file)
    except Exception as exc:
        raise PackBuildError(f"Failed to fetch or ingest live ISED SMS source: {exc}") from exc

    # 3. Civic
    try:
        cache_dir = (
            Path(civic_cache_dir)
            if civic_cache_dir is not None
            else Path.home() / ".meshscout" / "cache" / "overpass"
        )
        ingested_cached = False
        if cache_dir.is_dir():
            for candidate_file in sorted(cache_dir.glob("*.geojson")):
                if candidate_file.is_file():
                    ingest_cached_civic_geojson(registry, candidate_file)
                    ingested_cached = True

        if not ingested_cached:
            civic_fix = _find_fixture("civic_highsites_catalog.json")
            civic_candidates = load_civic_highsites(catalog_path=civic_fix)
            ingest_civic_candidates_with_suppression(registry, civic_candidates)
    except Exception as exc:
        raise PackBuildError(f"Failed to ingest civic high sites source: {exc}") from exc


def build_region_packs(
    regions: Sequence[str],
    out_dir: Union[str, Path],
    offline_fixtures: bool = False,
    base_url: Optional[str] = None,
    pack_version: str = "1.0.0",
    floors_path: Optional[Union[str, Path]] = None,
    civic_cache_dir: Optional[Union[str, Path]] = None,
) -> PackManifest:
    """Build regional tower data packs and manifest index.

    Ingests tower datasets (from offline fixtures or live authoritative sources),
    exports individual regional SQLite pack archives, and writes a manifest.json.

    Args:
        regions: Sequence of region codes to export (e.g. ['VT', 'QC', 'NH']).
        out_dir: Directory where archives and manifest.json will be written.
        offline_fixtures: If True, uses local sample fixtures without making any network calls.
        base_url: Optional remote URL prefix to populate download URLs in manifest.
        pack_version: Semantic release version string for generated packs.
        floors_path: Optional custom path to pack_floors.json for live mode validation.
        civic_cache_dir: Optional path to directory containing cached civic GeoJSON files.

    Returns:
        PackManifest containing metadata for all built regional packs.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    from meshscout.adapters.regions import NORTH_AMERICA_CATALOG
    from meshscout.core.contracts import (
        AccessDifficulty,
        Coordinate,
        SiteCandidate,
        SiteType,
    )

    if not regions or any(r.strip().upper() in ("ALL", "NORTH_AMERICA", "*") for r in regions):
        regions_list = list(NORTH_AMERICA_CATALOG.keys())
    else:
        regions_list = [r.strip().upper() for r in regions]

    with tempfile.TemporaryDirectory() as td:
        staging_db = Path(td) / "staging_packs.db"
        registry = UnifiedTowerRegistry(db_path=staging_db)
        try:
            if offline_fixtures:
                # STRICT ZERO NETWORK CALLS: ingest local fixtures
                for fix_name in [
                    "fcc_asr_vt_sample.dat",
                    "ised_sms_sample.csv",
                ]:
                    try:
                        fix_path = _find_fixture(fix_name)
                        if fix_path.exists():
                            src = "fcc_asr" if "fcc" in fix_name else "ised_sms"
                            ingest_tower_source(registry, src, fix_path)
                    except Exception as exc:
                        logger.warning("Could not ingest fixture %s: %s", fix_name, exc)

                # Ingest civic data: prefer cached GeoJSON if provided, else fallback to fixture catalog
                ingested_cached_civic = False
                if civic_cache_dir is not None:
                    c_dir = Path(civic_cache_dir)
                    for reg_code in regions_list:
                        for fname in (
                            f"{reg_code.lower()}_civic.geojson",
                            f"civic_{reg_code.lower()}.geojson",
                            f"{reg_code.lower()}.geojson",
                        ):
                            cand_file = c_dir / fname
                            if cand_file.is_file():
                                ingest_cached_civic_geojson(registry, cand_file, region_code=reg_code)
                                ingested_cached_civic = True
                                break

                if not ingested_cached_civic:
                    try:
                        fix_path = _find_fixture("civic_highsites_catalog.json")
                        if fix_path.exists():
                            from meshscout.adapters.civic_highsites import load_civic_highsites
                            civic_cands = load_civic_highsites(catalog_path=fix_path)
                            ingest_civic_candidates_with_suppression(registry, civic_cands)
                    except Exception as exc:
                        logger.warning("Could not ingest fixture civic_highsites_catalog.json: %s", exc)

                # Ingest regional pilot sample fixtures (ME, QC, NH, NY)
                for reg_code, fix_file in [
                    ("ME", "me_high_sites_sample.json"),
                    ("CA_QC", "qc_high_sites_sample.json"),
                    ("NH", "nh_high_sites_sample.json"),
                    ("NY", "ny_adirondack_champlain_sample.json"),
                ]:
                    try:
                        p = _find_fixture(fix_file)
                        if p.exists():
                            raw_items = json.loads(p.read_text(encoding="utf-8"))
                            for item in raw_items:
                                loc = item.get("location", {})
                                raw_type = item.get("site_type", "communications_tower")
                                try:
                                    s_type = SiteType(raw_type)
                                except ValueError:
                                    s_type = (
                                        SiteType.MOUNTAIN_PEAK
                                        if "summit" in raw_type
                                        else SiteType.COMMUNICATIONS_TOWER
                                    )
                                try:
                                    diff = AccessDifficulty(item.get("access_difficulty", "drive_up"))
                                except ValueError:
                                    diff = AccessDifficulty.DRIVE_UP
                                cand = SiteCandidate(
                                    site_id=item.get("site_id", f"{reg_code}-SEED-{loc.get('lat', 0)}"),
                                    name=item.get("name", f"{reg_code} Highsite"),
                                    location=Coordinate(
                                        lat=float(loc.get("lat", 0.0)),
                                        lon=float(loc.get("lon", 0.0)),
                                        elevation_m=float(loc.get("elevation_m", 500.0)),
                                    ),
                                    site_type=s_type,
                                    mast_height_m=float(item.get("mast_height_m", 25.0)),
                                    access_difficulty=diff,
                                    has_grid_power=bool(item.get("has_grid_power", True)),
                                    solar_exposure_pct=float(item.get("solar_exposure_pct", 85.0)),
                                    notes=item.get("notes", ""),
                                    source_url=item.get("source_url", ""),
                                )
                                registry.upsert_tower(cand, region_code=reg_code, source_dataset="regional_sample")
                    except Exception as exc:
                        logger.warning("Could not ingest regional fixture %s: %s", fix_file, exc)

                # For every requested region that lacks towers, generate a primary anchor node
                for reg_code in regions_list:
                    existing = registry.query_towers(region_code=reg_code)
                    if not existing and reg_code in NORTH_AMERICA_CATALOG:
                        info = NORTH_AMERICA_CATALOG[reg_code]
                        b = info.bounds
                        c_lat = round((b.min_lat + b.max_lat) / 2.0, 4)
                        c_lon = round((b.min_lon + b.max_lon) / 2.0, 4)
                        anchor_site = SiteCandidate(
                            site_id=f"CIVIC-{reg_code}-ANCHOR-01",
                            name=f"{info.name} Primary Regional Highsite",
                            location=Coordinate(lat=c_lat, lon=c_lon, elevation_m=650.0),
                            site_type=SiteType.COMMUNICATIONS_TOWER,
                            mast_height_m=35.0,
                            access_difficulty=AccessDifficulty.DRIVE_UP,
                            has_grid_power=True,
                            solar_exposure_pct=90.0,
                            notes=f"Statewide/provincial backbone repeater anchor for {info.name}.",
                            source_url="",
                        )
                        registry.upsert_tower(anchor_site, region_code=reg_code, source_dataset="synthetic_anchor")
            else:
                if civic_cache_dir is not None:
                    _ingest_live_sources(registry, civic_cache_dir=civic_cache_dir)
                else:
                    _ingest_live_sources(registry)

            # Build metadata sources attribution
            try:
                catalog = load_source_catalog()
                fcc_cat = catalog.get("fcc_asr", {})
                ised_cat = catalog.get("ised_sms", {})
                civic_cat = catalog.get("civic_osm", {})
            except Exception:
                fcc_cat, ised_cat, civic_cat = {}, {}, {}

            source_infos = [
                PackSourceInfo(
                    dataset="fcc_asr",
                    license=fcc_cat.get("license", "Public Domain"),
                    attribution=fcc_cat.get("attribution", "Federal Communications Commission (FCC)"),
                    source_url=fcc_cat.get("url", ""),
                ),
                PackSourceInfo(
                    dataset="ised_sms",
                    license=ised_cat.get("license", "Open Government Licence - Canada"),
                    attribution=ised_cat.get("attribution", "Innovation, Science and Economic Development Canada"),
                    source_url=ised_cat.get("url", ""),
                ),
                PackSourceInfo(
                    dataset="civic_osm",
                    license=civic_cat.get("license", "ODbL 1.0"),
                    attribution=civic_cat.get("attribution", "© OpenStreetMap contributors"),
                    source_url=civic_cat.get("url", ""),
                ),
            ]

            base_sources = [
                s for s in source_infos if s.dataset not in ("civic", "civic_osm", "osm")
            ]
            civic_sources = [
                s for s in source_infos if s.dataset in ("civic", "civic_osm", "osm")
            ]
            if not civic_sources:
                civic_sources = [
                    PackSourceInfo(
                        dataset="civic_osm",
                        license=civic_cat.get("license", "ODbL 1.0"),
                        attribution=civic_cat.get("attribution", "© OpenStreetMap contributors (ODbL 1.0)"),
                        source_url=civic_cat.get("url", ""),
                    )
                ]

            floors: Dict[str, int] = {}
            if not offline_fixtures:
                floors = load_pack_floors(floors_path)

            pack_infos: List[RegionPackInfo] = []
            for reg in regions_list:
                # 1. Base regional pack (Public Domain / Open Government Licence, strictly NO ODbL rows)
                pack_info = export_region_pack(
                    registry=registry,
                    region_code=reg,
                    out_dir=out_path,
                    pack_version=pack_version,
                    sources=base_sources,
                    exclude_datasets=["civic", "civic_osm", "osm"],
                )

                if not offline_fixtures:
                    min_floor = floors.get(reg.upper(), 50)
                    if pack_info.row_count < min_floor:
                        raise PackBuildError(
                            f"Region pack '{reg}' contains {pack_info.row_count} sites, "
                            f"failing minimum plausibility floor of {min_floor} sites."
                        )

                if base_url:
                    filename = f"towers-{reg.lower()}-{pack_info.pack_version}.sqlite.gz"
                    pack_info.url = f"{base_url.rstrip('/')}/{filename}"

                pack_infos.append(pack_info)

                # Maintain us-<region>-1.0.0.sqlite.gz companion for US regions
                base_archive = out_path / f"towers-{reg.lower()}-{pack_info.pack_version}.sqlite.gz"
                us_file = out_path / f"us-{reg.lower()}-{pack_info.pack_version}.sqlite.gz"
                if base_archive.is_file() and not us_file.exists():
                    import shutil
                    shutil.copy2(base_archive, us_file)

                # 2. Civic Infrastructure Overlay pack carrying ODbL-1.0 license metadata
                cursor = registry.conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM towers
                    WHERE (UPPER(COALESCE(region_code, '')) = UPPER(?)
                       OR UPPER(COALESCE(region_code, '')) = UPPER(?))
                      AND LOWER(source_dataset) IN ('civic', 'civic_osm', 'osm');
                    """,
                    (reg, f"US-{reg}"),
                )
                civic_count_row = cursor.fetchone()
                civic_count = civic_count_row[0] if civic_count_row else 0

                if civic_count > 0:
                    overlay_pack_id = f"towers-{reg.lower()}-civic-osm"
                    overlay_pack_info = export_region_pack(
                        registry=registry,
                        region_code=reg,
                        out_dir=out_path,
                        pack_version=pack_version,
                        sources=civic_sources,
                        pack_id=overlay_pack_id,
                        include_datasets=["civic", "civic_osm", "osm"],
                    )
                    if base_url:
                        overlay_filename = f"{overlay_pack_id}-{overlay_pack_info.pack_version}.sqlite.gz"
                        overlay_pack_info.url = f"{base_url.rstrip('/')}/{overlay_filename}"

                    pack_infos.append(overlay_pack_info)

                    # Maintain us-<region>-civic-osm companion for US regions
                    overlay_archive = out_path / f"{overlay_pack_id}-{pack_version}.sqlite.gz"
                    us_overlay_file = out_path / f"us-{reg.lower()}-civic-osm-{pack_version}.sqlite.gz"
                    if overlay_archive.is_file() and not us_overlay_file.exists():
                        import shutil
                        shutil.copy2(overlay_archive, us_overlay_file)

            manifest = build_pack_manifest(pack_infos)
            manifest_path = out_path / "manifest.json"
            manifest.write_json(manifest_path)
            return manifest
        finally:
            registry.close()


__all__ = [
    "PackBuildError",
    "_safe_extract_zip",
    "build_region_packs",
    "get_pack_floors_path",
    "haversine_distance_m",
    "ingest_cached_civic_geojson",
    "ingest_civic_candidates_with_suppression",
    "is_spatially_suppressed",
    "load_pack_floors",
]
