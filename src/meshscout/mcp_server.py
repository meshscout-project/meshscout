"""MeshScout Model Context Protocol (MCP) Stdio Server.

Provides a zero-dependency JSON-RPC 2.0 MCP server (`MeshScoutMCPServer`) and an
optional FastMCP compatibility wrapper when the `mcp` package is installed.
Exposes fourteen tools:
  1. `scout_repeater_sites`
  2. `evaluate_link_budget`
  3. `inspect_site_feasibility`
  4. `advise_node_role_and_airtime`
  5. `recommend_backhaul_architecture`
  6. `provision_node_radio`
  7. `simulate_winter_solar_survival`
  8. `analyze_mesh_coverage_gaps`
  9. `calibrate_empirical_clutter`
  10. `generate_landowner_brief`
  11. `stage_offline_field_kit`
  12. `manage_living_mesh_state`
  13. `advise_eirp`
  14. `list_region_packs`

Exposes eight MCP resources:
  - `meshscout://sites/all`
  - `meshscout://presets/hardware`
  - `meshscout://presets/protocols`
  - `meshscout://state/living-mesh`
  - `meshscout://fixtures/vt_counties`
  - `meshscout://presets/site-architectures`
  - `meshscout://regulatory/north-america`
  - `meshscout://packs/installed`

Exposes three MCP prompts:
  - `design_regional_emergency_backbone`
  - `audit_channel_contention`
  - `prepare_selectboard_pitch`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from meshscout.adapters.elevation import ElevationGrid, USGS3DEPElevationAdapter
from meshscout.adapters.fcc_asr import FCCASRAdapter
from meshscout.adapters.geodata import VERMONT_REFERENCE_TOWNS_DATA
from meshscout.adapters.mqtt import (
    analyze_unobserved_areas,
    ingest_mqtt_packets,
    load_mqtt_fixture,
)
from meshscout.adapters.vt_vcgi import VCGIRegionalAdapter
from meshscout.core.archetypes import (
    COMMUNITY_SITE_ARCHETYPES,
    SiteArchetype,
    classify_site_archetype,
    get_archetype_recommendation,
)
from meshscout.core.contracts import (
    Coordinate,
    RadioConfig,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)
from meshscout.core.fresnel import analyze_fresnel_clearance, haversine_distance_km
from meshscout.core.itm import evaluate_point_to_point_link
from meshscout.core.optimizer import solve_minimum_set_cover
from meshscout.core.presets import HARDWARE_PRESETS, PROTOCOL_PROFILES
from meshscout.core.provisioning import (
    ProvisioningTarget,
    generate_site_provisioning,
)
from meshscout.core.registry import (
    DeploymentStatus,
    LivingMeshRegistry,
    RegisteredNode,
    WorkspacePreferences,
)
from meshscout.core.scorer import (
    EmitterSpec,
    rank_candidate_sites,
    score_site_viability,
)
from meshscout.core.solar import (
    BatteryChemistry,
    SolarSetup,
    simulate_winter_battery_survival,
)
from meshscout.core.telemetry import (
    calibrate_ground_truth_clutter,
    parse_wardrive_log,
)
from meshscout.core.traffic import (
    advise_node_role,
    compute_lora_airtime_ms,
    forecast_channel_utilization,
    recommend_summit_backhaul,
)
from meshscout.core.viewshed import (
    ViewshedResult,
    compute_viewshed,
    generate_target_grid,
)
from meshscout.reporting import generate_landowner_pitch_html

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"
VT_CHITTENDEN_FIXTURE = FIXTURES_DIR / "vt_chittenden_sample.json"
VT_VCGI_FIXTURE = FIXTURES_DIR / "vt_vcgi_sample.json"
FCC_ASR_FIXTURE = FIXTURES_DIR / "fcc_asr_vt_sample.dat"

VT_CHITTENDEN_BOUNDS = RegionalBounds(
    name="Vermont_Chittenden_County",
    min_lat=44.25,
    max_lat=44.60,
    min_lon=-73.35,
    max_lon=-72.75,
)

VERMONT_STATE_BOUNDS = RegionalBounds(
    name="Vermont_Statewide",
    min_lat=42.72,
    max_lat=45.02,
    min_lon=-73.44,
    max_lon=-71.46,
)


def _synthetic_vermont_elevation_fn(lat: float, lon: float) -> float:
    """Deterministic topographic model of the Champlain Valley and Green Mountains.

    Models Lake Champlain basin (~60-120m in the west near -73.25) rising toward the
    Green Mountain spine (~800-1300m in the east near -72.81).
    """
    # West-to-east rise toward Green Mountain ridge (-72.81)
    east_progress = max(0.0, min(1.0, (lon - (-73.30)) / 0.50))
    valley_base = 65.0 + 180.0 * (east_progress ** 1.6)
    ridge_bonus = 950.0 * max(0.0, 1.0 - abs(lon - (-72.8143)) / 0.12) ** 2
    return round(valley_base + ridge_bonus, 2)


def _build_offline_elevation_adapter(bounds: RegionalBounds) -> USGS3DEPElevationAdapter:
    """Create an offline USGS3DEPElevationAdapter backed by a deterministic ElevationGrid."""
    grid = ElevationGrid.from_fn(
        bounds=bounds,
        rows=25,
        cols=25,
        fn=_synthetic_vermont_elevation_fn,
    )
    return USGS3DEPElevationAdapter(
        bounds=bounds,
        offline_grid=grid,
        offline_mode=True,
    )


def load_regional_fixtures(
    region: str = "vt_chittenden",
) -> Tuple[RegionalBounds, List[SiteCandidate]]:
    """Load and deduplicate offline regional SiteCandidates from bundled fixtures."""
    region_key = region.strip().lower()
    clean = region_key.removeprefix("vt_").removesuffix("_county").removesuffix(" county").strip()
    if region_key not in ("vt_chittenden", "chittenden", "all", "vt_statewide", "vermont", "vt", "*"):
        from meshscout.adapters.vt_counties import (
            VERMONT_COUNTY_BOUNDS,
            load_regional_fixtures as load_county_fixtures,
        )
        if any(c.lower() == clean or c.lower() == region_key for c in VERMONT_COUNTY_BOUNDS):
            return load_county_fixtures(region)

    if region_key in ("vt_statewide", "vermont", "vt", "all", "*"):
        bounds = VERMONT_STATE_BOUNDS
    else:
        bounds = VT_CHITTENDEN_BOUNDS

    by_id: Dict[str, SiteCandidate] = {}

    # 1. Load primary Chittenden sample fixture
    if VT_CHITTENDEN_FIXTURE.exists():
        raw_chit = json.loads(VT_CHITTENDEN_FIXTURE.read_text(encoding="utf-8"))
        for item in raw_chit.get("sites", []):
            site = SiteCandidate.model_validate(item)
            if bounds.contains(site.location):
                by_id[site.site_id] = site

    # 2. Load VCGI municipal & state infrastructure fixture
    vcgi_adapter = VCGIRegionalAdapter(
        bounds=bounds,
        fixture_path=VT_VCGI_FIXTURE,
        offline_mode=True,
    )
    vcgi_res = vcgi_adapter.fetch_sites(bounds=bounds)
    if vcgi_res.ok and vcgi_res.value:
        for site in vcgi_res.value:
            by_id.setdefault(site.site_id, site)

    # 3. Load FCC ASR registered antenna structures fixture
    asr_adapter = FCCASRAdapter(
        bounds=bounds,
        fixture_path=FCC_ASR_FIXTURE,
        offline_mode=True,
    )
    asr_res = asr_adapter.fetch_sites(bounds=bounds)
    if asr_res.ok and asr_res.value:
        for site in asr_res.value:
            by_id.setdefault(site.site_id, site)

    # 4. Load 14 Vermont county highpoint candidates if statewide
    if bounds == VERMONT_STATE_BOUNDS:
        try:
            from meshscout.adapters.vt_counties import load_county_candidates
            county_res = load_county_candidates("all")
            if county_res.ok and county_res.value:
                for site in county_res.value:
                    by_id.setdefault(site.site_id, site)
        except Exception:
            pass

    return bounds, list(by_id.values())


# Import county candidate adapter after load_regional_fixtures definition to support dynamic patching
from meshscout.adapters.vt_counties import (  # noqa: E402
    VT_14_COUNTIES_FIXTURE,
    list_vermont_counties,
    load_county_candidates,
)


def _resolve_site_by_id(site_id: str) -> Optional[SiteCandidate]:
    """Resolve a SiteCandidate by ID across statewide regional fixtures and county candidates."""
    clean_id = site_id.strip().upper()
    _, all_sites = load_regional_fixtures(region="vt_statewide")
    for s in all_sites:
        if s.site_id.strip().upper() == clean_id:
            return s
    try:
        county_res = load_county_candidates("all")
        if county_res.ok and county_res.value:
            for s in county_res.value:
                if s.site_id.strip().upper() == clean_id:
                    return s
    except Exception:
        pass

    # Well-known fallback for Mount Mansfield
    if clean_id in ("VT-MANS-01", "VT-MANSFIELD-01", "MANSFIELD"):
        return SiteCandidate(
            site_id="VT-MANS-01",
            name="Mount Mansfield Summit Ridge",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=10.0,
        )
    return None


def scout_repeater_sites(
    region: str = "vt_chittenden",
    min_coverage: float = 0.90,
    max_repeaters: int = 5,
    no_delay: bool = True,
) -> Dict[str, Any]:
    """Scout, optimize, and rank optimal repeater sites for a region using offline fixtures."""
    bounds, candidates = load_regional_fixtures(region=region)
    if not candidates:
        return {
            "ok": False,
            "error": {
                "code": "NO_CANDIDATE_SITES",
                "message": f"No candidate sites found for region '{region}'.",
            },
        }

    grid_res = generate_target_grid(
        bounds=bounds,
        lat_steps=4,
        lon_steps=4,
        elevation_fn=lambda lat, lon: 95.0,
        rx_height_m=2.0,
    )
    if not grid_res.ok or not grid_res.value:
        return {
            "ok": False,
            "error": {
                "code": "GRID_GENERATION_FAILED",
                "message": grid_res.error.message if grid_res.error else "Target grid generation failed",
            },
        }
    targets = grid_res.value

    viewsheds: List[ViewshedResult] = []
    coverage_by_site: Dict[str, float] = {}
    radio = RadioConfig(frequency_mhz=915.0, tx_power_dbm=20.0)

    for site in candidates:
        vs_res = compute_viewshed(
            repeater=site,
            targets=targets,
            radio=radio,
            min_margin_db=6.0,
            require_los=False,
            num_samples=12,
        )
        if vs_res.ok and vs_res.value is not None:
            viewsheds.append(vs_res.value)
            coverage_by_site[site.site_id] = vs_res.value.weighted_coverage_fraction

    opt_res = solve_minimum_set_cover(
        viewsheds=viewsheds,
        target_coverage_fraction=min_coverage,
        max_repeaters=max_repeaters,
    )
    if not opt_res.ok or opt_res.value is None:
        return {
            "ok": False,
            "error": {
                "code": opt_res.error.code if opt_res.error else "OPTIMIZATION_FAILED",
                "message": opt_res.error.message if opt_res.error else "Set-cover optimization failed",
            },
        }

    rank_res = rank_candidate_sites(
        sites=candidates,
        coverage_by_site=coverage_by_site,
    )
    ranked_scores = rank_res.value if (rank_res.ok and rank_res.value) else []
    score_lookup = {s.site.site_id: s for s in ranked_scores}

    opt = opt_res.value
    selected_summary = []
    for step in opt.selection_steps:
        viability = score_lookup.get(step.site.site_id)
        selected_summary.append(
            {
                "step": step.step,
                "site_id": step.site.site_id,
                "name": step.site.name,
                "site_type": step.site.site_type.value,
                "elevation_m": step.site.location.elevation_m,
                "mast_height_m": step.site.mast_height_m,
                "deployment_cost": step.cost,
                "newly_covered_targets": len(step.newly_covered_target_ids),
                "cumulative_coverage_fraction": step.cumulative_coverage_fraction,
                "viability_score": viability.composite_score if viability else None,
                "desense_risk": viability.desense_risk.value if viability else None,
                "requires_cavity_filter": viability.requires_cavity_filter if viability else None,
            }
        )

    return {
        "ok": True,
        "region": bounds.name,
        "no_delay": no_delay,
        "total_candidates_evaluated": len(candidates),
        "total_target_points": opt.total_targets,
        "target_coverage_threshold": opt.target_coverage_threshold,
        "achieved_coverage_fraction": opt.achieved_coverage_fraction,
        "achieved_weighted_coverage_fraction": opt.achieved_weighted_coverage_fraction,
        "threshold_met": opt.threshold_met,
        "total_deployment_cost": opt.total_cost,
        "selected_repeaters": selected_summary,
        "top_ranked_sites": [
            {
                "site_id": s.site.site_id,
                "name": s.site.name,
                "site_type": s.site.site_type.value,
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


def evaluate_link_budget(
    source_lat: float,
    source_lon: float,
    source_elev_m: float,
    target_lat: float,
    target_lon: float,
    target_elev_m: float,
    frequency_mhz: float = 915.0,
    tx_power_dbm: float = 20.0,
    source_mast_m: float = 10.0,
    target_mast_m: float = 5.0,
) -> Dict[str, Any]:
    """Evaluate point-to-point Fresnel clearance and Longley-Rice ITM link budget offline."""
    source_site = SiteCandidate(
        site_id="SOURCE-NODE",
        name="Source Node",
        location=Coordinate(lat=source_lat, lon=source_lon, elevation_m=source_elev_m),
        site_type=SiteType.CUSTOM,
        mast_height_m=source_mast_m,
    )
    target_site = SiteCandidate(
        site_id="TARGET-NODE",
        name="Target Node",
        location=Coordinate(lat=target_lat, lon=target_lon, elevation_m=target_elev_m),
        site_type=SiteType.CUSTOM,
        mast_height_m=target_mast_m,
    )

    min_lat = min(source_lat, target_lat) - 0.05
    max_lat = max(source_lat, target_lat) + 0.05
    min_lon = min(source_lon, target_lon) - 0.05
    max_lon = max(source_lon, target_lon) + 0.05
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
        return {
            "ok": False,
            "error": {
                "code": prof_res.error.code if prof_res.error else "PROFILE_ERROR",
                "message": prof_res.error.message if prof_res.error else "Failed to generate elevation profile",
            },
        }
    profile = prof_res.value

    fresnel_res = analyze_fresnel_clearance(
        profile=profile,
        frequency_mhz=frequency_mhz,
    )
    radio = RadioConfig(frequency_mhz=frequency_mhz, tx_power_dbm=tx_power_dbm)
    itm_res = evaluate_point_to_point_link(
        profile=profile,
        radio=radio,
    )

    if not fresnel_res.ok or fresnel_res.value is None:
        return {
            "ok": False,
            "error": {
                "code": fresnel_res.error.code if fresnel_res.error else "FRESNEL_ERROR",
                "message": fresnel_res.error.message if fresnel_res.error else "Fresnel analysis failed",
            },
        }
    if not itm_res.ok or itm_res.value is None:
        return {
            "ok": False,
            "error": {
                "code": itm_res.error.code if itm_res.error else "ITM_ERROR",
                "message": itm_res.error.message if itm_res.error else "ITM link budget failed",
            },
        }

    fresnel = fresnel_res.value
    link = itm_res.value

    return {
        "ok": True,
        "link_budget": link.model_dump(),
        "fresnel_analysis": {
            "total_distance_m": fresnel.total_distance_m,
            "frequency_mhz": fresnel.frequency_mhz,
            "has_line_of_sight": fresnel.has_line_of_sight,
            "fresnel_60pct_clear": fresnel.fresnel_60pct_clear,
            "min_clearance_m": round(fresnel.min_clearance_m, 3),
            "min_clearance_ratio": round(fresnel.min_clearance_ratio, 4),
            "max_knife_edge_nu": round(fresnel.max_knife_edge_nu, 4),
        },
    }


def inspect_site_feasibility(
    site_id: str,
    nearby_850_900mhz_erp_watts: float = 0.0,
) -> Dict[str, Any]:
    """Inspect a candidate site's co-location RF desense risk, ownership score, and hardware guidance."""
    target_site = _resolve_site_by_id(site_id)
    if target_site is None:
        return {
            "ok": False,
            "error": {
                "code": "SITE_NOT_FOUND",
                "message": f"Site ID '{site_id}' was not found in bundled regional fixtures.",
            },
        }

    emitters: List[EmitterSpec] = []
    if nearby_850_900mhz_erp_watts > 0.0:
        emitters.append(
            EmitterSpec(
                emitter_id=f"CO-LOC-{target_site.site_id}",
                location=Coordinate(
                    lat=target_site.location.lat + 0.0002,
                    lon=target_site.location.lon + 0.0002,
                    elevation_m=target_site.location.elevation_m,
                ),
                frequency_mhz=880.0,
                erp_watts=nearby_850_900mhz_erp_watts,
                service_type="cellular",
            )
        )

    score_res = score_site_viability(
        site=target_site,
        nearby_emitters=emitters,
    )
    if not score_res.ok or score_res.value is None:
        return {
            "ok": False,
            "error": {
                "code": score_res.error.code if score_res.error else "VIABILITY_SCORE_ERROR",
                "message": score_res.error.message if score_res.error else "Failed scoring site feasibility",
            },
        }

    viability = score_res.value
    return {
        "ok": True,
        "site_id": target_site.site_id,
        "name": target_site.name,
        "site_type": target_site.site_type.value,
        "viability": viability.model_dump(),
    }


