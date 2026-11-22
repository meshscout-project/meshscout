"""Stateless L3 command orchestration seam for MeshScout.

Hosts shared regional fixture loaders, link/viewshed orchestration commands,
and regulatory EIRP helpers used by MCP tools, FastAPI routes, and CLI surfaces.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from meshscout.adapters.elevation import ElevationGrid, USGS3DEPElevationAdapter
from meshscout.adapters.fcc_asr import FCCASRAdapter
from meshscout.adapters.vt_vcgi import VCGIRegionalAdapter
from meshscout.core.composite_viewshed import compute_composite_viewshed
from meshscout.core.contracts import (
    Coordinate,
    RadioConfig,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)
from meshscout.core.fresnel import analyze_fresnel_clearance
from meshscout.core.itm import evaluate_point_to_point_link
from meshscout.core.optimizer import solve_minimum_set_cover
from meshscout.core.presets import CLIENT_ENVIRONMENT_PROFILES, build_radio_config
from meshscout.core.regulatory import (
    RegulatoryDomain,
    advise_eirp as core_advise_eirp,
    detect_regulatory_domain,
)
from meshscout.core.resilience import evaluate_topology_resilience
from meshscout.core.scorer import (
    EmitterSpec,
    rank_candidate_sites,
    score_site_viability,
)
from meshscout.core.traffic import compute_meshtastic_channel_slot
from meshscout.core.viewshed import (
    ViewshedResult,
    _synthetic_vermont_elevation_fn,
    compute_viewshed,
    find_local_highpoint,
    generate_target_grid,
)
from meshscout.reporting import export_atak_cot_xml, parse_bulk_sites_csv

logger = logging.getLogger(__name__)

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


def build_offline_elevation_adapter(bounds: RegionalBounds) -> USGS3DEPElevationAdapter:
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


_build_offline_elevation_adapter = build_offline_elevation_adapter


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
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            logger.debug("Skipping 14-county fixture merge due to error: %s", exc)

    return bounds, list(by_id.values())


def _resolve_site_by_id(site_id: str) -> Optional[SiteCandidate]:
    """Resolve a SiteCandidate by ID across statewide regional fixtures and county candidates."""
    clean_id = site_id.strip().upper()
    _, all_sites = load_regional_fixtures(region="vt_statewide")
    for s in all_sites:
        if s.site_id.strip().upper() == clean_id:
            return s
    try:
        from meshscout.adapters.vt_counties import load_county_candidates

        county_res = load_county_candidates("all")
        if county_res.ok and county_res.value:
            for s in county_res.value:
                if s.site_id.strip().upper() == clean_id:
                    return s
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        logger.debug("Failed loading county candidates for site '%s': %s", site_id, exc)

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
    evaluation_mode: Optional[str] = None,
    source_preset: Optional[str] = None,
    target_preset: Optional[str] = None,
    client_env: Optional[str] = None,
    protocol_profile: str = "MESHTASTIC_LONGFAST",
    season_profile: str = "SUMMER_FOLIAGE",
    source_noise_penalty_db: float = 0.0,
    target_noise_penalty_db: float = 0.0,
) -> Dict[str, Any]:
    """Evaluate point-to-point Fresnel clearance and Longley-Rice ITM link budget offline."""
    is_dual_mode = (
        evaluation_mode is not None
        or source_preset is not None
        or target_preset is not None
        or client_env is not None
        or source_noise_penalty_db != 0.0
        or target_noise_penalty_db != 0.0
    )

    mode_norm: Optional[str] = None
    eff_source_preset: Optional[str] = None
    eff_target_preset: Optional[str] = None
    eff_env_key: Optional[str] = None
    client_env_loss_db: float = 0.0
    source_radio: Optional[RadioConfig] = None
    target_radio: Optional[RadioConfig] = None

    if is_dual_mode:
        mode_norm = evaluation_mode.strip().lower() if evaluation_mode is not None else "client"
        if mode_norm not in ("client", "backhaul"):
            return {
                "ok": False,
                "error": {
                    "code": "INVALID_EVALUATION_MODE",
                    "message": (
                        f"Unsupported evaluation_mode '{evaluation_mode}'. "
                        "Must be 'client' or 'backhaul'."
                    ),
                },
            }

        if client_env is not None:
            env_key = client_env.strip().upper()
            if env_key not in CLIENT_ENVIRONMENT_PROFILES:
                return {
                    "ok": False,
                    "error": {
                        "code": "UNKNOWN_CLIENT_ENV",
                        "message": (
                            f"Unknown client_env '{client_env}'. "
                            f"Available: {sorted(CLIENT_ENVIRONMENT_PROFILES.keys())}"
                        ),
                    },
                }
        else:
            env_key = "OUTDOOR_CLEAR"

        if mode_norm == "backhaul":
            client_env_loss_db = 0.0
            eff_env_key = None
            eff_source_preset = (source_preset or "STATION_G2_BACKBONE").strip().upper()
            eff_target_preset = (target_preset or "RAK4631_SOLAR").strip().upper()
        else:
            eff_env_key = env_key
            client_env_loss_db = CLIENT_ENVIRONMENT_PROFILES[env_key].clutter_loss_db
            eff_source_preset = (source_preset or "STATION_G2_BACKBONE").strip().upper()
            eff_target_preset = (target_preset or "SENSECAP_T1000E").strip().upper()

        src_res = build_radio_config(
            hardware_id=eff_source_preset,
            protocol_id=protocol_profile,
            season_id=season_profile,
        )
        if not src_res.ok or src_res.value is None:
            return {
                "ok": False,
                "error": {
                    "code": src_res.error.code if src_res.error else "RADIO_CONFIG_ERROR",
                    "message": (
                        src_res.error.message
                        if src_res.error
                        else "Failed to build source radio configuration."
                    ),
                },
            }

        tgt_res = build_radio_config(
            hardware_id=eff_target_preset,
            protocol_id=protocol_profile,
            season_id=season_profile,
        )
        if not tgt_res.ok or tgt_res.value is None:
            return {
                "ok": False,
                "error": {
                    "code": tgt_res.error.code if tgt_res.error else "RADIO_CONFIG_ERROR",
                    "message": (
                        tgt_res.error.message
                        if tgt_res.error
                        else "Failed to build target radio configuration."
                    ),
                },
            }

        source_radio = src_res.value
        target_radio = tgt_res.value

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

    if not is_dual_mode:
        fresnel_res = analyze_fresnel_clearance(
            profile=profile,
            frequency_mhz=frequency_mhz,
        )
        radio = RadioConfig(frequency_mhz=frequency_mhz, tx_power_dbm=tx_power_dbm)
        itm_res = evaluate_point_to_point_link(
            profile=profile,
            radio=radio,
        )
    else:
        if source_radio is None or target_radio is None:
            return {
                "ok": False,
                "error": {
                    "code": "RADIO_CONFIG_ERROR",
                    "message": "Dual-mode evaluation requires valid source and target radio configurations.",
                },
            }
        fresnel_res = analyze_fresnel_clearance(
            profile=profile,
            frequency_mhz=source_radio.frequency_mhz,
        )
        itm_res = evaluate_point_to_point_link(
            profile=profile,
            radio=source_radio,
            target_radio=target_radio,
            source_noise_penalty_db=float(source_noise_penalty_db),
            target_noise_penalty_db=float(target_noise_penalty_db),
            client_env_loss_db=client_env_loss_db,
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

    fresnel_dict = {
        "total_distance_m": fresnel.total_distance_m,
        "frequency_mhz": fresnel.frequency_mhz,
        "has_line_of_sight": fresnel.has_line_of_sight,
        "fresnel_60pct_clear": fresnel.fresnel_60pct_clear,
        "min_clearance_m": round(fresnel.min_clearance_m, 3),
        "min_clearance_ratio": round(fresnel.min_clearance_ratio, 4),
        "max_knife_edge_nu": round(fresnel.max_knife_edge_nu, 4),
    }

    if not is_dual_mode:
        return {
            "ok": True,
            "link_budget": link.model_dump(mode="json"),
            "fresnel_analysis": fresnel_dict,
        }

    return {
        "ok": True,
        "evaluation_mode": mode_norm,
        "source_preset": eff_source_preset,
        "target_preset": eff_target_preset,
        "client_env": eff_env_key,
        "client_env_loss_db": client_env_loss_db,
        "protocol_profile": protocol_profile.strip().upper(),
        "season_profile": season_profile.strip().upper(),
        "link_budget": link.model_dump(mode="json"),
        "fresnel_analysis": fresnel_dict,
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


def resolve_regulatory_domain(
    domain: Optional[str] = None,
    region: Optional[str] = None,
) -> RegulatoryDomain:
    """Resolve the active regulatory domain from an explicit enum value or region fallback."""
    if domain:
        try:
            return RegulatoryDomain(domain)
        except ValueError:
            detected_from_domain = detect_regulatory_domain(domain)
            if detected_from_domain != RegulatoryDomain.US_FCC_PART15 or not region:
                return detected_from_domain
            return detect_regulatory_domain(region)
    if region:
        return detect_regulatory_domain(region)
    return RegulatoryDomain.US_FCC_PART15


def advise_eirp(
    tx_power_dbm: float = 20.0,
    antenna_gain_dbi: float = 3.0,
    cable_loss_db: float = 0.0,
    frequency_mhz: float = 915.0,
    domain: Optional[str] = None,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate transmitter conducted power and EIRP limits against FCC Part 15.247 / ISED RSS-247 rules."""
    reg_domain = resolve_regulatory_domain(domain=domain, region=region)
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


