"""National and Multi-Source Tower Ingest Pipeline for MeshScout.

Coordinates extraction, jurisdiction normalization, geographic boundary resolution,
friction tier classification, and bulk database upsert across FCC ASR bulk,
Canadian ISED SMS, and OpenStreetMap/Civic infrastructure catalogs.
"""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union
import zipfile

from meshscout.adapters.civic_highsites import (
    harvest_civic_features_from_geojson,
    load_civic_highsites,
)
from meshscout.adapters.fcc_asr_bulk import (
    parse_fcc_asr_bulk,
    parse_fcc_asr_directory,
)
from meshscout.adapters.ised_sms import parse_ised_sms_records
from meshscout.adapters.regions import (
    detect_region_code,
    normalize_jurisdiction,
)
from meshscout.core.contracts import SiteCandidate, SiteType
from meshscout.core.tower_registry import (
    UnifiedTowerRegistry,
    resolve_friction_tier,
)

logger = logging.getLogger(__name__)


class FrictionTierCounts(dict):
    """Dictionary supporting friction tier lookup by string name or integer tier."""

    def __getitem__(self, key: Any) -> int:
        if key in (1, "1", "TIER_1_CIVIC"):
            return super().get("tier_1_civic", 0)
        if key in (2, "2", "TIER_2_AGRICULTURAL"):
            return super().get("tier_2_agricultural", 0)
        if key in (3, "3", "TIER_3_COMMERCIAL"):
            return super().get("tier_3_commercial", 0)
        return super().__getitem__(key)

    def get(self, key: Any, default: Any = 0) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


def _dir_has_table(dir_path: Path, table_name: str) -> bool:
    """Check case-insensitively whether a directory contains a specific table file."""
    try:
        t_low = table_name.lower()
        return any(p.name.lower() == t_low for p in dir_path.iterdir())
    except (OSError, NotADirectoryError):
        return False