def advise_node_role_and_airtime(
    site_id: str,
    exposed_population: int = 5000,
    overlapping_router_count: int = 0,
    protocol_family: str = "Meshtastic",
) -> Dict[str, Any]:
    """Evaluate operational role recommendation, LoRa airtime, and channel utilization forecast."""
    target_site = _resolve_site_by_id(site_id)
    if target_site is None:
        return {
            "ok": False,
            "error": {
                "code": "SITE_NOT_FOUND",
                "message": f"Site ID '{site_id}' was not found in bundled regional fixtures.",
            },
        }

    rec = advise_node_role(
        site=target_site,
        exposed_population=exposed_population,
        overlapping_router_count=overlapping_router_count,
        protocol_family=protocol_family,
    )
    sf = 9 if rec.recommended_preset == "MediumFast" else 11
    airtime = compute_lora_airtime_ms(
        payload_bytes=32,
        sf=sf,
        bw_hz=250000.0,
    )
    forecast = forecast_channel_utilization(
        exposed_population=exposed_population,
        airtime_ms=airtime.total_airtime_ms,
        hop_limit=rec.recommended_hop_limit,
    )

    arch = classify_site_archetype(target_site, exposed_population=exposed_population)
    arch_guidance = get_archetype_recommendation(arch, protocol_family=protocol_family)

    resp: Dict[str, Any] = {
        "ok": True,
        "site_id": target_site.site_id,
        "site_name": target_site.name,
        "site_archetype": arch.value,
        "recommendation": rec.model_dump(mode="json"),
        "archetype_guidance": arch_guidance,
        "airtime": airtime.model_dump(mode="json"),
        "forecast": forecast.model_dump(mode="json"),
    }
    if arch == SiteArchetype.ALPINE_MEGA_SUMMIT:
        resp["anti_pattern_warning"] = (
            "CRITICAL: High mountain summit qualifies as Tier 1 Alpine Mega-Summit. "
            "Do NOT deploy as a naive single-radio co-channel repeater on the public channel. "
            "Deploy a Dual-Radio Split-Channel Bridge (with 3.0m vertical mast isolation) or native "
            "Layer 3 cryptographic routing (MeshCore / Reticulum) to prevent catastrophic co-channel ping-pong loops."
        )
    return resp


