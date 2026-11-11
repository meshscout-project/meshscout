"""Vermont 14 Counties Regional Adapter for MeshScout.

Provides WGS84 bounding boxes, verified candidate high sites, and regional fixture
loading across all 14 Vermont counties.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from meshscout.core.contracts import (
    MeshScoutError,
    RegionalBounds,
    Result,
    SiteCandidate,
    SiteType,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures"
VT_14_COUNTIES_FIXTURE = FIXTURES_DIR / "vt_14_counties_sample.json"

# WGS84 Bounding Boxes for all 14 Vermont counties (42.7 <= lat <= 45.1, -73.5 <= lon <= -71.4)
VERMONT_COUNTY_BOUNDS: Dict[str, RegionalBounds] = {
    "Addison": RegionalBounds(
        name="Vermont_Addison_County",
        min_lat=43.85,
        max_lat=44.30,
        min_lon=-73.45,
        max_lon=-72.85,
    ),
    "Bennington": RegionalBounds(
        name="Vermont_Bennington_County",
        min_lat=42.73,
        max_lat=43.30,
        min_lon=-73.30,
        max_lon=-72.80,
    ),
    "Caledonia": RegionalBounds(
        name="Vermont_Caledonia_County",
        min_lat=44.20,
        max_lat=44.75,
        min_lon=-72.35,
        max_lon=-71.75,
    ),
    "Chittenden": RegionalBounds(
        name="Vermont_Chittenden_County",
        min_lat=44.25,
        max_lat=44.65,
        min_lon=-73.35,
        max_lon=-72.75,
    ),
    "Essex": RegionalBounds(
        name="Vermont_Essex_County",
        min_lat=44.45,
        max_lat=45.02,
        min_lon=-71.95,
        max_lon=-71.48,
    ),
    "Franklin": RegionalBounds(
        name="Vermont_Franklin_County",
        min_lat=44.65,
        max_lat=45.02,
        min_lon=-73.25,
        max_lon=-72.45,
    ),
    "Grand Isle": RegionalBounds(
        name="Vermont_Grand_Isle_County",
        min_lat=44.55,
        max_lat=45.02,
        min_lon=-73.40,
        max_lon=-73.15,
    ),
    "Lamoille": RegionalBounds(
        name="Vermont_Lamoille_County",
        min_lat=44.40,
        max_lat=44.80,
        min_lon=-72.85,
        max_lon=-72.40,
    ),
    "Orange": RegionalBounds(
        name="Vermont_Orange_County",
        min_lat=43.85,
        max_lat=44.28,
        min_lon=-72.70,
        max_lon=-72.05,
    ),
    "Orleans": RegionalBounds(
        name="Vermont_Orleans_County",
        min_lat=44.65,
        max_lat=45.02,
        min_lon=-72.55,
        max_lon=-71.90,
    ),
    "Rutland": RegionalBounds(
        name="Vermont_Rutland_County",
        min_lat=43.30,
        max_lat=43.90,
        min_lon=-73.40,
        max_lon=-72.70,
    ),
    "Washington": RegionalBounds(
        name="Vermont_Washington_County",
        min_lat=44.05,
        max_lat=44.55,
        min_lon=-72.92,
        max_lon=-72.35,
    ),
    "Windham": RegionalBounds(
        name="Vermont_Windham_County",
        min_lat=42.72,
        max_lat=43.20,
        min_lon=-73.00,
        max_lon=-72.40,
    ),
    "Windsor": RegionalBounds(
        name="Vermont_Windsor_County",
        min_lat=43.20,
        max_lat=43.85,
        min_lon=-72.85,
        max_lon=-72.30,
    ),
}

VERMONT_STATE_BOUNDS = RegionalBounds(
    name="Vermont_Statewide",
    min_lat=42.72,
    max_lat=45.02,
    min_lon=-73.44,
    max_lon=-71.46,
)


def list_vermont_counties() -> List[str]:
    """Return the alphabetical list of all 14 Vermont counties."""
    return sorted(list(VERMONT_COUNTY_BOUNDS.keys()))


def _normalize_site_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize raw site dict values into valid SiteCandidate properties."""
    data = dict(raw)
    raw_type = data.get("site_type")
    if raw_type == "mountain_summit":
        data["site_type"] = SiteType.MOUNTAIN_PEAK.value
    if "source_url" in raw:
        data["source_url"] = raw.get("source_url")
    return data


