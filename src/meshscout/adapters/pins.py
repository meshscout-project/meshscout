"""Ad-hoc community tactical pin adapter for MeshScout.

Enables community members to drop tactical pins with automatic terrain elevation sampling,
converting ad-hoc tactical pins into first-class SiteCandidate contracts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
import uuid

from pydantic import BaseModel, Field

try:
    from meshscout.core.models import (  # type: ignore
        AccessDifficulty,
        Coordinate,
        SiteCandidate,
        SiteType,
    )
except ImportError:
    from meshscout.core.contracts import (
        AccessDifficulty,
        Coordinate,
        SiteCandidate,
        SiteType,
    )

try:
    from meshscout.core.itm import _synthetic_vermont_elevation_fn  # type: ignore
except ImportError:
    try:
        from meshscout.adapters.elevation import _synthetic_vermont_elevation_fn
    except ImportError:
        def _synthetic_vermont_elevation_fn(lat: float, lon: float) -> float:
            east_progress = max(0.0, min(1.0, (lon - (-73.30)) / 0.50))
            valley_base = 65.0 + 180.0 * (east_progress ** 1.6)
            ridge_bonus = 950.0 * max(0.0, 1.0 - abs(lon - (-72.8143)) / 0.12) ** 2
            return round(valley_base + ridge_bonus, 2)


class AdHocPin(BaseModel):
    """User-submitted or ad-hoc tactical pin location."""
    pin_id: str = Field(default_factory=lambda: f"pin_{uuid.uuid4().hex[:8]}")
    name: str = Field(..., min_length=1)
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elevation_m: float = Field(..., ge=-100.0, le=9000.0)
    mast_height_m: float = Field(default=10.0, ge=1.0, le=300.0)
    site_type: SiteType = Field(default=SiteType.BUILDING_ROOFTOP)
    notes: str = Field(default="")
    source_url: Optional[str] = None
    created_at_iso: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def sample_terrain_elevation(
    lat: float,
    lon: float,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
) -> float:
    """Sample terrain elevation at given lat/lon coordinates.

    If elevation_fn is provided: returns round(elevation_fn(lat, lon), 1).
    Otherwise uses the deterministic Vermont synthetic elevation model.
    Returned elevation is always rounded to 1 decimal place.
    """
    if elevation_fn is not None:
        return round(float(elevation_fn(lat, lon)), 1)
    return round(float(_synthetic_vermont_elevation_fn(lat, lon)), 1)


def create_ad_hoc_pin(
    name: str,
    lat: float,
    lon: float,
    mast_height_m: float = 10.0,
    site_type: SiteType = SiteType.BUILDING_ROOFTOP,
    notes: str = "",
    elevation_m: Optional[float] = None,
    pin_id: Optional[str] = None,
    source_url: Optional[str] = None,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
) -> AdHocPin:
    """Create an AdHocPin, auto-sampling terrain elevation if omitted."""
    if elevation_m is None:
        elevation_m = sample_terrain_elevation(lat, lon, elevation_fn=elevation_fn)

    init_kwargs: Dict[str, Any] = {
        "name": name,
        "lat": lat,
        "lon": lon,
        "mast_height_m": mast_height_m,
        "site_type": site_type,
        "notes": notes,
        "elevation_m": elevation_m,
    }
    if pin_id is not None:
        init_kwargs["pin_id"] = pin_id
    if source_url is not None:
        init_kwargs["source_url"] = source_url

    return AdHocPin(**init_kwargs)


def pin_to_site_candidate(pin: AdHocPin) -> SiteCandidate:
    """Convert an AdHocPin into a fully valid SiteCandidate model."""
    candidate = SiteCandidate(
        site_id=f"adhoc_{pin.pin_id}",
        name=pin.name,
        location=Coordinate(lat=pin.lat, lon=pin.lon, elevation_m=pin.elevation_m),
        mast_height_m=pin.mast_height_m,
        site_type=pin.site_type,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        has_grid_power=True,
        solar_exposure_pct=85.0,
        notes=f"Community Tactical Pin: {pin.notes}".strip(),
        source_url=pin.source_url or "https://meshscout.local/ad-hoc",
    )
    object.__setattr__(candidate, "county", "Custom / Ad-Hoc")
    object.__setattr__(candidate, "is_public_land", False)
    return candidate