def recommend_backhaul_architecture(
    source_site_id: str,
    target_site_id: str,
    channel_utilization_pct: float = 10.0,
    protocol_family: str = "Meshtastic",
) -> Dict[str, Any]:
    """Recommend summit-to-summit backhaul architecture and RF decoupling parameters."""
    source_cand = _resolve_site_by_id(source_site_id)
    if source_cand is None:
        return {
            "ok": False,
            "error": {
                "code": "SITE_NOT_FOUND",
                "message": f"Source site ID '{source_site_id}' was not found in regional fixtures.",
            },
        }

    target_cand = _resolve_site_by_id(target_site_id)
    if target_cand is None:
        return {
            "ok": False,
            "error": {
                "code": "SITE_NOT_FOUND",
                "message": f"Target site ID '{target_site_id}' was not found in regional fixtures.",
            },
        }

    min_lat = min(source_cand.location.lat, target_cand.location.lat) - 0.05
    max_lat = max(source_cand.location.lat, target_cand.location.lat) + 0.05
    min_lon = min(source_cand.location.lon, target_cand.location.lon) - 0.05
    max_lon = max(source_cand.location.lon, target_cand.location.lon) + 0.05
    bounds = RegionalBounds(
        name="Backhaul_Link_Bounds",
        min_lat=max(-90.0, min_lat),
        max_lat=min(90.0, max_lat),
        min_lon=max(-180.0, min_lon),
        max_lon=min(180.0, max_lon),
    )
    elev_adapter = _build_offline_elevation_adapter(bounds=bounds)
    prof_res = elev_adapter.get_elevation_profile(
        source=source_cand,
        target=target_cand,
        num_samples=25,
    )
    if prof_res.ok and prof_res.value is not None:
        fresnel_res = analyze_fresnel_clearance(profile=prof_res.value, frequency_mhz=915.0)
        has_los = fresnel_res.value.has_line_of_sight if (fresnel_res.ok and fresnel_res.value is not None) else True
        dist_km = prof_res.value.distance_km
    else:
        dist_km = haversine_distance_km(source_cand.location, target_cand.location)
        has_los = True

    rec = recommend_summit_backhaul(
        site_a=source_cand,
        site_b=target_cand,
        distance_km=dist_km,
        line_of_sight=has_los,
        channel_utilization_pct=channel_utilization_pct,
    )

    source_arch = classify_site_archetype(source_cand)
    target_arch = classify_site_archetype(target_cand)
    is_mega_summit = (
        source_arch == SiteArchetype.ALPINE_MEGA_SUMMIT
        or target_arch == SiteArchetype.ALPINE_MEGA_SUMMIT
    )
    guidance_arch = SiteArchetype.ALPINE_MEGA_SUMMIT if is_mega_summit else source_arch
    arch_guidance = get_archetype_recommendation(guidance_arch, protocol_family=protocol_family)

    rec_dump = rec.model_dump(mode="json")
    if is_mega_summit:
        rec_dump["community_validated_architecture"] = "dual_radio_split_channel_bridge"
        rec_dump["anti_pattern_warning"] = (
            "CRITICAL: Elevated line-of-sight summit. Do NOT operate a single-radio co-channel repeater. "
            "Hardware dual-radio bridge or native Layer 3 split-horizon routing is required."
        )
        rec_dump["split_horizon_required"] = True
    else:
        rec_dump["community_validated_architecture"] = "single_radio_infill_repeater"
        rec_dump["anti_pattern_warning"] = None
        rec_dump["split_horizon_required"] = False

    return {
        "ok": True,
        "source_site_id": source_cand.site_id,
        "source_archetype": source_arch.value,
        "target_site_id": target_cand.site_id,
        "target_archetype": target_arch.value,
        "distance_km": round(dist_km, 2),
        "has_line_of_sight": has_los,
        "recommendation": rec_dump,
        "archetype_guidance": arch_guidance,
    }


def provision_node_radio(
    site_id: str,
    target: str = "meshtastic",
    channel_name: str = "MeshScout",
    psk_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate multi-protocol provisioning configuration and pure-Python SVG QR code."""
    target_clean = target.strip().lower()
    try:
        prov_target = ProvisioningTarget(target_clean)
    except ValueError:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_TARGET",
                "message": f"Unsupported provisioning target '{target}'. Must be one of: meshtastic, meshcore, reticulum.",
            },
        }

    site = _resolve_site_by_id(site_id)
    if site is None:
        return {
            "ok": False,
            "error": {
                "code": "SITE_NOT_FOUND",
                "message": f"Site ID '{site_id}' was not found in regional fixtures.",
            },
        }

    try:
        bundle = generate_site_provisioning(
            site=site,
            target=prov_target,
            channel_name=channel_name,
            psk_override=psk_override,
        )
        return {
            "ok": True,
            "site_id": site.site_id,
            "site_name": site.name,
            "target": bundle.target.value,
            "channel_name": bundle.channel_name,
            "frequency_mhz": bundle.frequency_mhz,
            "bandwidth_khz": bundle.bandwidth_khz,
            "spreading_factor": bundle.spreading_factor,
            "raw_url_or_text": bundle.raw_url_or_text,
            "cli_commands": bundle.cli_commands,
            "inline_svg_qr": bundle.inline_svg_qr,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": {
                "code": "PROVISIONING_ERROR",
                "message": f"Failed generating radio provisioning for site '{site_id}': {exc}",
            },
        }


def simulate_winter_solar_survival(
    site_id: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    panel_watts: float = 10.0,
    battery_chemistry: str = "lto",
    battery_capacity_wh: float = 24.0,
    radio_power_mw: float = 45.0,
    consecutive_cloudy_days: int = 5,
) -> Dict[str, Any]:
    """Simulate mountaintop winter solstice solar irradiance and sub-zero battery survival."""
    coord: Optional[Coordinate] = None
    resolved_site_name: Optional[str] = None

    if site_id:
        site = _resolve_site_by_id(site_id)
        if site is None:
            return {
                "ok": False,
                "error": {
                    "code": "SITE_NOT_FOUND",
                    "message": f"Site ID '{site_id}' was not found in regional fixtures.",
                },
            }
        coord = site.location
        resolved_site_name = site.name
    elif lat is not None and lon is not None:
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return {
                "ok": False,
                "error": {
                    "code": "INVALID_COORDINATES",
                    "message": f"Invalid latitude ({lat}) or longitude ({lon}).",
                },
            }
        coord = Coordinate(lat=lat, lon=lon, elevation_m=0.0)
    else:
        return {
            "ok": False,
            "error": {
                "code": "MISSING_COORDINATES",
                "message": "Either site_id or both lat and lon must be provided.",
            },
        }

    chem_str = battery_chemistry.strip().lower()
    chem_aliases = {
        "lto": BatteryChemistry.LTO,
        "lifepo4": BatteryChemistry.LIFEPO4,
        "sodium_ion": BatteryChemistry.SODIUM_ION,
        "sodium-ion": BatteryChemistry.SODIUM_ION,
        "agm": BatteryChemistry.LEAD_ACID_AGM,
        "lead_acid": BatteryChemistry.LEAD_ACID_AGM,
        "lead-acid": BatteryChemistry.LEAD_ACID_AGM,
    }
    if chem_str not in chem_aliases:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_BATTERY_CHEMISTRY",
                "message": f"Unsupported battery chemistry '{battery_chemistry}'. Allowed: lto, lifepo4, sodium_ion, agm.",
            },
        }
    chem = chem_aliases[chem_str]

    if panel_watts <= 0.0:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_PANEL_WATTS",
                "message": f"panel_watts must be strictly positive, got {panel_watts}",
            },
        }
    if battery_capacity_wh <= 0.0:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_BATTERY_CAPACITY",
                "message": f"battery_capacity_wh must be strictly positive, got {battery_capacity_wh}",
            },
        }
    if radio_power_mw <= 0.0:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_RADIO_POWER",
                "message": f"radio_power_mw must be strictly positive, got {radio_power_mw}",
            },
        }
    if consecutive_cloudy_days < 0 or consecutive_cloudy_days > 30:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_CLOUDY_DAYS",
                "message": f"consecutive_cloudy_days must be between 0 and 30, got {consecutive_cloudy_days}",
            },
        }

    setup = SolarSetup(
        panel_watts=panel_watts,
        battery_chemistry=chem,
        battery_capacity_wh=battery_capacity_wh,
        radio_power_mw=radio_power_mw,
    )

    sim_res = simulate_winter_battery_survival(
        coord=coord,
        setup=setup,
        consecutive_cloudy_days=consecutive_cloudy_days,
    )
    if not sim_res.ok or sim_res.value is None:
        return {
            "ok": False,
            "error": {
                "code": sim_res.error.code if sim_res.error else "SIMULATION_FAILED",
                "message": sim_res.error.message if sim_res.error else "Simulation failed",
            },
        }

    report = sim_res.value
    res_dict: Dict[str, Any] = {
        "ok": True,
        "site_id": site_id,
        "site_name": resolved_site_name,
        **report.model_dump(mode="json"),
    }
    return res_dict


def analyze_mesh_coverage_gaps(
    coverage_radius_km: float = 8.0,
    use_fixture: bool = True,
    custom_json_or_ndjson: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze mesh coverage gaps comparing heard MQTT nodes against municipal reference towns."""
    if coverage_radius_km <= 0.0:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_COVERAGE_RADIUS",
                "message": f"coverage_radius_km must be strictly positive, got {coverage_radius_km}",
            },
        }

    heard_nodes = []
    if custom_json_or_ndjson and custom_json_or_ndjson.strip():
        ingest_res = ingest_mqtt_packets(custom_json_or_ndjson, apply_privacy_fuzz=True)
        if not ingest_res.ok or ingest_res.value is None:
            return {
                "ok": False,
                "error": {
                    "code": ingest_res.error.code if ingest_res.error else "INGESTION_FAILED",
                    "message": ingest_res.error.message if ingest_res.error else "Failed to parse custom MQTT packets",
                },
            }
        heard_nodes = ingest_res.value
    elif use_fixture:
        fix_path = FIXTURES_DIR / "vt_mqtt_live_sample.json"
        if not fix_path.exists():
            return {
                "ok": False,
                "error": {
                    "code": "FIXTURE_NOT_FOUND",
                    "message": f"MQTT fixture not found at {fix_path}",
                },
            }
        load_res = load_mqtt_fixture(fix_path, apply_privacy_fuzz=True)
        if not load_res.ok or load_res.value is None:
            return {
                "ok": False,
                "error": {
                    "code": load_res.error.code if load_res.error else "LOAD_FAILED",
                    "message": load_res.error.message if load_res.error else "Failed to load MQTT fixture",
                },
            }
        heard_nodes = load_res.value

    # Gather candidate repeater high sites
    _, candidates = load_regional_fixtures("vt_statewide")
    try:
        c_res = load_county_candidates("all")
        if c_res.ok and c_res.value:
            cand_map = {c.site_id: c for c in candidates}
            for c in c_res.value:
                cand_map.setdefault(c.site_id, c)
            candidates = list(cand_map.values())
    except Exception:
        pass

    gap_res = analyze_unobserved_areas(
        heard_nodes=heard_nodes,
        registry_active_nodes=[],
        candidate_sites=candidates,
        reference_towns=VERMONT_REFERENCE_TOWNS_DATA,
        coverage_radius_km=coverage_radius_km,
    )
    if not gap_res.ok or gap_res.value is None:
        return {
            "ok": False,
            "error": {
                "code": gap_res.error.code if gap_res.error else "ANALYSIS_FAILED",
                "message": gap_res.error.message if gap_res.error else "Gap analysis failed",
            },
        }

    report = gap_res.value
    return {
        "ok": True,
        "coverage_radius_km": coverage_radius_km,
        "heard_nodes_count": len(heard_nodes),
        **report.model_dump(mode="json"),
    }


