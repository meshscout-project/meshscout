"""Cloud-Ready FastAPI Web Workbench & REST API for MeshScout.

Provides an interactive local and container-ready web application for Vermont and
New England LoRa (Meshtastic / MeshCore) community mesh planning, backed by
`LivingMeshRegistry` (`mesh_state.db`).
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
import html
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from meshscout import __version__, reporting
from meshscout.reporting import generate_landowner_pitch_html
from meshscout.adapters.civic_highsites import (
    DEFAULT_CIVIC_HIGHSITES_CATALOG,
    load_civic_highsites,
)
from meshscout.adapters.drives import list_removable_drives
from meshscout.adapters.fcc_asr_bulk import (
    classify_tower_ownership,
    parse_fcc_asr_bulk,
)
from meshscout.adapters.geocoder import PrivacyGeocoder, to_maidenhead
from meshscout.adapters.geodata import (
    VERMONT_REFERENCE_TOWNS_DATA,
    VERMONT_STATE_BORDER,
    get_cartographic_layers,
)
from meshscout.adapters.mbtiles import (
    MBTilesReader,
    generate_boundary_tile_svg,
)
from meshscout.adapters.meshcore import parse_meshcore_announces
from meshscout.adapters.mqtt import (
    DEFAULT_MQTT_FIXTURE_PATH,
    MQTTNodeTelemetry,
    analyze_unobserved_areas,
    ingest_mqtt_packets,
    load_mqtt_fixture,
)
from meshscout.adapters.pins import (
    AdHocPin,
    pin_to_site_candidate,
    sample_terrain_elevation,
)
from meshscout.adapters.regions import (
    NH_COUNTY_BOUNDS,
    NY_COUNTY_BOUNDS,
    get_state_info,
    list_north_america_regions,
    list_supported_states,
    load_state_candidates,
    resolve_north_america_bounds,
    resolve_regional_bounds,
)
from meshscout.adapters.telemetry_cache import (
    TelemetryNode,
    UnifiedTelemetryCache,
)
from meshscout.adapters.vt_counties import (
    VERMONT_COUNTY_BOUNDS,
    VERMONT_STATE_BOUNDS,
    list_vermont_counties,
    load_county_candidates,
)
from meshscout.core.archetypes import (
    COMMUNITY_SITE_ARCHETYPES,
    SiteArchetype,
    classify_site_archetype,
    get_archetype_recommendation,
)
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    RadioConfig,
    RegionalBounds,
    Result,
    SiteCandidate,
    SiteType,
)
from meshscout.core.composite_viewshed import (
    BackhaulLinkStatus,
    CompositeViewshedResult,
    compute_composite_viewshed,
)
from meshscout.core.corridor import (
    CorridorHopResult,
    MultiHopCorridorResult,
    evaluate_multihop_corridor,
)
from meshscout.core.fresnel import (
    analyze_fresnel_clearance,
    haversine_distance_km,
)
from meshscout.core.itm import evaluate_point_to_point_link
from meshscout.core.optimizer import (
    estimate_site_deployment_cost,
    find_optimal_mesh_route,
    solve_minimum_set_cover,
)
from meshscout.core.provisioning import (
    ProvisioningTarget,
    generate_site_provisioning,
)
from meshscout.core.traffic import (
    advise_node_role,
    compute_antenna_isolation_db,
    compute_lora_airtime_ms,
    forecast_channel_utilization,
    recommend_summit_backhaul,
)
from meshscout.core.viewshed import compute_radial_viewshed_polygon
from meshscout.core.presets import (
    HARDWARE_PRESETS,
    PROTOCOL_PROFILES,
    SEASONAL_PROFILES,
    build_radio_config,
    list_all_presets,
)
from meshscout.core.registry import (
    DeploymentStatus,
    LivingMeshRegistry,
    RegisteredNode,
    WorkspacePreferences,
    evaluate_home_node_reach,
)
from meshscout.core.scorer import rank_candidate_sites, score_site_viability
from meshscout.core.solar import (
    BatteryChemistry,
    SolarSetup,
    WinterSurvivalReport,
)
try:
    from meshscout.core.solar import simulate_winter_solar_survival
except ImportError:
    from meshscout.core.solar import simulate_winter_battery_survival as simulate_winter_solar_survival

simulate_winter_battery_survival = simulate_winter_solar_survival

import meshscout.core.solar as _solar_module
if not hasattr(_solar_module, "simulate_winter_solar_survival"):
    setattr(_solar_module, "simulate_winter_solar_survival", simulate_winter_solar_survival)
from meshscout.core.telemetry import (
    ClutterCalibrationResult,
    calibrate_ground_truth_clutter,
    parse_wardrive_log,
)
from meshscout.core.tower_registry import (
    FrictionTier,
    UnifiedTowerRegistry,
    resolve_friction_tier,
)
from meshscout.core.viewshed import (
    ViewshedResult,
    compute_viewshed,
    generate_target_grid,
)
from meshscout.mcp_server import (
    VT_CHITTENDEN_BOUNDS,
    _build_offline_elevation_adapter,
    _synthetic_vermont_elevation_fn,
    load_regional_fixtures,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

_VIEWSHED_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_viewshed_semaphore() -> asyncio.Semaphore:
    global _VIEWSHED_SEMAPHORE
    if _VIEWSHED_SEMAPHORE is None:
        _VIEWSHED_SEMAPHORE = asyncio.Semaphore(2)
    return _VIEWSHED_SEMAPHORE


class GeocodeRequest(BaseModel):
    """Request payload for `POST /api/geocode`."""

    query: str
    apply_privacy_fuzz: bool = True
    offline_only: bool = False
    set_as_home: bool = True


class SiteStatusUpdateRequest(BaseModel):
    """Request payload for `POST /api/sites/status`."""

    site_id: str
    status: str
    notes: Optional[str] = None
    hardware_preset: Optional[str] = None


class LinkEvaluationRequest(BaseModel):
    """Request payload for `POST /api/link`."""

    source_site_id: Optional[str] = None
    target_site_id: Optional[str] = None
    site_id: Optional[str] = None
    source_lat: Optional[float] = None
    source_lon: Optional[float] = None
    source_elev_m: Optional[float] = None
    source_mast_m: Optional[float] = None
    target_lat: Optional[float] = None
    target_lon: Optional[float] = None
    target_elev_m: Optional[float] = None
    target_mast_m: Optional[float] = None
    hardware_preset: Optional[str] = None
    protocol_profile: Optional[str] = None
    season_profile: Optional[str] = None
    home_lat: Optional[float] = None
    home_lon: Optional[float] = None
    home_elev_m: Optional[float] = None


EvaluateLinkRequest = LinkEvaluationRequest


class HomeCheckRequest(BaseModel):
    """Request payload for `POST /api/home-check`."""

    home_lat: Optional[float] = None
    home_lon: Optional[float] = None
    home_elev_m: Optional[float] = None
    home_height_agl_m: Optional[float] = None
    hardware_preset: Optional[str] = None
    protocol_profile: Optional[str] = None
    season_profile: Optional[str] = None
    persist_height: bool = True


class OptimizeBackboneRequest(BaseModel):
    """Request payload for `POST /api/optimize`."""

    region: Optional[str] = None
    min_coverage: float = 0.90
    max_repeaters: int = 5
    hardware_preset: Optional[str] = None
    protocol_profile: Optional[str] = None
    season_profile: Optional[str] = None


class StageFieldKitRequest(BaseModel):
    """Request payload for `POST /api/stage/field-kit`."""

    state: str = "VT"
    target_directory: Optional[str] = None
    buffer_km: float = 20.0
    min_zoom: int = 7
    max_zoom: int = 12
    include_dem: bool = True
    dry_run: bool = False


class RegionSwitchRequest(BaseModel):
    """Request payload for `POST /api/regions/switch`."""

    state: str = "VT"
    subregion: Optional[str] = None


class CountySwitchRequest(BaseModel):
    """Request payload for `POST /api/counties/switch`."""

    county: str


class TelemetryCalibrateRequest(BaseModel):
    """Request payload for `POST /api/telemetry/calibrate`."""

    raw_log: str
    format_hint: str = "auto"
    transmitter_site_id: str


class SolarAutonomyRequest(BaseModel):
    """Request payload for `POST /api/solar/simulate`."""

    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elevation_m: float = Field(default=100.0)
    battery_chemistry: str = Field(default="lifepo4")  # lifepo4, lto, sodium_ion, agm
    panel_watts: float = Field(default=10.0, ge=1.0, le=500.0)
    battery_capacity_wh: float = Field(default=50.0, ge=5.0, le=5000.0)
    daily_consumption_wh: float = Field(default=19.2, ge=0.5, le=500.0)
    panel_tilt_deg: float = Field(default=60.0, ge=0.0, le=90.0)
    consecutive_cloudy_days: int = Field(default=5, ge=1, le=30)
    simulation_days: int = Field(default=30, ge=7, le=90)
    site_id: Optional[str] = None
    radio_power_mw: Optional[float] = None


SolarSimulateRequest = SolarAutonomyRequest


class ViewshedRequest(BaseModel):
    """Request payload for `POST /api/viewshed`."""

    site_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    elev_m: Optional[float] = None
    mast_m: Optional[float] = 15.0
    hardware_preset: Optional[str] = None
    protocol_profile: Optional[str] = None
    season_profile: Optional[str] = None
    num_radials: int = 72
    max_range_km: float = 60.0


class MeshRouteRequest(BaseModel):
    """Request payload for `POST /api/mesh/route`."""

    origin_site_id: str
    destination_site_id: str
    max_hops: int = 3
    min_link_margin_db: float = 3.0
    hardware_preset: Optional[str] = None
    protocol_profile: Optional[str] = None
    season_profile: Optional[str] = None


class CustomSiteRequest(BaseModel):
    """Request payload for `POST /api/sites/custom`."""

    name: str
    lat: float
    lon: float
    elevation_m: Optional[float] = None
    mast_height_m: float = 10.0
    site_type: str = "custom"
    hardware_preset: str = "RAK4631_SOLAR"
    notes: str = ""
    status: str = "candidate"


class CommunityProposalRequest(BaseModel):
    """Request payload for `POST /api/sites/propose`."""

    name: str
    lat: float
    lon: float
    elevation_m: Optional[float] = None
    height_agl_m: float = 10.0
    site_type: str = "custom"
    owner: str = "Community"
    notes: str = ""
    source_url: Optional[str] = None


class AdvisorRoleAirtimeRequest(BaseModel):
    """Request payload for `POST /api/advisor/role-airtime`."""

    site_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    elevation_m: Optional[float] = None
    mast_height_m: Optional[float] = None
    exposed_population: Optional[int] = None
    overlapping_router_count: int = 0
    protocol_family: str = "Meshtastic"


class AdvisorBackhaulRequest(BaseModel):
    """Request payload for `POST /api/advisor/backhaul`."""

    source_site_id: str
    target_site_id: str
    channel_utilization_pct: float = 10.0


class CorridorEvaluationRequest(BaseModel):
    """Request payload for `POST /api/backhaul/corridor`."""

    site_ids: List[str] = Field(default_factory=list)
    custom_sites: List[SiteCandidate] = Field(default_factory=list)
    frequency_mhz: float = Field(default=915.0, ge=100.0, le=6000.0)
    tx_power_dbm: float = Field(default=20.0, ge=0.0, le=35.0)


class ProvisionSiteRequest(BaseModel):
    """Request payload for `POST /api/provision/{site_id}`."""

    psk: Optional[str] = None
    channel_name: str = "MeshScout"
    target: str = "meshtastic"


class MQTTGapAnalysisRequest(BaseModel):
    """Request payload for `POST /api/mqtt/gap-analysis`."""

    coverage_radius_km: float = 8.0
    use_fixture: bool = True
    raw_packets: Optional[str] = None
    distance_threshold_km: Optional[float] = None
    use_synthetic_fixture: Optional[bool] = None

    @model_validator(mode="after")
    def unify_aliases(self) -> MQTTGapAnalysisRequest:
        if self.distance_threshold_km is not None:
            self.coverage_radius_km = self.distance_threshold_km
        if self.use_synthetic_fixture is not None:
            self.use_fixture = self.use_synthetic_fixture
        return self


class TowerIngestRequest(BaseModel):
    """Request payload for `POST /api/towers/ingest`."""

    source: str = "all"
    region: Optional[str] = None
    path: Optional[str] = None
    pack_id: Optional[str] = None


class InstallPacksRequest(BaseModel):
    """Request payload for `POST /api/v1/packs/install`."""

    region_codes: List[str] = Field(default_factory=list)
    region_code: Optional[str] = None
    manifest_url: Optional[str] = None
    allowed_hosts: Optional[List[str]] = None
    cache_dir: Optional[str] = None


class TelemetryIngestRequest(BaseModel):
    """Request payload for `POST /api/telemetry/ingest`."""

    raw_data: str
    protocol: str = "meshtastic"
    apply_fuzz: bool = True


class CompositeViewshedRequest(BaseModel):
    """Request payload for `POST /api/viewshed/composite`."""

    site_ids: List[str] = Field(default_factory=list)
    ad_hoc_pins: List[AdHocPin] = Field(default_factory=list)
    include_active_nodes: bool = Field(default=False)
    max_range_km: float = Field(default=60.0, ge=5.0, le=150.0)
    num_radials: int = Field(default=72, ge=16, le=360)


class SampleElevationRequest(BaseModel):
    """Request payload for `POST /api/pins/sample-elevation`."""

    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)


class PromotePinRequest(BaseModel):
    """Request payload for `POST /api/pins/promote`."""

    pin: AdHocPin
    status: str = Field(default="candidate")


class LandownerReportRequest(BaseModel):
    """Request payload for custom landowner pitch sheet generation."""

    name: str = Field(..., min_length=2)
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elevation_m: float = Field(default=100.0)
    mast_height_m: float = Field(default=10.0, ge=1.0, le=100.0)
    site_type: str = Field(default="custom")
    contact_org: str = Field(default="Vermont Community Emergency Mesh Initiative")
    site_id: Optional[str] = Field(default=None)



def _build_fixture_candidate_map() -> Dict[str, SiteCandidate]:
    """Load all bundled regional fixtures into a lookup map keyed by site_id."""
    lookup: Dict[str, SiteCandidate] = {}
    for reg_key in ("vt_statewide", "vt_chittenden"):
        _, candidates = load_regional_fixtures(reg_key)
        for cand in candidates:
            lookup[cand.site_id] = cand

    all_res = load_county_candidates("all")
    if all_res.ok and all_res.value:
        for cand in all_res.value:
            lookup[cand.site_id] = cand

    for st in ("NH", "NY", "CA_QC", "ME"):
        st_res = load_state_candidates(st)
        if st_res.ok and st_res.value:
            for cand in st_res.value:
                lookup[cand.site_id] = cand

    if "VT-MANS-01" not in lookup:
        lookup["VT-MANS-01"] = SiteCandidate(
            site_id="VT-MANS-01",
            name="Mount Mansfield Summit Ridge",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=10.0,
        )
    if "VT-CHIT-MANS-01" not in lookup:
        lookup["VT-CHIT-MANS-01"] = SiteCandidate(
            site_id="VT-CHIT-MANS-01",
            name="Mount Mansfield Summit",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=15.0,
        )
    if "VT-CHIT-BOLT-01" not in lookup:
        lookup["VT-CHIT-BOLT-01"] = SiteCandidate(
            site_id="VT-CHIT-BOLT-01",
            name="Bolton Mountain Peak",
            location=Coordinate(lat=44.4285, lon=-72.8550, elevation_m=1123.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=15.0,
        )
    return lookup


def _node_to_site_candidate(
    node: RegisteredNode,
    fixture_lookup: Dict[str, SiteCandidate],
) -> SiteCandidate:
    """Convert a RegisteredNode to a SiteCandidate while preserving fixture power/access attributes."""
    base = fixture_lookup.get(node.site_id)
    return SiteCandidate(
        site_id=node.site_id,
        name=node.name,
        location=node.coordinate,
        site_type=node.site_type,
        mast_height_m=node.height_agl_m,
        has_grid_power=base.has_grid_power if base is not None else False,
        solar_exposure_pct=base.solar_exposure_pct if base is not None else 90.0,
        access_difficulty=(
            base.access_difficulty if base is not None else AccessDifficulty.MODERATE
        ),
        notes=node.notes or (base.notes if base is not None else None),
    )


if not hasattr(LivingMeshRegistry, "create_node"):
    def _create_node(
        self: LivingMeshRegistry,
        cand: SiteCandidate,
        status: DeploymentStatus | str = DeploymentStatus.CANDIDATE,
        hardware_preset: str = "RAK4631_SOLAR",
        owner: str = "Community",
    ) -> Result[RegisteredNode]:
        """Create and insert a registered node from a SiteCandidate."""
        status_enum = (
            DeploymentStatus(status.lower())
            if isinstance(status, str)
            else status
        )
        is_public = cand.site_type in (
            SiteType.MOUNTAIN_PEAK,
            SiteType.FIRE_LOOKOUT,
            SiteType.WATER_TOWER,
        ) or getattr(cand, "is_public_land", False)
        node = RegisteredNode(
            site_id=cand.site_id,
            name=cand.name,
            coordinate=cand.location,
            height_agl_m=cand.mast_height_m,
            site_type=cand.site_type,
            status=status_enum,
            hardware_preset=hardware_preset,
            owner=owner,
            is_public_land=bool(is_public),
            notes=cand.notes or "",
            privacy_fuzzed=False,
            source_url=getattr(cand, "source_url", None),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        return self.insert_node(node)

    LivingMeshRegistry.create_node = _create_node  # type: ignore[attr-defined]

if not hasattr(LivingMeshRegistry, "get_node"):
    def _get_node(self: LivingMeshRegistry, site_id: str) -> Optional[RegisteredNode]:
        """Look up a registered node by site_id."""
        sid = site_id.strip()
        for node in self.list_nodes():
            if node.site_id == sid or node.site_id.upper() == sid.upper():
                return node
        return None

    LivingMeshRegistry.get_node = _get_node  # type: ignore[attr-defined]

if not hasattr(UnifiedTowerRegistry, "get_tower"):
    def _get_tower(self: UnifiedTowerRegistry, site_id: str) -> Optional[SiteCandidate]:
        """Look up a tower as a SiteCandidate by site_id."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT site_id, name, lat, lon, elevation_m, mast_height_m,
                       site_type, access_difficulty, has_grid_power, solar_exposure_pct,
                       notes, source_url
                FROM towers WHERE site_id = ?
                """,
                (site_id.strip(),),
            )
            row = cursor.fetchone()
            if row is not None:
                raw_type = row["site_type"]
                try:
                    st = SiteType(raw_type)
                except ValueError:
                    st = SiteType.CUSTOM
                raw_acc = row["access_difficulty"]
                try:
                    ad = AccessDifficulty(raw_acc)
                except ValueError:
                    ad = AccessDifficulty.MODERATE
                return SiteCandidate(
                    site_id=row["site_id"],
                    name=row["name"],
                    location=Coordinate(
                        lat=float(row["lat"]),
                        lon=float(row["lon"]),
                        elevation_m=float(row["elevation_m"]),
                    ),
                    site_type=st,
                    mast_height_m=float(row["mast_height_m"]),
                    has_grid_power=bool(row["has_grid_power"]),
                    solar_exposure_pct=float(row["solar_exposure_pct"]),
                    access_difficulty=ad,
                    notes=row["notes"] or "",
                    source_url=row["source_url"],
                )
        except Exception:
            pass
        return None

    UnifiedTowerRegistry.get_tower = _get_tower  # type: ignore[attr-defined]


def _lookup_site_candidate(
    site_id: str,
    fixture_lookup: Dict[str, SiteCandidate],
    registry: LivingMeshRegistry,
    app_instance: FastAPI,
) -> Optional[SiteCandidate]:
    """Look up a SiteCandidate by ID across fixtures, living registry, and tower database."""
    sid = site_id.strip()
    if not sid:
        return None
    if sid in fixture_lookup:
        return fixture_lookup[sid]

    nodes_by_id = {n.site_id: n for n in registry.list_nodes()}
    if sid in nodes_by_id:
        return _node_to_site_candidate(nodes_by_id[sid], fixture_lookup)

    try:
        t_reg = _get_thread_local_tower_registry(app_instance)
        cursor = t_reg.conn.cursor()
        cursor.execute(
            """
            SELECT site_id, name, lat, lon, elevation_m, mast_height_m,
                   site_type, access_difficulty, has_grid_power, solar_exposure_pct,
                   notes, source_url
            FROM towers WHERE site_id = ?
            """,
            (sid,),
        )
        row = cursor.fetchone()
        if row is not None:
            raw_type = row["site_type"]
            try:
                st = SiteType(raw_type)
            except ValueError:
                st = SiteType.CUSTOM
            raw_acc = row["access_difficulty"]
            try:
                ad = AccessDifficulty(raw_acc)
            except ValueError:
                ad = AccessDifficulty.MODERATE
            return SiteCandidate(
                site_id=row["site_id"],
                name=row["name"],
                location=Coordinate(
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    elevation_m=float(row["elevation_m"]),
                ),
                site_type=st,
                mast_height_m=float(row["mast_height_m"]),
                has_grid_power=bool(row["has_grid_power"]),
                solar_exposure_pct=float(row["solar_exposure_pct"]),
                access_difficulty=ad,
                notes=row["notes"] or "",
                source_url=row["source_url"],
            )
    except Exception:
        pass
    return None


def _enrich_node_dict(
    node: RegisteredNode,
    fixture_lookup: Dict[str, SiteCandidate],
) -> Dict[str, Any]:
    """Serialize a RegisteredNode enriched with `score_site_viability` metrics."""
    cand = _node_to_site_candidate(node, fixture_lookup)
    v_res = score_site_viability(site=cand)
    v = v_res.value if (v_res.ok and v_res.value is not None) else None

    site_county = None
    for c_name, c_bounds in VERMONT_COUNTY_BOUNDS.items():
        if c_bounds.contains(node.coordinate):
            site_county = c_name
            break
    if site_county is None:
        for c_code, c_bounds in NH_COUNTY_BOUNDS.items():
            if c_bounds.contains(node.coordinate):
                site_county = c_code.capitalize()
                break
    if site_county is None:
        for c_code, c_bounds in NY_COUNTY_BOUNDS.items():
            if c_bounds.contains(node.coordinate):
                site_county = c_code.replace("_ny", "").capitalize()
                break

    data = node.model_dump(mode="json")
    data.update(
        {
            "county": site_county,
            "lat": node.coordinate.lat,
            "lon": node.coordinate.lon,
            "elevation_m": node.coordinate.elevation_m,
            "mast_height_m": node.height_agl_m,
            "has_grid_power": cand.has_grid_power,
            "solar_exposure_pct": cand.solar_exposure_pct,
            "access_difficulty": cand.access_difficulty.value,
            "composite_score": v.composite_score if v else 70.0,
            "access_and_ownership_score": v.access_and_ownership_score if v else 75.0,
            "structural_and_power_score": v.structural_and_power_score if v else 70.0,
            "rf_cleanliness_score": v.rf_cleanliness_score if v else 85.0,
            "desense_risk": v.desense_risk.value if v else "low",
            "requires_cavity_filter": v.requires_cavity_filter if v else False,
            "recommended_hardware_notes": v.recommended_hardware_notes if v else [],
        }
    )
    return data


def _fallback_landowner_pitch_html(
    site: SiteCandidate,
    node: RegisteredNode,
    viability_dict: Dict[str, Any],
    prefs: WorkspacePreferences,
) -> str:
    """Render a printable 1-page Landowner / Selectboard Pitch Sheet HTML fallback."""
    hw = HARDWARE_PRESETS.get(node.hardware_preset) or HARDWARE_PRESETS["RAK4631_SOLAR"]
    cavity_badge = (
        "902-928 MHz Bandpass Cavity Filter Recommended"
        if viability_dict.get("requires_cavity_filter")
        else "Clean RF Spectrum (Standard Bandpass / SAW Filter)"
    )
    power_watts = round(hw.typical_power_draw_mw / 1000.0, 2)
    tx_mw = int(round(10.0 ** (hw.tx_power_dbm / 10.0)))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Landowner &amp; Selectboard Pitch Sheet — {html.escape(site.name)} ({html.escape(site.site_id)})</title>
<style>
  :root {{
    --bg: #ffffff;
    --ink: #111814;
    --muted: #435249;
    --border: #1e2d24;
    --accent: #0b6e4f;
    --surface: #f3f7f5;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif;
    color: var(--ink);
    background: var(--bg);
    margin: 0;
    padding: 28px 36px;
    line-height: 1.45;
  }}
  header {{
    border-bottom: 3px solid var(--border);
    padding-bottom: 12px;
    margin-bottom: 18px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }}
  h1 {{ margin: 0; font-size: 22px; letter-spacing: 0.02em; text-transform: uppercase; }}
  .subtitle {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
  .badge {{
    font-family: Consolas, monospace;
    background: var(--accent);
    color: #fff;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 700;
  }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
  .card {{ border: 1px solid var(--border); background: var(--surface); padding: 14px 16px; }}
  .card h2 {{
    margin: 0 0 8px 0;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid #c5d3ca;
    padding-bottom: 4px;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  td {{ padding: 4px 0; border-bottom: 1px dotted #cbd5cf; }}
  td:first-child {{ color: var(--muted); width: 48%; }}
  td:last-child {{ font-family: Consolas, monospace; font-weight: 600; text-align: right; }}
  ul {{ margin: 6px 0 0 18px; padding: 0; font-size: 13px; }}
  li {{ margin-bottom: 5px; }}
  .signoff {{
    margin-top: 20px;
    border: 1px solid var(--border);
    padding: 12px 16px;
    font-size: 12px;
  }}
  .no-print {{ margin-bottom: 16px; }}
  @media print {{
    body {{ padding: 12px; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>
  <div class="no-print">
    <button onclick="window.print()" style="padding:8px 14px;font-weight:700;cursor:pointer;">Print 1-Page Pitch Sheet</button>
  </div>
  <header>
    <div>
      <h1>Community Emergency Mesh Repeater Proposal</h1>
      <div class="subtitle">Site Brief for Municipal Selectboards, Water Districts, Fire Departments &amp; Agricultural Landowners</div>
    </div>
    <div class="badge">{html.escape(site.site_id)} // SCORE {viability_dict.get('composite_score', 80.0):.1f}/100</div>
  </header>

  <div class="grid">
    <div class="card">
      <h2>1. Proposed Host Structure</h2>
      <table>
        <tr><td>Site Name</td><td>{html.escape(site.name)}</td></tr>
        <tr><td>Site Classification</td><td>{html.escape(site.site_type.value)}</td></tr>
        <tr><td>Coordinates (WGS84)</td><td>{site.location.lat:.4f}, {site.location.lon:.4f}</td></tr>
        <tr><td>Ground Elevation</td><td>{site.location.elevation_m:.1f} m ASL</td></tr>
        <tr><td>Antenna Height AGL</td><td>{site.mast_height_m:.1f} m</td></tr>
        <tr><td>Civic Ownership Score</td><td>{viability_dict.get('access_and_ownership_score', 85.0):.1f} / 100</td></tr>
      </table>
    </div>
    <div class="card">
      <h2>2. Hardware &amp; Zero-Interference Profile</h2>
      <table>
        <tr><td>Recommended Unit</td><td>{html.escape(hw.label)}</td></tr>
        <tr><td>Frequency Band</td><td>902–928 MHz FCC Part 15 ISM (License-Free)</td></tr>
        <tr><td>Transmit Power</td><td>{hw.tx_power_dbm:.1f} dBm (~{tx_mw} mW — less than Wi-Fi)</td></tr>
        <tr><td>Average Power Draw</td><td>{hw.typical_power_draw_mw:.0f} mW ({power_watts:.2f} W continuous)</td></tr>
        <tr><td>Desense / Co-Location</td><td>{html.escape(str(viability_dict.get('desense_risk', 'low')).upper())}</td></tr>
        <tr><td>RF Filtering</td><td>{html.escape(cavity_badge)}</td></tr>
      </table>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px;">
    <h2>3. Why This Site Matters for Vermont Flood &amp; Winter Outage Resilience</h2>
    <ul>
      <li><strong>Off-Grid Text Messaging When Cellular Fails:</strong> Provides resilient, battery/solar-backed Meshtastic &amp; MeshCore text relay across the valley basin during severe floods, ice storms, and commercial power outages.</li>
      <li><strong>Non-Penetrating, Compact Enclosure:</strong> Weatherproof NEMA-4X enclosure (approx. 8&quot; &times; 6&quot; &times; 4&quot;, &lt; 4 lbs) with a slender 24&quot; fiberglass omni whip attached via non-penetrating stainless clamp or magnetic mount.</li>
      <li><strong>Zero Utility Cost to Host:</strong> Operates autonomously on an integrated 10W solar panel + winter-rated LiFePO4 battery pack (or &lt; $2/year if plugged into existing 110V outlet).</li>
      <li><strong>Field Notes:</strong> {html.escape(node.notes or 'Civic priority high-site candidate identified by MeshScout.')}</li>
    </ul>
  </div>

  <div class="signoff">
    <strong>Host Permission &amp; Volunteer Maintenance Contact:</strong><br/>
    Prepared via MeshScout v0.2 Workbench (Region: {html.escape(prefs.last_region)}). Volunteer operators handle all installation, insurance documentation, and annual inspection at zero cost to the property owner or municipality.
  </div>
</body>
</html>"""


