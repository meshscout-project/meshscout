"""Pydantic v2 core schemas and contracts for MeshScout."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field, field_validator, model_validator


class SiteType(str, Enum):
    """Categorization of physical high sites."""
    MOUNTAIN_PEAK = "mountain_peak"
    COMMUNICATIONS_TOWER = "communications_tower"
    WATER_TOWER = "water_tower"
    SILO = "silo"
    FIRE_LOOKOUT = "fire_lookout"
    BUILDING_ROOFTOP = "building_rooftop"
    RESEARCH_TOWER = "research_tower"
    CUSTOM = "custom"


class AccessDifficulty(str, Enum):
    """Physical access difficulty for deployment and maintenance."""
    DRIVE_UP = "drive_up"
    MODERATE = "moderate"
    HIKE_IN = "hike_in"
    HELICOPTER = "helicopter"


class Coordinate(BaseModel):
    """Geodetic coordinate in EPSG:4326 with elevation in meters."""
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees (-90 to 90)")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees (-180 to 180)")
    elevation_m: float = Field(default=0.0, description="Ground elevation in meters above sea level")


class RegionalBounds(BaseModel):
    """Bounding box for geofenced regional analysis."""
    name: str = Field(..., min_length=1, description="Region identifier or name")
    min_lat: float = Field(..., ge=-90.0, le=90.0)
    max_lat: float = Field(..., ge=-90.0, le=90.0)
    min_lon: float = Field(..., ge=-180.0, le=180.0)
    max_lon: float = Field(..., ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def validate_bounds(self) -> RegionalBounds:
        if self.min_lat >= self.max_lat:
            raise ValueError(f"min_lat ({self.min_lat}) must be strictly less than max_lat ({self.max_lat})")
        if self.min_lon >= self.max_lon:
            raise ValueError(f"min_lon ({self.min_lon}) must be strictly less than max_lon ({self.max_lon})")
        return self

    def contains(self, coord: Coordinate) -> bool:
        """Check if a coordinate falls inside these regional bounds."""
        return (
            self.min_lat <= coord.lat <= self.max_lat
            and self.min_lon <= coord.lon <= self.max_lon
        )


class SiteCandidate(BaseModel):
    """Potential node or repeater high-site location."""
    site_id: str = Field(..., min_length=1, description="Unique site ID (e.g. VT-CHIT-01)")
    name: str = Field(..., min_length=1, description="Descriptive human-readable site name")
    location: Coordinate
    site_type: SiteType = Field(default=SiteType.CUSTOM)
    mast_height_m: float = Field(default=5.0, ge=0.0, description="Antenna mast height above ground in meters")
    has_grid_power: bool = Field(default=False, description="Whether continuous grid AC power is available")
    solar_exposure_pct: float = Field(default=100.0, ge=0.0, le=100.0, description="Estimated unshaded solar percentage")
    access_difficulty: AccessDifficulty = Field(default=AccessDifficulty.MODERATE)
    source_url: Optional[str] = None
    notes: Optional[str] = None


class ElevationPoint(BaseModel):
    """Sampled terrain point along a transect."""
    distance_m: float = Field(..., ge=0.0, description="Distance from transect start in meters")
    elevation_m: float = Field(..., description="Terrain surface elevation in meters")
    coordinate: Coordinate


class ElevationProfile(BaseModel):
    """Terrain profile between two candidate sites."""
    source_site: SiteCandidate
    target_site: SiteCandidate
    distance_km: float = Field(..., ge=0.0, description="Great circle distance in kilometers")
    points: List[ElevationPoint] = Field(default_factory=list, description="Ordered terrain elevation samples")


class RadioConfig(BaseModel):
    """Radio hardware RF parameters."""
    frequency_mhz: float = Field(default=915.0, gt=0.0, description="Carrier frequency in MHz (e.g. 915.0)")
    tx_power_dbm: float = Field(default=20.0, description="Transmit power in dBm (e.g. 20 dBm = 100mW)")
    rx_sensitivity_dbm: float = Field(default=-135.0, description="Receiver sensitivity threshold in dBm")
    antenna_gain_dbi: float = Field(default=3.0, description="Antenna gain in dBi")
    cable_loss_db: float = Field(default=1.0, ge=0.0, description="Coaxial transmission line loss in dB")
    environmental_clutter_db: float = Field(default=0.0, ge=0.0, description="Environmental foliage and clutter loss in dB")


class DowntiltAnalysisResult(BaseModel):
    """Antenna look-down angle and vertical beamwidth alignment metrics."""
    look_down_angle_deg: float = Field(..., description="Angle from local horizontal down to target receiver in degrees")
    vertical_beamwidth_deg: float = Field(..., description="Half-power vertical beamwidth (-3dB) in degrees based on antenna gain")
    is_overshooting: bool = Field(..., description="True if look-down angle exceeds half the antenna vertical beamwidth")
    recommended_downtilt_deg: float = Field(default=0.0, description="Recommended physical downtilt in degrees")
    pattern_attenuation_db: float = Field(default=0.0, description="Estimated antenna pattern roll-off attenuation due to beam misalignment")
    recommendation: str = Field(default="", description="Operator guidance for antenna selection or tilt bracket")


class LinkBudgetResult(BaseModel):
    """Calculated point-to-point RF link characteristics."""
    source_id: str
    target_id: str
    distance_km: float
    free_space_loss_db: float
    diffraction_loss_db: float
    total_path_loss_db: float
    rx_power_dbm: float
    link_margin_db: float
    has_line_of_sight: bool
    fresnel_clearance_ratio: float = Field(..., description="First Fresnel zone minimum clearance fraction")
    downtilt_analysis: Optional[DowntiltAnalysisResult] = None


class MeshScoutError(BaseModel):
    """Standardized error contract for fallible spatial and RF calculations."""
    code: str = Field(..., min_length=1, description="Machine-readable error code")
    message: str = Field(..., min_length=1, description="Human-readable error description")
    details: Optional[Dict[str, Any]] = None


T = TypeVar("T")


class Result(BaseModel, Generic[T]):
    """Explicit functional Result union pattern."""
    ok: bool
    value: Optional[T] = None
    error: Optional[MeshScoutError] = None

    @classmethod
    def success(cls, value: T) -> Result[T]:
        return cls(ok=True, value=value, error=None)

    @classmethod
    def fail(cls, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Result[T]:
        err = MeshScoutError(code=code, message=message, details=details)
        return cls(ok=False, value=None, error=err)