def calibrate_empirical_clutter(
    transmitter_site_id: str,
    raw_log: Optional[str] = None,
    format_hint: str = "auto",
    use_fixture: bool = True,
) -> Dict[str, Any]:
    """Ingest wardrive telemetry and calibrate ITM propagation and clutter loss in dB/km."""
    site = _resolve_site_by_id(transmitter_site_id)
    if site is None:
        return {
            "ok": False,
            "error": {
                "code": "SITE_NOT_FOUND",
                "message": f"Transmitter site ID '{transmitter_site_id}' was not found in regional fixtures.",
            },
        }

    packets = []
    if raw_log and raw_log.strip():
        parse_res = parse_wardrive_log(raw_log, format_hint=format_hint)
        if not parse_res.ok or not parse_res.value:
            return {
                "ok": False,
                "error": {
                    "code": parse_res.error.code if parse_res.error else "PARSE_ERROR",
                    "message": parse_res.error.message if parse_res.error else "Failed to parse wardriving telemetry log",
                },
            }
        packets = parse_res.value
    elif use_fixture:
        fixture_path = FIXTURES_DIR / "wardriving_sample.json"
        if not fixture_path.exists():
            return {
                "ok": False,
                "error": {
                    "code": "FIXTURE_NOT_FOUND",
                    "message": f"Wardriving fixture sample not found at {fixture_path}",
                },
            }
        try:
            raw_text = fixture_path.read_text(encoding="utf-8")
        except Exception as exc:
            return {
                "ok": False,
                "error": {
                    "code": "IO_ERROR",
                    "message": f"Failed reading wardriving fixture: {exc}",
                },
            }
        parse_res = parse_wardrive_log(raw_text, format_hint="json")
        if not parse_res.ok or not parse_res.value:
            return {
                "ok": False,
                "error": {
                    "code": parse_res.error.code if parse_res.error else "PARSE_ERROR",
                    "message": parse_res.error.message if parse_res.error else "Failed parsing wardriving fixture",
                },
            }
        packets = parse_res.value
    else:
        return {
            "ok": False,
            "error": {
                "code": "NO_TELEMETRY_LOG",
                "message": "Either raw_log must be provided or use_fixture must be True.",
            },
        }

    calib_res = calibrate_ground_truth_clutter(
        packets=packets,
        transmitter_site=site,
        elevation_fn=_synthetic_vermont_elevation_fn,
    )
    if not calib_res.ok or calib_res.value is None:
        return {
            "ok": False,
            "error": {
                "code": calib_res.error.code if calib_res.error else "CALIBRATION_FAILED",
                "message": calib_res.error.message if calib_res.error else "Clutter calibration failed",
            },
        }

    result = calib_res.value
    return {
        "ok": True,
        "transmitter_site_id": site.site_id,
        "transmitter_site_name": site.name,
        **result.model_dump(mode="json"),
    }


def generate_landowner_brief(
    site_id: str,
    contact_org: str = "Vermont Community Emergency Mesh Initiative",
) -> Dict[str, Any]:
    """Generate a printable 1-page civic landowner host brief and reassurance pitch HTML."""
    site = _resolve_site_by_id(site_id)
    if site is None:
        return {
            "ok": False,
            "error": {
                "code": "SITE_NOT_FOUND",
                "message": f"Site ID '{site_id}' was not found in regional fixtures.",
            },
        }

    score_res = score_site_viability(site)
    viability = score_res.value if (score_res.ok and score_res.value) else None

    html_brief = generate_landowner_pitch_html(
        site=site,
        viability=viability,
        contact_org=contact_org,
    )

    return {
        "ok": True,
        "site_id": site.site_id,
        "site_name": site.name,
        "site_type": site.site_type.value,
        "contact_org": contact_org,
        "composite_score": viability.composite_score if viability else None,
        "desense_risk": viability.desense_risk.value if viability else None,
        "requires_cavity_filter": viability.requires_cavity_filter if viability else None,
        "html_brief": html_brief,
    }


def stage_offline_field_kit(
    state: str = "VT",
    output_dir: Optional[str] = None,
    buffer_km: float = 20.0,
    min_zoom: int = 7,
    max_zoom: int = 12,
    include_dem: bool = True,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Stage a turnkey offline cartography field kit or calculate dry-run storage estimates."""
    from meshscout.core.staging import stage_offline_region
    from pathlib import Path

    out_dir = Path(output_dir) if output_dir else Path.home() / ".meshscout" / "field-kit"
    res = stage_offline_region(
        state_code=state,
        output_dir=out_dir,
        buffer_km=buffer_km,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        include_dem=include_dem,
        dry_run=dry_run,
    )
    if not res.ok:
        return {"ok": False, "error": res.error or "Failed to stage field kit"}
    return {
        "ok": True,
        "dry_run": dry_run,
        "summary": res.value,
        "output_dir": str(out_dir),
    }


def manage_living_mesh_state(
    action: str,
    site_id: Optional[str] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None,
    home_lat: Optional[float] = None,
    home_lon: Optional[float] = None,
    home_name: Optional[str] = None,
    pack_json: Optional[str] = None,
    pack: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Inspect and manage persistent living mesh network state, registered club nodes,
    deployment lifecycle statuses (candidate, testing, active_on_air, blocked, dismantled), and
    operator workspace preferences in the local LivingMeshRegistry SQLite database.
    """
    registry = LivingMeshRegistry(db_path=db_path)
    action_norm = action.strip().lower() if action else ""

    if action_norm == "list":
        dep_status = None
        if status:
            try:
                dep_status = DeploymentStatus(status.strip().lower())
            except ValueError:
                return {
                    "ok": False,
                    "error": {
                        "code": "INVALID_STATUS",
                        "message": (
                            f"Invalid deployment status: '{status}'. "
                            "Valid statuses: candidate, testing, active_on_air, blocked, dismantled"
                        ),
                    },
                }
        nodes = registry.list_nodes(status=dep_status)
        return {
            "ok": True,
            "action": "list",
            "filter_status": dep_status.value if dep_status else None,
            "total_nodes": len(nodes),
            "nodes": [n.model_dump(mode="json") for n in nodes],
        }

    elif action_norm == "update_status":
        if not site_id:
            return {
                "ok": False,
                "error": {
                    "code": "MISSING_SITE_ID",
                    "message": "site_id is required for update_status action.",
                },
            }
        if not status:
            return {
                "ok": False,
                "error": {
                    "code": "MISSING_STATUS",
                    "message": "status is required for update_status action.",
                },
            }
        try:
            dep_status = DeploymentStatus(status.strip().lower())
        except ValueError:
            return {
                "ok": False,
                "error": {
                    "code": "INVALID_STATUS",
                    "message": (
                        f"Invalid deployment status: '{status}'. "
                        "Valid statuses: candidate, testing, active_on_air, blocked, dismantled"
                    ),
                },
            }

        res = registry.update_node_status(site_id=site_id, status=dep_status, notes=notes)
        if not res.ok and res.error and res.error.code == "NODE_NOT_FOUND":
            cand = _resolve_site_by_id(site_id)
            if cand is not None:
                registry.seed_candidates([cand])
                res = registry.update_node_status(site_id=site_id, status=dep_status, notes=notes)

        if not res.ok or res.value is None:
            return {
                "ok": False,
                "error": {
                    "code": res.error.code if res.error else "UPDATE_FAILED",
                    "message": res.error.message if res.error else f"Failed to update status for site '{site_id}'",
                },
            }

        return {
            "ok": True,
            "action": "update_status",
            "node": res.value.model_dump(mode="json"),
        }

    elif action_norm == "set_home":
        prefs = registry.get_preferences()
        if home_lat is not None:
            prefs.home_lat = float(home_lat)
            prefs.last_lat = float(home_lat)
        if home_lon is not None:
            prefs.home_lon = float(home_lon)
            prefs.last_lon = float(home_lon)
        if home_name is not None:
            prefs.home_name = str(home_name)
        saved = registry.save_preferences(prefs)
        return {
            "ok": True,
            "action": "set_home",
            "preferences": saved.model_dump(mode="json"),
        }

    elif action_norm == "get_preferences":
        prefs = registry.get_preferences()
        return {
            "ok": True,
            "action": "get_preferences",
            "preferences": prefs.model_dump(mode="json"),
        }

    elif action_norm == "reconcile_dismantled":
        from meshscout.adapters.fcc_asr import extract_dismantled_site_ids

        dismantled_ids = extract_dismantled_site_ids()
        count = registry.reconcile_dismantled_sites(dismantled_ids)
        return {
            "ok": True,
            "reconciled_count": count,
            "dismantled_ids": dismantled_ids,
        }

    elif action_norm == "export_pack":
        snapshot = registry.export_snapshot(fuzz_private_nodes=True)
        return {
            "ok": True,
            "pack": snapshot,
        }

    elif action_norm == "import_pack":
        target_pack = pack
        if target_pack is None and pack_json:
            try:
                target_pack = json.loads(pack_json)
            except Exception as e:
                return {
                    "ok": False,
                    "error": {
                        "code": "INVALID_PACK_JSON",
                        "message": f"Failed to parse pack_json: {e}",
                    },
                }
        if target_pack is None:
            return {
                "ok": False,
                "error": {
                    "code": "MISSING_PACK",
                    "message": "pack or pack_json is required for import_pack action.",
                },
            }
        res = registry.import_snapshot(target_pack)
        if not res.ok:
            return {
                "ok": False,
                "error": {
                    "code": res.error.code if res.error else "IMPORT_FAILED",
                    "message": res.error.message if res.error else "Failed to import mesh pack snapshot",
                },
            }
        return {
            "ok": True,
            "imported_count": res.value,
        }

    else:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_ACTION",
                "message": (
                    f"Unknown action: '{action}'. "
                    "Valid actions: list, update_status, set_home, get_preferences, reconcile_dismantled, export_pack, import_pack"
                ),
            },
        }