def evaluate_backbone_resilience(
    region: str = "vt_chittenden",
    site_ids: Optional[Sequence[str]] = None,
    min_margin_db: float = 0.0,
    channel_name: str = "LongFast",
    protocol_key: str = "MESHTASTIC_LONGFAST",
    hardware_id: str = "RAK4631_SOLAR",
) -> Dict[str, Any]:
    """Evaluate backbone topology SPOFs, bridge links, BOM, and Meshtastic channel slot."""
    bounds, sites = load_regional_fixtures(region)
    if site_ids:
        allowed = set(site_ids)
        sites = [s for s in sites if s.site_id in allowed]
    if not sites:
        return {
            "ok": False,
            "error": {
                "code": "EMPTY_TOPOLOGY",
                "message": "No candidate sites matched selection.",
            },
        }

    rc_res = build_radio_config(hardware_id, protocol_key)
    if not rc_res.ok or rc_res.value is None:
        return {
            "ok": False,
            "error": {
                "code": rc_res.error.code if rc_res.error else "INVALID_CONFIG",
                "message": (
                    rc_res.error.message
                    if rc_res.error
                    else "Invalid radio configuration"
                ),
            },
        }

    adapter = _build_offline_elevation_adapter(bounds)

    def elev_fn(lat: float, lon: float) -> float:
        r = adapter.get_elevation_at(lat, lon)
        return (
            float(r.value)
            if (r.ok and r.value is not None)
            else float(_synthetic_vermont_elevation_fn(lat, lon))
        )

    cv = compute_composite_viewshed(
        sites,
        num_radials=8,
        direction="two_way",
        elevation_fn=elev_fn,
        radio_config=rc_res.value,
    )
    if not cv.ok or cv.value is None:
        return {
            "ok": False,
            "error": {
                "code": cv.error.code if cv.error else "VIEWSHED_ERROR",
                "message": (
                    cv.error.message if cv.error else "Failed composite viewshed"
                ),
            },
        }

    links = [
        (lnk.site_a_id, lnk.site_b_id, lnk.link_margin_db)
        for lnk in cv.value.intersite_backhaul_links
    ]
    rep_res = evaluate_topology_resilience(
        sites=sites,
        links=links,
        min_margin_db=float(min_margin_db),
    )
    if not rep_res.ok or rep_res.value is None:
        return {
            "ok": False,
            "error": {
                "code": rep_res.error.code if rep_res.error else "RESILIENCE_ERROR",
                "message": (
                    rep_res.error.message
                    if rep_res.error
                    else "Failed resilience evaluation"
                ),
            },
        }

    slot_res = compute_meshtastic_channel_slot(
        channel_name=channel_name,
        region_code="US",
    )
    return {
        "ok": True,
        "region": region,
        "report": rep_res.value.model_dump(mode="json"),
        "channel_slot": (
            slot_res.value.model_dump(mode="json")
            if (slot_res.ok and slot_res.value is not None)
            else None
        ),
    }


