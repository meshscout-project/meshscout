"""Vermont Center for Geographic Information (VCGI) Regional Adapter.

Ingests municipal assets, parcel boundaries, communications infrastructure,
and public structures from VCGI Open Geodata (ArcGIS REST and offline GeoJSON).
"""

from __future__ import annotations

from enum import Enum
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Union

from meshscout.adapters.base import (
    BaseRegionalAdapter,
    RateLimitBackoff,
    RateLimitConfig,
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

VERMONT_STATE_BOUNDS = RegionalBounds(
    name="Vermont_Statewide",
    min_lat=42.72,
    max_lat=45.02,
    min_lon=-73.44,
    max_lon=-71.46,
)

DEFAULT_VCGI_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "fixtures"
    / "vt_vcgi_sample.json"
)


class OwnershipTier(str, Enum):
    """Asset ownership category for municipal and regional infrastructure."""

    MUNICIPAL = "municipal"
    STATE = "state"
    PRIVATE_COMMERCIAL = "private/commercial"


def classify_ownership_tier(
    data: Union[str, Dict[str, Any], None] = None,
    attributes: Optional[Dict[str, Any]] = None,
) -> OwnershipTier:
    """Classify asset ownership into municipal, state, or private/commercial tiers.

    Inspects explicit ownership codes (MUNI, STATE, PRIV) and matches entity keywords.
    """
    attrs: Dict[str, Any] = {}
    owner_str = ""

    if isinstance(data, dict):
        attrs = data.get("attributes") or data.get("properties") or data
    elif isinstance(data, str):
        owner_str = data

    if attributes:
        attrs = {**attrs, **attributes}

    # 1. Check explicit categorical codes
    owner_type = str(
        attrs.get("OWNER_TYPE")
        or attrs.get("OWN_TYPE")
        or attrs.get("PROP_CLASS")
        or ""
    ).strip().upper()
    if owner_type in ("MUNI", "MUNICIPAL", "LOCAL", "CITY", "TOWN"):
        return OwnershipTier.MUNICIPAL
    if owner_type in ("STATE", "S", "VT_STATE", "AGENCY"):
        return OwnershipTier.STATE
    if owner_type in ("PRIV", "PRIVATE", "COMM", "COMMERCIAL", "CORP", "P"):
        return OwnershipTier.PRIVATE_COMMERCIAL

    # 2. Check pub_priv flag
    pub_priv = str(attrs.get("PUB_PRIV") or "").strip().upper()
    if pub_priv == "PRIV":
        return OwnershipTier.PRIVATE_COMMERCIAL

    # 3. Assemble text string for regex keyword matching
    tokens: List[str] = []
    if owner_str:
        tokens.append(owner_str)
    for field in (
        "OWNER",
        "OWNERSHIP",
        "MANAGING_AGENCY",
        "AGENCY",
        "OPERATOR",
        "FACNAME",
        "NAME",
        "SITE_NAME",
        "BLDG_NAME",
    ):
        val = attrs.get(field)
        if val is not None:
            tokens.append(str(val))

    text = " ".join(tokens).lower()

    # Match municipal indicators
    municipal_patterns = [
        r"\btown of\b",
        r"\bcity of\b",
        r"\bvillage of\b",
        r"\bmunicipal\b",
        r"\bmunicipality\b",
        r"\bwater dist\w*\b",
        r"\bfire dist\w*\b",
        r"\bdpw\b",
        r"\bhighway dept\b",
        r"\bschool dist\w*\b",
        r"\bselectboard\b",
        r"\bcity hall\b",
        r"\btown hall\b",
        r"\bvolunteer fire\b",
    ]
    for pat in municipal_patterns:
        if re.search(pat, text):
            return OwnershipTier.MUNICIPAL

    # Match state indicators
    state_patterns = [
        r"\bstate of vermont\b",
        r"\bstate of vt\b",
        r"\bvermont state\b",
        r"\bvt dps\b",
        r"\bstate police\b",
        r"\bvtrans\b",
        r"\bstate agency\b",
        r"\bstate dept\b",
        r"\bstate office\b",
        r"\bstate park\b",
        r"\buvm\b",
        r"\buniversity of vermont\b",
        r"\bdepartment of public safety\b",
        r"\bagency of transportation\b",
        r"\bagency of natural resources\b",
        r"\bstate public\b",
        r"\bvermont agency\b",
        r"\bbgs\b",
    ]
    for pat in state_patterns:
        if re.search(pat, text):
            return OwnershipTier.STATE

    # Match private / commercial indicators
    private_patterns = [
        r"\bamerican tower\b",
        r"\bcrown castle\b",
        r"\bsba\b",
        r"\bverizon\b",
        r"\bat&t\b",
        r"\bt-mobile\b",
        r"\bfirstlight\b",
        r"\bconsolidated communications\b",
        r"\bgreen mountain power\b",
        r"\bgmp\b",
        r"\bcommercial\b",
        r"\bprivate\b",
        r"\bcorp\b",
        r"\bcorporation\b",
        r"\binc\b",
        r"\bllc\b",
        r"\bl\.l\.c\b",
        r"\bcooperative\b",
        r"\bco-op\b",
        r"\bcellco\b",
    ]
    for pat in private_patterns:
        if re.search(pat, text):
            return OwnershipTier.PRIVATE_COMMERCIAL

    # General fallback
    if "state" in text:
        return OwnershipTier.STATE
    if any(k in text for k in ("town", "city", "village", "fire dept", "fire department")):
        return OwnershipTier.MUNICIPAL

    return OwnershipTier.PRIVATE_COMMERCIAL


