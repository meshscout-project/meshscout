"""FCC Antenna Structure Registration (ASR) Bulk Adapter.

Parses FCC ASR bulk database files and exports (ANT.dat, OWN.dat, CO.dat, EN.dat, RA.dat),
classifies tower ownership categories and structure types, converts coordinates to WGS84,
and produces SiteCandidate records for regional mesh network planning.
"""

from __future__ import annotations

from enum import Enum
import functools
from pathlib import Path
import re
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

from meshscout.adapters.fcc_asr import FEET_TO_METERS, dms_to_decimal
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)


class OwnerCategory(str, Enum):
    """Categorization of tower infrastructure ownership."""
    CIVIC_PUBLIC_SAFETY = "civic_public_safety"
    COOP_UTILITY_AG = "coop_utility_ag"
    COMMERCIAL_CARRIER = "commercial_carrier"
    UNKNOWN = "unknown"


# Keyword regex patterns for ownership classification
_CIVIC_PATTERNS = [
    r"\bpolice\b",
    r"\bfire\b",
    r"\bsheriff\b",
    r"\btown of\b",
    r"\bcity of\b",
    r"\bvillage of\b",
    r"\bcounty of\b",
    r"\bdepartment\b",
    r"\bdept\b",
    r"\bpublic safety\b",
    r"\bstate of\b",
    r"\buniversity\b",
    r"\bcollege\b",
    r"\bschool\b",
    r"\bwater district\b",
    r"\bemergency\b",
    r"\bems\b",
    r"\bdnr\b",
    r"\bdec\b",
    r"\busfs\b",
    r"\bdot\b",
    r"\bville de\b",
    r"\bmunicipal",
    r"\bs[eé]curit[eé] publique\b",
    r"\bs[uû]ret[eé] du qu[eé]bec\b",
    r"\brcmp\b",
    r"\bgrc\b",
    r"\bgovernment\b",
    r"\bgouvernement\b",
]

_COOP_UTILITY_AG_PATTERNS = [
    r"\belectric\b",
    r"\bpower\b",
    r"\benergy\b",
    r"\blight\b",
    r"\bcoop\b",
    r"\bco-op\b",
    r"\bcooperative\b",
    r"\bwater authority\b",
    r"\bfarm\b",
    r"\bgrain\b",
    r"\bsilo\b",
    r"\birrigation\b",
    r"\bdairy\b",
    r"\bhydro\b",
    r"\bagricultur",
]

_COMMERCIAL_PATTERNS = [
    r"\bamerican tower\b",
    r"\bcrown castle\b",
    r"\bsba\b",
    r"\bverizon\b",
    r"\bat&t\b",
    r"\batt\b",
    r"\bt-mobile\b",
    r"\btmobile\b",
    r"\bsprint\b",
    r"\bcellular\b",
    r"\btelecom\b",
    r"\btower llc\b",
    r"\bwireless\b",
    r"\bbell\b",
    r"\btelus\b",
    r"\brogers\b",
    r"\bvid[eé]otron\b",
    r"\bvertical bridge\b",
    r"\btowerco\b",
]

_COMMERCIAL_FALLBACK_PATTERNS = [
    r"\btower\b",
    r"\bcell\b",
    r"\bbroadcast\b",
    r"\brepeater\b",
    r"\bmast\b",
    r"\bpole\b",
    r"\bmonopole\b",
    r"\bguyed\b",
    r"\blattice\b",
    r"\bantenna\b",
    r"\bllc\b",
    r"\binc\b",
    r"\bcorp\b",
    r"\bcorporation\b",
    r"\bltd\b",
    r"\bholdings\b",
    r"\bcommunications\b",
    r"\bbroadcasting\b",
    r"\bnetwork\b",
    r"\bmedia\b",
    r"\bproperties\b",
]

_CIVIC_REGEX = re.compile("|".join(_CIVIC_PATTERNS), re.IGNORECASE)
_COOP_UTILITY_AG_REGEX = re.compile("|".join(_COOP_UTILITY_AG_PATTERNS), re.IGNORECASE)
_COMMERCIAL_REGEX = re.compile("|".join(_COMMERCIAL_PATTERNS), re.IGNORECASE)
_COMMERCIAL_FALLBACK_REGEX = re.compile("|".join(_COMMERCIAL_FALLBACK_PATTERNS), re.IGNORECASE)