def compute_channel_slot(
    channel_name: str = "LongFast",
    region_code: str = "US",
    bandwidth_khz: float = 250.0,
    explicit_channel_num: int = 0,
) -> Dict[str, Any]:
    """Compute Meshtastic djb2 channel hash, 1-indexed frequency slot, and center frequency."""
    res = compute_meshtastic_channel_slot(
        channel_name=channel_name,
        region_code=region_code,
        bandwidth_khz=float(bandwidth_khz),
        explicit_channel_num=int(explicit_channel_num),
    )
    if not res.ok or res.value is None:
        return {
            "ok": False,
            "error": (
                res.error.model_dump(mode="json")
                if res.error
                else {
                    "code": "INVALID_CHANNEL_PARAMS",
                    "message": "Invalid channel parameters",
                }
            ),
        }
    return {"ok": True, **res.value.model_dump(mode="json")}


def snap_site_highpoint(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    step_m: float = 50.0,
) -> Dict[str, Any]:
    """Snap a candidate coordinate to the highest local terrain point within radius_m."""
    adapter = _build_offline_elevation_adapter(VT_CHITTENDEN_BOUNDS)

    def elev_fn(sample_lat: float, sample_lon: float) -> float:
        r = adapter.get_elevation_at(sample_lat, sample_lon)
        return (
            float(r.value)
            if (r.ok and r.value is not None)
            else float(_synthetic_vermont_elevation_fn(sample_lat, sample_lon))
        )

    origin = Coordinate(
        lat=float(lat),
        lon=float(lon),
        elevation_m=elev_fn(float(lat), float(lon)),
    )
    res = find_local_highpoint(
        origin=origin,
        elevation_fn=elev_fn,
        radius_m=float(radius_m),
        step_m=float(step_m),
    )
    if res.ok and res.value is not None:
        return {"ok": True, **res.value.model_dump(mode="json")}
    return {
        "ok": False,
        "error": (
            res.error.model_dump(mode="json")
            if res.error
            else {"code": "INVALID_SEARCH_GRID", "message": "Highpoint search failed"}
        ),
    }


