"""Generic OpenStreetMap (OSM) Overpass API Adapter.

Provides sovereign fallback spatial discovery for towers, water towers,
and emergency infrastructure when regional GIS layers are unavailable.
"""

from __future__ import annotations

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
from meshscout.adapters.vt_vcgi import OwnershipTier, classify_ownership_tier
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    RegionalBounds,
    Result,
    SiteCandidate,
    SiteType,
)

DEFAULT_OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"


def build_overpass_query(bounds: RegionalBounds) -> str:
    """Construct Overpass QL query retrieving water towers, communications towers, and fire stations."""
    s, w, n, e = bounds.min_lat, bounds.min_lon, bounds.max_lat, bounds.max_lon
    return (
        f"[out:json][timeout:25];\n"
        f"(\n"
        f'  node["man_made"="water_tower"]({s},{w},{n},{e});\n'
        f'  way["man_made"="water_tower"]({s},{w},{n},{e});\n'
        f'  node["man_made"="tower"]({s},{w},{n},{e});\n'
        f'  way["man_made"="tower"]({s},{w},{n},{e});\n'
        f'  node["man_made"="mast"]({s},{w},{n},{e});\n'
        f'  way["man_made"="mast"]({s},{w},{n},{e});\n'
        f'  node["man_made"="communications_tower"]({s},{w},{n},{e});\n'
        f'  node["amenity"="fire_station"]({s},{w},{n},{e});\n'
        f'  way["amenity"="fire_station"]({s},{w},{n},{e});\n'
        f");\n"
        f"out center tags;"
    )


def _parse_height_tag(height_str: Optional[str], default_m: float) -> float:
    """Parse height tag string into float meters."""
    if not height_str:
        return default_m

    cleaned = str(height_str).strip().lower()
    match_m = re.search(r"^([0-9]+(?:\.[0-9]+)?)\s*(?:m|meters)?$", cleaned)
    if match_m:
        return float(match_m.group(1))

    match_ft = re.search(r"^([0-9]+(?:\.[0-9]+)?)\s*(?:ft|feet|')$", cleaned)
    if match_ft:
        return round(float(match_ft.group(1)) * 0.3048, 2)

    try:
        val = float(cleaned)
        if val >= 0.0:
            return round(val, 2)
    except ValueError:
        pass

    return default_m