def advise_eirp(
    tx_power_dbm: float,
    antenna_gain_dbi: float,
    cable_loss_db: float = 0.0,
    frequency_mhz: float = 915.0,
    domain: Optional[str] = None,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate transmitter conducted power and EIRP limits against FCC Part 15.247 / ISED RSS-247 rules."""
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
        tx_power_dbm=float(tx_power_dbm),
        antenna_gain_dbi=float(antenna_gain_dbi),
        cable_loss_db=float(cable_loss_db),
        frequency_mhz=float(frequency_mhz),
        domain=reg_domain,
    )
    res = report.model_dump(mode="json")
    res["ok"] = True
    return res


def list_region_packs(
    db_path: Optional[str] = None,
    include_available: bool = False,
) -> Dict[str, Any]:
    """List installed and available regional tower data packs with provenance and licensing metadata."""
    from meshscout.core.packs import list_installed_packs as core_list_installed_packs
    from meshscout.core.tower_registry import UnifiedTowerRegistry
    from meshscout.adapters.pack_client import PackClient

    with UnifiedTowerRegistry(db_path=db_path) as reg:
        installed = core_list_installed_packs(reg)

    available = []
    manifest_error = None
    if include_available:
        try:
            client = PackClient()
            avail_res = client.list_available_packs()
            if avail_res.ok and avail_res.value is not None:
                available = [p.model_dump(mode="json") for p in avail_res.value]
            else:
                manifest_error = avail_res.error.message if avail_res.error else "Failed to retrieve manifest"
        except Exception as exc:
            manifest_error = str(exc)

    return {
        "ok": True,
        "installed": installed,
        "installed_count": len(installed),
        "available": available,
        "manifest_error": manifest_error,
        "attributions": {
            "fcc_asr": "FCC Antenna Structure Registration (Public Domain)",
            "ised_sms": "ISED TAFL (Open Government Licence - Canada 2.0)",
            "civic_osm": "© OpenStreetMap contributors (ODbL 1.0)",
        },
    }


MCP_TOOLS_MANIFEST: List[Dict[str, Any]] = [
    {
        "name": "scout_repeater_sites",
        "description": (
            "Scout, compute viewsheds, solve greedy minimum set-cover repeater placement, "
            "and rank candidate sites for a target region."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "default": "vt_chittenden"},
                "min_coverage": {"type": "number", "default": 0.90},
                "max_repeaters": {"type": "integer", "default": 5},
                "no_delay": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "evaluate_link_budget",
        "description": (
            "Evaluate point-to-point 4/3 Earth Fresnel zone clearance and Longley-Rice ITM "
            "link budget between two coordinates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_lat": {"type": "number"},
                "source_lon": {"type": "number"},
                "source_elev_m": {"type": "number"},
                "target_lat": {"type": "number"},
                "target_lon": {"type": "number"},
                "target_elev_m": {"type": "number"},
                "frequency_mhz": {"type": "number", "default": 915.0},
                "tx_power_dbm": {"type": "number", "default": 20.0},
                "source_mast_m": {"type": "number", "default": 10.0},
                "target_mast_m": {"type": "number", "default": 5.0},
            },
            "required": [
                "source_lat",
                "source_lon",
                "source_elev_m",
                "target_lat",
                "target_lon",
                "target_elev_m",
            ],
        },
    },
    {
        "name": "inspect_site_feasibility",
        "description": (
            "Inspect a candidate site's co-location 900 MHz desense risk, civic ownership "
            "score, and cavity filter recommendations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string"},
                "nearby_850_900mhz_erp_watts": {"type": "number", "default": 0.0},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "advise_node_role_and_airtime",
        "description": (
            "Evaluate operational role recommendations (Client vs Router vs Router_Late) "
            "and compute LoRa packet airtime and channel utilization forecasts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string"},
                "exposed_population": {"type": "integer", "default": 5000},
                "overlapping_router_count": {"type": "integer", "default": 0},
                "protocol_family": {"type": "string", "default": "Meshtastic"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "recommend_backhaul_architecture",
        "description": (
            "Recommend summit-to-summit backhaul architecture (direct LoRa, dual-radio Pi bridge, "
            "or 5.8 GHz microwave IP) with vertical antenna decoupling isolation and cross-protocol split-horizon guidance."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_site_id": {"type": "string"},
                "target_site_id": {"type": "string"},
                "channel_utilization_pct": {"type": "number", "default": 10.0},
                "protocol_family": {
                    "type": "string",
                    "default": "Meshtastic",
                    "enum": ["Meshtastic", "MeshCore", "Reticulum", "GenericLoRa"],
                    "description": "Target protocol family for cross-protocol architectural recommendation",
                },
            },
            "required": ["source_site_id", "target_site_id"],
        },
    },
    {
        "name": "provision_node_radio",
        "description": (
            "Multi-protocol node provisioning generator for Meshtastic, MeshCore, "
            "and Reticulum. Produces protobuf channel URLs, pure-Python inline SVG QR codes, "
            "CLI configure scripts, and rns.conf stanzas."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "Candidate site or registered node identifier"},
                "target": {
                    "type": "string",
                    "enum": ["meshtastic", "meshcore", "reticulum"],
                    "default": "meshtastic",
                    "description": "Target protocol ecosystem",
                },
                "channel_name": {"type": "string", "default": "MeshScout", "description": "Channel or network interface name"},
                "psk_override": {"type": "string", "description": "Optional custom Pre-Shared Key (base64 or hex)"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "simulate_winter_solar_survival",
        "description": (
            "Simulate mountaintop winter solstice solar irradiance and sub-zero battery survival "
            "(LTO ultra-rugged cold charging, LiFePO4 cold lockout, Sodium-Ion, AGM) under severe storm streaks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "Candidate site ID to look up coordinates from"},
                "lat": {"type": "number", "description": "Target latitude in decimal degrees if site_id omitted"},
                "lon": {"type": "number", "description": "Target longitude in decimal degrees if site_id omitted"},
                "panel_watts": {"type": "number", "default": 10.0, "description": "Rated solar panel peak wattage"},
                "battery_chemistry": {
                    "type": "string",
                    "enum": ["lto", "lifepo4", "sodium_ion", "agm"],
                    "default": "lto",
                    "description": "Battery cell chemistry with thermal charging cutoff limits",
                },
                "battery_capacity_wh": {"type": "number", "default": 24.0, "description": "Nominal battery capacity in Watt-hours"},
                "radio_power_mw": {"type": "number", "default": 45.0, "description": "Average continuous radio power consumption in milliwatts"},
                "consecutive_cloudy_days": {"type": "integer", "default": 5, "description": "Severe sub-zero storm streak duration in days"},
            },
        },
    },
    {
        "name": "analyze_mesh_coverage_gaps",
        "description": (
            "Analyze regional mesh coverage gaps comparing heard MQTT telemetry and active nodes "
            "against municipal reference centers, ranking candidate repeater high-sites to bridge gaps."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "coverage_radius_km": {
                    "type": "number",
                    "default": 8.0,
                    "description": "Coverage threshold radius around heard/active nodes in kilometers",
                },
                "use_fixture": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to load bundled Vermont MQTT telemetry fixture if no custom data provided",
                },
                "custom_json_or_ndjson": {
                    "type": "string",
                    "description": "Optional raw JSON array or NDJSON string of Meshtastic MQTT packets",
                },
            },
        },
    },
    {
        "name": "calibrate_empirical_clutter",
        "description": (
            "Ingest wardriving field telemetry (CSV or JSON) and calibrate Longley-Rice ITM propagation "
            "against ground-truth RSSI to calculate canopy attenuation and clutter loss in dB/km."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "transmitter_site_id": {
                    "type": "string",
                    "description": "Site ID of the transmitting node to match wardrive packets against",
                },
                "raw_log": {
                    "type": "string",
                    "description": "Optional raw CSV or JSON text of wardriving drive-test log",
                },
                "format_hint": {
                    "type": "string",
                    "enum": ["auto", "json", "csv"],
                    "default": "auto",
                    "description": "Telemetry log format hint",
                },
                "use_fixture": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to fall back to bundled wardriving fixture sample if raw_log is not provided",
                },
            },
            "required": ["transmitter_site_id"],
        },
    },
    {
        "name": "generate_landowner_brief",
        "description": (
            "Generate a printable 1-page civic landowner host brief and reassurance pitch HTML "
            "for property owners, municipal water districts, silos, and town selectboards."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "Candidate site ID for which to generate the landowner pitch sheet",
                },
                "contact_org": {
                    "type": "string",
                    "default": "Vermont Community Emergency Mesh Initiative",
                    "description": "Name of requesting civic or community organization",
                },
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "stage_offline_field_kit",
        "description": (
            "Stage a turnkey offline cartography field kit or calculate dry-run storage and tile count "
            "estimates for a given state or province with an expanded cross-border buffer apron."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "default": "VT",
                    "description": "Target state or province code (e.g. VT, NH, NY, ME, CA_QC)",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Optional destination directory path for the offline field kit",
                },
                "buffer_km": {
                    "type": "number",
                    "default": 20.0,
                    "description": "Cross-border buffer apron in kilometers (default 20 km)",
                },
                "min_zoom": {
                    "type": "integer",
                    "default": 7,
                    "description": "Minimum zoom level (7-12)",
                },
                "max_zoom": {
                    "type": "integer",
                    "default": 12,
                    "description": "Maximum zoom level (7-14)",
                },
                "include_dem": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to bundle 1-arc-second SRTM/3DEP elevation tiles for Fresnel calculations",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": True,
                    "description": "If true, simulates staging and returns tile count and storage estimates without writing files",
                },
            },
        },
    },
    {
        "name": "manage_living_mesh_state",
        "description": (
            "Inspect and manage persistent living mesh network state, registered club nodes, "
            "deployment lifecycle statuses (candidate, testing, active_on_air, blocked, dismantled), "
            "and operator home node workspace preferences in the local SQLite registry."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "update_status",
                        "set_home",
                        "get_preferences",
                        "reconcile_dismantled",
                        "export_pack",
                        "import_pack",
                    ],
                    "description": "Management action to execute",
                },
                "site_id": {
                    "type": "string",
                    "description": "Registered node or candidate site identifier",
                },
                "status": {
                    "type": "string",
                    "enum": ["candidate", "testing", "active_on_air", "blocked", "dismantled"],
                    "description": "Lifecycle deployment status for update_status or filtering",
                },
                "notes": {
                    "type": "string",
                    "description": "Operational notes or installation details for the node",
                },
                "home_lat": {
                    "type": "number",
                    "description": "Operator home node latitude in decimal degrees",
                },
                "home_lon": {
                    "type": "number",
                    "description": "Operator home node longitude in decimal degrees",
                },
                "home_name": {
                    "type": "string",
                    "description": "Operator home node friendly name",
                },
                "pack_json": {
                    "type": "string",
                    "description": "JSON string of exported snapshot mesh pack for import_pack",
                },
                "pack": {
                    "type": "object",
                    "description": "Mesh pack dictionary for import_pack",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "advise_eirp",
        "description": (
            "Evaluate transmitter conducted power and EIRP limits against FCC Part 15.247 "
            "(US) and ISED RSS-247 (Canada) regulations for 902-928 MHz ISM band operation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tx_power_dbm": {
                    "type": "number",
                    "description": "Transmitter conducted output power in dBm",
                },
                "antenna_gain_dbi": {
                    "type": "number",
                    "description": "Antenna gain in dBi",
                },
                "cable_loss_db": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Coaxial cable and connector insertion loss in dB",
                },
                "frequency_mhz": {
                    "type": "number",
                    "default": 915.0,
                    "description": "Operating frequency in MHz (default 915.0)",
                },
                "domain": {
                    "type": "string",
                    "description": "Regulatory domain ('US_FCC_PART15' or 'CA_ISED_RSS247')",
                },
                "region": {
                    "type": "string",
                    "description": "Optional regional identifier (e.g. 'VT', 'CA_QC') for automatic domain detection",
                },
            },
            "required": ["tx_power_dbm", "antenna_gain_dbi"],
        },
    },
    {
        "name": "list_region_packs",
        "description": (
            "List installed and available regional tower data packs with provenance and licensing metadata."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_available": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to query the remote manifest for available uninstalled packs",
                },
                "db_path": {
                    "type": "string",
                    "description": "Optional path to tower registry database",
                },
            },
        },
    },
]

MCP_RESOURCES_MANIFEST: List[Dict[str, Any]] = [
    {
        "uri": "meshscout://sites/all",
        "name": "All Candidate Sites",
        "description": "Statewide candidate repeater and high-site locations in Vermont",
        "mimeType": "application/json",
    },
    {
        "uri": "meshscout://presets/hardware",
        "name": "Hardware Presets",
        "description": "Standard LoRa radio hardware specifications and power consumption profiles",
        "mimeType": "application/json",
    },
    {
        "uri": "meshscout://presets/protocols",
        "name": "Protocol Profiles",
        "description": "Meshtastic, MeshCore, and Reticulum protocol RF configurations",
        "mimeType": "application/json",
    },
    {
        "uri": "meshscout://state/living-mesh",
        "name": "Living Mesh State",
        "description": "Current registered club nodes, active deployment status, and workspace preferences",
        "mimeType": "application/json",
    },
    {
        "uri": "meshscout://fixtures/vt_counties",
        "name": "Vermont Counties Fixture",
        "description": "Vermont 14 counties reference fixture and candidate sites",
        "mimeType": "application/json",
    },
    {
        "uri": "meshscout://presets/site-architectures",
        "name": "Community Site Deployment Archetypes & Protocol Mappings",
        "description": "Authoritative community deployment archetypes (Alpine Summit, Civic Infill, Rooftop Base, Vehicular, Handheld) with cross-protocol split-horizon rules for Meshtastic, MeshCore, Reticulum, and Generic LoRa.",
        "mimeType": "application/json",
    },
    {
        "uri": "meshscout://regulatory/north-america",
        "name": "North America Regulatory Reference",
        "description": "Jurisdiction catalog, regulatory domains, and ISM rules across 65 US and Canadian regions",
        "mimeType": "application/json",
    },
    {
        "uri": "meshscout://packs/installed",
        "name": "Installed Regional Packs",
        "description": "Catalog of currently installed regional tower packs and source provenance",
        "mimeType": "application/json",
    },
]

MCP_PROMPTS_MANIFEST: List[Dict[str, Any]] = [
    {
        "name": "design_regional_emergency_backbone",
        "description": "Design an off-grid resilient emergency communications mesh backbone across mountain summits and municipal hubs.",
        "arguments": [
            {
                "name": "region",
                "description": "Target county or regional bounds key (e.g. vt_chittenden, vt_statewide)",
                "required": False,
            },
            {
                "name": "target_coverage",
                "description": "Desired geographic population coverage fraction (e.g. 0.90)",
                "required": False,
            },
            {
                "name": "max_repeaters",
                "description": "Maximum number of repeaters to select in set cover",
                "required": False,
            },
        ],
    },
    {
        "name": "audit_channel_contention",
        "description": "Audit LoRa channel airtime contention, duty cycle saturation, and multi-hop flood storm risks.",
        "arguments": [
            {
                "name": "site_id",
                "description": "High-site repeater ID to evaluate",
                "required": False,
            },
            {
                "name": "exposed_population",
                "description": "Estimated exposed population within RF line-of-sight horizon",
                "required": False,
            },
            {
                "name": "protocol",
                "description": "Mesh protocol family (e.g. Meshtastic, MeshCore, Reticulum)",
                "required": False,
            },
        ],
    },
    {
        "name": "prepare_selectboard_pitch",
        "description": "Prepare a 1-page host brief and presentation pitch for a municipal selectboard or landowner.",
        "arguments": [
            {
                "name": "site_id",
                "description": "Candidate site ID for which to prepare landowner brief",
                "required": False,
            },
            {
                "name": "town_name",
                "description": "Vermont municipality or host community name",
                "required": False,
            },
            {
                "name": "contact_org",
                "description": "Requesting civic or community emergency mesh organization",
                "required": False,
            },
        ],
    },
]


def _read_resource_content(uri: str, db_path: Optional[str] = None) -> Optional[str]:
    """Load resource payload text for a given MeshScout resource URI."""
    norm_uri = uri.strip().rstrip("/")
    if norm_uri == "meshscout://sites/all":
        _, all_sites = load_regional_fixtures(region="vt_statewide")
        return json.dumps([s.model_dump(mode="json") for s in all_sites], indent=2)

    if norm_uri == "meshscout://presets/hardware":
        hw = {k: v.model_dump(mode="json") for k, v in HARDWARE_PRESETS.items()}
        return json.dumps(hw, indent=2)

    if norm_uri == "meshscout://presets/protocols":
        protos = {k: v.model_dump(mode="json") for k, v in PROTOCOL_PROFILES.items()}
        return json.dumps(protos, indent=2)

    if norm_uri == "meshscout://state/living-mesh":
        reg = LivingMeshRegistry(db_path=db_path)
        nodes = reg.list_nodes()
        payload = {
            "preferences": reg.get_preferences().model_dump(mode="json"),
            "nodes": [n.model_dump(mode="json") for n in nodes],
            "total_nodes": len(nodes),
        }
        return json.dumps(payload, indent=2)

    if norm_uri == "meshscout://fixtures/vt_counties":
        if VT_14_COUNTIES_FIXTURE.exists():
            counties_data = json.loads(VT_14_COUNTIES_FIXTURE.read_text(encoding="utf-8"))
        else:
            counties_data = {
                "counties": list_vermont_counties(),
                "sites": [],
            }
        return json.dumps(counties_data, indent=2)

    if norm_uri == "meshscout://presets/site-architectures":
        arch_data = {k.value: v.model_dump(mode="json") for k, v in COMMUNITY_SITE_ARCHETYPES.items()}
        return json.dumps(arch_data, indent=2)

    if norm_uri == "meshscout://regulatory/north-america":
        from meshscout.adapters.regions import list_north_america_regions
        return json.dumps(list_north_america_regions(), indent=2)

    if norm_uri == "meshscout://packs/installed":
        from meshscout.core.packs import list_installed_packs as core_list_installed_packs
        from meshscout.core.tower_registry import UnifiedTowerRegistry
        with UnifiedTowerRegistry(db_path=db_path) as reg:
            packs = core_list_installed_packs(reg)
        return json.dumps(packs, indent=2)

    return None


def _render_prompt(name: str, arguments: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Render an MCP prompt by name and arguments into (description, text)."""
    clean_name = name.strip().lower()
    if clean_name == "design_regional_emergency_backbone":
        desc = "Design an off-grid resilient emergency communications mesh backbone across mountain summits and municipal hubs."
        region = str(arguments.get("region") or "vt_chittenden")
        target_cov = str(arguments.get("target_coverage") or "0.90")
        max_rep = str(arguments.get("max_repeaters") or "5")
        text = (
            f"Please design a regional emergency mesh backbone for region '{region}' targeting "
            f"{target_cov} coverage with at most {max_rep} repeater high-sites.\n\n"
            "Follow this MeshScout workflow:\n"
            "1. Scout candidate summit and repeater locations using `scout_repeater_sites`.\n"
            "2. Evaluate point-to-point link budgets and Fresnel clearance between selected nodes using `evaluate_link_budget`.\n"
            "3. Inspect RF co-location and 900 MHz desense risks using `inspect_site_feasibility`.\n"
            "4. Consult `meshscout://presets/site-architectures` and enforce the Split-Horizon principle on all Tier 1 Alpine Summits: strictly prohibit single-radio co-channel repeating on high summits.\n"
            "5. Determine optimal node operational roles and compute airtime using `advise_node_role_and_airtime`.\n"
            "6. Evaluate summit-to-summit backhaul decoupling using `recommend_backhaul_architecture` (mandating Dual-Radio Split-Channel Bridge with 3.0m vertical mast isolation or Reticulum Layer 3 routing for high summits).\n"
            "7. Verify off-grid winter solstice solar survival under sub-zero storm streaks using `simulate_winter_solar_survival`."
        )
        return desc, text

    if clean_name == "audit_channel_contention":
        desc = "Audit LoRa channel airtime contention, duty cycle saturation, and multi-hop flood storm risks."
        site_id = str(arguments.get("site_id") or "VT-PEAK-01")
        exposed_pop = str(arguments.get("exposed_population") or "5000")
        protocol = str(arguments.get("protocol") or "Meshtastic")
        text = (
            f"Audit LoRa channel airtime contention, duty cycle saturation, and multi-hop flood storm risks "
            f"for site '{site_id}' with exposed population {exposed_pop} using protocol '{protocol}'.\n\n"
            "Follow this MeshScout workflow:\n"
            "1. Run `advise_node_role_and_airtime` to compute expected hourly packet volume and airtime consumption.\n"
            "2. If channel utilization exceeds threshold, advise transitioning to ROUTER_LATE or CLIENT role.\n"
            "3. Run `recommend_backhaul_architecture` to determine if dual-radio Pi bridging or microwave IP is required to offload backbone traffic."
        )
        return desc, text

    if clean_name == "prepare_selectboard_pitch":
        desc = "Prepare a 1-page host brief and presentation pitch for a municipal selectboard or landowner."
        site_id = str(arguments.get("site_id") or "VT-PEAK-01")
        town_name = str(arguments.get("town_name") or "Burlington")
        contact_org = str(arguments.get("contact_org") or "Vermont Community Emergency Mesh Initiative")
        text = (
            f"Prepare a civic host brief and landowner reassurance pitch for candidate site '{site_id}' in {town_name} "
            f"on behalf of '{contact_org}'.\n\n"
            "Follow this MeshScout workflow:\n"
            "1. Inspect site feasibility and ownership score using `inspect_site_feasibility`.\n"
            "2. Generate printable HTML landowner pitch sheet using `generate_landowner_brief` with site_id '{site_id}' and contact_org '{contact_org}'.\n"
            "3. Present key civic assurances: zero RF interference with public safety, ultra-low power emission (<1W), battery/solar independence, and zero municipal cost."
        )
        return desc, text

    return None


class MeshScoutMCPServer:
    """Zero-dependency JSON-RPC 2.0 MCP Stdio Server for MeshScout."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path
        self._handlers: Dict[str, Callable[..., Dict[str, Any]]] = {
            "scout_repeater_sites": scout_repeater_sites,
            "evaluate_link_budget": evaluate_link_budget,
            "inspect_site_feasibility": inspect_site_feasibility,
            "advise_node_role_and_airtime": advise_node_role_and_airtime,
            "recommend_backhaul_architecture": recommend_backhaul_architecture,
            "provision_node_radio": provision_node_radio,
            "simulate_winter_solar_survival": simulate_winter_solar_survival,
            "analyze_mesh_coverage_gaps": analyze_mesh_coverage_gaps,
            "calibrate_empirical_clutter": calibrate_empirical_clutter,
            "generate_landowner_brief": generate_landowner_brief,
            "stage_offline_field_kit": stage_offline_field_kit,
            "manage_living_mesh_state": self._dispatch_manage_living_mesh_state,
            "advise_eirp": advise_eirp,
            "list_region_packs": self._dispatch_list_region_packs,
        }

    def _dispatch_manage_living_mesh_state(self, **kwargs: Any) -> Dict[str, Any]:
        if "db_path" not in kwargs and self.db_path is not None:
            kwargs["db_path"] = self.db_path
        return manage_living_mesh_state(**kwargs)

    def _dispatch_list_region_packs(self, **kwargs: Any) -> Dict[str, Any]:
        if "db_path" not in kwargs and self.db_path is not None:
            kwargs["db_path"] = self.db_path
        return list_region_packs(**kwargs)

    def handle_request(self, request: Any) -> Optional[Any]:
        """Process a JSON-RPC 2.0 request (dict, batch list, or malformed) and return response."""
        if isinstance(request, list):
            if not request:
                return {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request: empty batch"},
                }
            responses = []
            for item in request:
                res = self.handle_request(item)
                if res is not None:
                    responses.append(res)
            return responses if responses else None

        if not isinstance(request, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request: expected object"},
            }

        is_notification = "id" not in request
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}

        # Notifications (no id member or notifications/* method) must not return a response
        if is_notification or method.startswith("notifications/"):
            return None

        if method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                        "resources": {},
                        "prompts": {},
                    },
                    "serverInfo": {"name": "meshscout-mcp", "version": "0.1.0"},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": MCP_TOOLS_MANIFEST},
            }

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if tool_name not in self._handlers:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unknown tool '{tool_name}'",
                    },
                }
            try:
                payload = self._handlers[tool_name](**arguments)
                is_error = not payload.get("ok", True)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(payload, indent=2),
                            }
                        ],
                        "structuredContent": payload,
                        "isError": is_error,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Tool execution error in '{tool_name}': {exc}",
                    },
                }

        if method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": MCP_RESOURCES_MANIFEST},
            }

        if method == "resources/read":
            uri = str(params.get("uri") or "").strip()
            content = _read_resource_content(uri, db_path=self.db_path)
            if content is None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Resource not found: '{uri}'",
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": content,
                        }
                    ]
                },
            }

        if method == "prompts/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"prompts": MCP_PROMPTS_MANIFEST},
            }

        if method == "prompts/get":
            name = str(params.get("name") or "").strip()
            arguments = params.get("arguments") or {}
            rendered = _render_prompt(name, arguments)
            if rendered is None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Prompt not found: '{name}'",
                    },
                }
            desc, prompt_text = rendered
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "description": desc,
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": prompt_text,
                            },
                        }
                    ],
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: '{method}'",
            },
        }

    def run_stdio(self) -> None:
        """Run the MCP server loop over standard input/output."""
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
                continue

            resp = self.handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()


# ---------------------------------------------------------------------------
# Day-0 MCP Domain Capability Registry & Invariant Verification
# ---------------------------------------------------------------------------

DOMAIN_CAPABILITY_MAP: Dict[str, Dict[str, Any]] = {
    "core.contracts": {
        "tools": ["scout_repeater_sites", "evaluate_link_budget", "inspect_site_feasibility"],
        "resources": ["meshscout://sites/all"],
        "description": "Core geospatial and RF data contracts, entities, and candidate site definitions",
    },
    "core.fresnel": {
        "tools": ["evaluate_link_budget"],
        "resources": [],
        "description": "4/3 Earth radius Fresnel zone clearance calculation and knife-edge diffraction analysis",
    },
    "core.itm": {
        "tools": ["evaluate_link_budget"],
        "resources": [],
        "description": "Longley-Rice Irregular Terrain Model point-to-point path loss and fade margin calculation",
    },
    "core.optimizer": {
        "tools": ["scout_repeater_sites"],
        "resources": [],
        "description": "Greedy minimum set-cover heuristic and budget-constrained site optimization",
    },
    "core.viewshed": {
        "tools": ["scout_repeater_sites"],
        "resources": [],
        "description": "Line-of-sight viewshed computation and regional population coverage analysis",
    },
    "core.scorer": {
        "tools": ["inspect_site_feasibility"],
        "resources": [],
        "description": "Multi-criteria site viability ranking, RF desense risk, and cavity filter assessment",
    },
    "core.traffic": {
        "tools": ["advise_node_role_and_airtime", "recommend_backhaul_architecture"],
        "resources": [],
        "description": "LoRa airtime modeling, channel contention forecasting, and summit backhaul decoupled routing",
    },
    "core.provisioning": {
        "tools": ["provision_node_radio"],
        "resources": ["meshscout://presets/protocols"],
        "description": "Multi-protocol configuration generator, pure SVG QR code emission, and CLI scripts",
    },
    "core.solar": {
        "tools": ["simulate_winter_solar_survival"],
        "resources": [],
        "description": "Solstice solar irradiance simulation and cold-weather battery chemistry survival modeling",
    },
    "core.telemetry": {
        "tools": ["calibrate_empirical_clutter"],
        "resources": [],
        "description": "Wardriving log ingestion and empirical clutter/canopy attenuation calibration",
    },
    "core.registry": {
        "tools": ["manage_living_mesh_state"],
        "resources": ["meshscout://state/living-mesh"],
        "description": "SQLite living mesh persistence, node deployment lifecycle tracking, and home preferences",
    },
    "core.archetypes": {
        "tools": ["recommend_backhaul_architecture", "advise_node_role_and_airtime"],
        "resources": ["meshscout://presets/site-architectures"],
        "description": "Community site deployment archetypes, cross-protocol translation (Meshtastic, MeshCore, Reticulum), and split-horizon backhaul guidance",
    },
    "core.presets": {
        "tools": [],
        "resources": ["meshscout://presets/hardware", "meshscout://presets/protocols"],
        "description": "Hardware and protocol reference specifications and standard radio profiles",
    },
    "adapters.mqtt": {
        "tools": ["analyze_mesh_coverage_gaps"],
        "resources": [],
        "description": "Meshtastic MQTT packet telemetry ingestion and unobserved coverage gap analysis",
    },
    "adapters.telemetry_cache": {
        "tools": ["analyze_mesh_coverage_gaps"],
        "resources": [],
        "description": "Offline SQLite cache and cross-border 20km regional buffering for Meshtastic and MeshCore telemetry",
    },
    "adapters.mqtt_live": {
        "tools": ["analyze_mesh_coverage_gaps"],
        "resources": [],
        "description": "Live Meshtastic MQTT JSON packet parser and broker synchronization worker",
    },
    "adapters.meshcore": {
        "tools": ["analyze_mesh_coverage_gaps"],
        "resources": [],
        "description": "MeshCore and Reticulum identity announcement parser and telemetry normalizer",
    },
    "adapters.vt_counties": {
        "tools": [],
        "resources": ["meshscout://fixtures/vt_counties"],
        "description": "Vermont 14 counties reference fixture and candidate repeater sites",
    },
    "adapters.regions": {
        "tools": [],
        "resources": ["meshscout://fixtures/vt_counties"],
        "description": "Multi-state regional catalog and bounds resolver for Vermont, New Hampshire, and New York",
    },
    "adapters.geodata": {
        "tools": [],
        "resources": ["meshscout://fixtures/vt_counties", "meshscout://sites/all"],
        "description": "Geospatial reference points, municipal centers, and candidate site loader",
    },
    "reporting": {
        "tools": ["generate_landowner_brief"],
        "resources": [],
        "description": "Civic host pitch generation and 1-page HTML landowner reassuring brief",
    },
    "core.staging": {
        "tools": ["stage_offline_field_kit"],
        "resources": [],
        "description": "Offline region boundary expansion, tile estimation, and field-kit staging",
    },
    "core.tower_registry": {
        "tools": ["inspect_site_feasibility"],
        "resources": ["meshscout://sites/all"],
        "description": "Unified SQLite tower registry with spatial bounding-box indexing and approval friction tier sorting",
    },
    "core.composite_viewshed": {
        "tools": ["scout_repeater_sites"],
        "resources": ["meshscout://sites/all"],
        "description": "Multi-origin composite viewshed polygon union calculation, area estimation, and intersite backhaul link matrix",
    },
    "core.corridor": {
        "tools": ["evaluate_link_budget"],
        "resources": ["meshscout://sites/all"],
        "description": "Multi-hop linear backhaul corridor evaluation, cumulative distance, bottleneck link identification, and end-to-end RF feasibility",
    },
    "core.regulatory": {
        "tools": ["advise_eirp"],
        "resources": ["meshscout://regulatory/north-america"],
        "description": "Advisory EIRP power calculations, conducted limits, and Part 15 / RSS-247 regulatory rules",
    },
    "core.packs": {
        "tools": ["list_region_packs"],
        "resources": ["meshscout://packs/installed"],
        "description": "Regional tower data pack distribution, manifest verification, and lifecycle management",
    },
}


def verify_domain_mcp_coverage(
    server: Optional[MeshScoutMCPServer] = None,
) -> Tuple[bool, List[str]]:
    """Programmatically verify all mapped tools and resources exist in the server manifest and are properly bound to handlers.

    Returns:
        (is_valid, list_of_issues): Boolean flag indicating 100% coverage and list of any discrepancy descriptions.
    """
    if server is None:
        server = MeshScoutMCPServer()

    manifest_tool_names = {t["name"] for t in MCP_TOOLS_MANIFEST}
    manifest_resource_uris = {r["uri"] for r in MCP_RESOURCES_MANIFEST}
    handler_tool_names = set(server._handlers.keys())

    issues: List[str] = []

    for domain_key, capability in DOMAIN_CAPABILITY_MAP.items():
        tools = capability.get("tools", [])
        resources = capability.get("resources", [])

        if not tools and not resources:
            issues.append(f"Domain '{domain_key}' specifies neither tools nor resources.")

        for tool_name in tools:
            if tool_name not in manifest_tool_names:
                issues.append(
                    f"Domain '{domain_key}' references tool '{tool_name}' which is missing from MCP_TOOLS_MANIFEST."
                )
            if tool_name not in handler_tool_names:
                issues.append(
                    f"Domain '{domain_key}' references tool '{tool_name}' which has no handler registered in MeshScoutMCPServer."
                )
            elif not callable(server._handlers.get(tool_name)):
                issues.append(
                    f"Domain '{domain_key}' references tool '{tool_name}' whose handler in MeshScoutMCPServer is not callable."
                )

        for resource_uri in resources:
            if resource_uri not in manifest_resource_uris:
                issues.append(
                    f"Domain '{domain_key}' references resource '{resource_uri}' which is missing from MCP_RESOURCES_MANIFEST."
                )
            content = _read_resource_content(resource_uri)
            if content is None or len(content.strip()) == 0:
                issues.append(
                    f"Domain '{domain_key}' references resource '{resource_uri}' which returned empty or invalid content."
                )

    return len(issues) == 0, issues


def create_fastmcp_app(host: str = "127.0.0.1", port: int = 8000) -> Any:
    """Create a FastMCP application instance if the `mcp` package is installed."""
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore

        try:
            mcp = FastMCP("meshscout", host=host, port=port)
        except TypeError:
            mcp = FastMCP("meshscout")
            if hasattr(mcp, "settings"):
                mcp.settings.host = host
                mcp.settings.port = port
        mcp.tool()(scout_repeater_sites)
        mcp.tool()(evaluate_link_budget)
        mcp.tool()(inspect_site_feasibility)
        mcp.tool()(advise_node_role_and_airtime)
        mcp.tool()(recommend_backhaul_architecture)
        mcp.tool()(provision_node_radio)
        mcp.tool()(simulate_winter_solar_survival)
        mcp.tool()(analyze_mesh_coverage_gaps)
        mcp.tool()(calibrate_empirical_clutter)
        mcp.tool()(generate_landowner_brief)
        mcp.tool()(stage_offline_field_kit)
        mcp.tool()(manage_living_mesh_state)
        mcp.tool()(advise_eirp)
        mcp.tool()(list_region_packs)

        @mcp.resource("meshscout://sites/all", mime_type="application/json")
        def resource_sites_all() -> str:
            """All statewide candidate repeater and high-site locations in Vermont."""
            content = _read_resource_content("meshscout://sites/all")
            return content or "[]"

        @mcp.resource("meshscout://presets/hardware", mime_type="application/json")
        def resource_presets_hardware() -> str:
            """Standard LoRa radio hardware specifications and power consumption profiles."""
            content = _read_resource_content("meshscout://presets/hardware")
            return content or "{}"

        @mcp.resource("meshscout://presets/protocols", mime_type="application/json")
        def resource_presets_protocols() -> str:
            """Meshtastic, MeshCore, and Reticulum protocol RF configurations."""
            content = _read_resource_content("meshscout://presets/protocols")
            return content or "{}"

        @mcp.resource("meshscout://state/living-mesh", mime_type="application/json")
        def resource_state_living_mesh() -> str:
            """Current registered club nodes, active deployment status, and workspace preferences."""
            content = _read_resource_content("meshscout://state/living-mesh")
            return content or "{}"

        @mcp.resource("meshscout://fixtures/vt_counties", mime_type="application/json")
        def resource_fixtures_vt_counties() -> str:
            """Vermont 14 counties reference fixture and candidate sites."""
            content = _read_resource_content("meshscout://fixtures/vt_counties")
            return content or "{}"

        @mcp.resource("meshscout://presets/site-architectures", mime_type="application/json")
        def resource_presets_site_architectures() -> str:
            """Community Site Deployment Archetypes & Protocol Mappings."""
            content = _read_resource_content("meshscout://presets/site-architectures")
            return content or "{}"

        @mcp.resource("meshscout://regulatory/north-america", mime_type="application/json")
        def resource_regulatory_north_america() -> str:
            """North America Regulatory Reference."""
            content = _read_resource_content("meshscout://regulatory/north-america")
            return content or "{}"

        @mcp.resource("meshscout://packs/installed", mime_type="application/json")
        def resource_packs_installed() -> str:
            """Catalog of currently installed regional tower packs and source provenance."""
            content = _read_resource_content("meshscout://packs/installed")
            return content or "[]"

        @mcp.prompt("design_regional_emergency_backbone")
        def prompt_design_backbone(
            region: str = "vt_chittenden",
            target_coverage: str = "0.90",
            max_repeaters: str = "5",
        ) -> str:
            """Design an off-grid resilient emergency communications mesh backbone across mountain summits and municipal hubs."""
            res = _render_prompt(
                "design_regional_emergency_backbone",
                {"region": region, "target_coverage": target_coverage, "max_repeaters": max_repeaters},
            )
            return res[1] if res else ""

        @mcp.prompt("audit_channel_contention")
        def prompt_audit_channel(
            site_id: str = "VT-PEAK-01",
            exposed_population: str = "5000",
            protocol: str = "Meshtastic",
        ) -> str:
            """Audit LoRa channel airtime contention, duty cycle saturation, and multi-hop flood storm risks."""
            res = _render_prompt(
                "audit_channel_contention",
                {"site_id": site_id, "exposed_population": exposed_population, "protocol": protocol},
            )
            return res[1] if res else ""

        @mcp.prompt("prepare_selectboard_pitch")
        def prompt_selectboard_pitch(
            site_id: str = "VT-PEAK-01",
            town_name: str = "Burlington",
            contact_org: str = "Vermont Community Emergency Mesh Initiative",
        ) -> str:
            """Prepare a 1-page host brief and presentation pitch for a municipal selectboard or landowner."""
            res = _render_prompt(
                "prepare_selectboard_pitch",
                {"site_id": site_id, "town_name": town_name, "contact_org": contact_org},
            )
            return res[1] if res else ""

        return mcp
    except ImportError:
        return MeshScoutMCPServer()