def export_cot_bundle(
    region: str = "vt_chittenden",
    site_ids: Optional[Sequence[str]] = None,
    stale_minutes: int = 60,
) -> Dict[str, Any]:
    """Export regional candidate repeater sites as an ATAK Cursor-on-Target (CoT) 2.0 XML bundle."""
    _, sites = load_regional_fixtures(region)
    if site_ids:
        allowed = set(site_ids)
        sites = [s for s in sites if s.site_id in allowed]
    return {
        "ok": True,
        "region": region,
        "site_count": len(sites),
        "cot_xml": export_atak_cot_xml(sites, stale_minutes=int(stale_minutes)),
    }


def import_sites_csv(csv_text: str) -> Dict[str, Any]:
    """Parse and validate candidate repeater sites from bulk CSV text."""
    res = parse_bulk_sites_csv(csv_text)
    if res.ok and res.value is not None:
        return {
            "ok": True,
            "count": len(res.value),
            "sites": [s.model_dump(mode="json") for s in res.value],
        }
    return {
        "ok": False,
        "error": (
            res.error.model_dump(mode="json")
            if res.error
            else {"code": "INVALID_CSV_ROW", "message": "CSV import failed"}
        ),
    }


__all__ = [
    "FCC_ASR_FIXTURE",
    "FIXTURES_DIR",
    "VERMONT_STATE_BOUNDS",
    "VT_CHITTENDEN_BOUNDS",
    "VT_CHITTENDEN_FIXTURE",
    "VT_VCGI_FIXTURE",
    "_build_offline_elevation_adapter",
    "_resolve_site_by_id",
    "advise_eirp",
    "build_offline_elevation_adapter",
    "compute_channel_slot",
    "evaluate_backbone_resilience",
    "evaluate_link_budget",
    "export_cot_bundle",
    "import_sites_csv",
    "inspect_site_feasibility",
    "load_regional_fixtures",
    "resolve_regulatory_domain",
    "scout_repeater_sites",
    "snap_site_highpoint",
]
