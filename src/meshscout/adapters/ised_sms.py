"""Canadian Innovation, Science and Economic Development (ISED) SMS Adapter.

Parses Canadian Spectrum Management System (SMS) records (CSV, TSV, or pipe-delimited),
converts geodetic coordinates to WGS84, categorizes structure types and ownership,
and constructs validated SiteCandidate records.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import itertools
from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, TextIO, Tuple, Union

from meshscout.adapters.fcc_asr import FEET_TO_METERS, dms_to_decimal
from meshscout.adapters.fcc_asr_bulk import classify_tower_ownership
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)


@dataclass
class _StationGroup:
    """Internal grouping accumulator for O(1) spatial station collapse."""

    prov: str
    lat: float
    lon: float
    elevation_m: float
    max_mast_height_m: float
    clean_id: str
    row_idx: int
    site_name: str
    struct_type_raw: str
    licensees: List[str]
    site_type: SiteType
    owner_cat: str


def classify_ised_structure_type(struct_desc: str) -> SiteType:
    """Classify Canadian ISED structure description or code into a SiteType.

    Supports English and French structure designations.
    """
    if not struct_desc:
        return SiteType.COMMUNICATIONS_TOWER

    token = struct_desc.strip().lower()

    # Water tower / Tank / Réservoir
    if any(k in token for k in ("water", "tank", "réservoir", "reservoir", "château d'eau", "chateau d'eau", "wt", "tk")):
        return SiteType.WATER_TOWER

    # Fire lookout / Tour de guet
    if any(k in token for k in ("fire", "lookout", "guet", "garde-feu", "tour de feu")):
        return SiteType.FIRE_LOOKOUT

    # Research / Observatory / Station météorologique
    if any(k in token for k in ("research", "recherche", "observat", "flux", "meteorolog", "météorolog", "met ")):
        return SiteType.RESEARCH_TOWER

    # Building / Rooftop / Toit / Bâtiment
    if any(k in token for k in ("building", "bâtiment", "batiment", "immeuble", "rooftop", "roof", "toit")):
        return SiteType.BUILDING_ROOFTOP

    # Silo
    if any(k in token for k in ("silo", "grain")):
        return SiteType.SILO

    # Communications Tower / Tour de télécom
    return SiteType.COMMUNICATIONS_TOWER


def _detect_delimiter(lines: Sequence[str]) -> str:
    """Detect CSV, TSV, or pipe delimiter from sample lines."""
    counts = {",": 0, "\t": 0, "|": 0, ";": 0}
    for line in lines[:25]:
        line_s = line.strip()
        if not line_s or line_s.startswith("#"):
            continue
        for delim in counts:
            counts[delim] += line_s.count(delim)
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _open_input_stream(
    content_or_path: Union[str, Path, TextIO],
) -> Tuple[TextIO, bool]:
    """Return an open text stream and a boolean indicating whether it should be closed."""
    if isinstance(content_or_path, Path):
        return open(content_or_path, "r", encoding="utf-8-sig", errors="replace"), True

    if isinstance(content_or_path, str):
        if "\n" not in content_or_path and "\r" not in content_or_path:
            try:
                p = Path(content_or_path)
                if p.is_file():
                    return open(p, "r", encoding="utf-8-sig", errors="replace"), True
            except OSError:
                pass
        return io.StringIO(content_or_path), True

    if hasattr(content_or_path, "read"):
        if hasattr(content_or_path, "seekable") and content_or_path.seekable():
            try:
                content_or_path.seek(0)
            except (OSError, io.UnsupportedOperation):
                pass
        return content_or_path, False

    return io.StringIO(str(content_or_path)), True


def parse_ised_sms_records(
    content_or_path: Union[str, Path, TextIO],
    bounds: Optional[RegionalBounds] = None,
    return_metadata: bool = False,
) -> Union[List[SiteCandidate], List[Tuple[SiteCandidate, Dict[str, str]]]]:
    """Parse Canadian ISED SMS records from CSV, TSV, or pipe-delimited stream/text/file.

    Streams rows directly without loading large files into memory. Supports:
    1. Headerless 61-column TAFL (TAFL_LTAF.csv) with spatial station collapse.
    2. Extract files with headers (e.g. Site_Data_Extract_FX.csv).
    3. Legacy positional CSV/TSV/pipe-delimited formats.

    Args:
        content_or_path: File path, string buffer, or text stream containing ISED SMS data.
        bounds: Optional RegionalBounds to filter results.
        return_metadata: If True, returns tuples of (SiteCandidate, metadata_dict).

    Returns:
        List of SiteCandidate instances, or list of (SiteCandidate, metadata) if return_metadata=True.
    """
    stream, should_close = _open_input_stream(content_or_path)

    try:
        sample_lines: List[str] = []
        for _ in range(25):
            line = stream.readline()
            if not line:
                break
            sample_lines.append(line)

        if not sample_lines:
            return []

        delim = _detect_delimiter(sample_lines)
        if hasattr(stream, "seekable") and stream.seekable():
            stream.seek(0)

        reader = csv.reader(stream, delimiter=delim)

        # Retrieve the first non-empty, non-comment row to determine format
        first_row: Optional[List[str]] = None
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            if row[0].strip().startswith("#"):
                continue
            first_row = [c.strip() for c in row]
            break

        if first_row is None:
            return []

        if first_row and first_row[0]:
            first_row[0] = first_row[0].lstrip("\ufeff")

        id_idx: Optional[int] = None
        licensee_idx: Optional[int] = None
        site_name_idx: Optional[int] = None
        lat_idx: Optional[int] = None
        lon_idx: Optional[int] = None
        height_idx: Optional[int] = None
        elev_idx: Optional[int] = None
        struct_type_idx: Optional[int] = None
        prov_idx: Optional[int] = None

        first_col_clean = first_row[0].strip().strip('"\'').upper()
        is_tafl = len(first_row) >= 55 and first_col_clean in ("TX", "RX", "TXRX")

        if is_tafl:
            # 61-column headerless TAFL_LTAF.csv format
            is_header = False
            id_idx = 2
            site_name_idx = 31
            prov_idx = 39
            lat_idx = 40
            lon_idx = 41
            elev_idx = 42
            height_idx = 43
            licensee_idx = 54
            struct_type_idx = None
        else:
            first_row_lower = [c.lower().replace("_", " ").replace("-", " ") for c in first_row]
            is_header = any(
                any(k in cell for k in ("licensee", "titulaire", "site", "latitude", "lat", "ban", "hauteur", "height", "station"))
                for cell in first_row_lower
            )

            if is_header:
                for idx, cell in enumerate(first_row_lower):
                    if id_idx is None and (
                        any(k in cell for k in ("site id", "station id", "identifiant", "numero", "numéro", "record id", "ban"))
                        or cell in ("id", "ban")
                    ):
                        id_idx = idx
                    elif licensee_idx is None and any(k in cell for k in ("licensee", "titulaire", "operator", "owner", "client", "compagnie", "company")):
                        licensee_idx = idx
                    elif site_name_idx is None and any(k in cell for k in ("site name", "location", "emplacement", "nom", "description", "address")):
                        site_name_idx = idx
                    elif lat_idx is None and any(k in cell for k in ("latitude", "lat")):
                        lat_idx = idx
                    elif lon_idx is None and any(k in cell for k in ("longitude", "long", "lon")):
                        lon_idx = idx
                    elif height_idx is None and any(k in cell for k in ("structure height", "height", "hauteur", "mast height")):
                        height_idx = idx
                    elif elev_idx is None and any(k in cell for k in ("elevation", "elev", "altitude", "amsl", "asml", "ground elev")):
                        elev_idx = idx
                    elif prov_idx is None and any(k in cell for k in ("province", "prov", "territory", "territoire", "jurisdiction", "state", "region")):
                        prov_idx = idx

                # Disambiguate structure type from station type / site type
                for idx, cell in enumerate(first_row_lower):
                    if any(k in cell for k in ("structure type", "type de structure", "struct type")):
                        struct_type_idx = idx
                        break
                if struct_type_idx is None:
                    for idx, cell in enumerate(first_row_lower):
                        if ("structure" in cell and "station" not in cell) or cell == "type":
                            struct_type_idx = idx
                            break

                # Fallback if BAN was matched as ID or licensee
                if licensee_idx is None:
                    for idx, cell in enumerate(first_row_lower):
                        if "ban" in cell:
                            licensee_idx = idx
                            break
            else:
                num_cols = len(first_row)
                if lat_idx is None or lon_idx is None:
                    if num_cols >= 7:
                        id_idx = 0 if id_idx is None else id_idx
                        licensee_idx = 1 if licensee_idx is None else licensee_idx
                        site_name_idx = 2 if site_name_idx is None else site_name_idx
                        lat_idx = 3 if lat_idx is None else lat_idx
                        lon_idx = 4 if lon_idx is None else lon_idx
                        height_idx = 5 if height_idx is None else height_idx
                        struct_type_idx = 6 if struct_type_idx is None else struct_type_idx
                    elif num_cols == 6:
                        licensee_idx = 0 if licensee_idx is None else licensee_idx
                        site_name_idx = 1 if site_name_idx is None else site_name_idx
                        lat_idx = 2 if lat_idx is None else lat_idx
                        lon_idx = 3 if lon_idx is None else lon_idx
                        height_idx = 4 if height_idx is None else height_idx
                        struct_type_idx = 5 if struct_type_idx is None else struct_type_idx
                    else:
                        licensee_idx = 0 if licensee_idx is None else licensee_idx
                        site_name_idx = 1 if site_name_idx is None else site_name_idx
                        lat_idx = 2 if lat_idx is None else lat_idx
                        lon_idx = 3 if lon_idx is None else lon_idx
                        height_idx = 4 if height_idx is None and num_cols > 4 else height_idx

        data_rows_iter = reader if is_header else itertools.chain([first_row], reader)

        collapsed_groups: Dict[Tuple[str, int, int], _StationGroup] = {}

        for row_idx, row in enumerate(data_rows_iter, start=1):
            if not row or not any(cell.strip() for cell in row):
                continue
            if row[0].strip().startswith("#"):
                continue

            if (lat_idx is not None and lat_idx >= len(row)) or (lon_idx is not None and lon_idx >= len(row)):
                continue

            raw_lat = row[lat_idx].strip() if lat_idx is not None and lat_idx < len(row) else ""
            raw_lon = row[lon_idx].strip() if lon_idx is not None and lon_idx < len(row) else ""

            if not raw_lat or not raw_lon:
                continue

            try:
                lat = dms_to_decimal(raw_lat)
                lon = dms_to_decimal(raw_lon)
            except (ValueError, TypeError):
                continue

            # In Canada/North America, longitude is West (negative in WGS84)
            if lon > 0 and 40.0 <= lat <= 85.0:
                lon = -abs(lon)

            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                continue

            # Ground elevation AMSL
            elev_m = 0.0
            if elev_idx is not None and elev_idx < len(row):
                elev_raw = row[elev_idx].strip()
                if elev_raw:
                    try:
                        cleaned_elev = re.sub(r"[^\d\.\-]", "", elev_raw)
                        if cleaned_elev:
                            elev_m = round(float(cleaned_elev), 2)
                    except ValueError:
                        elev_m = 0.0

            # Mast height AGL
            height_raw = row[height_idx].strip() if height_idx is not None and height_idx < len(row) else "5.0"
            try:
                cleaned_num = re.sub(r"[^\d\.\-]", "", height_raw)
                val = float(cleaned_num) if cleaned_num else 5.0
                if "ft" in height_raw.lower() or "feet" in height_raw.lower():
                    mast_height_m = max(0.0, round(val * FEET_TO_METERS, 2))
                else:
                    mast_height_m = max(0.0, round(val, 2))
                if mast_height_m == 0.0:
                    mast_height_m = 5.0
            except ValueError:
                mast_height_m = 5.0

            coord = Coordinate(lat=lat, lon=lon, elevation_m=elev_m)

            # Apply RegionalBounds filter if requested
            if bounds is not None and not bounds.contains(coord):
                continue

            licensee = row[licensee_idx].strip() if licensee_idx is not None and licensee_idx < len(row) else ""
            if licensee:
                licensee = re.sub(r"\s+", " ", licensee.strip().strip('"\''))

            site_name = row[site_name_idx].strip() if site_name_idx is not None and site_name_idx < len(row) else ""
            if site_name:
                site_name = re.sub(r"\s+", " ", site_name.strip().strip('"\''))

            struct_type_raw = row[struct_type_idx].strip() if struct_type_idx is not None and struct_type_idx < len(row) else "Tower"
            prov = row[prov_idx].strip().upper() if prov_idx is not None and prov_idx < len(row) else ""

            # ID extraction
            raw_id = ""
            if id_idx is not None and id_idx < len(row):
                raw_id = row[id_idx].strip()
            if not raw_id:
                if licensee and (licensee.isdigit() or (len(licensee) <= 10 and "-" in licensee)):
                    raw_id = licensee
                else:
                    raw_id = f"{row_idx:05d}"

            clean_id = re.sub(r"[^A-Za-z0-9_-]", "", raw_id)
            if clean_id.upper().startswith("ISED_"):
                clean_id = clean_id[5:]
            if not clean_id:
                clean_id = f"{row_idx:05d}"

            # O(1) spatial station collapse using 1-arcsecond spatial grid key
            grid_key = (prov, round(lat * 3600), round(lon * 3600))

            if grid_key not in collapsed_groups:
                site_type = classify_ised_structure_type(struct_type_raw)
                owner_cat = classify_tower_ownership(licensee, notes=f"{struct_type_raw} {site_name}")
                group = _StationGroup(
                    prov=prov,
                    lat=lat,
                    lon=lon,
                    elevation_m=elev_m,
                    max_mast_height_m=mast_height_m,
                    clean_id=clean_id,
                    row_idx=row_idx,
                    site_name=site_name,
                    struct_type_raw=struct_type_raw,
                    licensees=[licensee] if licensee else [],
                    site_type=site_type,
                    owner_cat=owner_cat,
                )
                collapsed_groups[grid_key] = group
            else:
                group = collapsed_groups[grid_key]
                if mast_height_m > group.max_mast_height_m:
                    group.max_mast_height_m = mast_height_m
                if elev_m > group.elevation_m:
                    group.elevation_m = elev_m
                if licensee and licensee not in group.licensees and len(group.licensees) < 5:
                    group.licensees.append(licensee)
                if not group.site_name and site_name:
                    group.site_name = site_name
                if group.struct_type_raw in ("Tower", "") and struct_type_raw not in ("Tower", ""):
                    group.struct_type_raw = struct_type_raw
                    group.site_type = classify_ised_structure_type(struct_type_raw)
                if licensee:
                    group.owner_cat = classify_tower_ownership(
                        ", ".join(group.licensees),
                        notes=f"{group.struct_type_raw} {group.site_name}",
                    )

        candidates: List[SiteCandidate] = []
        candidates_with_meta: List[Tuple[SiteCandidate, Dict[str, str]]] = []
        seen_ids: set[str] = set()

        for group in collapsed_groups.values():
            coord = Coordinate(lat=group.lat, lon=group.lon, elevation_m=group.elevation_m)

            site_id = f"ISED_{group.clean_id}"
            if site_id in seen_ids:
                site_id = f"{site_id}_{group.row_idx}"
            seen_ids.add(site_id)

            primary_licensee = group.licensees[0] if group.licensees else ""
            if primary_licensee and group.site_name:
                name = f"{primary_licensee} - {group.site_name}"
            elif group.site_name:
                name = f"{group.site_name} (ISED {group.clean_id})"
            elif primary_licensee:
                name = f"{primary_licensee} (ISED {group.clean_id})"
            else:
                name = f"ISED Tower {group.clean_id}"

            notes_parts = [
                f"ISED SMS: {group.clean_id}",
            ]
            if group.licensees:
                if len(group.licensees) == 1:
                    notes_parts.append(f"Licensee: {group.licensees[0]}")
                else:
                    notes_parts.append(f"Licensees: {', '.join(group.licensees)}")
            notes_parts.append(f"Owner Category: {group.owner_cat}")
            notes_parts.append(f"Structure: {group.struct_type_raw}")
            notes_parts.append(f"Height: {group.max_mast_height_m:.1f} m")
            if group.elevation_m > 0:
                notes_parts.append(f"Elevation: {group.elevation_m:.1f} m")
            if group.site_name:
                notes_parts.append(f"Location: {group.site_name}")

            candidate = SiteCandidate(
                site_id=site_id,
                name=name,
                location=coord,
                site_type=group.site_type,
                mast_height_m=group.max_mast_height_m,
                has_grid_power=True,
                solar_exposure_pct=95.0,
                access_difficulty=AccessDifficulty.DRIVE_UP,
                notes=" | ".join(notes_parts),
            )
            if return_metadata:
                meta: Dict[str, str] = {
                    "jurisdiction": group.prov,
                    "owner": ", ".join(group.licensees) if group.licensees else "",
                    "owner_category": group.owner_cat,
                    "source_record_id": group.clean_id,
                }
                candidates_with_meta.append((candidate, meta))
            else:
                candidates.append(candidate)

        return candidates_with_meta if return_metadata else candidates
    finally:
        if should_close:
            stream.close()