@functools.lru_cache(maxsize=16384)
def classify_tower_ownership(owner_name: str, notes: str = "") -> str:
    """Classify tower ownership into civic_public_safety, coop_utility_ag, or commercial_carrier.

    Args:
        owner_name: Owner or licensee name string.
        notes: Optional additional context or notes.

    Returns:
        One of "civic_public_safety", "coop_utility_ag", "commercial_carrier", or "unknown".
    """
    text = f"{owner_name or ''} {notes or ''}".lower()

    if _CIVIC_REGEX.search(text):
        return OwnerCategory.CIVIC_PUBLIC_SAFETY.value

    if _COOP_UTILITY_AG_REGEX.search(text):
        return OwnerCategory.COOP_UTILITY_AG.value

    if _COMMERCIAL_REGEX.search(text):
        return OwnerCategory.COMMERCIAL_CARRIER.value

    if _COMMERCIAL_FALLBACK_REGEX.search(text):
        return OwnerCategory.COMMERCIAL_CARRIER.value

    return OwnerCategory.UNKNOWN.value


@functools.lru_cache(maxsize=512)
def classify_fcc_structure_type(struct_code_or_desc: str) -> SiteType:
    """Classify FCC structure code or description into a typed SiteType.

    Rules:
        - TANK, WT, TK, WATER TANK -> SiteType.WATER_TOWER
        - SILO -> SiteType.SILO
        - LOOKOUT, FIRE, FIRE TOWER -> SiteType.FIRE_LOOKOUT
        - BLDG, ROOF, BUILDING -> SiteType.BUILDING_ROOFTOP
        - RESEARCH, OBS, OBSERVATORY, FLUX -> SiteType.RESEARCH_TOWER
        - TOWER, MAST, POLE, STACK, UTOWER, GTOWER -> SiteType.COMMUNICATIONS_TOWER
        - Else -> SiteType.COMMUNICATIONS_TOWER
    """
    if not struct_code_or_desc:
        return SiteType.COMMUNICATIONS_TOWER

    token = struct_code_or_desc.strip().upper().replace("-", " ").replace("_", " ")

    # Water tank
    if token in ("TANK", "WT", "TK", "WATER TANK", "WATER TOWER") or "WATER TANK" in token or "WATER TOWER" in token:
        return SiteType.WATER_TOWER
    if re.search(r"\b(TANK|WT|TK)\b", token):
        return SiteType.WATER_TOWER

    # Silo
    if "SILO" in token:
        return SiteType.SILO

    # Fire Lookout
    if any(k in token for k in ("LOOKOUT", "FIRE TOWER", "FIRE WATCH", "FIRE_LOOKOUT")) or token == "FIRE":
        return SiteType.FIRE_LOOKOUT

    # Building rooftop
    if any(k in token for k in ("BLDG", "ROOF", "BUILDING", "ROOFTOP")):
        return SiteType.BUILDING_ROOFTOP

    # Research / Observatory
    if any(k in token for k in ("RESEARCH", "OBS", "OBSERVATORY", "FLUX")):
        return SiteType.RESEARCH_TOWER

    # Communications Tower default for TOWER, MAST, POLE, STACK, UTOWER, GTOWER, etc.
    return SiteType.COMMUNICATIONS_TOWER


def _read_content_or_path(input_val: Union[str, Path]) -> str:
    """Read file content if Path or existing file path, otherwise return string."""
    if isinstance(input_val, Path):
        return input_val.read_text(encoding="utf-8", errors="replace")
    if isinstance(input_val, str):
        try:
            p = Path(input_val)
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        return input_val
    return str(input_val)