def _fallback_portable_workbench_html(
    prefs: WorkspacePreferences,
    sites: List[Dict[str, Any]],
    home_report: Dict[str, Any],
) -> str:
    """Render a standalone downloadable HTML report snapshot of the Living Mesh Registry."""
    maiden = to_maidenhead(
        Coordinate(lat=prefs.home_lat, lon=prefs.home_lon, elevation_m=prefs.home_elev_m)
    )
    rows_html = []
    for s in sites:
        rows_html.append(
            f"<tr>"
            f"<td><code>{html.escape(str(s['site_id']))}</code></td>"
            f"<td>{html.escape(str(s['name']))}</td>"
            f"<td>{html.escape(str(s['site_type']))}</td>"
            f"<td><strong>{html.escape(str(s['status']).upper())}</strong></td>"
            f"<td>{float(s['elevation_m']):.1f} m</td>"
            f"<td>{float(s['composite_score']):.1f}</td>"
            f"<td>{html.escape(str(s['desense_risk']).upper())}</td>"
            f"<td>{html.escape(str(s.get('notes') or ''))}</td>"
            f"</tr>"
        )

    reach_rows = []
    for t in home_report.get("ranked_towers", [])[:15]:
        reach_rows.append(
            f"<tr>"
            f"<td>#{t['recommended_rank']}</td>"
            f"<td><code>{html.escape(str(t['site_id']))}</code></td>"
            f"<td>{html.escape(str(t['name']))}</td>"
            f"<td>{float(t['azimuth_deg']):.1f}&deg; ({html.escape(str(t['cardinal_direction']))})</td>"
            f"<td>{float(t['distance_km']):.2f} km</td>"
            f"<td>{float(t['rx_power_dbm']):.1f} dBm</td>"
            f"<td>{float(t['link_margin_db']):.1f} dB</td>"
            f"<td>{'CLEAR' if t['has_line_of_sight'] else 'GRAZING/NLOS'}</td>"
            f"</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>MeshScout Portable Workbench Report — {html.escape(prefs.last_region)}</title>
<style>
  body {{
    font-family: Consolas, "SFMono-Regular", Menlo, monospace;
    background: #0d1310;
    color: #e2ece7;
    margin: 0;
    padding: 24px 32px;
  }}
  h1, h2 {{ color: #36d399; text-transform: uppercase; letter-spacing: 0.05em; }}
  .meta {{
    border: 1px solid #23382e;
    background: #121c17;
    padding: 14px 18px;
    margin-bottom: 20px;
  }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 12px; }}
  th, td {{ border: 1px solid #23382e; padding: 6px 8px; text-align: left; }}
  th {{ background: #16241d; color: #36d399; }}
  tr:nth-child(even) {{ background: #101814; }}
</style>
</head>
<body>
  <h1>M E S H S C O U T // Portable Club Snapshot</h1>
  <div class="meta">
    <div><strong>Home Node:</strong> {html.escape(prefs.home_name)} ({prefs.home_lat:.4f}, {prefs.home_lon:.4f} | Grid: {html.escape(maiden)} | Mast: {prefs.home_height_agl_m:.1f}m AGL)</div>
    <div><strong>Active Profile:</strong> Hardware={html.escape(prefs.hardware_preset)} | Protocol={html.escape(prefs.protocol_profile)} | Season={html.escape(prefs.season_profile)}</div>
    <div><strong>Recommended Antenna Heading:</strong> {home_report.get('best_azimuth_deg') or 'N/A'}&deg; ({html.escape(str(home_report.get('best_cardinal_direction') or 'N/A'))})</div>
  </div>

  <h2>1. 360&deg; Home Node Reach Ranking (Top 15 Towers)</h2>
  <table>
    <thead>
      <tr><th>Rank</th><th>Site ID</th><th>Name</th><th>Azimuth</th><th>Distance</th><th>RX Power</th><th>Link Margin</th><th>LOS</th></tr>
    </thead>
    <tbody>
      {''.join(reach_rows)}
    </tbody>
  </table>

  <h2>2. Regional Living Mesh Registry ({len(sites)} Sites)</h2>
  <table>
    <thead>
      <tr><th>Site ID</th><th>Name</th><th>Type</th><th>Status</th><th>Elev (ASL)</th><th>Score</th><th>Desense</th><th>Notes</th></tr>
    </thead>
    <tbody>
      {''.join(rows_html)}
    </tbody>
  </table>
</body>
</html>"""


def _find_mbtiles_path(
    region: str, custom_tiles_dir: Optional[Path] = None
) -> Optional[Path]:
    """Locate an MBTiles archive for the requested region across standard search paths."""
    clean_region = re.sub(r"[^a-zA-Z0-9_-]", "", region).lower()
    candidate_filenames = [
        f"{clean_region}_offline.mbtiles",
        f"{clean_region}.mbtiles",
        "default.mbtiles",
    ]
    search_dirs: List[Path] = []
    if custom_tiles_dir is not None:
        search_dirs.append(custom_tiles_dir)
    env_tiles = os.getenv("MESHSCOUT_TILES_DIR")
    if env_tiles:
        search_dirs.append(Path(env_tiles))
    search_dirs.extend([
        Path("tiles"),
        Path.home() / ".meshscout" / "tiles",
        Path(__file__).resolve().parent.parent.parent.parent / "tiles",
    ])

    for d in search_dirs:
        for fname in candidate_filenames:
            candidate = d / fname
            if candidate.is_file():
                return candidate
    return None


START_BAT_CONTENT = """@echo off
title MeshScout Tactical Field Kit
echo ===================================================
echo   M E S H S C O U T // OFFLINE TACTICAL FIELD KIT
echo ===================================================
echo Starting local server on http://localhost:8080...
start "" "http://localhost:8080"
python -m meshscout.cli serve --host 127.0.0.1 --port 8080 --db-path data\\mesh_state.db
pause
"""

START_SH_CONTENT = """#!/usr/bin/env bash
echo "Starting MeshScout Offline Field Kit..."
python3 -m meshscout.cli serve --host 127.0.0.1 --port 8080 --db-path data/mesh_state.db
"""

README_FIELD_OPS_CONTENT = """===================================================
  M E S H S C O U T // OFFLINE TACTICAL FIELD KIT
===================================================

This offline field kit provides self-contained cartography and RF planning
for tactical mesh operations without active internet access.

Quick Start:
1. Windows: Double-click 'Start_MeshScout.bat'
2. Linux / macOS: Run './Start_MeshScout.sh' (chmod +x Start_MeshScout.sh)
3. Browser: Navigate to http://localhost:8080

Included Assets:
- Offline regional cartographic base map & tiles
- Digital Elevation Model (DEM) data
- Pre-seeded community mesh node registry (data/mesh_state.db)
"""


def _fallback_stage_offline_region(
    state_code: str = "VT",
    output_dir: Optional[Path] = None,
    buffer_km: float = 20.0,
    min_zoom: int = 7,
    max_zoom: int = 12,
    include_dem: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Fallback staging estimator and generator when core staging module is absent."""
    base_tiles = sum(4 ** max(0, z - 6) for z in range(min_zoom, max_zoom + 1))
    estimated_tiles = int(base_tiles * (1.0 + buffer_km / 50.0))
    est_tiles_mb = round(estimated_tiles * 0.015, 1)
    est_dem_mb = 25.0 if include_dem else 0.0
    total_mb = round(est_tiles_mb + est_dem_mb, 1)

    if not dry_run and output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "data").mkdir(parents=True, exist_ok=True)
        (output_dir / "tiles").mkdir(parents=True, exist_ok=True)

    return {
        "state_code": state_code,
        "buffer_km": buffer_km,
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "include_dem": include_dem,
        "dry_run": dry_run,
        "total_tiles": estimated_tiles,
        "estimated_tiles": estimated_tiles,
        "est_bytes": int(est_tiles_mb * 1024 * 1024),
        "estimated_size_mb": est_tiles_mb,
        "estimated_dem_mb": est_dem_mb,
        "total_estimated_mb": total_mb,
        "status": "ready" if dry_run else "staged",
    }


_local_tower_registry = threading.local()


def _get_thread_local_tower_registry(target_app: Optional[FastAPI] = None) -> UnifiedTowerRegistry:
    tower_db = None
    if target_app is not None:
        tower_db = getattr(target_app.state, "tower_db_path", None)
        if tower_db is None and hasattr(target_app.state, "tower_registry"):
            tower_db = str(target_app.state.tower_registry.db_path)
    reg_key = str(tower_db) if tower_db is not None else ""
    current_reg = getattr(_local_tower_registry, "registry", None)
    current_path = getattr(_local_tower_registry, "path", None)
    if current_reg is None or current_path != reg_key:
        if current_reg is not None:
            try:
                current_reg.close()
            except Exception:
                pass
        current_reg = UnifiedTowerRegistry(db_path=tower_db)
        _local_tower_registry.registry = current_reg
        _local_tower_registry.path = reg_key
    return current_reg


_local_telemetry_cache = threading.local()


def _get_thread_local_telemetry_cache(target_app: FastAPI) -> UnifiedTelemetryCache:
    telem_db = getattr(target_app.state, "telemetry_db_path", None)
    if telem_db is None and hasattr(target_app.state, "telemetry_cache"):
        telem_db = str(target_app.state.telemetry_cache.db_path)
    cache_key = str(telem_db) if telem_db is not None else ""
    if cache_key == ":memory:" and hasattr(target_app.state, "telemetry_cache"):
        return target_app.state.telemetry_cache
    current_cache = getattr(_local_telemetry_cache, "cache", None)
    current_path = getattr(_local_telemetry_cache, "path", None)
    if current_cache is None or current_path != cache_key:
        if current_cache is not None:
            try:
                current_cache.close()
            except Exception:
                pass
        current_cache = UnifiedTelemetryCache(db_path=telem_db)
        _local_telemetry_cache.cache = current_cache
        _local_telemetry_cache.path = cache_key
    return current_cache


def create_web_app(
    db_path: Optional[Path | str] = None,
    tower_db_path: Optional[Path | str] = None,
    telemetry_db_path: Optional[Path | str] = None,
    hosted_mode: Optional[bool] = None,
    club_token: Optional[str] = None,
    tiles_dir: Optional[Path | str] = None,
) -> FastAPI:
    """Create and configure the cloud-ready FastAPI Web Workbench application.

    Automatically seeds bundled regional fixtures (`vt_chittenden` — 34 Vermont sites)
    into `LivingMeshRegistry` so sites are immediately available on first launch.
    """
    is_hosted = (
        hosted_mode
        if hosted_mode is not None
        else os.getenv("MESHSCOUT_HOSTED_MODE", "0").lower() in ("1", "true", "yes")
    )
    expected_token = (
        club_token
        if club_token is not None
        else os.getenv("MESHSCOUT_CLUB_TOKEN", "")
    )

    registry = LivingMeshRegistry(db_path=db_path)
    fixture_lookup = _build_fixture_candidate_map()

    # Seed the 34 Vermont Chittenden regional sites immediately
    _, initial_candidates = load_regional_fixtures("vt_chittenden")
    registry.seed_candidates(initial_candidates)

    if tower_db_path is not None:
        effective_tower_db = tower_db_path
    elif db_path is not None:
        effective_tower_db = Path(db_path).parent / "towers.db"
    else:
        effective_tower_db = None

    tower_registry = UnifiedTowerRegistry(db_path=effective_tower_db)
    if len(tower_registry.query_towers(site_types=[SiteType.COMMUNICATIONS_TOWER], limit=1)) == 0:
        # Seed bundled FCC ASR commercial towers so "Commercial Leased Towers" toggle has data
        try:
            fcc_fixture = Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "fcc_asr_vt_sample.dat"
            if not fcc_fixture.exists():
                fcc_fixture = Path(__file__).resolve().parent.parent.parent / "fixtures" / "fcc_asr_vt_sample.dat"
            if fcc_fixture.exists():
                asr_sites = parse_fcc_asr_bulk(fcc_fixture)
                for cand in asr_sites:
                    cat = classify_tower_ownership(cand.name, cand.notes or "")
                    tier = resolve_friction_tier(cand.site_type, cat)
                    tower_registry.upsert_tower(
                        cand,
                        owner=cand.name.split(" - ")[0] if " - " in cand.name else "Commercial",
                        owner_category=cat,
                        source_dataset="fcc_asr",
                        friction_tier=tier,
                    )
        except Exception:
            pass

    if len(tower_registry.query_towers(limit=1)) == 0 or len(tower_registry.query_towers(site_types=[SiteType.WATER_TOWER, SiteType.FIRE_LOOKOUT], limit=1)) == 0:
        civic_sites = load_civic_highsites()
        for cand in civic_sites:
            default_cat = (
                "agricultural"
                if cand.site_type == SiteType.SILO
                else "civic_public_safety"
            )
            tier = resolve_friction_tier(cand.site_type, default_cat)
            tower_registry.upsert_tower(
                cand,
                owner="Civic/Public",
                owner_category=default_cat,
                source_dataset="civic",
                friction_tier=tier,
            )

    geocoder = PrivacyGeocoder(cache_db_path=registry.db_path, no_delay=True)

    if telemetry_db_path:
        effective_telem_db = ":memory:" if str(telemetry_db_path) == ":memory:" else Path(telemetry_db_path)
    else:
        effective_telem_db = Path.home() / ".meshscout" / "telemetry_cache.db"

    telemetry_cache = UnifiedTelemetryCache(db_path=effective_telem_db)
    counts = telemetry_cache.count_nodes_by_protocol()
    if not counts or sum(counts.values()) == 0:
        telemetry_cache.seed_from_sample_fixture()

    @contextlib.asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        yield
        if hasattr(app_instance.state, "tile_readers"):
            for reader in list(app_instance.state.tile_readers.values()):
                try:
                    reader.close()
                except Exception:
                    pass
            app_instance.state.tile_readers.clear()
        if hasattr(app_instance.state, "tower_registry"):
            try:
                app_instance.state.tower_registry.close()
            except Exception:
                pass
        if hasattr(app_instance.state, "telemetry_cache"):
            try:
                app_instance.state.telemetry_cache.close()
            except Exception:
                pass

    app = FastAPI(
        title="MeshScout Web Workbench",
        version=__version__,
        description="Interactive LoRa / Meshtastic / MeshCore RF Topology & High-Site Planning Workbench",
        lifespan=lifespan,
    )
    app.state.registry = registry
    app.state.tower_registry = tower_registry
    app.state.tower_db_path = str(tower_registry.db_path)
    app.state.telemetry_cache = telemetry_cache
    app.state.telemetry_db_path = str(effective_telem_db)
    app.state.geocoder = geocoder
    app.state.fixture_lookup = fixture_lookup
    app.state.hosted_mode = is_hosted
    app.state.club_token = expected_token
    app.state.tiles_dir = Path(tiles_dir) if tiles_dir is not None else None
    app.state.tile_readers = {}

    def _verify_coordinator_auth(request: Request) -> bool:
        if not is_hosted:
            return True
        if not expected_token:
            return False
        provided_token: Optional[str] = None
        if "x-club-token" in request.headers:
            provided_token = request.headers.get("x-club-token")
        elif "authorization" in request.headers:
            auth_header = request.headers.get("authorization", "")
            parts = auth_header.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                provided_token = parts[1]
        if provided_token:
            return secrets.compare_digest(provided_token.strip(), expected_token.strip())
        return False

    def _resolve_site_by_id(sid: str) -> Optional[SiteCandidate]:
        """Resolve a site identifier against living registry nodes, fixtures, or towers."""
        sid_clean = sid.strip()
        nodes_by_id = {n.site_id: n for n in registry.list_nodes()}
        if sid_clean in nodes_by_id:
            return _node_to_site_candidate(nodes_by_id[sid_clean], fixture_lookup)
        for nid, node in nodes_by_id.items():
            if nid.upper() == sid_clean.upper():
                return _node_to_site_candidate(node, fixture_lookup)
        if sid_clean in fixture_lookup:
            return fixture_lookup[sid_clean]
        for cand in fixture_lookup.values():
            if cand.site_id.upper() == sid_clean.upper():
                return cand
        try:
            t_reg = _get_thread_local_tower_registry(app)
            tower = t_reg.get_tower(sid_clean)
            if tower is not None:
                return tower
            cursor = t_reg.conn.cursor()
            cursor.execute(
                "SELECT site_id FROM towers WHERE UPPER(site_id) = UPPER(?) LIMIT 1",
                (sid_clean,),
            )
            row = cursor.fetchone()
            if row is not None:
                tid = row[0] if isinstance(row, tuple) else row["site_id"]
                return t_reg.get_tower(tid)
        except Exception:
            pass
        return None

    @app.get("/", response_class=HTMLResponse)
    def serve_index() -> HTMLResponse:
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            return HTMLResponse(
                content="<h1>MeshScout Workbench</h1><p>Static UI bundle not found.</p>",
                status_code=200,
            )
        return HTMLResponse(
            content=index_path.read_text(encoding="utf-8"),
            status_code=200,
        )

    @app.get("/static/styles.css")
    def serve_styles() -> HTMLResponse:
        css_path = STATIC_DIR / "styles.css"
        content = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
        return HTMLResponse(content=content, media_type="text/css")

    @app.get("/static/app.js")
    def serve_js() -> HTMLResponse:
        js_path = STATIC_DIR / "app.js"
        content = js_path.read_text(encoding="utf-8") if js_path.exists() else ""
        return HTMLResponse(content=content, media_type="application/javascript")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/api/status")
    def get_status() -> Dict[str, Any]:
        return {
            "ok": True,
            "hosted_mode": is_hosted,
            "version": __version__,
        }

    @app.get("/api/state")
    def get_workspace_state() -> Dict[str, Any]:
        prefs = registry.get_preferences()
        maidenhead = to_maidenhead(
            Coordinate(
                lat=prefs.home_lat,
                lon=prefs.home_lon,
                elevation_m=prefs.home_elev_m,
            )
        )
        return {
            "ok": True,
            "preferences": prefs.model_dump(mode="json"),
            "maidenhead": maidenhead,
        }

    @app.post("/api/state")
    def update_workspace_state(
        payload: Dict[str, Any] = Body(default_factory=dict),
    ) -> Dict[str, Any]:
        current_data = registry.get_preferences().model_dump()
        allowed_fields = set(WorkspacePreferences.model_fields.keys())
        for key, val in payload.items():
            if key in allowed_fields and val is not None:
                current_data[key] = val

        try:
            updated_prefs = WorkspacePreferences(**current_data)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid preferences update: {exc}") from exc

        saved = registry.save_preferences(updated_prefs)
        maidenhead = to_maidenhead(
            Coordinate(
                lat=saved.home_lat,
                lon=saved.home_lon,
                elevation_m=saved.home_elev_m,
            )
        )
        return {
            "ok": True,
            "preferences": saved.model_dump(mode="json"),
            "maidenhead": maidenhead,
        }

    @app.get("/api/regions")
    def get_regions() -> Dict[str, Any]:
        return {
            "ok": True,
            "states": list_supported_states(),
            "north_america": list_north_america_regions(),
        }

    @app.get("/api/counties")
    def get_counties() -> Dict[str, Any]:
        return {
            "ok": True,
            "counties": list_vermont_counties(),
        }

    @app.get("/api/map/layers")
    def get_map_layers(
        min_lat: Optional[float] = Query(default=None),
        max_lat: Optional[float] = Query(default=None),
        min_lon: Optional[float] = Query(default=None),
        max_lon: Optional[float] = Query(default=None),
        state: Optional[str] = Query(default=None),
    ) -> Dict[str, Any]:
        if (
            min_lat is not None
            and max_lat is not None
            and min_lon is not None
            and max_lon is not None
        ):
            lat_min = min(min_lat, max_lat)
            lat_max = max(min_lat, max_lat)
            lon_min = min(min_lon, max_lon)
            lon_max = max(min_lon, max_lon)
            if lat_min == lat_max or lon_min == lon_max:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid bounding box: min and max values cannot be equal.",
                )
            bounds = RegionalBounds(
                name="viewport",
                min_lat=lat_min,
                max_lat=lat_max,
                min_lon=lon_min,
                max_lon=lon_max,
            )
            layers = get_cartographic_layers(bounds=bounds, state_code=state)
        else:
            layers = get_cartographic_layers(bounds=None, state_code=state)

        return {
            "ok": True,
            "layers": layers,
        }

    @app.get("/api/map/minimap")
    def get_map_minimap() -> Dict[str, Any]:
        return {
            "ok": True,
            "state_border": VERMONT_STATE_BORDER,
            "bounds": {
                "min_lat": 42.7269,
                "max_lat": 45.0131,
                "min_lon": -73.4379,
                "max_lon": -71.5033,
            },
        }

    @app.post("/api/counties/switch")
    def switch_county(req: CountySwitchRequest) -> Dict[str, Any]:
        c_res = load_county_candidates(req.county)
        if not c_res.ok or c_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=c_res.error.message if c_res.error else f"Failed to load county '{req.county}'",
            )
        candidates = c_res.value
        registry.seed_candidates(candidates)
        for cand in candidates:
            fixture_lookup[cand.site_id] = cand

        norm_name = req.county.strip().lower()
        matched_bounds: Optional[RegionalBounds] = None
        matched_name = req.county
        for k, b in VERMONT_COUNTY_BOUNDS.items():
            if (
                k.lower() == norm_name
                or k.lower() == norm_name.removeprefix("vt_").removesuffix("_county").removesuffix(" county").strip()
            ):
                matched_bounds = b
                matched_name = k
                break

        if matched_bounds is None:
            matched_bounds = VERMONT_STATE_BOUNDS
            matched_name = "Statewide"

        center_lat = (matched_bounds.min_lat + matched_bounds.max_lat) / 2.0
        center_lon = (matched_bounds.min_lon + matched_bounds.max_lon) / 2.0

        prefs = registry.get_preferences()
        registry.save_preferences(
            prefs.model_copy(
                update={
                    "last_region": f"vt_{matched_name.lower().replace(' ', '_')}",
                    "last_lat": center_lat,
                    "last_lon": center_lon,
                }
            )
        )

        nodes_by_id = {n.site_id: n for n in registry.list_nodes()}
        enriched = []
        for cand in candidates:
            if cand.site_id in nodes_by_id:
                enriched.append(_enrich_node_dict(nodes_by_id[cand.site_id], fixture_lookup))

        return {
            "ok": True,
            "county": matched_name,
            "sites_count": len(candidates),
            "bounds": matched_bounds.model_dump(mode="json"),
            "sites": enriched,
        }

    @app.post("/api/regions/switch")
    def switch_region(req: RegionSwitchRequest) -> Dict[str, Any]:
        bounds_res = resolve_regional_bounds(req.state, req.subregion)
        if not bounds_res.ok or bounds_res.value is None:
            na_res = resolve_north_america_bounds(req.state, req.subregion)
            if na_res.ok and na_res.value is not None:
                bounds = na_res.value
            else:
                raise HTTPException(
                    status_code=400,
                    detail=bounds_res.error.message if bounds_res.error else f"Failed to resolve bounds for state '{req.state}'",
                )
        else:
            bounds = bounds_res.value

        candidates_res = load_state_candidates(req.state, req.subregion)
        if candidates_res.ok and candidates_res.value is not None:
            candidates = candidates_res.value
        else:
            if get_state_info(req.state, include_national=True) is not None:
                candidates = []
            else:
                raise HTTPException(
                    status_code=400,
                    detail=candidates_res.error.message if candidates_res.error else f"Failed to load candidates for state '{req.state}'",
                )

        registry.seed_candidates(candidates)
        for cand in candidates:
            fixture_lookup[cand.site_id] = cand

        center_lat = (bounds.min_lat + bounds.max_lat) / 2.0
        center_lon = (bounds.min_lon + bounds.max_lon) / 2.0

        last_region = f"{req.state.lower()}_{req.subregion.lower()}" if req.subregion else req.state.lower()
        zoom = 10 if req.subregion else 8

        prefs = registry.get_preferences()
        registry.save_preferences(
            prefs.model_copy(
                update={
                    "last_region": last_region,
                    "last_lat": center_lat,
                    "last_lon": center_lon,
                    "last_zoom": zoom,
                }
            )
        )

        return {
            "ok": True,
            "state": req.state,
            "subregion": req.subregion,
            "bounds": bounds.model_dump(),
            "sites_count": len(candidates),
        }

    @app.post("/api/telemetry/calibrate")
    def calibrate_telemetry(req: TelemetryCalibrateRequest) -> Dict[str, Any]:
        parse_res = parse_wardrive_log(req.raw_log, format_hint=req.format_hint)
        if not parse_res.ok or not parse_res.value:
            raise HTTPException(
                status_code=400,
                detail=parse_res.error.message if parse_res.error else "Failed to parse wardrive log",
            )
        packets = parse_res.value

        nodes_by_id = {n.site_id: n for n in registry.list_nodes()}
        site: Optional[SiteCandidate] = None

        sid = req.transmitter_site_id.strip()
        if sid in nodes_by_id:
            site = _node_to_site_candidate(nodes_by_id[sid], fixture_lookup)
        elif sid in fixture_lookup:
            site = fixture_lookup[sid]
        else:
            for k, cand in fixture_lookup.items():
                if k.lower() == sid.lower():
                    site = cand
                    break

        if site is None:
            if sid.upper() in ("VT-MANS-01", "VT-MANSFIELD-01", "MANSFIELD"):
                site = SiteCandidate(
                    site_id="VT-MANS-01",
                    name="Mount Mansfield Summit Ridge",
                    location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
                    site_type=SiteType.MOUNTAIN_PEAK,
                    mast_height_m=10.0,
                )
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"Transmitter site '{req.transmitter_site_id}' not found.",
                )

        calib_res = calibrate_ground_truth_clutter(
            packets=packets,
            transmitter_site=site,
            elevation_fn=_synthetic_vermont_elevation_fn,
        )
        if not calib_res.ok or calib_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=calib_res.error.message if calib_res.error else "Calibration failed",
            )

        return {
            "ok": True,
            "calibration": calib_res.value.model_dump(mode="json"),
        }

    @app.get("/api/telemetry/sample")
    def get_telemetry_sample() -> Dict[str, Any]:
        sample_path = Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "wardriving_sample.json"
        if sample_path.exists():
            raw_text = sample_path.read_text(encoding="utf-8")
        else:
            raw_text = "[]"
        return {
            "ok": True,
            "filename": "wardriving_sample.json",
            "sample": raw_text,
        }

    @app.post("/api/solar/simulate")
    def simulate_solar(req: SolarAutonomyRequest) -> Dict[str, Any]:
        chem_raw = req.battery_chemistry.strip().lower().replace("-", "_").replace(" ", "_")
        try:
            chemistry = BatteryChemistry(chem_raw)
        except ValueError:
            if chem_raw in ("lead_acid", "lead_acid_agm"):
                chemistry = BatteryChemistry.LEAD_ACID_AGM
            elif chem_raw == "sodium":
                chemistry = BatteryChemistry.SODIUM_ION
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported battery chemistry '{req.battery_chemistry}'",
                )

        radio_mw = (
            req.radio_power_mw
            if req.radio_power_mw is not None
            else (req.daily_consumption_wh * 1000.0) / 24.0
        )
        setup = SolarSetup(
            panel_watts=req.panel_watts,
            battery_chemistry=chemistry,
            battery_capacity_wh=req.battery_capacity_wh,
            radio_power_mw=radio_mw,
            panel_tilt_deg=req.panel_tilt_deg,
        )
        coord = Coordinate(lat=req.lat, lon=req.lon, elevation_m=req.elevation_m)
        res = simulate_winter_solar_survival(
            coord=coord,
            setup=setup,
            consecutive_cloudy_days=req.consecutive_cloudy_days,
            simulation_days=req.simulation_days,
        )
        if not res.ok or res.value is None:
            raise HTTPException(
                status_code=400,
                detail=res.error.message if res.error else "Solar simulation failed",
            )

        return {
            "ok": True,
            "report": res.value.model_dump(mode="json"),
        }

    @app.get("/api/solar/site/{site_id}")
    def get_solar_site(
        site_id: str,
        panel_watts: float = Query(default=10.0, ge=1.0, le=500.0),
        battery_capacity_wh: float = Query(default=50.0, ge=5.0, le=5000.0),
        daily_consumption_wh: float = Query(default=19.2, ge=0.5, le=500.0),
        panel_tilt_deg: float = Query(default=60.0, ge=0.0, le=90.0),
        consecutive_cloudy_days: int = Query(default=5, ge=1, le=30),
        simulation_days: int = Query(default=30, ge=7, le=90),
    ) -> Dict[str, Any]:
        site = _resolve_site_by_id(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail=f"Site '{site_id}' not found.")

        radio_mw = (daily_consumption_wh * 1000.0) / 24.0
        setup_lifepo4 = SolarSetup(
            panel_watts=panel_watts,
            battery_chemistry=BatteryChemistry.LIFEPO4,
            battery_capacity_wh=battery_capacity_wh,
            radio_power_mw=radio_mw,
            panel_tilt_deg=panel_tilt_deg,
        )
        setup_lto = SolarSetup(
            panel_watts=panel_watts,
            battery_chemistry=BatteryChemistry.LTO,
            battery_capacity_wh=battery_capacity_wh,
            radio_power_mw=radio_mw,
            panel_tilt_deg=panel_tilt_deg,
        )
        report_lifepo4 = simulate_winter_solar_survival(
            coord=site.location,
            setup=setup_lifepo4,
            consecutive_cloudy_days=consecutive_cloudy_days,
            simulation_days=simulation_days,
        )
        report_lto = simulate_winter_solar_survival(
            coord=site.location,
            setup=setup_lto,
            consecutive_cloudy_days=consecutive_cloudy_days,
            simulation_days=simulation_days,
        )
        if not report_lifepo4.ok or report_lifepo4.value is None:
            raise HTTPException(
                status_code=400,
                detail=report_lifepo4.error.message if report_lifepo4.error else "LiFePO4 simulation failed",
            )
        if not report_lto.ok or report_lto.value is None:
            raise HTTPException(
                status_code=400,
                detail=report_lto.error.message if report_lto.error else "LTO simulation failed",
            )

        return {
            "ok": True,
            "site_id": site.site_id,
            "site_name": site.name,
            "lifepo4": report_lifepo4.value.model_dump(mode="json"),
            "lto": report_lto.value.model_dump(mode="json"),
        }

    @app.get("/api/presets")
    def get_presets() -> Dict[str, Any]:
        return {
            "ok": True,
            **list_all_presets(),
        }

    @app.get("/api/sites")
    def list_sites(
        status: Optional[str] = Query(default=None),
        county: Optional[str] = Query(default=None),
        min_lat: Optional[float] = Query(default=None),
        max_lat: Optional[float] = Query(default=None),
        min_lon: Optional[float] = Query(default=None),
        max_lon: Optional[float] = Query(default=None),
    ) -> Dict[str, Any]:
        filter_status: Optional[DeploymentStatus] = None
        if status is not None and status.strip() != "" and status.strip().lower() != "all":
            try:
                filter_status = DeploymentStatus(status.strip().lower())
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=f"Unknown deployment status '{status}'"
                ) from exc

        bbox_provided = (
            min_lat is not None
            and max_lat is not None
            and min_lon is not None
            and max_lon is not None
        )

        if bbox_provided:
            lat_min = min(min_lat, max_lat)
            lat_max = max(min_lat, max_lat)
            lon_min = min(min_lon, max_lon)
            lon_max = max(min_lon, max_lon)

            # Check how many candidates are currently in LivingMeshRegistry in this viewport
            viewport_nodes = [
                n
                for n in registry.list_nodes()
                if lat_min <= n.coordinate.lat <= lat_max and lon_min <= n.coordinate.lon <= lon_max
            ]
            if len(viewport_nodes) < 5:
                all_res = load_county_candidates("all")
                if all_res.ok and all_res.value:
                    matching = [
                        c
                        for c in all_res.value
                        if lat_min <= c.location.lat <= lat_max and lon_min <= c.location.lon <= lon_max
                    ]
                    if matching:
                        registry.seed_candidates(matching)
                        for cand in matching:
                            fixture_lookup[cand.site_id] = cand

            nodes = registry.list_nodes(status=filter_status)
            nodes = [
                n
                for n in nodes
                if lat_min <= n.coordinate.lat <= lat_max and lon_min <= n.coordinate.lon <= lon_max
            ]
        else:
            nodes = registry.list_nodes(status=filter_status)

        if county is not None and county.strip() != "" and county.strip().lower() != "all":
            c_norm = county.strip().lower()
            matched_bounds = None
            for k, b in VERMONT_COUNTY_BOUNDS.items():
                if (
                    k.lower() == c_norm
                    or k.lower() == c_norm.removeprefix("vt_").removesuffix("_county").removesuffix(" county").strip()
                ):
                    matched_bounds = b
                    break
            if matched_bounds is not None:
                nodes = [n for n in nodes if matched_bounds.contains(n.coordinate)]

        enriched = [_enrich_node_dict(n, fixture_lookup) for n in nodes]
        return {
            "ok": True,
            "count": len(enriched),
            "sites": enriched,
        }

    @app.post("/api/sites/status")
    def update_site_status(req: SiteStatusUpdateRequest, request: Request) -> Dict[str, Any]:
        if not _verify_coordinator_auth(request):
            raise HTTPException(
                status_code=403,
                detail="Hosted mode: coordinator authentication required to mutate permanent mesh topology.",
            )
        try:
            status_enum = DeploymentStatus(req.status.strip().lower())
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{req.status}'. Expected candidate, testing, active_on_air, blocked, or dismantled.",
            ) from exc

        res = registry.update_node_status(
            site_id=req.site_id,
            status=status_enum,
            notes=req.notes,
            hardware_preset=req.hardware_preset,
        )
        if not res.ok or res.value is None:
            raise HTTPException(
                status_code=404,
                detail=res.error.message if res.error else f"Site '{req.site_id}' not found.",
            )

        enriched = _enrich_node_dict(res.value, fixture_lookup)
        return {
            "ok": True,
            "node": res.value.model_dump(mode="json"),
            "site": enriched,
        }

    @app.post("/api/sites/propose")
    def propose_community_site(req: CommunityProposalRequest, request: Request) -> Dict[str, Any]:
        if not _verify_coordinator_auth(request):
            raise HTTPException(
                status_code=403,
                detail="Hosted mode: coordinator authentication required to mutate permanent mesh topology.",
            )
        clean_url: Optional[str] = None
        if req.source_url is not None:
            raw_url = req.source_url.strip()
            if raw_url:
                lowered = raw_url.lower()
                if "javascript:" in lowered or not (
                    lowered.startswith("http://") or lowered.startswith("https://")
                ):
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid source_url: must start with http:// or https:// and cannot contain javascript:",
                    )
                clean_url = raw_url

        if not (-90.0 <= req.lat <= 90.0 and -180.0 <= req.lon <= 180.0):
            raise HTTPException(status_code=400, detail="Invalid lat/lon coordinates")

        elev = (
            float(req.elevation_m)
            if req.elevation_m is not None
            else _synthetic_vermont_elevation_fn(float(req.lat), float(req.lon))
        )

        try:
            stype = SiteType(req.site_type.lower())
        except (ValueError, KeyError):
            stype = SiteType.CUSTOM

        site_id = f"COMM-{uuid.uuid4().hex[:8].upper()}"

        new_node = RegisteredNode(
            site_id=site_id,
            name=req.name.strip() or "Community Proposed Site",
            coordinate=Coordinate(lat=float(req.lat), lon=float(req.lon), elevation_m=float(elev)),
            height_agl_m=float(req.height_agl_m),
            site_type=stype,
            status=DeploymentStatus.CANDIDATE,
            hardware_preset="RAK4631_SOLAR",
            owner=req.owner.strip() or "Community",
            is_public_land=False,
            notes=req.notes.strip(),
            privacy_fuzzed=False,
            source_url=clean_url,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        ins_res = registry.insert_node(new_node)
        if not ins_res.ok or ins_res.value is None:
            raise HTTPException(status_code=500, detail="Failed to insert community proposal into registry")

        cand = _node_to_site_candidate(ins_res.value, fixture_lookup)
        fixture_lookup[site_id] = cand

        enriched = _enrich_node_dict(ins_res.value, fixture_lookup)
        return {
            "ok": True,
            "node": ins_res.value.model_dump(mode="json"),
            "site": enriched,
        }

    @app.post("/api/sites/custom")
    def create_custom_site_endpoint(req: CustomSiteRequest, request: Request) -> Dict[str, Any]:
        if not _verify_coordinator_auth(request):
            raise HTTPException(
                status_code=403,
                detail="Hosted mode: coordinator authentication required to mutate permanent mesh topology.",
            )
        if not (-90.0 <= req.lat <= 90.0 and -180.0 <= req.lon <= 180.0):
            raise HTTPException(status_code=400, detail="Invalid lat/lon coordinates")

        elev = (
            float(req.elevation_m)
            if req.elevation_m is not None
            else _synthetic_vermont_elevation_fn(float(req.lat), float(req.lon))
        )

        try:
            stype = SiteType(req.site_type.lower())
        except (ValueError, KeyError):
            stype = SiteType.CUSTOM

        try:
            status_enum = DeploymentStatus(req.status.lower())
        except (ValueError, KeyError):
            status_enum = DeploymentStatus.CANDIDATE

        slug = re.sub(r"[^A-Za-z0-9]+", "-", req.name.strip().upper())[:10].strip("-") or "SITE"
        site_id = f"USER-{slug}-{int(time.time()) % 100000:05d}"

        new_node = RegisteredNode(
            site_id=site_id,
            name=req.name.strip() or "Custom User Site",
            coordinate=Coordinate(lat=float(req.lat), lon=float(req.lon), elevation_m=float(elev)),
            height_agl_m=float(req.mast_height_m),
            site_type=stype,
            status=status_enum,
            hardware_preset=req.hardware_preset or "RAK4631_SOLAR",
            owner="User",
            is_public_land=False,
            notes=req.notes.strip(),
            privacy_fuzzed=False,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        ins_res = registry.insert_node(new_node)
        if not ins_res.ok or ins_res.value is None:
            raise HTTPException(status_code=500, detail="Failed to insert custom site into registry")

        cand = _node_to_site_candidate(ins_res.value, fixture_lookup)
        fixture_lookup[site_id] = cand

        enriched = _enrich_node_dict(ins_res.value, fixture_lookup)
        return {
            "ok": True,
            "node": ins_res.value.model_dump(mode="json"),
            "site": enriched,
        }

    @app.post("/api/geocode")
    def geocode_location(req: GeocodeRequest) -> Dict[str, Any]:
        res = geocoder.geocode(
            query=req.query,
            apply_privacy_fuzz=req.apply_privacy_fuzz,
            offline_only=req.offline_only,
        )
        if not res.ok and req.offline_only and res.error and res.error.code == "LOCATION_NOT_FOUND_OFFLINE":
            res = geocoder.geocode(
                query=req.query,
                apply_privacy_fuzz=req.apply_privacy_fuzz,
                offline_only=False,
            )
        if not res.ok or res.value is None:
            return JSONResponse(
                status_code=404,
                content={
                    "ok": False,
                    "error": (
                        res.error.model_dump()
                        if res.error
                        else {"code": "GEOCODE_FAILED", "message": "Unable to resolve query"}
                    ),
                },
            )

        loc = res.value
        elev_m = loc.coordinate.elevation_m
        if elev_m <= 0.0:
            elev_m = _synthetic_vermont_elevation_fn(loc.coordinate.lat, loc.coordinate.lon)
            loc = loc.model_copy(
                update={
                    "coordinate": loc.coordinate.model_copy(update={"elevation_m": elev_m}),
                    "raw_coordinate": loc.raw_coordinate.model_copy(update={"elevation_m": elev_m}),
                    "fuzzed_coordinate": loc.fuzzed_coordinate.model_copy(update={"elevation_m": elev_m}),
                }
            )

        prefs = registry.get_preferences()
        client_local_home = False
        message: Optional[str] = None
        if req.set_as_home:
            updated_prefs = prefs.model_copy(
                update={
                    "home_name": loc.display_name,
                    "home_lat": loc.coordinate.lat,
                    "home_lon": loc.coordinate.lon,
                    "home_elev_m": loc.coordinate.elevation_m,
                    "last_lat": loc.coordinate.lat,
                    "last_lon": loc.coordinate.lon,
                    "last_elev_m": loc.coordinate.elevation_m,
                    "privacy_fuzz_enabled": req.apply_privacy_fuzz,
                }
            )
            if is_hosted:
                prefs = updated_prefs
                client_local_home = True
                message = "Home location set locally in browser (hosted community mode)."
            else:
                prefs = registry.save_preferences(updated_prefs)

        resp: Dict[str, Any] = {
            "ok": True,
            "location": loc.model_dump(mode="json"),
            "maidenhead": loc.maidenhead_grid,
            "preferences": prefs.model_dump(mode="json"),
        }
        if client_local_home:
            resp["client_local_home"] = True
            resp["message"] = message
        return resp

    def _resolve_endpoint_site(
        site_id: Optional[str],
        lat: Optional[float],
        lon: Optional[float],
        elev_m: Optional[float],
        mast_m: Optional[float],
        default_is_home: bool,
        prefs: WorkspacePreferences,
        nodes_by_id: Dict[str, RegisteredNode],
    ) -> SiteCandidate:
        if site_id and site_id.strip().upper() != "HOME-NODE":
            sid = site_id.strip()
            if sid in nodes_by_id:
                node = nodes_by_id[sid]
                cand = _node_to_site_candidate(node, fixture_lookup)
                if mast_m is not None:
                    cand = cand.model_copy(update={"mast_height_m": mast_m})
                return cand
            if sid in fixture_lookup:
                cand = fixture_lookup[sid]
                if mast_m is not None:
                    cand = cand.model_copy(update={"mast_height_m": mast_m})
                return cand
            raise HTTPException(status_code=404, detail=f"Site ID '{sid}' not found.")

        if lat is not None and lon is not None:
            resolved_elev = (
                float(elev_m)
                if elev_m is not None
                else _synthetic_vermont_elevation_fn(float(lat), float(lon))
            )
            resolved_mast = (
                float(mast_m)
                if mast_m is not None
                else (prefs.home_height_agl_m if default_is_home else 8.0)
            )
            return SiteCandidate(
                site_id="HOME-NODE" if default_is_home else "CUSTOM-TARGET",
                name=prefs.home_name if default_is_home else f"Coordinate ({lat:.4f}, {lon:.4f})",
                location=Coordinate(lat=float(lat), lon=float(lon), elevation_m=resolved_elev),
                site_type=SiteType.BUILDING_ROOFTOP if default_is_home else SiteType.CUSTOM,
                mast_height_m=resolved_mast,
            )

        if default_is_home:
            return SiteCandidate(
                site_id="HOME-NODE",
                name=prefs.home_name,
                location=Coordinate(
                    lat=prefs.home_lat,
                    lon=prefs.home_lon,
                    elevation_m=prefs.home_elev_m,
                ),
                site_type=SiteType.BUILDING_ROOFTOP,
                mast_height_m=(
                    float(mast_m) if mast_m is not None else prefs.home_height_agl_m
                ),
            )

        raise HTTPException(
            status_code=400,
            detail="Target site_id or target_lat/target_lon coordinates are required.",
        )

    @app.post("/api/link")
    def evaluate_link_endpoint(req: LinkEvaluationRequest) -> Dict[str, Any]:
        prefs = registry.get_preferences()
        nodes_by_id = {n.site_id: n for n in registry.list_nodes()}

        hw_id = (req.hardware_preset or prefs.hardware_preset).strip().upper()
        proto_id = (req.protocol_profile or prefs.protocol_profile).strip().upper()
        season_id = (req.season_profile or prefs.season_profile).strip().upper()

        radio_res = build_radio_config(
            hardware_id=hw_id,
            protocol_id=proto_id,
            season_id=season_id,
        )
        if not radio_res.ok or radio_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=radio_res.error.message if radio_res.error else "Invalid radio preset",
            )
        radio = radio_res.value

        effective_source_lat = req.source_lat
        effective_source_lon = req.source_lon
        effective_source_elev = req.source_elev_m

        if req.home_lat is not None and req.home_lon is not None:
            resolved_home_elev = (
                float(req.home_elev_m)
                if req.home_elev_m is not None
                else _synthetic_vermont_elevation_fn(float(req.home_lat), float(req.home_lon))
            )
            prefs = prefs.model_copy(
                update={
                    "home_lat": float(req.home_lat),
                    "home_lon": float(req.home_lon),
                    "home_elev_m": float(resolved_home_elev),
                }
            )
            if effective_source_lat is None and (
                req.source_site_id is None or req.source_site_id.strip().upper() == "HOME-NODE"
            ):
                effective_source_lat = float(req.home_lat)
                effective_source_lon = float(req.home_lon)
                effective_source_elev = float(resolved_home_elev)

        source_site = _resolve_endpoint_site(
            site_id=req.source_site_id,
            lat=effective_source_lat,
            lon=effective_source_lon,
            elev_m=effective_source_elev,
            mast_m=req.source_mast_m,
            default_is_home=True,
            prefs=prefs,
            nodes_by_id=nodes_by_id,
        )
        target_site_id = req.target_site_id or req.site_id
        target_site = _resolve_endpoint_site(
            site_id=target_site_id,
            lat=req.target_lat,
            lon=req.target_lon,
            elev_m=req.target_elev_m,
            mast_m=req.target_mast_m,
            default_is_home=False,
            prefs=prefs,
            nodes_by_id=nodes_by_id,
        )

        min_lat = min(source_site.location.lat, target_site.location.lat) - 0.05
        max_lat = max(source_site.location.lat, target_site.location.lat) + 0.05
        min_lon = min(source_site.location.lon, target_site.location.lon) - 0.05
        max_lon = max(source_site.location.lon, target_site.location.lon) + 0.05
        bounds = RegionalBounds(
            name="Link_Transect_Bounds",
            min_lat=max(-90.0, min_lat),
            max_lat=min(90.0, max_lat),
            min_lon=max(-180.0, min_lon),
            max_lon=min(180.0, max_lon),
        )

        elev_adapter = _build_offline_elevation_adapter(bounds=bounds)
        prof_res = elev_adapter.get_elevation_profile(
            source=source_site,
            target=target_site,
            num_samples=25,
        )
        if not prof_res.ok or prof_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=prof_res.error.message if prof_res.error else "Elevation profile failed",
            )
        profile = prof_res.value

        fresnel_res = analyze_fresnel_clearance(
            profile=profile,
            frequency_mhz=radio.frequency_mhz,
        )
        itm_res = evaluate_point_to_point_link(
            profile=profile,
            radio=radio,
        )
        if not fresnel_res.ok or fresnel_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=fresnel_res.error.message if fresnel_res.error else "Fresnel analysis failed",
            )
        if not itm_res.ok or itm_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=itm_res.error.message if itm_res.error else "ITM evaluation failed",
            )

        fresnel = fresnel_res.value
        link = itm_res.value

        profile_points: List[Dict[str, Any]] = []
        for pt in fresnel.point_analyses:
            f60_lower = pt.los_height_m - 0.60 * pt.first_fresnel_radius_m
            f60_upper = pt.los_height_m + 0.60 * pt.first_fresnel_radius_m
            profile_points.append(
                {
                    "distance_km": round(pt.distance_m / 1000.0, 4),
                    "distance_m": round(pt.distance_m, 2),
                    "terrain_elev_m": round(pt.terrain_elevation_m, 2),
                    "earth_bulge_m": round(pt.earth_bulge_m, 2),
                    "effective_terrain_m": round(pt.effective_terrain_height_m, 2),
                    "los_height_m": round(pt.los_height_m, 2),
                    "fresnel_radius_m": round(pt.first_fresnel_radius_m, 2),
                    "fresnel_60pct_lower_m": round(f60_lower, 2),
                    "fresnel_60pct_upper_m": round(f60_upper, 2),
                    "clearance_m": round(pt.clearance_m, 2),
                    "clearance_ratio": round(pt.clearance_ratio, 4),
                    "knife_edge_nu": round(pt.knife_edge_nu, 4),
                }
            )

        return {
            "ok": True,
            "source": source_site.model_dump(mode="json"),
            "target": target_site.model_dump(mode="json"),
            "hardware_preset": hw_id,
            "protocol_profile": proto_id,
            "season_profile": season_id,
            "radio_config": radio.model_dump(mode="json"),
            "link_budget": link.model_dump(mode="json"),
            "fresnel_analysis": {
                "source_id": fresnel.source_id,
                "target_id": fresnel.target_id,
                "total_distance_m": round(fresnel.total_distance_m, 2),
                "frequency_mhz": fresnel.frequency_mhz,
                "k_factor": round(fresnel.k_factor, 4),
                "has_line_of_sight": fresnel.has_line_of_sight,
                "fresnel_60pct_clear": fresnel.fresnel_60pct_clear,
                "min_clearance_m": round(fresnel.min_clearance_m, 3),
                "min_clearance_ratio": round(fresnel.min_clearance_ratio, 4),
                "max_knife_edge_nu": round(fresnel.max_knife_edge_nu, 4),
            },
            "profile_points": profile_points,
        }

    @app.post("/api/viewshed")
    async def post_viewshed_radial_polygon(
        req: Optional[ViewshedRequest] = Body(default=None),
    ) -> Dict[str, Any]:
        async with _get_viewshed_semaphore():
            prefs = registry.get_preferences()
            nodes_by_id = {n.site_id: n for n in registry.list_nodes()}
            req_obj = req or ViewshedRequest()

            hw_id = (req_obj.hardware_preset or prefs.hardware_preset).strip().upper()
            proto_id = (req_obj.protocol_profile or prefs.protocol_profile).strip().upper()
            season_id = (req_obj.season_profile or prefs.season_profile).strip().upper()

            radio_res = build_radio_config(
                hardware_id=hw_id,
                protocol_id=proto_id,
                season_id=season_id,
            )
            if not radio_res.ok or radio_res.value is None:
                raise HTTPException(
                    status_code=400,
                    detail=radio_res.error.message if radio_res.error else "Invalid radio preset",
                )
            radio = radio_res.value

            origin_site = _resolve_endpoint_site(
                site_id=req_obj.site_id,
                lat=req_obj.lat,
                lon=req_obj.lon,
                elev_m=req_obj.elev_m,
                mast_m=req_obj.mast_m,
                default_is_home=True,
                prefs=prefs,
                nodes_by_id=nodes_by_id,
            )

            radials = min(max(req_obj.num_radials, 8), 720)
            max_range = min(max(req_obj.max_range_km, 1.0), 150.0)

            res = await asyncio.to_thread(
                compute_radial_viewshed_polygon,
                origin=origin_site,
                num_radials=radials,
                max_range_km=max_range,
                radio=radio,
                elevation_fn=_synthetic_vermont_elevation_fn,
            )
            if not res.ok or res.value is None:
                raise HTTPException(
                    status_code=500,
                    detail=res.error.message if res.error else "Radial viewshed calculation failed",
                )

            poly_data = res.value.model_dump(mode="json")
            return {
                "ok": True,
                "viewshed": poly_data,
            }

    compute_viewshed_endpoint = post_viewshed_radial_polygon

    @app.post("/api/viewshed/composite")
    async def post_composite_viewshed(
        req: Optional[CompositeViewshedRequest] = Body(default=None),
    ) -> Dict[str, Any]:
        async with _get_viewshed_semaphore():
            req_obj = req or CompositeViewshedRequest()
            combined_candidates: List[SiteCandidate] = []
            seen_ids = set()

            def add_candidate(cand: Optional[SiteCandidate]) -> None:
                if cand is not None and cand.site_id not in seen_ids:
                    seen_ids.add(cand.site_id)
                    combined_candidates.append(cand)

            if req_obj.include_active_nodes:
                all_nodes = registry.list_nodes()
                for node in all_nodes:
                    if node.status == DeploymentStatus.ACTIVE_ON_AIR:
                        cand = _node_to_site_candidate(node, fixture_lookup)
                        add_candidate(cand)

            for sid in req_obj.site_ids:
                cand = _lookup_site_candidate(sid, fixture_lookup, registry, app)
                if cand is not None:
                    add_candidate(cand)

            for pin in req_obj.ad_hoc_pins:
                cand = pin_to_site_candidate(pin)
                add_candidate(cand)

            radials = min(max(req_obj.num_radials, 8), 720)
            max_range = min(max(req_obj.max_range_km, 1.0), 150.0)

            res = await asyncio.to_thread(
                compute_composite_viewshed,
                origins=combined_candidates,
                max_range_km=max_range,
                num_radials=radials,
            )
            if not res.ok or res.value is None:
                raise HTTPException(
                    status_code=500,
                    detail=res.error.message if res.error else "Composite viewshed calculation failed",
                )

            comp_data = res.value.model_dump(mode="json")
            return {
                "ok": True,
                "count": len(combined_candidates),
                "composite": comp_data,
                "composite_viewshed": comp_data,
            }

    compute_composite_viewshed_endpoint = post_composite_viewshed

    @app.post("/api/pins/sample-elevation")
    def sample_elevation_endpoint(
        req: SampleElevationRequest,
    ) -> Dict[str, Any]:
        elev = sample_terrain_elevation(req.lat, req.lon)
        return {
            "ok": True,
            "lat": req.lat,
            "lon": req.lon,
            "elevation_m": elev,
        }

    @app.post("/api/pins/promote")
    def promote_pin_endpoint(req: PromotePinRequest) -> Dict[str, Any]:
        cand = pin_to_site_candidate(req.pin)
        try:
            status_enum = (
                DeploymentStatus(req.status.lower())
                if isinstance(req.status, str)
                else req.status
            )
        except (ValueError, KeyError):
            status_enum = DeploymentStatus.CANDIDATE

        res = registry.create_node(cand, status=status_enum)
        if not res.ok or res.value is None:
            raise HTTPException(
                status_code=500,
                detail=res.error.message if res.error else "Failed to promote pin to registry",
            )
        fixture_lookup[cand.site_id] = cand
        return {
            "ok": True,
            "site_id": cand.site_id,
            "name": cand.name,
        }

    @app.post("/api/home-check")
    def evaluate_home_check(
        req: Optional[HomeCheckRequest] = Body(default=None),
    ) -> Dict[str, Any]:
        prefs = registry.get_preferences()
        req_obj = req or HomeCheckRequest()

        home_lat = req_obj.home_lat if req_obj.home_lat is not None else prefs.home_lat
        home_lon = req_obj.home_lon if req_obj.home_lon is not None else prefs.home_lon
        home_elev = (
            req_obj.home_elev_m
            if req_obj.home_elev_m is not None
            else (
                prefs.home_elev_m
                if (req_obj.home_lat is None and req_obj.home_lon is None)
                else _synthetic_vermont_elevation_fn(home_lat, home_lon)
            )
        )
        home_agl = (
            req_obj.home_height_agl_m
            if req_obj.home_height_agl_m is not None
            else prefs.home_height_agl_m
        )

        if req_obj.persist_height and req_obj.home_height_agl_m is not None:
            prefs = registry.save_preferences(
                prefs.model_copy(update={"home_height_agl_m": home_agl})
            )

        hw_id = (req_obj.hardware_preset or prefs.hardware_preset).strip().upper()
        proto_id = (req_obj.protocol_profile or prefs.protocol_profile).strip().upper()
        season_id = (req_obj.season_profile or prefs.season_profile).strip().upper()

        radio_res = build_radio_config(
            hardware_id=hw_id,
            protocol_id=proto_id,
            season_id=season_id,
        )
        if not radio_res.ok or radio_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=radio_res.error.message if radio_res.error else "Invalid radio preset",
            )

        nodes = registry.list_nodes()
        reach_res = evaluate_home_node_reach(
            home_coord=Coordinate(lat=home_lat, lon=home_lon, elevation_m=home_elev),
            home_height_agl_m=home_agl,
            nodes=nodes,
            radio=radio_res.value,
            elevation_fn=_synthetic_vermont_elevation_fn,
        )
        if not reach_res.ok or reach_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=reach_res.error.message if reach_res.error else "Home reach check failed",
            )

        report_dict = reach_res.value.model_dump(mode="json")
        return {
            "ok": True,
            **report_dict,
            "report": report_dict,
        }

    @app.post("/api/optimize")
    def optimize_backbone(
        req: Optional[OptimizeBackboneRequest] = Body(default=None),
    ) -> Dict[str, Any]:
        prefs = registry.get_preferences()
        req_obj = req or OptimizeBackboneRequest()

        region = req_obj.region or prefs.last_region or "vt_chittenden"
        bounds, _ = load_regional_fixtures(region=region)

        hw_id = (req_obj.hardware_preset or prefs.hardware_preset).strip().upper()
        proto_id = (req_obj.protocol_profile or prefs.protocol_profile).strip().upper()
        season_id = (req_obj.season_profile or prefs.season_profile).strip().upper()
        radio_res = build_radio_config(
            hardware_id=hw_id,
            protocol_id=proto_id,
            season_id=season_id,
        )
        radio = (
            radio_res.value
            if (radio_res.ok and radio_res.value is not None)
            else RadioConfig(frequency_mhz=915.0, tx_power_dbm=20.0)
        )

        # Build candidates from LivingMeshRegistry (excluding BLOCKED and DISMANTLED sites)
        all_nodes = registry.list_nodes()
        active_nodes = [
            n
            for n in all_nodes
            if n.status not in (DeploymentStatus.BLOCKED, DeploymentStatus.DISMANTLED)
            and bounds.contains(n.coordinate)
        ]
        if not active_nodes:
            active_nodes = [
                n
                for n in all_nodes
                if n.status not in (DeploymentStatus.BLOCKED, DeploymentStatus.DISMANTLED)
            ]

        node_by_id = {n.site_id: n for n in active_nodes}
        candidates = [_node_to_site_candidate(n, fixture_lookup) for n in active_nodes]

        grid_res = generate_target_grid(
            bounds=bounds,
            lat_steps=4,
            lon_steps=4,
            elevation_fn=lambda lat, lon: 95.0,
            rx_height_m=2.0,
        )
        if not grid_res.ok or not grid_res.value:
            raise HTTPException(status_code=500, detail="Target grid generation failed.")
        targets = grid_res.value

        viewsheds: List[ViewshedResult] = []
        coverage_by_site: Dict[str, float] = {}
        custom_costs: Dict[str, float] = {}

        for cand in candidates:
            vs_res = compute_viewshed(
                repeater=cand,
                targets=targets,
                radio=radio,
                min_margin_db=6.0,
                require_los=False,
                num_samples=12,
            )
            if vs_res.ok and vs_res.value is not None:
                viewsheds.append(vs_res.value)
                coverage_by_site[cand.site_id] = vs_res.value.weighted_coverage_fraction

            node_status = node_by_id[cand.site_id].status
            if node_status == DeploymentStatus.ACTIVE_ON_AIR:
                # Sunk cost for already on-air repeaters prioritizes them first in greedy set-cover
                custom_costs[cand.site_id] = 0.01
            elif node_status == DeploymentStatus.TESTING:
                custom_costs[cand.site_id] = round(
                    max(0.05, estimate_site_deployment_cost(cand) * 0.5), 4
                )

        opt_res = solve_minimum_set_cover(
            viewsheds=viewsheds,
            target_coverage_fraction=req_obj.min_coverage,
            max_repeaters=req_obj.max_repeaters,
            site_costs=custom_costs,
        )
        if not opt_res.ok or opt_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=opt_res.error.message if opt_res.error else "Set-cover optimization failed",
            )

        rank_res = rank_candidate_sites(
            sites=candidates,
            coverage_by_site=coverage_by_site,
        )
        ranked_scores = rank_res.value if (rank_res.ok and rank_res.value) else []
        score_lookup = {s.site.site_id: s for s in ranked_scores}

        opt = opt_res.value
        selected_summary: List[Dict[str, Any]] = []
        for step in opt.selection_steps:
            viability = score_lookup.get(step.site.site_id)
            reg_node = node_by_id.get(step.site.site_id)
            selected_summary.append(
                {
                    "step": step.step,
                    "site_id": step.site.site_id,
                    "name": step.site.name,
                    "site_type": step.site.site_type.value,
                    "status": reg_node.status.value if reg_node else "candidate",
                    "lat": step.site.location.lat,
                    "lon": step.site.location.lon,
                    "elevation_m": step.site.location.elevation_m,
                    "mast_height_m": step.site.mast_height_m,
                    "deployment_cost": step.cost,
                    "newly_covered_targets": len(step.newly_covered_target_ids),
                    "cumulative_coverage_fraction": step.cumulative_coverage_fraction,
                    "cumulative_weighted_coverage_fraction": step.cumulative_weighted_coverage_fraction,
                    "viability_score": viability.composite_score if viability else 75.0,
                    "desense_risk": viability.desense_risk.value if viability else "low",
                    "requires_cavity_filter": (
                        viability.requires_cavity_filter if viability else False
                    ),
                }
            )

        return {
            "ok": True,
            "region": bounds.name,
            "total_candidates_evaluated": len(candidates),
            "total_target_points": opt.total_targets,
            "target_coverage_threshold": opt.target_coverage_threshold,
            "achieved_coverage_fraction": opt.achieved_coverage_fraction,
            "achieved_weighted_coverage_fraction": opt.achieved_weighted_coverage_fraction,
            "threshold_met": opt.threshold_met,
            "total_deployment_cost": opt.total_cost,
            "active_on_air_count": sum(
                1 for n in active_nodes if n.status == DeploymentStatus.ACTIVE_ON_AIR
            ),
            "selected_repeaters": selected_summary,
            "top_ranked_sites": [
                {
                    "site_id": s.site.site_id,
                    "name": s.site.name,
                    "site_type": s.site.site_type.value,
                    "status": (
                        node_by_id[s.site.site_id].status.value
                        if s.site.site_id in node_by_id
                        else "candidate"
                    ),
                    "composite_score": s.composite_score,
                    "access_and_ownership_score": s.access_and_ownership_score,
                    "rf_cleanliness_score": s.rf_cleanliness_score,
                    "desense_risk": s.desense_risk.value,
                    "requires_cavity_filter": s.requires_cavity_filter,
                    "coverage_fraction": coverage_by_site.get(s.site.site_id, 0.0),
                }
                for s in ranked_scores[:10]
            ],
        }

    @app.post("/api/mesh/route")
    def find_mesh_route_endpoint(req: MeshRouteRequest) -> Dict[str, Any]:
        prefs = registry.get_preferences()
        nodes = registry.list_nodes()
        nodes_by_id = {n.site_id: n for n in nodes}

        def _get_cand(sid: str) -> SiteCandidate:
            if sid in nodes_by_id:
                return _node_to_site_candidate(nodes_by_id[sid], fixture_lookup)
            if sid in fixture_lookup:
                return fixture_lookup[sid]
            raise HTTPException(status_code=404, detail=f"Site '{sid}' not found")

        origin_cand = _get_cand(req.origin_site_id)
        dest_cand = _get_cand(req.destination_site_id)

        all_cands_dict: Dict[str, SiteCandidate] = {
            s.site_id: s for s in fixture_lookup.values()
        }
        for n in nodes:
            if n.status not in (DeploymentStatus.BLOCKED, DeploymentStatus.DISMANTLED):
                all_cands_dict[n.site_id] = _node_to_site_candidate(n, fixture_lookup)
        all_cands = list(all_cands_dict.values())

        hw_id = (req.hardware_preset or prefs.hardware_preset).strip().upper()
        proto_id = (req.protocol_profile or prefs.protocol_profile).strip().upper()
        season_id = (req.season_profile or prefs.season_profile).strip().upper()
        radio_res = build_radio_config(hardware_id=hw_id, protocol_id=proto_id, season_id=season_id)
        radio = radio_res.value if radio_res.ok else RadioConfig()

        route_res = find_optimal_mesh_route(
            origin=origin_cand,
            destination=dest_cand,
            candidate_repeaters=all_cands,
            radio=radio,
            elevation_fn=_synthetic_vermont_elevation_fn,
            max_hops=req.max_hops,
            min_link_margin_db=req.min_link_margin_db,
        )
        if not route_res.ok or route_res.value is None:
            raise HTTPException(status_code=500, detail="Failed to calculate mesh route")

        return {
            "ok": True,
            "route": route_res.value.model_dump(mode="json"),
        }

    @app.get("/api/export/snapshot")
    def export_club_snapshot(
        fuzz_private_nodes: bool = Query(default=True),
    ) -> Dict[str, Any]:
        snap = registry.export_snapshot(fuzz_private_nodes=fuzz_private_nodes)
        return {
            "ok": True,
            **snap,
        }

    @app.post("/api/import/snapshot")
    def import_club_snapshot(
        request: Request,
        payload: Dict[str, Any] = Body(...),
    ) -> Dict[str, Any]:
        if not _verify_coordinator_auth(request):
            raise HTTPException(
                status_code=403,
                detail="Hosted mode: coordinator authentication required to mutate permanent mesh topology.",
            )
        target_payload = payload.get("snapshot") if "snapshot" in payload else payload
        if not isinstance(target_payload, dict):
            raise HTTPException(status_code=400, detail="Invalid snapshot JSON payload.")

        raw_nodes = target_payload.get("nodes")
        if isinstance(raw_nodes, list):
            if len(raw_nodes) > 500:
                raise HTTPException(
                    status_code=400,
                    detail=f"Snapshot payload contains {len(raw_nodes)} nodes, exceeding maximum limit of 500 nodes.",
                )
            for node_data in raw_nodes:
                if isinstance(node_data, dict):
                    if not node_data.get("updated_at"):
                        node_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                    src_url = node_data.get("source_url")
                    if src_url is not None and isinstance(src_url, str):
                        clean_url = src_url.strip()
                        if clean_url:
                            lowered = clean_url.lower()
                            if "javascript:" in lowered or not (
                                lowered.startswith("http://") or lowered.startswith("https://")
                            ):
                                raise HTTPException(
                                    status_code=400,
                                    detail="Invalid source_url: must start with http:// or https:// and cannot contain javascript:",
                                )

        res = registry.import_snapshot(target_payload)
        if not res.ok or res.value is None:
            raise HTTPException(
                status_code=400,
                detail=res.error.message if res.error else "Snapshot import failed.",
            )

        for node in registry.list_nodes():
            if node.site_id not in fixture_lookup:
                fixture_lookup[node.site_id] = _node_to_site_candidate(node, fixture_lookup)

        return {
            "ok": True,
            "imported_count": res.value,
        }

    @app.get("/api/pitch-sheet/{site_id}", response_class=HTMLResponse)
    def get_landowner_pitch_sheet(site_id: str) -> HTMLResponse:
        nodes_by_id = {n.site_id: n for n in registry.list_nodes()}
        if site_id not in nodes_by_id and site_id not in fixture_lookup:
            raise HTTPException(status_code=404, detail=f"Site '{site_id}' not found.")

        node = nodes_by_id.get(site_id)
        if node is None:
            cand = fixture_lookup[site_id]
            node = RegisteredNode(
                site_id=cand.site_id,
                name=cand.name,
                coordinate=cand.location,
                height_agl_m=cand.mast_height_m,
                site_type=cand.site_type,
                status=DeploymentStatus.CANDIDATE,
                hardware_preset="RAK4631_SOLAR",
                is_public_land=True,
                notes=cand.notes or "",
                updated_at="2026-10-26T00:00:00Z",
            )
        else:
            cand = _node_to_site_candidate(node, fixture_lookup)

        enriched = _enrich_node_dict(node, fixture_lookup)
        prefs = registry.get_preferences()

        # Use meshscout.reporting.generate_landowner_pitch_html if available
        pitch_fn = getattr(reporting, "generate_landowner_pitch_html", None)
        if callable(pitch_fn):
            try:
                v_score = score_site_viability(cand).value
                sig = inspect.signature(pitch_fn)
                kwargs: Dict[str, Any] = {}
                for param_name in sig.parameters:
                    if param_name in ("site", "candidate", "site_candidate"):
                        kwargs[param_name] = cand
                    elif param_name in ("viability", "viability_score", "score"):
                        kwargs[param_name] = v_score
                    elif param_name in ("node", "registered_node"):
                        kwargs[param_name] = node
                    elif param_name in ("hardware_preset", "preset_id"):
                        kwargs[param_name] = node.hardware_preset
                    elif param_name in ("preferences", "prefs"):
                        kwargs[param_name] = prefs
                html_out = pitch_fn(**kwargs)
                if isinstance(html_out, str) and "<html" in html_out.lower():
                    return HTMLResponse(content=html_out, status_code=200)
            except Exception:
                pass

        html_fallback = _fallback_landowner_pitch_html(
            site=cand,
            node=node,
            viability_dict=enriched,
            prefs=prefs,
        )
        return HTMLResponse(content=html_fallback, status_code=200)

    @app.get("/api/reports/landowner/{site_id}")
    def get_landowner_report_endpoint(
        site_id: str,
        format: Optional[str] = Query(default=None),
        contact_org: str = Query(default="Vermont Community Emergency Mesh Initiative"),
    ) -> Any:
        sid = site_id.strip()
        site: Optional[SiteCandidate] = None

        if hasattr(registry, "get_node") and callable(getattr(registry, "get_node")):
            try:
                node = registry.get_node(sid)
                if node is not None:
                    site = (
                        _node_to_site_candidate(node, fixture_lookup)
                        if isinstance(node, RegisteredNode)
                        else node
                    )
            except Exception:
                pass

        if site is None:
            if sid in fixture_lookup:
                site = fixture_lookup[sid]
            else:
                for k, v in fixture_lookup.items():
                    if k.upper() == sid.upper():
                        site = v
                        break

        if site is None:
            t_reg = _get_thread_local_tower_registry(app)
            if hasattr(t_reg, "get_tower") and callable(getattr(t_reg, "get_tower")):
                try:
                    site = t_reg.get_tower(sid)
                except Exception:
                    pass

        if site is None:
            site = _lookup_site_candidate(sid, fixture_lookup, registry, app)

        if site is None:
            return JSONResponse(
                status_code=404,
                content={"ok": False, "error": "Site not found"},
            )

        html_content = generate_landowner_pitch_html(
            site=site,
            contact_org=contact_org,
        )

        if format and format.strip().lower() == "html":
            return HTMLResponse(content=html_content, status_code=200)

        return {
            "ok": True,
            "site_id": site.site_id,
            "site_name": site.name,
            "html": html_content,
        }

    @app.post("/api/reports/landowner")
    def post_landowner_report_endpoint(
        req: LandownerReportRequest,
        format: Optional[str] = Query(default=None),
    ) -> Any:
        if isinstance(req.site_type, SiteType):
            st = req.site_type
        else:
            try:
                st = SiteType(str(req.site_type).lower())
            except ValueError:
                st = SiteType.CUSTOM

        raw_id = getattr(req, "site_id", None)
        if not raw_id:
            clean_slug = re.sub(r"[^A-Za-z0-9]+", "-", req.name.strip()).strip("-").upper()
            raw_id = f"CUSTOM-{clean_slug[:16]}" if clean_slug else f"CUSTOM-{uuid.uuid4().hex[:8].upper()}"

        site = SiteCandidate(
            site_id=raw_id,
            name=req.name.strip(),
            location=Coordinate(
                lat=float(req.lat),
                lon=float(req.lon),
                elevation_m=float(req.elevation_m),
            ),
            site_type=st,
            mast_height_m=float(req.mast_height_m),
            has_grid_power=False,
            solar_exposure_pct=90.0,
            access_difficulty=AccessDifficulty.MODERATE,
        )

        html_content = generate_landowner_pitch_html(
            site=site,
            contact_org=req.contact_org,
        )

        if format and format.strip().lower() == "html":
            return HTMLResponse(content=html_content, status_code=200)

        return {
            "ok": True,
            "site_id": site.site_id,
            "site_name": site.name,
            "html": html_content,
        }

    @app.get("/api/survey/{source_id}/{target_id}", response_class=HTMLResponse)
    def get_link_survey_dossier(source_id: str, target_id: str) -> HTMLResponse:
        prefs = registry.get_preferences()
        nodes_by_id = {n.site_id: n for n in registry.list_nodes()}

        def _resolve_cand(sid: str) -> SiteCandidate:
            sid_clean = sid.strip()
            if sid_clean.upper() in ("HOME-NODE", "HOME"):
                return SiteCandidate(
                    site_id="HOME-NODE",
                    name=prefs.home_name,
                    location=Coordinate(lat=prefs.home_lat, lon=prefs.home_lon, elevation_m=prefs.home_elev_m),
                    site_type=SiteType.BUILDING_ROOFTOP,
                    mast_height_m=prefs.home_height_agl_m,
                )
            if sid_clean in nodes_by_id:
                return _node_to_site_candidate(nodes_by_id[sid_clean], fixture_lookup)
            if sid_clean in fixture_lookup:
                return fixture_lookup[sid_clean]
            raise HTTPException(status_code=404, detail=f"Site '{sid}' not found.")

        source_cand = _resolve_cand(source_id)
        target_cand = _resolve_cand(target_id)

        min_lat = min(source_cand.location.lat, target_cand.location.lat) - 0.05
        max_lat = max(source_cand.location.lat, target_cand.location.lat) + 0.05
        min_lon = min(source_cand.location.lon, target_cand.location.lon) - 0.05
        max_lon = max(source_cand.location.lon, target_cand.location.lon) + 0.05
        bounds = RegionalBounds(
            name="Survey_Link_Bounds",
            min_lat=max(-90.0, min_lat),
            max_lat=min(90.0, max_lat),
            min_lon=max(-180.0, min_lon),
            max_lon=min(180.0, max_lon),
        )

        elev_adapter = _build_offline_elevation_adapter(bounds=bounds)
        prof_res = elev_adapter.get_elevation_profile(source=source_cand, target=target_cand, num_samples=25)
        if not prof_res.ok or prof_res.value is None:
            raise HTTPException(status_code=500, detail="Elevation profile sampling failed.")

        radio_res = build_radio_config(
            hardware_id=prefs.hardware_preset,
            protocol_id=prefs.protocol_profile,
            season_id=prefs.season_profile,
        )
        radio = radio_res.value if radio_res.ok else RadioConfig()
        itm_res = evaluate_point_to_point_link(profile=prof_res.value, radio=radio)
        if not itm_res.ok or itm_res.value is None:
            raise HTTPException(status_code=500, detail="ITM link evaluation failed.")

        survey_fn = getattr(reporting, "generate_link_survey_html", None)
        if callable(survey_fn):
            html_out = survey_fn(
                source=source_cand,
                target=target_cand,
                link=itm_res.value,
                radio=radio,
            )
            return HTMLResponse(content=html_out, status_code=200)

        raise HTTPException(status_code=500, detail="Survey generator unavailable.")

    @app.get("/api/export/html", response_class=HTMLResponse)
    def export_portable_html() -> HTMLResponse:
        prefs = registry.get_preferences()
        nodes = registry.list_nodes()
        enriched_sites = [_enrich_node_dict(n, fixture_lookup) for n in nodes]
        radio_res = build_radio_config(
            hardware_id=prefs.hardware_preset,
            protocol_id=prefs.protocol_profile,
            season_id=prefs.season_profile,
        )
        reach_res = evaluate_home_node_reach(
            home_coord=Coordinate(
                lat=prefs.home_lat, lon=prefs.home_lon, elevation_m=prefs.home_elev_m
            ),
            home_height_agl_m=prefs.home_height_agl_m,
            nodes=nodes,
            radio=radio_res.value if radio_res.ok else None,
            elevation_fn=_synthetic_vermont_elevation_fn,
        )
        reach_dict = (
            reach_res.value.model_dump(mode="json")
            if (reach_res.ok and reach_res.value is not None)
            else {"ranked_towers": []}
        )

        export_fn = getattr(reporting, "generate_portable_workbench_html", None)
        if callable(export_fn):
            try:
                sig = inspect.signature(export_fn)
                kwargs: Dict[str, Any] = {}
                for param_name in sig.parameters:
                    if param_name in ("preferences", "prefs"):
                        kwargs[param_name] = prefs
                    elif param_name in ("nodes", "registered_nodes"):
                        kwargs[param_name] = nodes
                    elif param_name in ("sites", "enriched_sites"):
                        kwargs[param_name] = enriched_sites
                    elif param_name in ("home_reach", "reach_report", "report"):
                        kwargs[param_name] = reach_res.value if reach_res.ok else None
                html_out = export_fn(**kwargs)
                if isinstance(html_out, str) and "<html" in html_out.lower():
                    return HTMLResponse(content=html_out, status_code=200)
            except Exception:
                pass

        html_fallback = _fallback_portable_workbench_html(
            prefs=prefs,
            sites=enriched_sites,
            home_report=reach_dict,
        )
        return HTMLResponse(content=html_fallback, status_code=200)

    @app.get("/api/export/gpx")
    def export_gpx_file() -> Response:
        prefs = registry.get_preferences()
        nodes = registry.list_nodes()
        candidates = [_node_to_site_candidate(n, fixture_lookup) for n in nodes]
        home_coord = Coordinate(lat=prefs.home_lat, lon=prefs.home_lon, elevation_m=prefs.home_elev_m)
        gpx_xml = reporting.export_gpx_waypoints(
            sites=candidates,
            include_home=home_coord,
            home_name=prefs.home_name,
        )
        return Response(
            content=gpx_xml,
            media_type="application/gpx+xml",
            headers={"Content-Disposition": 'attachment; filename="meshscout_waypoints.gpx"'},
        )

    @app.get("/api/export/kml")
    def export_kml_file() -> Response:
        prefs = registry.get_preferences()
        nodes = registry.list_nodes()
        candidates = [_node_to_site_candidate(n, fixture_lookup) for n in nodes]
        home_coord = Coordinate(lat=prefs.home_lat, lon=prefs.home_lon, elevation_m=prefs.home_elev_m)
        kml_xml = reporting.export_kml_document(
            sites=candidates,
            include_home=home_coord,
            home_name=prefs.home_name,
        )
        return Response(
            content=kml_xml,
            media_type="application/vnd.google-earth.kml+xml",
            headers={"Content-Disposition": 'attachment; filename="meshscout_topology.kml"'},
        )

    @app.get("/api/export/geojson")
    def export_geojson_file() -> Response:
        nodes = registry.list_nodes()
        candidates = [_node_to_site_candidate(n, fixture_lookup) for n in nodes]
        geojson_data = reporting.export_geojson_feature_collection(sites=candidates)
        return JSONResponse(
            content=geojson_data,
            headers={"Content-Disposition": 'attachment; filename="meshscout_nodes.geojson"'},
        )

    # ==========================================================================
    # Traffic Advisor, Provisioning & MQTT Gap Analysis Endpoints
    # ==========================================================================

    @app.post("/api/advisor/role-airtime")
    def post_advisor_role_airtime(req: AdvisorRoleAirtimeRequest) -> Dict[str, Any]:
        target_site: Optional[SiteCandidate] = None
        if req.site_id:
            target_site = _resolve_site_by_id(req.site_id)

        if target_site is None:
            if req.lat is not None and req.lon is not None:
                target_site = SiteCandidate(
                    site_id=req.site_id or "CUSTOM-NODE",
                    name=req.site_id or "Custom Node",
                    location=Coordinate(
                        lat=req.lat,
                        lon=req.lon,
                        elevation_m=req.elevation_m if req.elevation_m is not None else 100.0,
                    ),
                    site_type=SiteType.CUSTOM,
                    mast_height_m=req.mast_height_m if req.mast_height_m is not None else 10.0,
                )
            elif req.site_id:
                raise HTTPException(status_code=404, detail=f"Site '{req.site_id}' not found.")
            else:
                raise HTTPException(status_code=400, detail="Must provide either site_id or lat and lon.")
        else:
            if (
                req.lat is not None
                or req.lon is not None
                or req.elevation_m is not None
                or req.mast_height_m is not None
            ):
                new_lat = req.lat if req.lat is not None else target_site.location.lat
                new_lon = req.lon if req.lon is not None else target_site.location.lon
                new_elev = req.elevation_m if req.elevation_m is not None else target_site.location.elevation_m
                new_mast = req.mast_height_m if req.mast_height_m is not None else target_site.mast_height_m
                target_site = target_site.model_copy(
                    update={
                        "location": Coordinate(lat=new_lat, lon=new_lon, elevation_m=new_elev),
                        "mast_height_m": new_mast,
                    }
                )

        pop = req.exposed_population if req.exposed_population is not None else 5000
        rec = advise_node_role(
            site=target_site,
            exposed_population=pop,
            overlapping_router_count=req.overlapping_router_count,
            protocol_family=req.protocol_family,
        )
        sf = 9 if rec.recommended_preset == "MediumFast" else 11
        airtime = compute_lora_airtime_ms(payload_bytes=32, sf=sf, bw_hz=250000.0)
        forecast = forecast_channel_utilization(
            exposed_population=pop,
            airtime_ms=airtime.total_airtime_ms,
            hop_limit=rec.recommended_hop_limit,
        )
        isolation_db = compute_antenna_isolation_db(vertical_sep_m=3.0, horizontal_sep_m=0.0)

        return {
            "ok": True,
            "recommendation": rec.model_dump(mode="json"),
            "forecast": forecast.model_dump(mode="json"),
            "isolation_db": isolation_db,
        }

    @app.post("/api/advisor/backhaul")
    def post_advisor_backhaul(req: AdvisorBackhaulRequest) -> Dict[str, Any]:
        src = _resolve_site_by_id(req.source_site_id)
        if src is None:
            raise HTTPException(status_code=404, detail=f"Source site '{req.source_site_id}' not found.")

        tgt = _resolve_site_by_id(req.target_site_id)
        if tgt is None:
            raise HTTPException(status_code=404, detail=f"Target site '{req.target_site_id}' not found.")

        min_lat = min(src.location.lat, tgt.location.lat) - 0.05
        max_lat = max(src.location.lat, tgt.location.lat) + 0.05
        min_lon = min(src.location.lon, tgt.location.lon) - 0.05
        max_lon = max(src.location.lon, tgt.location.lon) + 0.05
        bounds = RegionalBounds(
            name="Backhaul_Bounds",
            min_lat=max(-90.0, min_lat),
            max_lat=min(90.0, max_lat),
            min_lon=max(-180.0, min_lon),
            max_lon=min(180.0, max_lon),
        )
        elev_adapter = _build_offline_elevation_adapter(bounds=bounds)
        prof_res = elev_adapter.get_elevation_profile(source=src, target=tgt, num_samples=25)
        if prof_res.ok and prof_res.value is not None:
            fresnel_res = analyze_fresnel_clearance(profile=prof_res.value, frequency_mhz=915.0)
            has_los = (
                fresnel_res.value.has_line_of_sight
                if (fresnel_res.ok and fresnel_res.value is not None)
                else True
            )
            dist_km = prof_res.value.distance_km
        else:
            dist_km = haversine_distance_km(src.location, tgt.location)
            has_los = True

        rec = recommend_summit_backhaul(
            site_a=src,
            site_b=tgt,
            distance_km=dist_km,
            line_of_sight=has_los,
            channel_utilization_pct=req.channel_utilization_pct,
        )
        return {
            "ok": True,
            "recommendation": rec.model_dump(mode="json"),
        }

    @app.post("/api/backhaul/corridor")
    def post_backhaul_corridor(req: CorridorEvaluationRequest) -> Dict[str, Any]:
        """Evaluate a multi-hop corridor across ordered site IDs and custom sites."""
        resolved_nodes: List[SiteCandidate] = []
        nodes_by_id = {n.site_id: n for n in registry.list_nodes()}

        for sid in req.site_ids:
            sid_clean = sid.strip()
            if not sid_clean:
                continue

            matched: Optional[SiteCandidate] = None

            # 1. Check registry
            if sid_clean in nodes_by_id:
                matched = _node_to_site_candidate(nodes_by_id[sid_clean], fixture_lookup)
            else:
                for n in nodes_by_id.values():
                    if n.site_id.upper() == sid_clean.upper():
                        matched = _node_to_site_candidate(n, fixture_lookup)
                        break

            # 2. Check fixture_lookup
            if matched is None:
                if sid_clean in fixture_lookup:
                    matched = fixture_lookup[sid_clean]
                else:
                    for cand in fixture_lookup.values():
                        if cand.site_id.upper() == sid_clean.upper():
                            matched = cand
                            break

            # 3. Check custom_sites
            if matched is None:
                for cs in req.custom_sites:
                    if cs.site_id == sid_clean or cs.site_id.upper() == sid_clean.upper():
                        matched = cs
                        break

            # 4. Query tower_reg
            if matched is None:
                try:
                    tower_reg = _get_thread_local_tower_registry(app)
                    cursor = tower_reg.conn.cursor()
                    cursor.execute(
                        """
                        SELECT site_id, name, lat, lon, elevation_m, mast_height_m,
                               site_type, access_difficulty, has_grid_power, solar_exposure_pct,
                               notes, source_url
                        FROM towers WHERE site_id = ?
                        """,
                        (sid_clean,),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        raw_type = row["site_type"]
                        try:
                            st = SiteType(raw_type)
                        except ValueError:
                            st = SiteType.CUSTOM
                        raw_acc = row["access_difficulty"]
                        try:
                            ad = AccessDifficulty(raw_acc)
                        except ValueError:
                            ad = AccessDifficulty.MODERATE
                        matched = SiteCandidate(
                            site_id=row["site_id"],
                            name=row["name"],
                            location=Coordinate(
                                lat=float(row["lat"]),
                                lon=float(row["lon"]),
                                elevation_m=float(row["elevation_m"]),
                            ),
                            site_type=st,
                            mast_height_m=float(row["mast_height_m"]),
                            has_grid_power=bool(row["has_grid_power"]),
                            solar_exposure_pct=float(row["solar_exposure_pct"]),
                            access_difficulty=ad,
                            notes=row["notes"] or "",
                            source_url=row["source_url"],
                        )
                    else:
                        for t in tower_reg.query_towers(limit=500):
                            if t.site_id.upper() == sid_clean.upper():
                                matched = t
                                break
                except Exception:
                    pass

            # 5. Append if matched
            if matched is not None:
                resolved_nodes.append(matched)

        # Also append any candidates from req.custom_sites whose IDs are not yet in resolved_nodes
        existing_ids = {n.site_id for n in resolved_nodes}
        for cs in req.custom_sites:
            if cs.site_id not in existing_ids:
                resolved_nodes.append(cs)
                existing_ids.add(cs.site_id)

        radio_cfg = RadioConfig(
            frequency_mhz=req.frequency_mhz,
            tx_power_dbm=req.tx_power_dbm,
        )
        eval_res = evaluate_multihop_corridor(resolved_nodes, radio_config=radio_cfg)
        if not eval_res.ok or eval_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=eval_res.error.message if eval_res.error else "Corridor evaluation failed.",
            )

        return {
            "ok": True,
            "count": len(resolved_nodes),
            "corridor": eval_res.value.model_dump(mode="json"),
        }

    @app.get("/api/provision/{site_id}")
    def get_site_provisioning(
        site_id: str,
        target: str = Query(default="meshtastic"),
        channel_name: str = Query(default="MeshScout"),
    ) -> Dict[str, Any]:
        target_site = _resolve_site_by_id(site_id)
        if target_site is None:
            raise HTTPException(status_code=404, detail=f"Site '{site_id}' not found.")

        target_lower = target.strip().lower()
        if target_lower in ("meshtastic", "mesh"):
            prov_target = ProvisioningTarget.MESHTASTIC
        elif target_lower in ("meshcore", "mesh_core"):
            prov_target = ProvisioningTarget.MESHCORE
        elif target_lower in ("reticulum", "rns"):
            prov_target = ProvisioningTarget.RETICULUM
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported provisioning target: '{target}'"
            )

        payload = generate_site_provisioning(
            site=target_site,
            target=prov_target,
            channel_name=channel_name,
        )
        return {
            "ok": True,
            "payload": payload.model_dump(mode="json"),
        }

    @app.post("/api/provision/{site_id}")
    def post_site_provisioning(
        site_id: str,
        body: Optional[ProvisionSiteRequest] = None,
    ) -> Dict[str, Any]:
        req = body or ProvisionSiteRequest()
        target_site = _resolve_site_by_id(site_id)
        if target_site is None:
            raise HTTPException(status_code=404, detail=f"Site '{site_id}' not found.")

        target_lower = req.target.strip().lower()
        if target_lower in ("meshtastic", "mesh"):
            prov_target = ProvisioningTarget.MESHTASTIC
        elif target_lower in ("meshcore", "mesh_core"):
            prov_target = ProvisioningTarget.MESHCORE
        elif target_lower in ("reticulum", "rns"):
            prov_target = ProvisioningTarget.RETICULUM
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported provisioning target: '{req.target}'"
            )

        # Invariant: Never log or persist private PSK
        payload = generate_site_provisioning(
            site=target_site,
            target=prov_target,
            channel_name=req.channel_name,
            psk_override=req.psk,
        )
        return {
            "ok": True,
            "payload": payload.model_dump(mode="json"),
        }

    @app.post("/api/mqtt/gap-analysis")
    def post_mqtt_gap_analysis(
        body: Optional[MQTTGapAnalysisRequest] = None,
    ) -> Dict[str, Any]:
        req = body or MQTTGapAnalysisRequest()
        heard_nodes: List[MQTTNodeTelemetry] = []

        if req.raw_packets:
            ingest_res = ingest_mqtt_packets(req.raw_packets, apply_privacy_fuzz=True)
            if not ingest_res.ok or ingest_res.value is None:
                raise HTTPException(
                    status_code=400,
                    detail=ingest_res.error.message if ingest_res.error else "Packet parsing error",
                )
            heard_nodes = ingest_res.value
        elif req.use_fixture:
            fix_res = load_mqtt_fixture(DEFAULT_MQTT_FIXTURE_PATH)
            if fix_res.ok and fix_res.value:
                heard_nodes = fix_res.value

        registry_nodes = registry.list_nodes()
        candidates = list(fixture_lookup.values())

        report_res = analyze_unobserved_areas(
            heard_nodes=heard_nodes,
            registry_active_nodes=registry_nodes,
            candidate_sites=candidates,
            reference_towns=VERMONT_REFERENCE_TOWNS_DATA,
            coverage_radius_km=req.coverage_radius_km,
        )
        if not report_res.ok or report_res.value is None:
            raise HTTPException(
                status_code=400,
                detail=report_res.error.message if report_res.error else "Gap analysis failed",
            )

        return {
            "ok": True,
            "report": report_res.value.model_dump(mode="json"),
        }

    @app.get("/api/system/drives")
    def get_removable_drives() -> Dict[str, Any]:
        drives = list_removable_drives()
        return {
            "ok": True,
            "drives": [d.model_dump() for d in drives],
            "count": len(drives),
        }

    @app.get("/api/tiles/{region}/{z}/{x}/{y}.png")
    def get_offline_tile(region: str, z: int, x: int, y: int) -> Response:
        """Serve an offline cartographic raster tile from regional MBTiles or fallback boundary SVG."""
        mbtiles_path = _find_mbtiles_path(
            region, custom_tiles_dir=getattr(app.state, "tiles_dir", None)
        )
        tile_bytes: Optional[bytes] = None

        if mbtiles_path is not None:
            reader_key = str(mbtiles_path.resolve())
            readers = getattr(app.state, "tile_readers", None)
            if readers is None:
                app.state.tile_readers = {}
                readers = app.state.tile_readers

            reader = readers.get(reader_key)
            if reader is None:
                try:
                    reader = MBTilesReader(mbtiles_path)
                    readers[reader_key] = reader
                except Exception:
                    reader = None

            if reader is not None:
                try:
                    tile_bytes = reader.get_tile_bytes(z, x, y)
                except Exception:
                    tile_bytes = None

        if tile_bytes is not None:
            return Response(content=tile_bytes, media_type="image/png")

        return Response(
            content=generate_boundary_tile_svg(region.upper()),
            media_type="image/svg+xml",
        )

    @app.post("/api/stage/field-kit")
    def stage_field_kit(req: StageFieldKitRequest) -> Dict[str, Any]:
        """Stage an offline tactical field kit to a removable USB drive or local path."""
        if req.target_directory:
            out_dir = Path(req.target_directory)
        else:
            out_dir = Path.home() / ".meshscout" / "field-kit"

        staging_fn = None
        try:
            from meshscout.core.staging import stage_offline_region
            staging_fn = stage_offline_region
        except ImportError:
            staging_fn = _fallback_stage_offline_region

        res = staging_fn(
            state_code=req.state,
            output_dir=out_dir,
            buffer_km=req.buffer_km,
            min_zoom=req.min_zoom,
            max_zoom=req.max_zoom,
            include_dem=req.include_dem,
            dry_run=req.dry_run,
        )

        if not req.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "Start_MeshScout.bat").write_text(START_BAT_CONTENT, encoding="utf-8")
            (out_dir / "Start_MeshScout.sh").write_text(START_SH_CONTENT, encoding="utf-8")
            (out_dir / "README_FIELD_OPS.txt").write_text(README_FIELD_OPS_CONTENT, encoding="utf-8")

        summary = res.value if hasattr(res, "value") else res

        return {
            "ok": True,
            "dry_run": req.dry_run,
            "summary": summary,
            "output_dir": str(out_dir),
        }

    @app.get("/api/towers/search")
    def search_towers(
        min_lat: Optional[float] = Query(default=None),
        max_lat: Optional[float] = Query(default=None),
        min_lon: Optional[float] = Query(default=None),
        max_lon: Optional[float] = Query(default=None),
        types: Optional[str] = Query(default=None),
        max_friction: Optional[int] = Query(default=None),
        limit: int = Query(default=300),
        zoom: Optional[int] = Query(default=None),
        region: Optional[str] = Query(default=None),
    ) -> Dict[str, Any]:
        """Search and filter tower infrastructure with spatial, categorical, and friction-tier filters."""
        t_reg = _get_thread_local_tower_registry(app)
        bounds: Optional[RegionalBounds] = None
        if (
            min_lat is not None
            and max_lat is not None
            and min_lon is not None
            and max_lon is not None
        ):
            bounds = RegionalBounds(
                name="search_bbox",
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
            )

        parsed_types: Optional[List[SiteType]] = None
        if types:
            parsed_types = []
            for t_str in types.split(","):
                t_clean = t_str.strip().lower()
                if not t_clean:
                    continue
                try:
                    parsed_types.append(SiteType(t_clean))
                except ValueError:
                    pass

        results = t_reg.query_towers(
            bounds=bounds,
            site_types=parsed_types if parsed_types is not None else None,
            max_friction_tier=max_friction,
            limit=limit,
            zoom=zoom,
            region_code=region,
        )
        return {
            "ok": True,
            "count": len(results),
            "towers": [t.model_dump(mode="json") for t in results],
        }

    @app.post("/api/towers/ingest")
    def ingest_towers_endpoint(
        req: TowerIngestRequest = Body(default_factory=TowerIngestRequest),
    ) -> Dict[str, Any]:
        """Trigger tower ingestion from civic, FCC ASR, or Canadian ISED sources."""
        t_reg = _get_thread_local_tower_registry(app)
        if req.region:
            reg_res = resolve_regional_bounds(req.region)
            if not reg_res.ok and "_" in req.region:
                parts = req.region.split("_", 1)
                reg_res = resolve_regional_bounds(parts[0], parts[1])
            if not reg_res.ok:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid region '{req.region}': {reg_res.error.message if reg_res.error else 'Unknown'}",
                )

        source = (req.source or "all").lower().strip()
        fixtures_dir = Path(__file__).resolve().parent.parent.parent.parent / "fixtures"
        if not fixtures_dir.exists():
            fixtures_dir = Path(__file__).resolve().parent.parent.parent / "fixtures"

        fcc_sample = fixtures_dir / "fcc_asr_vt_sample.dat"
        ised_sample = fixtures_dir / "ised_sms_sample.csv"
        civic_sample = fixtures_dir / "civic_highsites_catalog.json"

        tier_counts = {1: 0, 2: 0, 3: 0}
        total_ingested = 0
        by_region: Dict[str, int] = {}
        sources_to_run: List[Tuple[str, Path]] = []

        if source in ("civic", "civic_osm", "osm"):
            sources_to_run.append(("civic", Path(req.path) if req.path else civic_sample))
        elif source in ("fcc", "fcc_asr"):
            sources_to_run.append(("fcc_asr", Path(req.path) if req.path else fcc_sample))
        elif source in ("ised", "ised_sms"):
            sources_to_run.append(("ised_sms", Path(req.path) if req.path else ised_sample))
        elif source == "all":
            if civic_sample.exists():
                sources_to_run.append(("civic", civic_sample))
            if fcc_sample.exists():
                sources_to_run.append(("fcc_asr", fcc_sample))
            if ised_sample.exists():
                sources_to_run.append(("ised_sms", ised_sample))
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported tower source '{req.source}'. Supported: civic, fcc, ised, all",
            )

        from meshscout.adapters.tower_ingest import ingest_tower_source

        for src_name, src_path in sources_to_run:
            if src_path.exists():
                res = ingest_tower_source(
                    t_reg,
                    source=src_name,
                    path=src_path,
                    region_code=req.region,
                    pack_id=req.pack_id,
                )
                total_ingested += res.get("ingested_count", 0)
                f_counts = res.get("by_friction_tier", {})
                tier_counts[1] += f_counts.get("tier_1_civic", 0) or f_counts.get(1, 0)
                tier_counts[2] += f_counts.get("tier_2_agricultural", 0) or f_counts.get(2, 0)
                tier_counts[3] += f_counts.get("tier_3_commercial", 0) or f_counts.get(3, 0)
                for reg_k, cnt in res.get("by_region", {}).items():
                    by_region[reg_k] = by_region.get(reg_k, 0) + cnt

        return {
            "ok": True,
            "source": source,
            "region": req.region,
            "ingested_count": total_ingested,
            "by_region": by_region,
            "by_friction_tier": {
                "tier_1_civic": tier_counts[1],
                "tier_2_agricultural": tier_counts[2],
                "tier_3_commercial": tier_counts[3],
            },
        }

    @app.get("/api/telemetry/nodes")
    def get_telemetry_nodes(
        region: Optional[str] = Query(default="VT"),
        protocol: Optional[str] = Query(default=None),
        buffer_km: float = Query(default=20.0),
        min_lat: Optional[float] = Query(default=None),
        max_lat: Optional[float] = Query(default=None),
        min_lon: Optional[float] = Query(default=None),
        max_lon: Optional[float] = Query(default=None),
        limit: int = Query(default=500),
    ) -> Dict[str, Any]:
        """Query active and cached telemetry nodes filtered by regional bounds or bounding box."""
        cache = _get_thread_local_telemetry_cache(app)
        if min_lat is not None and max_lat is not None:
            bounds = RegionalBounds(
                name="bbox",
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon if min_lon is not None else -180.0,
                max_lon=max_lon if max_lon is not None else 180.0,
            )
            nodes = cache.query_nodes(bounds=bounds, protocol=protocol, limit=limit)
            counts = cache.count_nodes_by_protocol(bounds=bounds)
        else:
            nodes = cache.query_nodes(
                state_code=region, buffer_km=buffer_km, protocol=protocol, limit=limit
            )
            counts = cache.count_nodes_by_protocol(state_code=region, buffer_km=buffer_km)

        return {
            "ok": True,
            "region": region,
            "buffer_km": buffer_km,
            "count": len(nodes),
            "counts_by_protocol": counts,
            "nodes": [n.model_dump(mode="json") for n in nodes],
        }

    @app.post("/api/telemetry/ingest")
    def ingest_telemetry_endpoint(
        req: TelemetryIngestRequest = Body(...),
    ) -> Dict[str, Any]:
        """Ingest live telemetry packets from Meshtastic MQTT or MeshCore / Reticulum announcements."""
        proto = req.protocol.strip().lower()
        if proto == "meshtastic":
            res = ingest_mqtt_packets(req.raw_data, apply_privacy_fuzz=req.apply_fuzz)
            if not res.ok:
                raise HTTPException(
                    status_code=400,
                    detail=res.error.message if res.error else "Invalid meshtastic packet stream",
                )
            mqtt_records = res.value or []
            telemetry_nodes = [
                TelemetryNode(
                    node_id=rec.node_id,
                    protocol="meshtastic",
                    short_name=rec.short_name,
                    long_name=rec.long_name,
                    coordinate=rec.coordinate,
                    snr_db=rec.snr_db,
                    rssi_dbm=rec.rssi_dbm,
                    channel=rec.channel,
                    last_heard_iso=rec.last_heard_iso,
                    is_synthetic=rec.is_synthetic,
                )
                for rec in mqtt_records
            ]
        elif proto == "meshcore":
            telemetry_nodes = parse_meshcore_announces(req.raw_data)
            if req.apply_fuzz:
                from meshscout.adapters.mqtt import _fuzz_coordinate
                for node in telemetry_nodes:
                    node.coordinate = _fuzz_coordinate(node.coordinate)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported protocol '{req.protocol}'. Must be 'meshtastic' or 'meshcore'.",
            )

        cache = _get_thread_local_telemetry_cache(app)
        count = cache.bulk_upsert_nodes(telemetry_nodes)
        return {"ok": True, "ingested_count": count}

    @app.get("/api/v1/archetypes")
    def get_community_archetypes_endpoint() -> Dict[str, Any]:
        """List all canonical community deployment archetypes and cross-protocol mappings."""
        return {
            "ok": True,
            "archetypes": {k.value: v.model_dump(mode="json") for k, v in COMMUNITY_SITE_ARCHETYPES.items()},
        }

    @app.get("/api/v1/archetypes/{site_id}/evaluate")
    def evaluate_site_archetype_endpoint(
        site_id: str,
        protocol_family: str = Query("Meshtastic", description="Target protocol (Meshtastic, MeshCore, Reticulum, GenericLoRa)"),
        exposed_population: int = Query(5000, description="Estimated exposed population"),
    ) -> Dict[str, Any]:
        """Classify a site candidate into its community archetype and return validated cross-protocol guidance."""
        from meshscout.mcp_server import _resolve_site_by_id
        site = _resolve_site_by_id(site_id)
        if not site:
            reg = LivingMeshRegistry(db_path=getattr(app.state, "db_path", None))
            node = reg.get_node(site_id)
            if node:
                site = SiteCandidate(
                    site_id=node.node_id,
                    name=node.name,
                    location=node.location,
                    site_type=SiteType.BUILDING_ROOFTOP,
                    mast_height_m=node.mast_height_m,
                )
        if not site:
            raise HTTPException(status_code=404, detail=f"Site ID '{site_id}' not found.")

        arch = classify_site_archetype(site, exposed_population=exposed_population)
        guidance = get_archetype_recommendation(arch, protocol_family=protocol_family)
        spec = COMMUNITY_SITE_ARCHETYPES[arch]
        all_mappings = {k: v.model_dump(mode="json") for k, v in spec.protocol_mappings.items()}

        is_mega_summit = (arch == SiteArchetype.ALPINE_MEGA_SUMMIT)
        return {
            "ok": True,
            "site_id": site.site_id,
            "site_name": site.name,
            "elevation_m": site.location.elevation_m,
            "mast_height_m": site.mast_height_m,
            "site_type": site.site_type.value,
            "archetype": arch.value,
            "archetype_label": spec.label,
            "is_mega_summit": is_mega_summit,
            "split_horizon_required": is_mega_summit,
            "anti_pattern_warning": (
                "CRITICAL: Elevated summit. Do NOT operate a single-radio co-channel repeater on the public channel."
                if is_mega_summit else None
            ),
            "protocol_recommendation": guidance,
            "all_protocol_mappings": all_mappings,
        }

    @app.get("/api/v1/packs")
    def get_packs_endpoint() -> Dict[str, Any]:
        """List installed and remotely available regional tower data packs."""
        from meshscout.core.packs import list_installed_packs
        from meshscout.adapters.pack_client import PackClient
        from meshscout.adapters.regions import get_state_info

        t_reg = _get_thread_local_tower_registry(app)
        installed = list_installed_packs(t_reg)
        available: List[Dict[str, Any]] = []
        manifest_error: Optional[str] = None
        try:
            client = PackClient()
            avail_res = client.list_available_packs()
            if avail_res.ok and avail_res.value is not None:
                for p in avail_res.value:
                    pd = p.model_dump(mode="json")
                    # Enrich license tags and bounds
                    lics = [
                        s.get("license") for s in pd.get("sources", [])
                        if isinstance(s, dict) and s.get("license")
                    ]
                    pd["licenses"] = list(dict.fromkeys(lics))
                    pd["site_count"] = pd.get("row_count", 0)
                    bounds = None
                    if pd.get("bounds"):
                        bounds = pd["bounds"]
                    elif pd.get("region_code"):
                        st = get_state_info(pd["region_code"], include_national=True)
                        if st and st.bounds:
                            bounds = {
                                "min_lat": float(st.bounds.min_lat),
                                "max_lat": float(st.bounds.max_lat),
                                "min_lon": float(st.bounds.min_lon),
                                "max_lon": float(st.bounds.max_lon),
                            }
                    pd["bounds"] = bounds
                    available.append(pd)
            else:
                manifest_error = avail_res.error.message if avail_res.error else "Failed to retrieve manifest"
        except Exception as exc:
            manifest_error = str(exc)

        return {
            "ok": True,
            "installed": installed,
            "available": available,
            "manifest_error": manifest_error,
        }

    @app.post("/api/v1/packs/install")
    def install_packs_endpoint(
        req: InstallPacksRequest = Body(...),
    ) -> Dict[str, Any]:
        """Download and install regional data packs into the active tower registry."""
        import urllib.parse
        from meshscout.adapters.pack_client import DEFAULT_ALLOWED_HOSTS, PackClient
        from meshscout.core.packs import install_region_pack

        t_reg = _get_thread_local_tower_registry(app)
        allowed = list(DEFAULT_ALLOWED_HOSTS)
        if req.allowed_hosts:
            allowed.extend(req.allowed_hosts)
        if req.manifest_url:
            parsed = urllib.parse.urlparse(req.manifest_url)
            if parsed.hostname and parsed.hostname not in allowed:
                allowed.append(parsed.hostname)

        client_kwargs: Dict[str, Any] = {"allowed_hosts": allowed}
        if req.manifest_url:
            client_kwargs["manifest_url"] = req.manifest_url
        if req.cache_dir:
            client_kwargs["cache_dir"] = req.cache_dir

        client = PackClient(**client_kwargs)

        target_codes = list(req.region_codes)
        if not target_codes and req.region_code:
            target_codes.append(req.region_code)

        if not target_codes:
            raise HTTPException(
                status_code=400,
                detail="No region_codes provided for pack installation.",
            )

        installed_packs: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []
        total_rows = 0

        for code in target_codes:
            p_code = Path(code)
            if p_code.is_file() and (code.endswith(".sqlite.gz") or code.endswith(".gz")):
                res = install_region_pack(t_reg, p_code)
            else:
                res = client.install_pack(t_reg, code)

            if res.ok and res.value is not None:
                pack_info = res.value
                installed_packs.append(pack_info.model_dump(mode="json"))
                total_rows += pack_info.row_count
            else:
                err_msg = res.error.message if res.error else f"Failed to install pack for '{code}'"
                errors.append({"region_code": code, "error": err_msg})

        return {
            "ok": len(installed_packs) > 0,
            "installed": installed_packs,
            "row_count": total_rows,
            "total_rows": total_rows,
            "errors": errors,
        }

    @app.delete("/api/v1/packs/{pack_id}")
    def delete_pack_endpoint(pack_id: str) -> Dict[str, Any]:
        """Uninstall a regional data pack and remove orphaned tower records."""
        from meshscout.core.packs import uninstall_region_pack

        t_reg = _get_thread_local_tower_registry(app)
        removed = uninstall_region_pack(t_reg, pack_id)
        return {
            "ok": True,
            "pack_id": pack_id,
            "removed_rows": removed,
        }

    @app.get("/api/v1/attribution")
    def get_attribution_endpoint() -> Dict[str, Any]:
        """Return dataset licensing and attribution metadata from sources.json."""
        from meshscout.adapters.source_fetch import load_source_catalog

        sources = load_source_catalog()
        return {
            "ok": True,
            "sources": sources,
            "count": len(sources),
        }

    @app.get("/api/v1/regions/north-america")
    def get_north_america_regions_endpoint(
        country: Optional[str] = Query(default=None, description="Optional country filter ('US' or 'CA')"),
    ) -> Dict[str, Any]:
        """List regional states, provinces, and territories across North America."""
        from meshscout.adapters.regions import list_north_america_regions

        regions = list_north_america_regions(country=country)
        return {
            "ok": True,
            "count": len(regions),
            "regions": regions,
        }

    @app.get("/api/v1/regulatory/eirp")
    def get_regulatory_eirp_endpoint(
        tx_power_dbm: float = Query(default=20.0, description="Transmitter conducted power in dBm"),
        antenna_gain_dbi: float = Query(default=3.0, description="Antenna gain in dBi"),
        cable_loss_db: float = Query(default=0.0, description="Cable/connector loss in dB"),
        frequency_mhz: float = Query(default=915.0, description="Operating frequency in MHz"),
        domain: Optional[str] = Query(default=None, description="Regulatory domain (US_FCC_PART15 or CA_ISED_RSS247)"),
        region: Optional[str] = Query(default=None, description="Region code (e.g. VT, CA_QC) for domain detection"),
    ) -> Dict[str, Any]:
        """Evaluate conducted power and EIRP compliance under FCC Part 15.247 / ISED RSS-247 rules."""
        from meshscout.core.regulatory import (
            RegulatoryDomain,
            advise_eirp as core_advise_eirp,
            detect_regulatory_domain,
        )

        reg_domain = RegulatoryDomain.US_FCC_PART15
        if domain:
            try:
                reg_domain = RegulatoryDomain(domain)
            except ValueError:
                reg_domain = detect_regulatory_domain(domain)
        elif region:
            reg_domain = detect_regulatory_domain(region)

        report = core_advise_eirp(
            tx_power_dbm=tx_power_dbm,
            antenna_gain_dbi=antenna_gain_dbi,
            cable_loss_db=cable_loss_db,
            frequency_mhz=frequency_mhz,
            domain=reg_domain,
        )
        res = report.model_dump(mode="json")
        res["ok"] = True
        return res

    return app


class _LazyASGIApp:
    """Lazy ASGI application proxy to defer database initialization until runtime."""

    def __init__(self) -> None:
        self._app: Optional[FastAPI] = None
        self._lock = threading.Lock()

    def _get_app(self) -> FastAPI:
        if self._app is None:
            with self._lock:
                if self._app is None:
                    self._app = create_web_app()
        return self._app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        app = self._get_app()
        await app(scope, receive, send)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_app(), name)


app = _LazyASGIApp()