def ingest_tower_source(
    registry: UnifiedTowerRegistry,
    source: str,
    path: Union[str, Path],
    region_code: Optional[str] = None,
    pack_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Ingest, normalize, and register tower sites from a supported source dataset.

    Args:
        registry: Initialized UnifiedTowerRegistry instance.
        source: Source dataset key ('fcc_asr', 'ised_sms', or 'civic').
        path: Path to the local raw source dataset file.
        region_code: Optional administrative region filter (e.g. 'VT', 'CA_QC', 'NY').
        pack_id: Optional pack identifier for provenance tracking in tower_packs.

    Returns:
        Summary dictionary containing:
            ok: bool (True on success)
            source: str (the source input tag)
            ingested_count: int (total sites inserted/updated)
            by_region: Dict[str, int] (count of ingested sites by region code)
            by_friction_tier: Dict[str, int] (count of ingested sites by friction tier)

    Raises:
        ValueError: If source is unsupported.
        FileNotFoundError: If the source path does not exist.
    """
    clean_src = source.strip().lower()
    if clean_src in ("fcc_asr", "fcc"):
        canonical_source = "fcc_asr"
        default_country = "US"
    elif clean_src in ("ised_sms", "ised"):
        canonical_source = "ised_sms"
        default_country = "CA"
    elif clean_src in ("civic", "civic_osm", "osm"):
        canonical_source = "civic"
        default_country = "US"
    else:
        raise ValueError(
            f"Unsupported tower source '{source}'. Supported sources: ('fcc_asr', 'ised_sms', 'civic')"
        )

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Tower source dataset not found: {file_path}")

    temp_dir_obj: Optional[tempfile.TemporaryDirectory] = None
    try:
        if file_path.is_file() and file_path.suffix.lower() == ".zip":
            from meshscout.adapters.pack_builder import _safe_extract_zip

            temp_dir_obj = tempfile.TemporaryDirectory()
            extract_dir = Path(temp_dir_obj.name)
            with zipfile.ZipFile(file_path, "r") as zf:
                _safe_extract_zip(zf, extract_dir)
            file_path = extract_dir
            if canonical_source == "ised_sms":
                csv_files = [p for p in extract_dir.rglob("*") if p.suffix.lower() == ".csv"]
                if csv_files:
                    file_path = csv_files[0]
            elif canonical_source == "fcc_asr":
                ra_files = [p for p in extract_dir.rglob("*") if p.name.lower() == "ra.dat"]
                if ra_files:
                    file_path = ra_files[0].parent

        # 1. Parse raw records with return_metadata=True
        records: List[Tuple[SiteCandidate, Dict[str, str]]] = []

        if canonical_source == "fcc_asr":
            if file_path.is_dir():
                records = list(parse_fcc_asr_directory(file_path, return_metadata=True))
            elif file_path.is_file() and (
                _dir_has_table(file_path.parent, "RA.dat") and _dir_has_table(file_path.parent, "CO.dat")
            ):
                records = list(parse_fcc_asr_directory(file_path.parent, return_metadata=True))
            else:
                raw_parsed = parse_fcc_asr_bulk(file_path, return_metadata=True)
                records = raw_parsed  # type: ignore[assignment]
        elif canonical_source == "ised_sms":
            raw_parsed = parse_ised_sms_records(file_path, return_metadata=True)
            records = raw_parsed  # type: ignore[assignment]
        elif canonical_source == "civic":
            if file_path.suffix.lower() == ".geojson" or "geojson" in file_path.name.lower():
                civic_candidates = harvest_civic_features_from_geojson(
                    file_path, site_type=SiteType.COMMUNICATIONS_TOWER
                )
            else:
                civic_candidates = load_civic_highsites(catalog_path=file_path)

            for cand in civic_candidates:
                jurisdiction = ""
                parts = cand.site_id.split("-")
                if len(parts) >= 2 and len(parts[1]) in (2, 5):
                    jurisdiction = parts[1]

                owner = "Civic/Public"
                owner_cat = "civic_public_safety"
                if cand.site_type == SiteType.SILO:
                    owner_cat = "coop_utility_ag"

                if cand.notes:
                    for part in cand.notes.split(" | "):
                        if part.startswith("Owner: ") or part.startswith("Licensee: "):
                            owner = part.split(": ", 1)[1].strip()
                        elif part.startswith("Owner Category: "):
                            owner_cat = part.split(": ", 1)[1].strip()

                records.append(
                    (
                        cand,
                        {
                            "jurisdiction": jurisdiction,
                            "owner": owner,
                            "owner_category": owner_cat,
                            "source_record_id": cand.site_id,
                        },
                    )
                )

        # 2. Resolve region codes and apply optional region filter
        target_region: Optional[str] = None
        if region_code:
            target_region = (
                normalize_jurisdiction("US", region_code)
                or normalize_jurisdiction("CA", region_code)
                or region_code.strip().upper()
            )

        sites_to_upsert: List[SiteCandidate] = []
        owner_categories: List[str] = []
        resolved_region_codes: List[str] = []
        source_record_ids: List[str] = []
        owners: List[str] = []

        by_region: Dict[str, int] = {}
        tier_counts: Dict[int, int] = {1: 0, 2: 0, 3: 0}

        for site, meta in records:
            raw_jur = meta.get("jurisdiction", "")
            owner_cat = meta.get("owner_category", "")
            owner_name = meta.get("owner", "")
            src_rec_id = meta.get("source_record_id", "")

            # Region resolution:
            # a. normalize_jurisdiction
            resolved_reg: Optional[str] = None
            if raw_jur:
                resolved_reg = normalize_jurisdiction(default_country, raw_jur)
                if resolved_reg is None and canonical_source == "civic":
                    resolved_reg = normalize_jurisdiction("CA", raw_jur)

            # b. detect_region_code fallback based on coordinates
            if resolved_reg is None:
                resolved_reg = detect_region_code(site.location)

            # c. target_region fallback if given
            if resolved_reg is None and target_region is not None:
                resolved_reg = target_region

            # Filter by region_code if filter was requested
            if target_region is not None and resolved_reg != target_region:
                continue

            # Classify friction tier
            tier = resolve_friction_tier(site.site_type, owner_cat)
            tier_int = int(tier.value if hasattr(tier, "value") else tier)

            sites_to_upsert.append(site)
            owner_categories.append(owner_cat)
            owners.append(owner_name)
            resolved_region_codes.append(resolved_reg or "")
            source_record_ids.append(src_rec_id)

            reg_key = resolved_reg or "UNKNOWN"
            by_region[reg_key] = by_region.get(reg_key, 0) + 1
            tier_counts[tier_int] = tier_counts.get(tier_int, 0) + 1

        # 3. Perform bulk database upsert
        total_ingested = registry.bulk_upsert_towers(
            sites=sites_to_upsert,
            source_dataset=canonical_source,
            owner_categories=owner_categories,
            region_codes=resolved_region_codes,
            source_record_ids=source_record_ids,
            owners=owners,
            pack_id=pack_id,
        )

        by_friction_tier = FrictionTierCounts(
            {
                "tier_1_civic": tier_counts.get(1, 0),
                "tier_2_agricultural": tier_counts.get(2, 0),
                "tier_3_commercial": tier_counts.get(3, 0),
                1: tier_counts.get(1, 0),
                2: tier_counts.get(2, 0),
                3: tier_counts.get(3, 0),
            }
        )

        return {
            "ok": True,
            "source": source,
            "ingested_count": total_ingested,
            "by_region": by_region,
            "by_friction_tier": by_friction_tier,
        }
    finally:
        if temp_dir_obj is not None:
            temp_dir_obj.cleanup()