def load_county_candidates(
    county_name_or_all: str = "all",
    fixture_path: Optional[Path] = None,
) -> Result[List[SiteCandidate]]:
    """Load high-site candidates from vt_14_counties_sample.json.

    Args:
        county_name_or_all: County name (e.g. 'Rutland', 'washington', 'Lamoille County')
                           or 'all'/'vt_statewide' for all 14 counties.
        fixture_path: Optional override path for the sample fixture.

    Returns:
        Result containing the filtered list of SiteCandidates or a MeshScoutError.
    """
    path = fixture_path or VT_14_COUNTIES_FIXTURE
    if not path.exists():
        return Result.fail(
            code="FIXTURE_NOT_FOUND",
            message=f"County candidates fixture not found at {path}",
            details={"path": str(path)},
        )

    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return Result.fail(
            code="FIXTURE_PARSE_ERROR",
            message=f"Failed to parse JSON fixture: {exc}",
            details={"error": str(exc)},
        )

    raw_sites: List[Dict[str, Any]]
    if isinstance(raw_data, list):
        raw_sites = raw_data
    elif isinstance(raw_data, dict):
        raw_sites = raw_data.get("sites", [])
    else:
        return Result.fail(
            code="INVALID_FIXTURE_STRUCTURE",
            message="Fixture JSON must be a list or dict with 'sites' key",
        )

    query = county_name_or_all.strip().lower()
    is_all = query in ("all", "vt_statewide", "vermont", "vt", "*", "")

    matched_county: Optional[str] = None
    if not is_all:
        clean_query = query.removeprefix("vt_").removesuffix("_county").removesuffix(" county").strip()
        for county_name in VERMONT_COUNTY_BOUNDS:
            if county_name.lower() == clean_query or county_name.lower() == query:
                matched_county = county_name
                break
        if not matched_county:
            return Result.fail(
                code="UNKNOWN_COUNTY",
                message=f"Unknown Vermont county '{county_name_or_all}'. Valid counties: {list_vermont_counties()}",
                details={"requested": county_name_or_all},
            )

    candidates: List[SiteCandidate] = []
    for item in raw_sites:
        item_county = str(item.get("county", "")).strip()
        if is_all or (matched_county and item_county.lower() == matched_county.lower()):
            normalized = _normalize_site_dict(item)
            try:
                candidate = SiteCandidate.model_validate(normalized)
                candidates.append(candidate)
            except Exception as exc:
                return Result.fail(
                    code="SITE_VALIDATION_ERROR",
                    message=f"Failed to validate site candidate {item.get('site_id')}: {exc}",
                    details={"item": item, "error": str(exc)},
                )

    return Result.success(candidates)


def load_regional_fixtures(
    region: str = "vt_chittenden",
) -> Tuple[RegionalBounds, List[SiteCandidate]]:
    """Load regional bounds and candidates for any Vermont county, statewide, or default region.

    Seamlessly integrates with `mcp_server.load_regional_fixtures`, supporting county
    names (e.g. 'rutland', 'washington', 'lamoille', 'windham'), 'all', or 'vt_statewide'.
    """
    region_key = region.strip().lower()
    clean_key = region_key.removeprefix("vt_").removesuffix("_county").removesuffix(" county").strip()

    # 1. Statewide check (merging county candidates with core fixtures if present)
    if region_key in ("all", "vt_statewide", "vermont", "vt", "*"):
        bounds = VERMONT_STATE_BOUNDS
        res = load_county_candidates("all")
        candidates = res.value if res.ok and res.value else []
        try:
            import meshscout.mcp_server as _mcp_ref
            orig_fn = getattr(_mcp_ref, "_orig_load_regional_fixtures", None)
            if orig_fn:
                _, orig_sites = orig_fn("vt_statewide")
                by_id = {s.site_id: s for s in orig_sites}
                for s in candidates:
                    by_id.setdefault(s.site_id, s)
                candidates = list(by_id.values())
        except Exception:
            pass
        return bounds, candidates

    # 2. County check against 14 Vermont counties
    matched_county = next(
        (c for c in VERMONT_COUNTY_BOUNDS if c.lower() == clean_key or c.lower() == region_key),
        None,
    )
    if matched_county:
        bounds = VERMONT_COUNTY_BOUNDS[matched_county]
        res = load_county_candidates(matched_county)
        candidates = res.value if res.ok and res.value else []
        return bounds, candidates

    # 3. Default fallback (e.g. vt_chittenden or other legacy identifiers)
    try:
        import meshscout.mcp_server as _mcp_ref
        orig_fn = getattr(_mcp_ref, "_orig_load_regional_fixtures", None)
        if orig_fn:
            return orig_fn(region)
    except Exception:
        pass

    bounds = VERMONT_COUNTY_BOUNDS.get("Chittenden", VERMONT_STATE_BOUNDS)
    res = load_county_candidates("Chittenden")
    candidates = res.value if res.ok and res.value else []
    return bounds, candidates