def _extract_coordinate(record: Dict[str, Any]) -> Optional[Coordinate]:
    """Extract and validate WGS84 EPSG:4326 Coordinate from GeoJSON or Esri JSON."""
    lat: Optional[float] = None
    lon: Optional[float] = None
    elev_m: float = 0.0

    geom = record.get("geometry")
    if isinstance(geom, dict):
        # GeoJSON Point
        coords = geom.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lon = float(coords[0])
                lat = float(coords[1])
                if len(coords) >= 3 and coords[2] is not None:
                    elev_m = float(coords[2])
            except (ValueError, TypeError):
                pass
        # Esri JSON Point
        elif "x" in geom and "y" in geom:
            try:
                lon = float(geom["x"])
                lat = float(geom["y"])
                if "z" in geom and geom["z"] is not None:
                    elev_m = float(geom["z"])
            except (ValueError, TypeError):
                pass

    attrs = record.get("attributes") or record.get("properties") or record
    if lat is None:
        for k in ("lat", "latitude", "LAT", "LATITUDE", "y", "Y"):
            v = attrs.get(k)
            if v is not None:
                try:
                    lat = float(v)
                    break
                except (ValueError, TypeError):
                    pass

    if lon is None:
        for k in ("lon", "longitude", "LON", "LONGITUDE", "x", "X"):
            v = attrs.get(k)
            if v is not None:
                try:
                    lon = float(v)
                    break
                except (ValueError, TypeError):
                    pass

    if elev_m == 0.0:
        for k in ("elevation_m", "elevation", "ELEV_M", "ELEVM", "ELEVATION_M", "z", "Z"):
            v = attrs.get(k)
            if v is not None:
                try:
                    elev_m = float(v)
                    break
                except (ValueError, TypeError):
                    pass
        if elev_m == 0.0:
            for k in ("ELEV_FT", "ELEVFT", "elevation_ft"):
                v = attrs.get(k)
                if v is not None:
                    try:
                        elev_m = float(v) * 0.3048
                        break
                    except (ValueError, TypeError):
                        pass

    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    return Coordinate(lat=lat, lon=lon, elevation_m=round(elev_m, 2))