def _parse_coordinates(fields: Sequence[str]) -> Tuple[Optional[float], Optional[float]]:
    """Attempt to parse latitude and longitude from a sequence of raw tokens."""
    # Case 1: Two DMS strings e.g. ["44-28-33.0 N", "073-12-45.0 W"]
    for i in range(len(fields) - 1):
        f1, f2 = fields[i].strip(), fields[i + 1].strip()
        if any(h in f1.upper() for h in ("N", "S")) and any(h in f2.upper() for h in ("E", "W")):
            try:
                lat = dms_to_decimal(f1)
                lon = dms_to_decimal(f2)
                return lat, lon
            except ValueError:
                pass

    # Case 2: Discrete DMS fields (deg, min, sec, dir)
    for i in range(len(fields) - 4):
        if fields[i + 3].strip().upper() in ("N", "S"):
            for j in range(i + 4, len(fields) - 3):
                if fields[j + 3].strip().upper() in ("E", "W"):
                    try:
                        lat = dms_to_decimal(fields[i], fields[i + 1], fields[i + 2], fields[i + 3])
                        lon = dms_to_decimal(fields[j], fields[j + 1], fields[j + 2], fields[j + 3])
                        return lat, lon
                    except (ValueError, TypeError):
                        pass

    # Case 3: Plain decimal degrees e.g. ["44.5375", "-72.8144"]
    for i in range(len(fields) - 1):
        try:
            val1 = float(fields[i])
            val2 = float(fields[i + 1])
            if -90.0 <= val1 <= 90.0 and -180.0 <= val2 <= 180.0:
                return val1, val2
        except ValueError:
            pass

    return None, None


def _find_table_file(dir_path: Path, table_name: str) -> Optional[Path]:
    """Find a table file in dir_path case-insensitively."""
    target = table_name.lower()
    try:
        for p in dir_path.iterdir():
            if p.name.lower() == target:
                return p
    except (OSError, NotADirectoryError):
        pass
    return None