class OSMRegionalAdapter(RegionalAdapterBase):
    """OpenStreetMap Overpass API adapter for physical high sites and emergency structures."""

    def __init__(
        self,
        bounds: Optional[RegionalBounds] = None,
        endpoint_url: str = DEFAULT_OVERPASS_ENDPOINT,
        fixture_path: Optional[Union[str, Path]] = None,
        raw_records: Optional[Sequence[Dict[str, Any]]] = None,
        offline_mode: bool = True,
        rate_limiter: Optional[RateLimitBackoff] = None,
    ) -> None:
        super().__init__(
            name="osm_overpass",
            bounds=bounds,
            rate_limiter=rate_limiter or RateLimitBackoff(),
        )
        self.endpoint_url = endpoint_url
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.raw_records = list(raw_records) if raw_records is not None else None
        self.offline_mode = offline_mode

    def build_query(self, bounds: Optional[RegionalBounds] = None) -> str:
        """Build Overpass QL query string for this adapter's regional bounds."""
        target_bounds = bounds or self.bounds
        if target_bounds is None:
            raise ValueError("Regional bounds must be provided to build Overpass query")
        return build_overpass_query(target_bounds)

    def parse_overpass_response(
        self,
        data: Dict[str, Any],
        bounds: Optional[RegionalBounds] = None,
    ) -> List[SiteCandidate]:
        """Parse raw Overpass JSON dictionary elements into SiteCandidate models."""
        effective_bounds = bounds or self.bounds
        elements = data.get("elements", [])
        candidates: List[SiteCandidate] = []

        for elem in elements:
            elem_id = elem.get("id")
            elem_type = elem.get("type", "node")
            tags = elem.get("tags", {})

            # Extract location
            lat: Optional[float] = None
            lon: Optional[float] = None
            if "lat" in elem and "lon" in elem:
                lat = float(elem["lat"])
                lon = float(elem["lon"])
            elif "center" in elem and isinstance(elem["center"], dict):
                lat = float(elem["center"].get("lat"))
                lon = float(elem["center"].get("lon"))

            if lat is None or lon is None:
                continue

            elev_m = 0.0
            if "ele" in tags:
                try:
                    elev_m = float(tags["ele"])
                except (ValueError, TypeError):
                    pass

            coord = Coordinate(lat=lat, lon=lon, elevation_m=elev_m)
            if effective_bounds is not None and not effective_bounds.contains(coord):
                continue

            # Classify site type
            man_made = tags.get("man_made", "").lower()
            amenity = tags.get("amenity", "").lower()
            tower_type = tags.get("tower:type", "").lower()

            if man_made == "water_tower":
                site_type = SiteType.WATER_TOWER
                default_height = 25.0
                access = AccessDifficulty.DRIVE_UP
            elif amenity == "fire_station":
                site_type = SiteType.BUILDING_ROOFTOP
                default_height = 8.0
                access = AccessDifficulty.DRIVE_UP
            elif tower_type == "observation":
                site_type = SiteType.FIRE_LOOKOUT
                default_height = 15.0
                access = AccessDifficulty.HIKE_IN
            elif man_made in ("tower", "mast", "communications_tower"):
                site_type = SiteType.COMMUNICATIONS_TOWER
                default_height = 30.0
                access = AccessDifficulty.DRIVE_UP
            else:
                site_type = SiteType.CUSTOM
                default_height = 5.0
                access = AccessDifficulty.MODERATE

            mast_height_m = _parse_height_tag(tags.get("height"), default_height)

            # Detect name
            name = (
                tags.get("name")
                or tags.get("description")
                or f"OSM {site_type.value.replace('_', ' ').title()} {elem_id}"
            )

            # Classify ownership tier
            owner_text = tags.get("operator") or tags.get("owner") or name
            tier = classify_ownership_tier(owner_text, attributes=tags)
            notes = f"[Ownership: {tier.value}] OSM {elem_type}/{elem_id}"

            site_id = f"OSM-{elem_type[0].upper()}-{elem_id}"
            candidates.append(
                SiteCandidate(
                    site_id=site_id,
                    name=name,
                    location=coord,
                    site_type=site_type,
                    mast_height_m=mast_height_m,
                    has_grid_power=True,
                    solar_exposure_pct=90.0,
                    access_difficulty=access,
                    notes=notes,
                )
            )

        return candidates

    def _fetch_online_overpass(self, query_bounds: RegionalBounds) -> List[SiteCandidate]:
        """Execute live query against Overpass API with RateLimitBackoff."""
        ql = self.build_query(query_bounds)
        req_data = urllib.parse.urlencode({"data": ql}).encode("utf-8")

        def _request_action() -> Dict[str, Any]:
            req = urllib.request.Request(
                self.endpoint_url,
                data=req_data,
                headers={
                    "User-Agent": "MeshScout/0.1.0 (OSM-Overpass-Fallback)",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=25.0) as resp:
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
        return self.parse_overpass_response(data, bounds=query_bounds)

    def fetch_sites(
        self, bounds: Optional[RegionalBounds] = None
    ) -> Result[List[SiteCandidate]]:
        """Fetch or parse site candidates from OSM Overpass."""
        effective_bounds = bounds or self.bounds

        if self.offline_mode:
            if self.raw_records is not None:
                payload = {"elements": self.raw_records}
                candidates = self.parse_overpass_response(payload, bounds=effective_bounds)
                return Result[List[SiteCandidate]].success(candidates)

            if self.fixture_path and self.fixture_path.exists():
                try:
                    payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
                    candidates = self.parse_overpass_response(payload, bounds=effective_bounds)
                    return Result[List[SiteCandidate]].success(candidates)
                except Exception as exc:
                    return Result[List[SiteCandidate]].fail(
                        code="OSM_FIXTURE_READ_FAILED",
                        message=f"Failed to read OSM fixture: {exc}",
                        details={"path": str(self.fixture_path), "error": str(exc)},
                    )

            return Result[List[SiteCandidate]].success([])

        # Online Overpass query
        if effective_bounds is None:
            return Result[List[SiteCandidate]].fail(
                code="NO_BOUNDS_SPECIFIED",
                message="Regional bounds must be specified for live OSM Overpass queries",
            )

        try:
            candidates = self._fetch_online_overpass(effective_bounds)
            return Result[List[SiteCandidate]].success(candidates)
        except Exception as exc:
            # Fallback to offline fixture/records if available
            if self.raw_records is not None:
                payload = {"elements": self.raw_records}
                candidates = self.parse_overpass_response(payload, bounds=effective_bounds)
                return Result[List[SiteCandidate]].success(candidates)

            return Result[List[SiteCandidate]].fail(
                code="OVERPASS_QUERY_FAILED",
                message=f"Failed to query OSM Overpass API: {exc}",
                details={"endpoint": self.endpoint_url, "error": str(exc)},
            )

    def health_check(self) -> Result[bool]:
        """Check status of OSM Overpass adapter."""
        if self.offline_mode:
            return Result[bool].success(True)

        try:
            status_url = self.endpoint_url.replace("/interpreter", "/status")

            def _ping() -> bool:
                req = urllib.request.Request(
                    status_url,
                    headers={"User-Agent": "MeshScout/0.1.0 (HealthCheck)"},
                )
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    return resp.status == 200

            ok = self.rate_limiter.execute(_ping)
            return Result[bool].success(ok)
        except Exception as exc:
            return Result[bool].fail(
                code="HEALTH_CHECK_FAILED",
                message=f"OSM Overpass endpoint unreachable: {exc}",
                details={"error": str(exc)},
            )