def _detect_site_type(attrs: Dict[str, Any]) -> SiteType:
    """Map VCGI asset attributes to SiteType enumeration."""
    tokens = []
    for k in (
        "site_type",
        "FEATURE_TYPE",
        "FACILITY_TYPE",
        "STRUCTURE_TYPE",
        "TYPE",
        "DESCRIPT",
        "CATEGORY",
        "BLDG_TYPE",
        "FACNAME",
        "NAME",
    ):
        v = attrs.get(k)
        if v:
            tokens.append(str(v).lower())
    text = " ".join(tokens)

    if any(w in text for w in ("water tower", "water tank", "standpipe", "reservoir tank", "water storage")):
        return SiteType.WATER_TOWER
    if any(w in text for w in ("comm", "tower", "mast", "antenna", "cell", "broadcast", "radio", "telecom")):
        return SiteType.COMMUNICATIONS_TOWER
    if any(w in text for w in ("fire lookout", "lookout tower")):
        return SiteType.FIRE_LOOKOUT
    if any(w in text for w in ("silo", "grain elevator")):
        return SiteType.SILO
    if any(w in text for w in ("mountain", "peak", "summit", "ridge")):
        return SiteType.MOUNTAIN_PEAK
    if any(w in text for w in ("fire station", "fire dept", "rescue", "police", "town hall", "municipal building", "city hall", "public works", "highway garage", "school", "library", "civic", "office", "public structure")):
        return SiteType.BUILDING_ROOFTOP

    return SiteType.BUILDING_ROOFTOP


def _detect_mast_height(attrs: Dict[str, Any], site_type: SiteType) -> float:
    """Detect antenna mast height in meters or assign domain default."""
    for k in ("mast_height_m", "HEIGHT_M", "STRUCT_HT", "TOWER_HT", "HEIGHT"):
        v = attrs.get(k)
        if v is not None:
            try:
                val = float(v)
                if val >= 0.0:
                    return round(val, 2)
            except (ValueError, TypeError):
                pass
    for k in ("HEIGHT_FT", "TOWER_HT_FT", "STRUCT_HT_FT"):
        v = attrs.get(k)
        if v is not None:
            try:
                val = float(v) * 0.3048
                if val >= 0.0:
                    return round(val, 2)
            except (ValueError, TypeError):
                pass

    defaults = {
        SiteType.WATER_TOWER: 25.0,
        SiteType.COMMUNICATIONS_TOWER: 30.0,
        SiteType.FIRE_LOOKOUT: 15.0,
        SiteType.SILO: 12.0,
        SiteType.BUILDING_ROOFTOP: 8.0,
        SiteType.MOUNTAIN_PEAK: 5.0,
        SiteType.CUSTOM: 5.0,
    }
    return defaults.get(site_type, 5.0)


def _detect_grid_power(attrs: Dict[str, Any], site_type: SiteType) -> bool:
    """Detect presence of grid utility AC power."""
    for k in ("has_grid_power", "GRID_POWER", "POWER", "ELECTRIC"):
        v = attrs.get(k)
        if v is not None:
            if isinstance(v, bool):
                return v
            if str(v).lower() in ("true", "1", "yes", "y", "t"):
                return True
            if str(v).lower() in ("false", "0", "no", "n", "f"):
                return False

    if site_type in (SiteType.BUILDING_ROOFTOP, SiteType.COMMUNICATIONS_TOWER, SiteType.WATER_TOWER):
        return True
    return False


def _detect_access_difficulty(attrs: Dict[str, Any], site_type: SiteType) -> AccessDifficulty:
    """Detect physical access difficulty."""
    for k in ("access_difficulty", "ACCESS_DIFF", "ACCESS"):
        v = attrs.get(k)
        if v:
            try:
                return AccessDifficulty(str(v).lower())
            except ValueError:
                pass

    if site_type in (SiteType.BUILDING_ROOFTOP, SiteType.WATER_TOWER):
        return AccessDifficulty.DRIVE_UP
    if site_type == SiteType.FIRE_LOOKOUT:
        return AccessDifficulty.HIKE_IN
    if site_type == SiteType.MOUNTAIN_PEAK:
        return AccessDifficulty.MODERATE
    return AccessDifficulty.DRIVE_UP


def _detect_solar_exposure(attrs: Dict[str, Any], site_type: SiteType) -> float:
    """Detect estimated unshaded solar percentage."""
    for k in ("solar_exposure_pct", "SOLAR_PCT", "SOLAR"):
        v = attrs.get(k)
        if v is not None:
            try:
                val = float(v)
                if 0.0 <= val <= 100.0:
                    return val
            except (ValueError, TypeError):
                pass

    defaults = {
        SiteType.WATER_TOWER: 95.0,
        SiteType.COMMUNICATIONS_TOWER: 95.0,
        SiteType.MOUNTAIN_PEAK: 95.0,
        SiteType.FIRE_LOOKOUT: 90.0,
        SiteType.BUILDING_ROOFTOP: 85.0,
        SiteType.SILO: 80.0,
        SiteType.CUSTOM: 80.0,
    }
    return defaults.get(site_type, 85.0)