def parse_fcc_asr_directory(
    dir_path: Union[str, Path],
    bounds: Optional[RegionalBounds] = None,
    return_metadata: bool = False,
) -> Iterator[Any]:
    """Stream and join FCC ASR multi-table bulk database files (CO.dat, EN.dat, RA.dat).

    Performs a memory-bounded streaming join across the three core tables extracted from
    FCC r_tower.zip:
      - CO.dat (18 cols): Registration / System ID to WGS84 coordinates.
      - EN.dat (25 cols): Entity ownership data, preferring owner ('O') over representative ('R').
      - RA.dat (49 cols): Structure registration details, filtering for constructed status
        ('C', 'G', 'CONSTRUCTED') and height >= 15.0 m.

    CRITICAL UNIT INVARIANT:
      Heights (Cols 28, 30) and elevations (Col 29) in RA.dat are native METERS.
      They are NOT multiplied by FEET_TO_METERS (0.3048).

    Args:
        dir_path: Path to directory containing extracted FCC tables (or parent directory).
        bounds: Optional RegionalBounds to filter candidate sites.
        return_metadata: If True, yields (SiteCandidate, metadata_dict). Otherwise yields SiteCandidate.

    Yields:
        SiteCandidate objects, or (SiteCandidate, Dict[str, str]) if return_metadata=True.

    Raises:
        FileNotFoundError: If dir_path does not exist or required tables (CO.dat, RA.dat) are missing.
    """
    path = Path(dir_path)
    if not path.exists():
        raise FileNotFoundError(f"FCC ASR directory not found: {path}")

    target_dir = path
    if path.is_file():
        target_dir = path.parent

    co_path = _find_table_file(target_dir, "CO.dat")
    ra_path = _find_table_file(target_dir, "RA.dat")
    en_path = _find_table_file(target_dir, "EN.dat")

    if co_path is None or not co_path.exists():
        raise FileNotFoundError(f"Missing required FCC ASR table CO.dat in {target_dir}")
    if ra_path is None or not ra_path.exists():
        raise FileNotFoundError(f"Missing required FCC ASR table RA.dat in {target_dir}")

    # 1. Stream CO.dat line-by-line: registration / system id -> (lat, lon)
    coords: Dict[str, Tuple[float, float]] = {}
    with open(co_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if not parts or parts[0].strip().upper() != "CO":
                continue

            reg_col3 = parts[3].strip() if len(parts) > 3 else ""
            reg_col4 = parts[4].strip() if len(parts) > 4 else ""
            if not reg_col3 and not reg_col4:
                continue

            lat: Optional[float] = None
            lon: Optional[float] = None

            if len(parts) > 14:
                lat_deg = parts[6].strip()
                lat_min = parts[7].strip()
                lat_sec = parts[8].strip()
                lat_dir = parts[9].strip().upper()

                lon_deg = parts[11].strip()
                lon_min = parts[12].strip()
                lon_sec = parts[13].strip()
                lon_dir = parts[14].strip().upper()

                try:
                    lat_deg_f = float(lat_deg) if lat_deg else 0.0
                    lat_min_f = float(lat_min) if lat_min else 0.0
                    lat_sec_f = float(lat_sec) if lat_sec else 0.0
                    lat = lat_deg_f + (lat_min_f / 60.0) + (lat_sec_f / 3600.0)
                    if lat_dir == "S":
                        lat = -lat
                except (ValueError, TypeError):
                    try:
                        lat = dms_to_decimal(lat_deg, lat_min, lat_sec, lat_dir or "N")
                    except Exception:
                        lat = None

                try:
                    lon_deg_f = float(lon_deg) if lon_deg else 0.0
                    lon_min_f = float(lon_min) if lon_min else 0.0
                    lon_sec_f = float(lon_sec) if lon_sec else 0.0
                    lon = lon_deg_f + (lon_min_f / 60.0) + (lon_sec_f / 3600.0)
                    if lon_dir == "E":
                        lon = abs(lon)
                    elif lon_dir in ("W", "S") or lon_dir == "":
                        lon = -abs(lon)
                except (ValueError, TypeError):
                    try:
                        lon = dms_to_decimal(lon_deg, lon_min, lon_sec, lon_dir or "W")
                    except Exception:
                        lon = None

            # Fallback to decimal fields (Col 10, Col 15) if DMS parsing failed
            if lat is None and len(parts) > 10 and parts[10].strip():
                try:
                    lat = float(parts[10].strip())
                except ValueError:
                    pass
            if lon is None and len(parts) > 15 and parts[15].strip():
                try:
                    lon = float(parts[15].strip())
                    if lon_dir == "E" or (len(parts) > 14 and parts[14].strip().upper() == "E"):
                        lon = abs(lon)
                    elif (len(parts) > 14 and parts[14].strip().upper() in ("W", "S")) or lon_dir in ("W", "S"):
                        if lon > 0:
                            lon = -lon
                    elif lon > 0 and not lon_dir:
                        lon = -lon
                except ValueError:
                    pass

            if lat is None or lon is None:
                continue
            if lat == 0.0 and lon == 0.0:
                continue

            if reg_col4:
                coords[reg_col4] = (lat, lon)
            if reg_col3 and reg_col3 not in coords:
                coords[reg_col3] = (lat, lon)

    # 2. Stream EN.dat line-by-line: registration / system id -> (owner_name, city, state)
    # Preferring entity type 'O' (Owner) over 'R' (Representative)
    owners: Dict[str, Tuple[str, str, str]] = {}
    owner_types: Dict[str, str] = {}
    if en_path is not None and en_path.exists():
        with open(en_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("|")
                if not parts or parts[0].strip().upper() != "EN":
                    continue

                reg_col3 = parts[3].strip() if len(parts) > 3 else ""
                reg_col4 = parts[4].strip() if len(parts) > 4 else ""
                if not reg_col3 and not reg_col4:
                    continue

                entity_type = parts[5].strip().upper() if len(parts) > 5 else ""
                owner_name = parts[9].strip() if len(parts) > 9 else ""
                city = parts[20].strip() if len(parts) > 20 else ""
                state = parts[21].strip() if len(parts) > 21 else ""

                is_owner = (entity_type == "O")
                for reg in (reg_col3, reg_col4):
                    if not reg:
                        continue
                    curr_type = owner_types.get(reg)
                    if reg not in owners or is_owner or curr_type != "O":
                        owners[reg] = (owner_name, city, state)
                        owner_types[reg] = "O" if is_owner else entity_type

    # 3. Stream RA.dat line-by-line: structure records, filter status, join coords + owner
    seen_ids: Set[str] = set()
    with open(ra_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if not parts or parts[0].strip().upper() != "RA":
                continue

            status = parts[8].strip().upper() if len(parts) > 8 else ""
            if status not in ("C", "G", "CONSTRUCTED"):
                continue

            reg_num = parts[3].strip() if len(parts) > 3 else ""
            sys_id = parts[4].strip() if len(parts) > 4 else ""
            target_key = reg_num or sys_id
            if not target_key:
                continue

            coord_tuple = (coords.get(sys_id) if sys_id else None) or coords.get(reg_num)
            if coord_tuple is None:
                continue
            lat, lon = coord_tuple

            # Heights in RA.dat are native METERS: Col 30 overall height AGL, Col 28 structure height AGL
            p30 = parts[30].strip() if len(parts) > 30 else ""
            p28 = parts[28].strip() if len(parts) > 28 else ""

            try:
                h30 = float(p30) if p30 else 0.0
            except (ValueError, TypeError):
                h30 = 0.0

            try:
                h28 = float(p28) if p28 else 0.0
            except (ValueError, TypeError):
                h28 = 0.0

            mast_height_m = h30 if h30 > 0.0 else h28
            if mast_height_m < 15.0:
                continue
            mast_height_m = round(mast_height_m, 2)

            # Ground elevation AMSL in METERS (Col 29)
            p29 = parts[29].strip() if len(parts) > 29 else ""
            try:
                elev_m = round(float(p29), 1) if p29 else 0.0
            except (ValueError, TypeError):
                elev_m = 0.0

            coord = Coordinate(lat=lat, lon=lon, elevation_m=elev_m)
            if bounds is not None and not bounds.contains(coord):
                continue

            site_id = f"ASR_{target_key}"
            if site_id in seen_ids:
                if sys_id and f"ASR_{reg_num}_{sys_id}" not in seen_ids:
                    site_id = f"ASR_{reg_num}_{sys_id}"
                elif sys_id and f"ASR_{sys_id}" not in seen_ids:
                    site_id = f"ASR_{sys_id}"
                else:
                    continue
            seen_ids.add(site_id)

            struct_type_str = parts[32].strip() if len(parts) > 32 and parts[32] else "TOWER"
            site_type = classify_fcc_structure_type(struct_type_str)

            owner_info = owners.get(reg_num) or (owners.get(sys_id) if sys_id else None) or ("", "", "")
            owner_name, en_city, en_state = owner_info

            p24 = parts[24].strip() if len(parts) > 24 else ""
            p25 = parts[25].strip() if len(parts) > 25 else ""
            city = p24 if p24 else en_city
            state = p25 if p25 else en_state

            owner_cat = classify_tower_ownership(owner_name, notes=f"{struct_type_str} {city} {state}")

            if owner_name and city:
                name = f"{owner_name} - {city}"
            elif owner_name:
                name = f"{owner_name} (ASR {target_key})"
            elif city:
                name = f"ASR {struct_type_str} {target_key} - {city}"
            else:
                name = f"ASR {struct_type_str} {target_key}"

            notes_parts = [
                f"FCC ASR: {target_key}",
            ]
            if owner_name:
                notes_parts.append(f"Owner: {owner_name}")
            notes_parts.append(f"Owner Category: {owner_cat}")
            notes_parts.append(f"Structure: {struct_type_str}")
            notes_parts.append(f"Height AGL: {mast_height_m:.1f} m")
            if city or state:
                loc_str = ", ".join(filter(None, [city, state]))
                notes_parts.append(f"Location: {loc_str}")

            candidate = SiteCandidate(
                site_id=site_id,
                name=name,
                location=coord,
                site_type=site_type,
                mast_height_m=mast_height_m,
                has_grid_power=True,
                solar_exposure_pct=95.0,
                access_difficulty=AccessDifficulty.DRIVE_UP,
                notes=" | ".join(notes_parts),
            )

            if return_metadata:
                meta = {
                    "jurisdiction": state or "",
                    "owner": owner_name or "",
                    "owner_category": owner_cat or "",
                    "source_record_id": str(target_key),
                }
                yield (candidate, meta)
            else:
                yield candidate


def parse_fcc_asr_bulk(
    ant_path_or_content: Union[str, Path],
    own_path_or_content: Optional[Union[str, Path]] = None,
    bounds: Optional[RegionalBounds] = None,
    return_metadata: bool = False,
) -> Union[List[SiteCandidate], List[Tuple[SiteCandidate, Dict[str, str]]]]:
    """Parse bulk FCC ASR database records and convert them to SiteCandidate objects.

    Supports ANT/OWN records, CO/EN/RA records, and single-file or paired-file inputs.
    Uses dms_to_decimal for WGS84 coordinate transformation, classifies SiteType,
    converts heights to meters, tags ownership category, and applies RegionalBounds filtering.

    Args:
        ant_path_or_content: Antenna structure file path or string content (ANT, CO, or combined).
        own_path_or_content: Optional owner file path or string content (OWN, EN).
        bounds: Optional RegionalBounds to filter candidate sites.
        return_metadata: If True, returns tuples of (SiteCandidate, metadata_dict).

    Returns:
        List of validated SiteCandidate objects, or list of (SiteCandidate, metadata) if return_metadata=True.
    """

    if isinstance(ant_path_or_content, (str, Path)):
        try:
            p = Path(ant_path_or_content)
            if p.is_dir():
                return list(parse_fcc_asr_directory(p, bounds=bounds, return_metadata=return_metadata))
        except OSError:
            pass

    owners: Dict[str, Dict[str, str]] = {}
    structures: Dict[str, Dict[str, Any]] = []
    raw_records: List[Dict[str, Any]] = []

    # 1. Parse separate owner file if provided
    if own_path_or_content is not None:
        own_text = _read_content_or_path(own_path_or_content)
        for raw_line in own_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            rec_type = parts[0].upper()
            if rec_type == "OWN" and len(parts) >= 3:
                reg_num = parts[1]
                owners[reg_num] = {
                    "owner_name": parts[2],
                    "address": parts[3] if len(parts) > 3 else "",
                    "city": parts[4] if len(parts) > 4 else "",
                    "state": parts[5] if len(parts) > 5 else "",
                }
            elif rec_type == "EN" and len(parts) >= 3:
                if len(parts) > 6 and parts[3].isdigit():
                    reg_num = parts[3]
                    owner_name = parts[6]
                    city = parts[15] if len(parts) > 15 else ""
                    state = parts[16] if len(parts) > 16 else ""
                else:
                    reg_num = parts[1]
                    owner_name = parts[2]
                    city = parts[4] if len(parts) > 4 else ""
                    state = parts[5] if len(parts) > 5 else ""
                owners[reg_num] = {
                    "owner_name": owner_name,
                    "address": "",
                    "city": city,
                    "state": state,
                }

    # 2. Parse main content (ANT / CO / RA / combined OWN)
    ant_text = _read_content_or_path(ant_path_or_content)
    struct_dict: Dict[str, Dict[str, Any]] = {}

    for raw_line in ant_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split("|")]
        if not parts:
            continue

        rec_type = parts[0].upper()

        if rec_type == "OWN":
            if len(parts) >= 3:
                reg_num = parts[1]
                owners[reg_num] = {
                    "owner_name": parts[2],
                    "address": parts[3] if len(parts) > 3 else "",
                    "city": parts[4] if len(parts) > 4 else "",
                    "state": parts[5] if len(parts) > 5 else "",
                }
        elif rec_type == "EN":
            if len(parts) > 6 and parts[3].isdigit():
                reg_num = parts[3]
                owner_name = parts[6]
                city = parts[15] if len(parts) > 15 else ""
                state = parts[16] if len(parts) > 16 else ""
            elif len(parts) > 2:
                reg_num = parts[1]
                owner_name = parts[2]
                city = parts[4] if len(parts) > 4 else ""
                state = parts[5] if len(parts) > 5 else ""
            else:
                continue
            owners[reg_num] = {
                "owner_name": owner_name,
                "address": "",
                "city": city,
                "state": state,
            }
        elif rec_type == "RA":
            # Structure registration data
            sys_id = ""
            if len(parts) >= 30:
                # Full FCC ASR RA table format (native meters)
                reg_num = parts[3].strip() if len(parts) > 3 else ""
                sys_id = parts[4].strip() if len(parts) > 4 else ""
                height_agl = parts[30].strip() or (parts[28].strip() if len(parts) > 28 else "0.0")
                elev_amsl = parts[29].strip() if len(parts) > 29 else "0.0"
                struct_type = parts[32].strip() if len(parts) > 32 and parts[32] else "TOWER"
                city = parts[24].strip() if len(parts) > 24 else ""
                state = parts[25].strip() if len(parts) > 25 else ""
                county = ""
            elif len(parts) > 4 and parts[3].isdigit():
                reg_num = parts[3]
                struct_type = parts[4]
                height_agl = parts[5] if len(parts) > 5 else "0.0"
                elev_amsl = parts[6] if len(parts) > 6 else "0.0"
                city = parts[8] if len(parts) > 8 else ""
                state = parts[9] if len(parts) > 9 else ""
                county = parts[10] if len(parts) > 10 else ""
            elif len(parts) > 3:
                reg_num = parts[1]
                struct_type = parts[2]
                height_agl = parts[3] if len(parts) > 3 else "0.0"
                elev_amsl = parts[4] if len(parts) > 4 else "0.0"
                city = parts[5] if len(parts) > 5 else ""
                state = parts[6] if len(parts) > 6 else ""
                county = parts[7] if len(parts) > 7 else ""
            else:
                continue
            ra_entry = {
                "struct_type": struct_type,
                "height_agl": height_agl,
                "elev_amsl": elev_amsl,
                "city": city,
                "state": state,
                "county": county,
                "is_meters": True,
                "sys_id": sys_id,
            }
            if reg_num:
                struct_dict[reg_num] = ra_entry
            if sys_id:
                struct_dict[sys_id] = ra_entry
        elif rec_type == "CO":
            # Coordinate registration data
            if len(parts) >= 4:
                if parts[1].isdigit() and len(parts[1]) >= 6:
                    reg_num = parts[1]
                    coord_parts = parts[2:]
                elif len(parts) > 3 and parts[3].isdigit():
                    reg_num = parts[3]
                    coord_parts = parts[4:]
                elif parts[2].isdigit():
                    reg_num = parts[2]
                    coord_parts = parts[3:]
                else:
                    reg_num = parts[1]
                    coord_parts = parts[2:]

                lat, lon = _parse_coordinates(coord_parts)
                if lat is not None and lon is not None:
                    raw_records.append({
                        "reg_num": reg_num,
                        "lat": lat,
                        "lon": lon,
                        "struct_type": None,
                        "height_agl": None,
                        "elev_amsl": None,
                        "city": "",
                        "state": "",
                        "county": "",
                        "status": "CONSTRUCTED",
                    })
        elif rec_type == "ANT":
            if len(parts) < 4:
                continue
            reg_num = parts[1]
            field_2 = parts[2]
            is_lat_field_2 = bool(
                re.search(r"\d+[\-:\s°]\d+", field_2)
                or any(h in field_2.upper() for h in ("N", "S"))
            )

            if is_lat_field_2:
                file_num = ""
                lat_dms = parts[2]
                lon_dms = parts[3]
                idx_offset = 4
            else:
                file_num = parts[2]
                lat_dms = parts[3]
                lon_dms = parts[4] if len(parts) > 4 else ""
                idx_offset = 5

            struct_type = parts[idx_offset] if len(parts) > idx_offset else "TOWER"
            height_agl_raw = parts[idx_offset + 1] if len(parts) > idx_offset + 1 else "0.0"
            elev_amsl_raw = parts[idx_offset + 2] if len(parts) > idx_offset + 2 else "0.0"
            height_amsl_raw = parts[idx_offset + 3] if len(parts) > idx_offset + 3 else "0.0"
            city = parts[idx_offset + 4] if len(parts) > idx_offset + 4 else ""
            state = parts[idx_offset + 5] if len(parts) > idx_offset + 5 else ""
            county = parts[idx_offset + 6] if len(parts) > idx_offset + 6 else ""
            status = parts[idx_offset + 7] if len(parts) > idx_offset + 7 else "CONSTRUCTED"

            try:
                lat = dms_to_decimal(lat_dms)
                lon = dms_to_decimal(lon_dms)
            except ValueError:
                continue

            raw_records.append({
                "reg_num": reg_num,
                "lat": lat,
                "lon": lon,
                "struct_type": struct_type,
                "height_agl": height_agl_raw,
                "elev_amsl": elev_amsl_raw,
                "city": city,
                "state": state,
                "county": county,
                "status": status,
            })
        elif len(parts) >= 4 and parts[0].isdigit():
            # Fallback numeric record
            reg_num = parts[0]
            lat_dms = parts[1]
            lon_dms = parts[2]
            height_agl_raw = parts[3] if len(parts) > 3 else "0.0"
            struct_type = parts[4] if len(parts) > 4 else "TOWER"
            try:
                lat = dms_to_decimal(lat_dms)
                lon = dms_to_decimal(lon_dms)
                raw_records.append({
                    "reg_num": reg_num,
                    "lat": lat,
                    "lon": lon,
                    "struct_type": struct_type,
                    "height_agl": height_agl_raw,
                    "elev_amsl": "0.0",
                    "city": "",
                    "state": "",
                    "county": "",
                    "status": "CONSTRUCTED",
                })
            except ValueError:
                continue

    # Merge RA structure info for CO records
    for rec in raw_records:
        reg_num = rec["reg_num"]
        if reg_num in struct_dict:
            s_info = struct_dict[reg_num]
            if not rec.get("struct_type"):
                rec["struct_type"] = s_info.get("struct_type")
            if not rec.get("height_agl"):
                rec["height_agl"] = s_info.get("height_agl")
            if not rec.get("elev_amsl"):
                rec["elev_amsl"] = s_info.get("elev_amsl")
            if not rec.get("city"):
                rec["city"] = s_info.get("city", "")
            if not rec.get("state"):
                rec["state"] = s_info.get("state", "")
            if not rec.get("county"):
                rec["county"] = s_info.get("county", "")
            if s_info.get("is_meters"):
                rec["is_meters"] = True
            if s_info.get("sys_id"):
                rec["sys_id"] = s_info.get("sys_id")

    # Construct SiteCandidate items
    candidates: List[SiteCandidate] = []
    seen_ids = set()

    for rec in raw_records:
        status = (rec.get("status") or "").strip().upper()
        if status in ("DISMANTLED", "DISMANTLE", "CANCELLED", "TERMINATED", "EXPIRED", "CANCEL"):
            continue

        lat = rec["lat"]
        lon = rec["lon"]
        elev_raw = rec.get("elev_amsl")
        try:
            if rec.get("is_meters"):
                elev_m = round(float(elev_raw), 1) if elev_raw else 0.0
            else:
                elev_m = round(float(elev_raw) * FEET_TO_METERS, 1) if elev_raw else 0.0
        except ValueError:
            elev_m = 0.0

        coord = Coordinate(lat=lat, lon=lon, elevation_m=elev_m)

        if bounds is not None and not bounds.contains(coord):
            continue

        height_raw = rec.get("height_agl")
        try:
            if rec.get("is_meters"):
                mast_height_m = max(0.0, round(float(height_raw), 2)) if height_raw else 5.0
            else:
                height_ft = float(height_raw) if height_raw else 0.0
                mast_height_m = max(0.0, round(height_ft * FEET_TO_METERS, 2))
                if mast_height_m == 0.0:
                    mast_height_m = 5.0
        except ValueError:
            mast_height_m = 5.0

        reg_num = rec["reg_num"]
        site_id = f"ASR_{reg_num}"
        if site_id in seen_ids:
            sys_id = rec.get("sys_id", "")
            if sys_id and f"ASR_{reg_num}_{sys_id}" not in seen_ids:
                site_id = f"ASR_{reg_num}_{sys_id}"
            elif sys_id and f"ASR_{sys_id}" not in seen_ids:
                site_id = f"ASR_{sys_id}"
            else:
                continue
        seen_ids.add(site_id)

        owner_info = owners.get(reg_num, {})
        owner_name = owner_info.get("owner_name", "").strip()

        struct_type_str = rec.get("struct_type") or "TOWER"
        site_type = classify_fcc_structure_type(struct_type_str)

        city = rec.get("city") or owner_info.get("city", "")
        state = rec.get("state") or owner_info.get("state", "")
        county = rec.get("county", "")

        owner_cat = classify_tower_ownership(owner_name, notes=f"{struct_type_str} {city} {state}")

        if owner_name and city:
            name = f"{owner_name} - {city}"
        elif owner_name:
            name = f"{owner_name} (ASR {reg_num})"
        elif city:
            name = f"ASR {struct_type_str} {reg_num} - {city}"
        else:
            name = f"ASR {struct_type_str} {reg_num}"

        notes_parts = [
            f"FCC ASR: {reg_num}",
        ]
        if owner_name:
            notes_parts.append(f"Owner: {owner_name}")
        notes_parts.append(f"Owner Category: {owner_cat}")
        notes_parts.append(f"Structure: {struct_type_str}")
        notes_parts.append(f"Height AGL: {height_raw or '0.0'} ft ({mast_height_m:.1f} m)")
        if city or county or state:
            loc_str = ", ".join(filter(None, [city, f"{county} Co." if county else "", state]))
            notes_parts.append(f"Location: {loc_str}")

        candidate = SiteCandidate(
            site_id=site_id,
            name=name,
            location=coord,
            site_type=site_type,
            mast_height_m=mast_height_m,
            has_grid_power=True,
            solar_exposure_pct=95.0,
            access_difficulty=AccessDifficulty.DRIVE_UP,
            notes=" | ".join(notes_parts),
        )
        if return_metadata:
            meta: Dict[str, str] = {
                "jurisdiction": state or "",
                "owner": owner_name or "",
                "owner_category": owner_cat or "",
                "source_record_id": str(reg_num),
            }
            candidates.append((candidate, meta))
        else:
            candidates.append(candidate)

    return candidates
