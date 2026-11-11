"""Co-Location RF Desense and Site Viability Scorer for MeshScout.

Follows Functional Core / Imperative Shell architecture: zero I/O, deterministic math,
and strict Pydantic v2 contracts. Evaluates front-end LNA overload / desense risk from
nearby high-power 850-940 MHz cellular/paging transmitters and ranks civic infrastructure
(municipal water towers, fire lookouts, agricultural silos) above high-lease commercial
carrier towers.
"""

from __future__ import annotations

from enum import Enum
import math
from typing import Dict, List, Optional, Sequence, Tuple
from pydantic import BaseModel, Field

from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    Result,
    SiteCandidate,
    SiteType,
)

EARTH_RADIUS_M: float = 6_371_000.0

COMMERCIAL_TOWER_KEYWORDS: Tuple[str, ...] = (
    "american tower",
    "crown castle",
    "sba",
    "leased",
    "commercial",
    "cellular",
    "verizon",
    "at&t",
    "t-mobile",
)

CIVIC_FRIENDLY_KEYWORDS: Tuple[str, ...] = (
    "municipal",
    "town",
    "city",
    "fire",
    "water",
    "public",
    "cooperative",
    "school",
    "university",
    "farm",
    "silo",
)


class DesenseRiskLevel(str, Enum):
    """Severity of receiver front-end LNA overload / desense on 902-928 MHz ISM."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class EmitterSpec(BaseModel):
    """High-power RF emitter specification (e.g. FCC ASR/ULS licensed transmitter)."""

    emitter_id: str = Field(..., min_length=1, description="Unique emitter identifier or callsign")
    location: Coordinate
    frequency_mhz: float = Field(..., gt=0.0, description="Transmit carrier frequency in MHz")
    erp_watts: float = Field(default=100.0, gt=0.0, description="Effective Radiated Power (ERP) in Watts")
    service_type: str = Field(default="cellular", description="Service category (e.g. cellular, paging, smr, fm)")


class SiteViabilityScore(BaseModel):
    """Composite deployment viability and RF co-location assessment for a candidate site."""

    site: SiteCandidate
    composite_score: float = Field(..., ge=0.0, le=100.0, description="Overall viability score (0-100)")
    access_and_ownership_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Civic ownership and lease friendliness score (0-100)",
    )
    structural_and_power_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Mast elevation, grid/solar autonomy, and access difficulty score (0-100)",
    )
    rf_cleanliness_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="RF noise floor and front-end overload cleanliness score (0-100)",
    )
    desense_risk: DesenseRiskLevel
    requires_cavity_filter: bool = Field(
        ...,
        description="True if 902-928 MHz bandpass cavity filter is required to prevent LNA desense",
    )
    recommended_hardware_notes: List[str] = Field(default_factory=list)


def _haversine_distance_m(c1: Coordinate, c2: Coordinate) -> float:
    """Compute surface Haversine distance in meters between two WGS84 coordinates."""
    lat1 = math.radians(c1.lat)
    lat2 = math.radians(c2.lat)
    dlat = lat2 - lat1
    dlon = math.radians(c2.lon - c1.lon)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    horiz_m = EARTH_RADIUS_M * c
    dz_m = c2.elevation_m - c1.elevation_m
    return math.hypot(horiz_m, dz_m)


def _is_commercial_carrier_tower(site: SiteCandidate) -> bool:
    """Identify leased commercial telecom towers from site type and metadata."""
    text = f"{site.name} {site.notes or ''}".lower()
    if any(kw in text for kw in COMMERCIAL_TOWER_KEYWORDS):
        return True
    return site.site_type == SiteType.COMMUNICATIONS_TOWER and not any(
        kw in text for kw in CIVIC_FRIENDLY_KEYWORDS
    )


def evaluate_rf_desense_risk(
    site: SiteCandidate,
    nearby_emitters: Sequence[EmitterSpec] = (),
) -> Tuple[float, DesenseRiskLevel, bool, List[str]]:
    """Evaluate 902-928 MHz receiver front-end overload and out-of-band blocking risk.

    SX1262/SX1276 LoRa transceivers with wide-open front-end LNAs experience severe
    compression and phase-noise desensitization when co-located near high-ERP
    850-894 MHz cellular, 896-901 MHz SMR, or 929-941 MHz paging transmitters.

    Returns:
        Tuple of `(rf_cleanliness_score, desense_risk, requires_cavity_filter, notes)`.
    """
    penalty = 0.0
    requires_cavity = False
    notes: List[str] = []

    is_comm_tower = _is_commercial_carrier_tower(site)
    if is_comm_tower:
        # Commercial communications towers typically host 850 MHz cellular / 900 MHz SMR arrays
        penalty += 45.0
        requires_cavity = True

    max_coupled_dbm = -120.0
    for emitter in nearby_emitters:
        dist_m = max(_haversine_distance_m(site.location, emitter.location), 5.0)
        dist_km = dist_m / 1000.0

        # ERP in Watts -> EIRP in dBm (EIRP = ERP * 1.64 -> +2.15 dB, +30 dBm/W)
        eirp_dbm = 10.0 * math.log10(emitter.erp_watts) + 32.15
        fspl_db = 32.44 + 20.0 * math.log10(dist_km) + 20.0 * math.log10(emitter.frequency_mhz)
        coupled_dbm = eirp_dbm - fspl_db

        # Spectral proximity weighting relative to 902-928 MHz US915 band center (915 MHz)
        freq_offset_mhz = min(
            abs(emitter.frequency_mhz - 915.0),
            abs(emitter.frequency_mhz - 902.0),
            abs(emitter.frequency_mhz - 928.0),
        )
        if 845.0 <= emitter.frequency_mhz <= 945.0:
            # Near-band 850 MHz cellular, 900 MHz SMR/paging, 930 MHz paging
            band_weight = 1.0 if freq_offset_mhz <= 25.0 else 0.75
        elif 700.0 <= emitter.frequency_mhz < 845.0 or 945.0 < emitter.frequency_mhz <= 1000.0:
            band_weight = 0.45
        else:
            # VHF / FM / UHF broadcast harmonics and wideband LNA overload
            band_weight = 0.25

        # Threshold where unfiltered LNA begins saturating is roughly -25 dBm to -10 dBm
        excess_db = (coupled_dbm + 25.0) * band_weight
        if excess_db > 0.0:
            penalty += min(65.0, excess_db * 2.2)
        if coupled_dbm > max_coupled_dbm and band_weight >= 0.75:
            max_coupled_dbm = coupled_dbm

        if (coupled_dbm >= -20.0 and band_weight >= 0.75) or (dist_m <= 250.0 and emitter.erp_watts >= 50.0 and 845.0 <= emitter.frequency_mhz <= 945.0):
            requires_cavity = True

    rf_cleanliness_score = max(0.0, min(100.0, 100.0 - penalty))

    if rf_cleanliness_score < 35.0 or max_coupled_dbm >= -5.0:
        risk = DesenseRiskLevel.CRITICAL
        requires_cavity = True
    elif rf_cleanliness_score < 60.0 or requires_cavity:
        risk = DesenseRiskLevel.HIGH
        requires_cavity = True
    elif rf_cleanliness_score < 85.0:
        risk = DesenseRiskLevel.MODERATE
    else:
        risk = DesenseRiskLevel.LOW

    if requires_cavity:
        notes.append("Install 902-928 MHz bandpass cavity filter ahead of LNA to prevent front-end desense")
    elif risk == DesenseRiskLevel.MODERATE:
        notes.append("Recommend 915 MHz SAW bandpass filter for out-of-band rejection")

    return (round(rf_cleanliness_score, 2), risk, requires_cavity, notes)


def _score_access_and_ownership(site: SiteCandidate) -> float:
    """Score civic ownership & lease viability (0-100).

    Prioritizes municipal water towers, fire lookouts, public rooftops, and agricultural
    silos over high-cost commercial carrier towers (American Tower, Crown Castle, SBA).
    """
    base_by_type: Dict[SiteType, float] = {
        SiteType.WATER_TOWER: 95.0,
        SiteType.FIRE_LOOKOUT: 92.0,
        SiteType.SILO: 90.0,
        SiteType.BUILDING_ROOFTOP: 86.0,
        SiteType.MOUNTAIN_PEAK: 78.0,
        SiteType.CUSTOM: 75.0,
        SiteType.COMMUNICATIONS_TOWER: 42.0,
    }
    score = base_by_type.get(site.site_type, 75.0)
    text = f"{site.name} {site.notes or ''}".lower()

    if any(kw in text for kw in COMMERCIAL_TOWER_KEYWORDS):
        score -= 25.0
    elif any(kw in text for kw in CIVIC_FRIENDLY_KEYWORDS):
        score += 8.0

    return max(0.0, min(100.0, round(score, 2)))


def _score_structural_and_power(site: SiteCandidate) -> Tuple[float, List[str]]:
    """Score mast height, grid/solar power availability, and physical access (0-100)."""
    notes: List[str] = []

    # 1. Power & solar score (0 to 45 pts)
    if site.has_grid_power:
        power_pts = 45.0
        notes.append("Continuous AC grid power available; include UPS battery backup")
    else:
        # Off-grid relies on solar exposure
        power_pts = 10.0 + 30.0 * (site.solar_exposure_pct / 100.0)
        if site.solar_exposure_pct >= 70.0:
            notes.append("Solar + LiFePO4 battery autonomy required (winter sizing)")
        else:
            notes.append("Low solar exposure (<70%); oversized LiFePO4 bank and high-tilt winter PV required")

    # 2. Physical access difficulty (0 to 35 pts)
    access_map: Dict[AccessDifficulty, float] = {
        AccessDifficulty.DRIVE_UP: 35.0,
        AccessDifficulty.MODERATE: 26.0,
        AccessDifficulty.HIKE_IN: 14.0,
        AccessDifficulty.HELICOPTER: 4.0,
    }
    access_pts = access_map.get(site.access_difficulty, 20.0)
    if site.access_difficulty in (AccessDifficulty.HIKE_IN, AccessDifficulty.HELICOPTER):
        notes.append(f"Remote access ({site.access_difficulty.value}); deploy dual-redundant watchdog hardware")

    # 3. Mast height clearance bonus (0 to 20 pts, saturating at 30m)
    mast_pts = min(20.0, (site.mast_height_m / 30.0) * 20.0)

    total = max(0.0, min(100.0, round(power_pts + access_pts + mast_pts, 2)))
    return (total, notes)


def score_site_viability(
    site: SiteCandidate,
    nearby_emitters: Sequence[EmitterSpec] = (),
    coverage_fraction: Optional[float] = None,
) -> Result[SiteViabilityScore]:
    """Compute composite viability score and hardware guidance for a single candidate site."""
    if coverage_fraction is not None and not (0.0 <= coverage_fraction <= 1.0):
        return Result.fail(
            code="INVALID_COVERAGE_FRACTION",
            message=f"coverage_fraction must be between 0.0 and 1.0, got {coverage_fraction}",
        )

    ownership_score = _score_access_and_ownership(site)
    struct_power_score, power_notes = _score_structural_and_power(site)
    rf_score, desense_risk, requires_cavity, rf_notes = evaluate_rf_desense_risk(
        site=site,
        nearby_emitters=nearby_emitters,
    )

    if coverage_fraction is None:
        # Weights: 40% ownership/lease friendliness, 30% structural/power, 30% RF cleanliness
        composite = (
            0.40 * ownership_score
            + 0.30 * struct_power_score
            + 0.30 * rf_score
        )
    else:
        cov_score = coverage_fraction * 100.0
        composite = (
            0.35 * ownership_score
            + 0.25 * struct_power_score
            + 0.25 * rf_score
            + 0.15 * cov_score
        )

    all_notes = rf_notes + power_notes
    return Result.success(
        SiteViabilityScore(
            site=site,
            composite_score=round(max(0.0, min(100.0, composite)), 2),
            access_and_ownership_score=ownership_score,
            structural_and_power_score=struct_power_score,
            rf_cleanliness_score=rf_score,
            desense_risk=desense_risk,
            requires_cavity_filter=requires_cavity,
            recommended_hardware_notes=all_notes,
        )
    )


def rank_candidate_sites(
    sites: Sequence[SiteCandidate],
    nearby_emitters: Sequence[EmitterSpec] = (),
    coverage_by_site: Optional[Dict[str, float]] = None,
) -> Result[List[SiteViabilityScore]]:
    """Score and rank candidate sites in descending order of composite viability."""
    if not sites:
        return Result.fail(
            code="EMPTY_CANDIDATES",
            message="At least one SiteCandidate must be provided to rank_candidate_sites.",
        )

    scored: List[SiteViabilityScore] = []
    for site in sites:
        cov = coverage_by_site.get(site.site_id) if coverage_by_site else None
        res = score_site_viability(site=site, nearby_emitters=nearby_emitters, coverage_fraction=cov)
        if not res.ok or res.value is None:
            return Result.fail(
                code=res.error.code if res.error else "SCORING_FAILED",
                message=res.error.message if res.error else f"Failed scoring site {site.site_id}",
            )
        scored.append(res.value)

    scored.sort(
        key=lambda s: (
            s.composite_score,
            s.access_and_ownership_score,
            s.rf_cleanliness_score,
            s.structural_and_power_score,
        ),
        reverse=True,
    )
    return Result.success(scored)