class VCGIRegionalAdapter(RegionalAdapterBase):
    """Regional adapter for Vermont VCGI Open Geodata municipal assets and parcels."""

    def __init__(
        self,
        bounds: Optional[RegionalBounds] = None,
        fixture_path: Optional[Union[str, Path]] = None,
        raw_records: Optional[Sequence[Dict[str, Any]]] = None,
        arcgis_url: Optional[str] = None,
        offline_mode: bool = True,
        rate_limiter: Optional[RateLimitBackoff] = None,
    ) -> None:
        super().__init__(
            name="vt_vcgi",
            bounds=bounds or VERMONT_STATE_BOUNDS,
            rate_limiter=rate_limiter or RateLimitBackoff(),
        )
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.raw_records = list(raw_records) if raw_records is not None else None
        self.arcgis_url = arcgis_url
        self.offline_mode = offline_mode

    def parse_record(self, record: Dict[str, Any], idx: int = 1) -> Optional[SiteCandidate]:
        """Parse an individual VCGI record or feature dictionary into a SiteCandidate."""
        coord = _extract_coordinate(record)
        if coord is None:
            return None

        attrs = record.get("attributes") or record.get("properties") or record
        site_type = _detect_site_type(attrs)

        # Detect site_id
        site_id = ""
        for k in ("site_id", "FACILITY_ID", "FAC_ID", "ID", "OBJECTID", "TOWER_ID", "GLOBALID"):
            v = attrs.get(k)
            if v is not None and str(v).strip():
                site_id = str(v).strip()
                break
        if not site_id:
            site_id = f"VT-VCGI-{idx:04d}"

        # Detect name
        name = ""
        for k in ("name", "FACNAME", "FACILITY_NAME", "SITE_NAME", "BLDG_NAME", "LABEL", "NAME"):
            v = attrs.get(k)
            if v is not None and str(v).strip():
                name = str(v).strip()
                break
        if not name:
            name = f"{site_type.value.replace('_', ' ').title()} ({site_id})"

        mast_height_m = _detect_mast_height(attrs, site_type)
        has_grid_power = _detect_grid_power(attrs, site_type)
        access_diff = _detect_access_difficulty(attrs, site_type)
        solar_pct = _detect_solar_exposure(attrs, site_type)

        tier = classify_ownership_tier(attributes=attrs)
        raw_notes = attrs.get("notes") or attrs.get("NOTES") or attrs.get("DESCRIPT") or ""
        notes = f"[Ownership: {tier.value}] {raw_notes}".strip()

        return SiteCandidate(
            site_id=site_id,
            name=name,
            location=coord,
            site_type=site_type,
            mast_height_m=mast_height_m,
            has_grid_power=has_grid_power,
            solar_exposure_pct=solar_pct,
            access_difficulty=access_diff,
            notes=notes if notes else None,
        )

    def parse_records(
        self,
        records: Sequence[Dict[str, Any]],
        bounds: Optional[RegionalBounds] = None,
    ) -> List[SiteCandidate]:
        """Convert a sequence of records into filtered SiteCandidate models."""
        effective_bounds = bounds or self.bounds
        candidates: List[SiteCandidate] = []

        for idx, rec in enumerate(records, start=1):
            site = self.parse_record(rec, idx=idx)
            if site is None:
                continue
            if effective_bounds is not None and not effective_bounds.contains(site.location):
                continue
            candidates.append(site)

        return candidates

    def _load_offline_records(self) -> List[Dict[str, Any]]:
        """Load records from in-memory list, configured fixture path, or default bundle."""
        if self.raw_records is not None:
            return self.raw_records

        path = self.fixture_path
        if path is None or not path.exists():
            path = DEFAULT_VCGI_FIXTURE_PATH

        if not path.exists():
            return []

        raw_content = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw_content, list):
            return raw_content
        if isinstance(raw_content, dict):
            if "features" in raw_content and isinstance(raw_content["features"], list):
                return raw_content["features"]
            if "records" in raw_content and isinstance(raw_content["records"], list):
                return raw_content["records"]
            if "sites" in raw_content and isinstance(raw_content["sites"], list):
                return raw_content["sites"]

        return []

    def _fetch_online_arcgis(self, query_bounds: Optional[RegionalBounds]) -> List[SiteCandidate]:
        """Query live ArcGIS REST FeatureServer endpoint with RateLimitBackoff."""
        if not self.arcgis_url:
            raise ValueError("arcgis_url is not specified for live online queries")

        params: Dict[str, Any] = {
            "where": "1=1",
            "outFields": "*",
            "f": "json",
            "returnGeometry": "true",
            "outSR": "4326",
        }
        if query_bounds:
            params["geometry"] = (
                f"{query_bounds.min_lon},{query_bounds.min_lat},"
                f"{query_bounds.max_lon},{query_bounds.max_lat}"
            )
            params["geometryType"] = "esriGeometryEnvelope"
            params["inSR"] = "4326"
            params["spatialRel"] = "esriSpatialRelIntersects"

        url = f"{self.arcgis_url}/query?{urllib.parse.urlencode(params)}"

        def _request_action() -> Dict[str, Any]:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "MeshScout/0.1.0 (VCGI-Disaster-GIS)",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return json.loads(resp.read().decode("utf-8"))

        data = self.rate_limiter.execute(
            _request_action,
            retryable_exceptions=(
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                ConnectionError,
            ),
        )

        features = data.get("features", [])
        return self.parse_records(features, bounds=query_bounds)

    def fetch_sites(
        self, bounds: Optional[RegionalBounds] = None
    ) -> Result[List[SiteCandidate]]:
        """Fetch or parse site candidates within requested regional bounds."""
        effective_bounds = bounds or self.bounds

        if self.offline_mode:
            try:
                records = self._load_offline_records()
                candidates = self.parse_records(records, bounds=effective_bounds)
                return Result[List[SiteCandidate]].success(candidates)
            except Exception as exc:
                return Result[List[SiteCandidate]].fail(
                    code="VCGI_OFFLINE_LOAD_FAILED",
                    message=f"Failed to load VCGI offline records: {exc}",
                    details={"error": str(exc)},
                )

        # Online ArcGIS REST query with offline fallback
        try:
            candidates = self._fetch_online_arcgis(effective_bounds)
            return Result[List[SiteCandidate]].success(candidates)
        except Exception as exc:
            # Fallback to offline records
            try:
                records = self._load_offline_records()
                if records:
                    candidates = self.parse_records(records, bounds=effective_bounds)
                    return Result[List[SiteCandidate]].success(candidates)
            except Exception:
                pass

            return Result[List[SiteCandidate]].fail(
                code="ARCGIS_REST_FETCH_FAILED",
                message=f"Failed to query VCGI ArcGIS REST endpoint: {exc}",
                details={"url": self.arcgis_url, "error": str(exc)},
            )

    def health_check(self) -> Result[bool]:
        """Verify VCGI adapter operating state and data availability."""
        if self.offline_mode:
            records = self._load_offline_records()
            if records:
                return Result[bool].success(True)
            return Result[bool].fail(
                code="NO_OFFLINE_DATA",
                message="VCGI offline records and fixtures unavailable",
            )

        if not self.arcgis_url:
            return Result[bool].fail(
                code="NO_URL_CONFIGURED",
                message="Online mode requested but no arcgis_url configured",
            )

        try:
            ping_url = f"{self.arcgis_url}?f=json"

            def _ping() -> bool:
                req = urllib.request.Request(
                    ping_url,
                    headers={"User-Agent": "MeshScout/0.1.0 (HealthCheck)"},
                )
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    return resp.status == 200

            ok = self.rate_limiter.execute(_ping)
            return Result[bool].success(ok)
        except Exception as exc:
            return Result[bool].fail(
                code="HEALTH_CHECK_FAILED",
                message=f"VCGI endpoint unreachable: {exc}",
                details={"error": str(exc)},
            )

    @staticmethod
    def classify_site_ownership(site: SiteCandidate) -> OwnershipTier:
        """Extract or classify ownership tier directly from a SiteCandidate."""
        if site.notes:
            for tier in OwnershipTier:
                if f"[ownership: {tier.value}]" in site.notes.lower():
                    return tier
                if f"ownership: {tier.value}" in site.notes.lower():
                    return tier
        return classify_ownership_tier(site.name)
