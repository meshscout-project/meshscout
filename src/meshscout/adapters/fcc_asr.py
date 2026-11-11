"""FCC Antenna Structure Registration (ASR) Pipe-Delimited Regional Adapter.

Parses FCC ASR database records (ANT.dat and OWN.dat), converts DMS coordinates
to WGS84 decimal degrees, transforms AGL tower heights to meters, and produces
validated SiteCandidate contracts for regional mesh planning.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from meshscout.adapters.base import (
    BaseRegionalAdapter,
    RateLimitBackoff,
    RegionalAdapterBase,
)
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    MeshScoutError,
    RegionalBounds,
    Result,
    SiteCandidate,
    SiteType,
)

FEET_TO_METERS = 0.3048


def feet_to_meters(feet: Union[float, int, str]) -> float:
    """Convert height or elevation from feet to meters using exact 0.3048 factor."""
    return float(feet) * FEET_TO_METERS


DEFAULT_FCC_ASR_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "fixtures"
    / "fcc_asr_vt_sample.dat"
)


def dms_to_decimal(
    dms: Union[str, float, int],
    direction_or_minutes: Optional[Union[str, float, int]] = None,
    seconds: Optional[Union[float, int]] = None,
    direction: Optional[str] = None,
) -> float:
    """Convert Degrees-Minutes-Seconds (DMS) coordinate to decimal degrees (WGS84).

    Supports:
      - FCC format: "44-32-15.0 N", "072-48-52.0 W"
      - Compact: "44-32-15.0N", "072-48-52.0W"
      - Separators: "44:32:15.0 N", "44 32 15.0 N", "44-32-15 N"
      - Symbols: "44°32'15.0\" N"
      - Multi-arg: dms_to_decimal("44-32-15.0", "N") or dms_to_decimal(44, 32, 15.0, "N")
      - Direct signed decimal: "44.5375", -72.8144

    Args:
        dms: DMS string or degrees value.
        direction_or_minutes: Direction ('N', 'S', 'E', 'W') or minutes numeric value.
        seconds: Seconds numeric value (when using multi-argument signature).
        direction: Direction ('N', 'S', 'E', 'W') when minutes and seconds are provided.

    Returns:
        Decimal degrees as float. Latitude in [-90, 90], Longitude in [-180, 180].

    Raises:
        ValueError: If input format is malformed, minutes/seconds >= 60, or values are out of bounds.
    """
    if dms is None:
        raise ValueError("Coordinate cannot be None")

    hemisphere: Optional[str] = None
    deg: float = 0.0
    minutes_val: float = 0.0
    seconds_val: float = 0.0

    # Branch 1: Multi-argument numeric call e.g. dms_to_decimal(44, 32, 15.0, "N")
    if seconds is not None:
        deg = float(dms)
        minutes_val = float(direction_or_minutes) if direction_or_minutes is not None else 0.0
        seconds_val = float(seconds)
        if direction is not None:
            hemisphere = str(direction).strip().upper()
    elif isinstance(direction_or_minutes, str) and direction_or_minutes.strip().upper() in ("N", "S", "E", "W"):
        # Branch 2: dms_to_decimal("44-32-15.0", "N")
        hemisphere = direction_or_minutes.strip().upper()
        raw = str(dms).strip()
    elif direction_or_minutes is not None and not isinstance(direction_or_minutes, str):
        # Branch 3: dms_to_decimal(44, 32.25)
        deg = float(dms)
        minutes_val = float(direction_or_minutes)
        seconds_val = 0.0
        if direction is not None:
            hemisphere = str(direction).strip().upper()
    else:
        # Branch 4: Single string e.g. "44-32-15.0 N"
        raw = str(dms).strip()
        if not raw:
            raise ValueError("Empty DMS coordinate string")
        if direction is not None:
            hemisphere = str(direction).strip().upper()

    # If single-string or dms-as-string:
    if seconds is None and not (direction_or_minutes is not None and not isinstance(direction_or_minutes, str)):
        raw = str(dms).strip()
        if not raw:
            raise ValueError("Empty DMS coordinate string")

        is_negative_sign = False
        if raw.startswith("+"):
            raw = raw[1:].strip()
        elif raw.startswith("-"):
            rest = raw[1:].strip()
            # If plain negative decimal number like "-73.1234"
            if "-" not in rest and ":" not in rest and " " not in rest and "'" not in rest and '"' not in rest and "°" not in rest:
                try:
                    val = float(raw)
                    if hemisphere in ("N", "S") and not (-90.0 <= val <= 90.0):
                        raise ValueError(f"Latitude {val} out of bounds [-90, 90]")
                    if not (-180.0 <= val <= 180.0):
                        raise ValueError(f"Coordinate {val} out of bounds [-180, 180]")
                    return val
                except ValueError as e:
                    if "out of bounds" in str(e):
                        raise
            is_negative_sign = True
            raw = rest

        # Look for trailing hemisphere indicator (e.g. "44-32-15.0 N" or "44-32-15.0N")
        match_hemi_end = re.search(r"([NSEWnsew])$", raw)
        if match_hemi_end:
            found_hemi = match_hemi_end.group(1).upper()
            if hemisphere and hemisphere != found_hemi:
                raise ValueError(f"Conflicting hemisphere indicators: '{hemisphere}' and '{found_hemi}'")
            hemisphere = found_hemi
            raw = raw[:-1].strip()
        else:
            match_hemi_start = re.match(r"^([NSEWnsew])\s*", raw)
            if match_hemi_start:
                found_hemi = match_hemi_start.group(1).upper()
                if hemisphere and hemisphere != found_hemi:
                    raise ValueError(f"Conflicting hemisphere indicators: '{hemisphere}' and '{found_hemi}'")
                hemisphere = found_hemi
                raw = raw[match_hemi_start.end():].strip()

        # Tokenize degrees, minutes, seconds
        tokens = [t for t in re.split(r"[\s\-:°\'\"dmsDMS]+", raw) if t]
        if not tokens:
            raise ValueError(f"Cannot parse DMS tokens from '{dms}'")

        if len(tokens) == 1:
            try:
                deg = float(tokens[0])
                minutes_val = 0.0
                seconds_val = 0.0
            except ValueError:
                raise ValueError(f"Invalid DMS token: '{tokens[0]}'")
        elif len(tokens) == 2:
            try:
                deg = float(tokens[0])
                minutes_val = float(tokens[1])
                seconds_val = 0.0
            except ValueError:
                raise ValueError(f"Invalid DMS tokens: {tokens}")
        elif len(tokens) == 3:
            try:
                deg = float(tokens[0])
                minutes_val = float(tokens[1])
                seconds_val = float(tokens[2])
            except ValueError:
                raise ValueError(f"Invalid DMS tokens: {tokens}")
        else:
            raise ValueError(f"Too many tokens in DMS string '{dms}': {tokens}")

        if is_negative_sign:
            if hemisphere in ("N", "E"):
                raise ValueError("Negative sign cannot be combined with North/East hemisphere indicator")
            if hemisphere is None:
                hemisphere = "W"

    # Validate individual component ranges
    if deg < 0.0:
        raise ValueError(f"Degrees component must be non-negative, got {deg}")
    if minutes_val < 0.0 or minutes_val >= 60.0:
        raise ValueError(f"Minutes component must be in range [0, 60), got {minutes_val}")
    if seconds_val < 0.0 or seconds_val >= 60.0:
        raise ValueError(f"Seconds component must be in range [0, 60), got {seconds_val}")

    total = deg + (minutes_val / 60.0) + (seconds_val / 3600.0)

    if hemisphere in ("S", "W"):
        total = -total
    elif hemisphere is not None and hemisphere not in ("N", "E"):
        raise ValueError(f"Invalid hemisphere indicator: '{hemisphere}'. Expected N, S, E, or W.")

    # Geodetic boundary enforcement
    if hemisphere in ("N", "S"):
        if total < -90.0 or total > 90.0:
            raise ValueError(f"Latitude {total} out of bounds [-90, 90]")
    elif hemisphere in ("E", "W"):
        if total < -180.0 or total > 180.0:
            raise ValueError(f"Longitude {total} out of bounds [-180, 180]")
    else:
        if total < -180.0 or total > 180.0:
            raise ValueError(f"Coordinate {total} out of bounds [-180, 180]")

    return total


def parse_asr_buffer(
    content: str,
    bounds: Optional[RegionalBounds] = None,
) -> List[SiteCandidate]:
    """Parse FCC ASR pipe-delimited records from a string buffer.

    Extracts ANT and OWN records, converts DMS coordinates to WGS84,
    converts AGL heights to meters, and constructs SiteCandidate objects.
    Optionally filters by RegionalBounds.
    """
    owners: Dict[str, Dict[str, str]] = {}
    ant_records: List[Dict[str, Any]] = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split("|")]
        if not parts:
            continue

        rec_type = parts[0].upper()

        if rec_type == "OWN":
            # Format: OWN|reg_num|owner_name|address|city|state|zip|phone|frn
            if len(parts) >= 3:
                reg_num = parts[1]
                owners[reg_num] = {
                    "owner_name": parts[2],
                    "address": parts[3] if len(parts) > 3 else "",
                    "city": parts[4] if len(parts) > 4 else "",
                    "state": parts[5] if len(parts) > 5 else "",
                    "zip": parts[6] if len(parts) > 6 else "",
                    "phone": parts[7] if len(parts) > 7 else "",
                    "frn": parts[8] if len(parts) > 8 else "",
                }
        elif rec_type == "ANT":
            # Format A: ANT|reg_num|file_num|lat_dms|lon_dms|struct_type|height_agl|elev_amsl|height_amsl|city|state|county|status
            # Format B: ANT|reg_num|lat_dms|lon_dms|struct_type|height_agl|...
            if len(parts) < 4:
                continue

            reg_num = parts[1]

            # Distinguish whether parts[2] is file_number or lat_dms
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

            ant_records.append({
                "reg_num": reg_num,
                "file_num": file_num,
                "lat_dms": lat_dms,
                "lon_dms": lon_dms,
                "struct_type": struct_type,
                "height_agl": height_agl_raw,
                "elev_amsl": elev_amsl_raw,
                "height_amsl": height_amsl_raw,
                "city": city,
                "state": state,
                "county": county,
                "status": status,
            })
        else:
            # Fallback for files without explicit ANT record prefix if line has pipe delimiters
            # and first token looks like registration number
            if len(parts) >= 4 and parts[0].isdigit():
                reg_num = parts[0]
                lat_dms = parts[1]
                lon_dms = parts[2]
                height_agl_raw = parts[3] if len(parts) > 3 else "0.0"
                ant_records.append({
                    "reg_num": reg_num,
                    "file_num": "",
                    "lat_dms": lat_dms,
                    "lon_dms": lon_dms,
                    "struct_type": "TOWER",
                    "height_agl": height_agl_raw,
                    "elev_amsl": "0.0",
                    "height_amsl": "0.0",
                    "city": "",
                    "state": "",
                    "county": "",
                    "status": "CONSTRUCTED",
                })

    # Assemble SiteCandidates
    candidates: List[SiteCandidate] = []
    for ant in ant_records:
        reg_num = ant["reg_num"]
        owner_info = owners.get(reg_num, {})
        owner_name = owner_info.get("owner_name", "").strip()

        # Exclude dismantled, cancelled, or terminated antenna structures
        ant_status = (ant.get("status") or "").strip().upper()
        if ant_status in ("DISMANTLED", "DISMANTLE", "CANCELLED", "TERMINATED", "EXPIRED", "CANCEL"):
            continue

        try:
            lat = dms_to_decimal(ant["lat_dms"])
            lon = dms_to_decimal(ant["lon_dms"])
        except ValueError:
            # Skip invalid coordinate records
            continue

        try:
            elev_ft = float(ant["elev_amsl"]) if ant["elev_amsl"] else 0.0
            elev_m = round(elev_ft * FEET_TO_METERS, 1)
        except ValueError:
            elev_m = 0.0

        coord = Coordinate(lat=lat, lon=lon, elevation_m=elev_m)

        # Apply RegionalBounds filter if requested
        if bounds is not None and not bounds.contains(coord):
            continue

        try:
            height_ft = float(ant["height_agl"]) if ant["height_agl"] else 0.0
            mast_height_m = max(0.0, round(height_ft * FEET_TO_METERS, 2))
            if mast_height_m == 0.0:
                mast_height_m = 5.0
        except ValueError:
            mast_height_m = 5.0

        city = ant["city"]
        state = ant["state"]
        county = ant["county"]
        struct_type = ant["struct_type"]

        # Human-readable descriptive site name
        if owner_name and city:
            name = f"{owner_name} - {city}"
        elif owner_name:
            name = f"{owner_name} (ASR {reg_num})"
        elif city:
            name = f"ASR Tower {reg_num} - {city}"
        else:
            name = f"ASR Tower {reg_num}"

        notes_parts = [f"FCC ASR: {reg_num}"]
        if owner_name:
            notes_parts.append(f"Owner: {owner_name}")
        notes_parts.append(f"Height AGL: {ant['height_agl']} ft ({mast_height_m:.1f} m)")
        notes_parts.append(f"Structure: {struct_type}")
        if city or county or state:
            loc_str = ", ".join(filter(None, [city, f"{county} Co." if county else "", state]))
            notes_parts.append(f"Location: {loc_str}")

        candidate = SiteCandidate(
            site_id=f"ASR_{reg_num}",
            name=name,
            location=coord,
            site_type=SiteType.COMMUNICATIONS_TOWER,
            mast_height_m=mast_height_m,
            has_grid_power=True,
            solar_exposure_pct=95.0,
            access_difficulty=AccessDifficulty.DRIVE_UP,
            notes=" | ".join(notes_parts),
        )
        candidates.append(candidate)

    return candidates


def parse_asr_files(
    ant_path: Union[str, Path],
    own_path: Optional[Union[str, Path]] = None,
    bounds: Optional[RegionalBounds] = None,
) -> List[SiteCandidate]:
    """Parse FCC ASR pipe-delimited files from local paths."""
    ant_file = Path(ant_path)
    if not ant_file.exists():
        raise FileNotFoundError(f"ANT data file not found: {ant_file}")

    content_parts = [ant_file.read_text(encoding="utf-8", errors="replace")]

    if own_path is not None:
        own_file = Path(own_path)
        if own_file.exists():
            content_parts.append(own_file.read_text(encoding="utf-8", errors="replace"))

    combined_content = "\n".join(content_parts)
    return parse_asr_buffer(combined_content, bounds=bounds)


DISMANTLED_STATUS_TOKENS: Tuple[str, ...] = (
    "DISMANTLED",
    "DISMANTLE",
    "CANCELLED",
    "TERMINATED",
    "EXPIRED",
    "CANCEL",
)


def extract_dismantled_site_ids(
    content: Optional[str] = None,
    fixture_path: Optional[Union[str, Path]] = None,
) -> List[str]:
    """Scan FCC ASR records for dismantled, cancelled, or terminated antenna structures.

    Args:
        content: Optional raw pipe-delimited buffer string.
        fixture_path: Optional path to data file. If both content and fixture_path
            are None, defaults to DEFAULT_FCC_ASR_FIXTURE_PATH.

    Returns:
        List of formatted site IDs (e.g. ['ASR_1010008']).
    """
    if content is None:
        target = Path(fixture_path) if fixture_path is not None else DEFAULT_FCC_ASR_FIXTURE_PATH
        if not target.exists():
            return []
        content = target.read_text(encoding="utf-8", errors="replace")

    dismantled_ids: List[str] = []
    seen: Set[str] = set()

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split("|")]
        if not parts:
            continue

        rec_type = parts[0].upper()
        if rec_type == "ANT":
            if len(parts) < 4:
                continue
            reg_num = parts[1]
            field_2 = parts[2]
            is_lat_field_2 = bool(
                re.search(r"\d+[\-:\s°]\d+", field_2)
                or any(h in field_2.upper() for h in ("N", "S"))
            )
            idx_offset = 4 if is_lat_field_2 else 5
            status = parts[idx_offset + 7] if len(parts) > idx_offset + 7 else "CONSTRUCTED"
            if status.strip().upper() in DISMANTLED_STATUS_TOKENS:
                s_id = f"ASR_{reg_num}"
                if s_id not in seen:
                    seen.add(s_id)
                    dismantled_ids.append(s_id)
        elif len(parts) >= 4 and parts[0].isdigit():
            reg_num = parts[0]
            for field in parts[1:]:
                if field.strip().upper() in DISMANTLED_STATUS_TOKENS:
                    s_id = f"ASR_{reg_num}"
                    if s_id not in seen:
                        seen.add(s_id)
                        dismantled_ids.append(s_id)
                    break

    return dismantled_ids


class FCCASRAdapter(RegionalAdapterBase):
    """Regional adapter for Federal Communications Commission (FCC) Antenna Structure Registration (ASR)."""

    DEFAULT_FIXTURE = DEFAULT_FCC_ASR_FIXTURE_PATH

    def __init__(
        self,
        bounds: Optional[RegionalBounds] = None,
        fixture_path: Optional[Union[str, Path]] = None,
        ant_file: Optional[Union[str, Path]] = None,
        own_file: Optional[Union[str, Path]] = None,
        raw_content: Optional[str] = None,
        offline_mode: bool = True,
        rate_limiter: Optional[RateLimitBackoff] = None,
    ) -> None:
        super().__init__(
            name="fcc_asr",
            bounds=bounds,
            rate_limiter=rate_limiter or RateLimitBackoff(),
        )
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.ant_file = Path(ant_file) if ant_file else None
        self.own_file = Path(own_file) if own_file else None
        self.raw_content = raw_content
        self.offline_mode = offline_mode
        self._cached_sites: Optional[List[SiteCandidate]] = None

    def health_check(self) -> Result[bool]:
        """Verify FCC ASR adapter operating readiness."""
        if self.raw_content is not None:
            return Result[bool].success(True)

        target_file = self.ant_file or self.fixture_path or self.DEFAULT_FIXTURE
        if target_file and target_file.exists():
            return Result[bool].success(True)

        return Result[bool].fail(
            code="FIXTURE_NOT_FOUND",
            message=f"FCC ASR fixture or data file not found at {target_file}",
        )

    def parse_buffer(
        self,
        content: str,
        bounds: Optional[RegionalBounds] = None,
    ) -> Result[List[SiteCandidate]]:
        """Parse raw pipe-delimited buffer into site candidates."""
        effective_bounds = bounds or self.bounds
        try:
            sites = parse_asr_buffer(content, bounds=effective_bounds)
            return Result[List[SiteCandidate]].success(sites)
        except Exception as exc:
            return Result[List[SiteCandidate]].fail(
                code="ASR_PARSE_ERROR",
                message=f"Failed to parse ASR buffer: {exc}",
                details={"error": str(exc)},
            )

    def parse_file(
        self,
        path: Union[str, Path],
        bounds: Optional[RegionalBounds] = None,
    ) -> Result[List[SiteCandidate]]:
        """Parse pipe-delimited file into site candidates."""
        effective_bounds = bounds or self.bounds
        p = Path(path)
        if not p.exists():
            return Result[List[SiteCandidate]].fail(
                code="FILE_NOT_FOUND",
                message=f"File not found: {p}",
            )
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            return self.parse_buffer(content, bounds=effective_bounds)
        except Exception as exc:
            return Result[List[SiteCandidate]].fail(
                code="ASR_PARSE_ERROR",
                message=f"Failed to read/parse ASR file {p}: {exc}",
                details={"path": str(p), "error": str(exc)},
            )

    def fetch_sites(
        self,
        bounds: Optional[RegionalBounds] = None,
    ) -> Result[List[SiteCandidate]]:
        """Fetch FCC ASR site candidates within regional bounds."""
        effective_bounds = bounds or self.bounds

        # If raw content was injected
        if self.raw_content is not None:
            return self.parse_buffer(self.raw_content, bounds=effective_bounds)

        # If separate ANT / OWN files were specified
        if self.ant_file is not None:
            try:
                sites = parse_asr_files(
                    self.ant_file,
                    own_path=self.own_file,
                    bounds=effective_bounds,
                )
                return Result[List[SiteCandidate]].success(sites)
            except Exception as exc:
                return Result[List[SiteCandidate]].fail(
                    code="ASR_PARSE_ERROR",
                    message=f"Failed to parse ASR files: {exc}",
                    details={"error": str(exc)},
                )

        # Fallback to fixture path or default fixture
        target_fixture = self.fixture_path or self.DEFAULT_FIXTURE
        if not target_fixture.exists():
            return Result[List[SiteCandidate]].fail(
                code="FIXTURE_NOT_FOUND",
                message=f"FCC ASR fixture not found: {target_fixture}",
            )

        return self.parse_file(target_fixture, bounds=effective_bounds)
