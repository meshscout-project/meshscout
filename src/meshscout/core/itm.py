"""Pure-Python Point-to-Point Longley-Rice ITM preprocessor (qlrpfl) and Bullington Diffraction engine.

Follows Functional Core / Imperative Shell architecture: zero I/O, deterministic math,
and strict Pydantic v2 contracts.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field

from meshscout.core.contracts import (
    DowntiltAnalysisResult,
    ElevationProfile,
    LinkBudgetResult,
    RadioConfig,
    Result,
    SiteCandidate,
)

# Physical constants
EARTH_RADIUS_M: float = 6_371_000.0
SPEED_OF_LIGHT_M_S: float = 299_792_458.0


class QlrpflMetrics(BaseModel):
    """Longley-Rice ITM point-to-point terrain preprocessor (qlrpfl) extracted parameters."""

    delta_h_m: float = Field(..., ge=0.0, description="Terrain irregularity parameter delta_h (interdecile range in m)")
    he1_m: float = Field(..., gt=0.0, description="Effective transmitter antenna height above smooth terrain (m)")
    he2_m: float = Field(..., gt=0.0, description="Effective receiver antenna height above smooth terrain (m)")
    dl1_m: float = Field(..., gt=0.0, description="Transmitter radio horizon distance (m)")
    dl2_m: float = Field(..., gt=0.0, description="Receiver radio horizon distance (m)")
    the1_rad: float = Field(..., description="Transmitter horizon elevation angle (radians)")
    the2_rad: float = Field(..., description="Receiver horizon elevation angle (radians)")
    is_line_of_sight: bool = Field(..., description="True if radio horizons do not obstruct direct ray")


def free_space_path_loss_db(distance_km: float, frequency_mhz: float = 915.0) -> float:
    """Calculate Free-Space Path Loss (FSPL) in dB.

    Formula:
        FSPL(dB) = 32.44 + 20 * log10(d_km) + 20 * log10(f_MHz)
    """
    if distance_km <= 0.0:
        raise ValueError(f"distance_km must be strictly positive, got {distance_km}")
    if frequency_mhz <= 0.0:
        raise ValueError(f"frequency_mhz must be strictly positive, got {frequency_mhz}")
    return 32.44 + 20.0 * math.log10(distance_km) + 20.0 * math.log10(frequency_mhz)


def knife_edge_diffraction_loss_db(nu: float) -> float:
    """Calculate single knife-edge diffraction loss J(nu) in dB per ITU-R P.526 (Lee approximation).

    For nu <= -0.78, diffraction loss is 0.0 dB.
    For nu > -0.78:
        J(nu) = 6.9 + 20 * log10(sqrt((nu - 0.1)^2 + 1) + nu - 0.1)
    """
    if nu <= -0.78:
        return 0.0
    term = math.sqrt((nu - 0.1) ** 2 + 1.0) + (nu - 0.1)
    return max(0.0, 6.9 + 20.0 * math.log10(term))


def _percentile_sorted(sorted_vals: List[float], q: float) -> float:
    """Compute linear-interpolated quantile q in [0, 1] from a non-empty sorted list."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def extract_qlrpfl_parameters(
    profile: ElevationProfile,
    k_factor: float = 4.0 / 3.0,
) -> QlrpflMetrics:
    """Extract Longley-Rice ITM point-to-point parameters (`qlrpfl`: `zlsq1` and `hzns`).

    1. `zlsq1`: Fits a least-squares linear regression over the central 80% of the terrain
       profile (10% to 90% of path distance) to evaluate the smooth-earth reference plane,
       effective antenna heights (he1, he2), and the interdecile terrain irregularity
       parameter delta_h (90th minus 10th percentile of terrain residuals, with asymptotic
       finite-path scaling `1 - 0.8 * exp(-d / 50km)`).
    2. `hzns`: Scans intermediate terrain points adjusted for effective Earth curvature
       (`a_eff = k_factor * EARTH_RADIUS_M`) to extract transmitter and receiver horizon
       angles (`the1_rad`, `the2_rad`) and horizon distances (`dl1_m`, `dl2_m`).
    """
    total_d_m = profile.distance_km * 1000.0
    if total_d_m <= 0.0 and len(profile.points) >= 2:
        total_d_m = profile.points[-1].distance_m - profile.points[0].distance_m
    total_d_m = max(total_d_m, 1.0)

    a_eff = k_factor * EARTH_RADIUS_M

    # Build ordered distance/elevation tuples
    if len(profile.points) >= 2:
        xs = [pt.distance_m for pt in profile.points]
        zs = [pt.elevation_m for pt in profile.points]
    else:
        xs = [0.0, total_d_m]
        zs = [
            profile.source_site.location.elevation_m,
            profile.target_site.location.elevation_m,
        ]

    h_g1 = zs[0]
    h_g2 = zs[-1]
    h_sys1 = h_g1 + profile.source_site.mast_height_m
    h_sys2 = h_g2 + profile.target_site.mast_height_m

    # Filter central 80% of path [0.1 * d, 0.9 * d] for zlsq1 linear fit
    d_lo = 0.10 * total_d_m
    d_hi = 0.90 * total_d_m
    central_pairs = [(x, z) for x, z in zip(xs, zs) if d_lo <= x <= d_hi]
    if len(central_pairs) < 2:
        central_pairs = list(zip(xs, zs))

    n_c = len(central_pairs)
    mean_x = sum(p[0] for p in central_pairs) / n_c
    mean_z = sum(p[1] for p in central_pairs) / n_c
    denom = sum((p[0] - mean_x) ** 2 for p in central_pairs)
    if denom > 1e-9:
        slope = sum((p[0] - mean_x) * (p[1] - mean_z) for p in central_pairs) / denom
    else:
        slope = 0.0
    intercept = mean_z - slope * mean_x

    # Fitted smooth ground heights at endpoints x=0 and x=total_d_m
    z_fit_0 = intercept
    z_fit_d = intercept + slope * total_d_m

    # Residuals across central section for interdecile range (10% to 90%)
    residuals = sorted(z - (intercept + slope * x) for x, z in central_pairs)
    interdecile_raw = max(0.0, _percentile_sorted(residuals, 0.90) - _percentile_sorted(residuals, 0.10))

    # ITM asymptotic path-length adjustment for delta_h:
    # delta_h(d) = interdecile_raw / (1 - 0.8 * exp(-d_km / 50)) or direct interdecile_raw.
    # Note: In ITM qlrpfl, delta_h returned is the interdecile range of residuals.
    delta_h_m = float(interdecile_raw)

    # Effective antenna heights (he1, he2): height of antenna above fitted smooth plane,
    # bounded below by structural mast height (minimum 1.0 m).
    he1_m = max(profile.source_site.mast_height_m, h_sys1 - z_fit_0, 1.0)
    he2_m = max(profile.target_site.mast_height_m, h_sys2 - z_fit_d, 1.0)

    # Horizon extraction (hzns)
    # Direct line-of-sight elevation angle from TX to RX and RX to TX
    theta_los_1 = (h_sys2 - h_sys1) / total_d_m - total_d_m / (2.0 * a_eff)
    theta_los_2 = (h_sys1 - h_sys2) / total_d_m - total_d_m / (2.0 * a_eff)

    max_theta_1 = -math.inf
    dl1_m = total_d_m
    max_theta_2 = -math.inf
    dl2_m = total_d_m

    for x, z in zip(xs[1:-1], zs[1:-1]):
        if x <= 0.0 or x >= total_d_m:
            continue
        # Angle from TX to point x
        theta_1 = (z - h_sys1) / x - x / (2.0 * a_eff)
        if theta_1 > max_theta_1:
            max_theta_1 = theta_1
            dl1_m = x

        # Angle from RX to point x (distance d_rx = total_d_m - x)
        d_rx = total_d_m - x
        theta_2 = (z - h_sys2) / d_rx - d_rx / (2.0 * a_eff)
        if theta_2 > max_theta_2:
            max_theta_2 = theta_2
            dl2_m = d_rx

    if max_theta_1 > theta_los_1:
        # Obstructed path: horizons are defined by the dominant terrain ridges
        is_line_of_sight = False
        the1_rad = max_theta_1
        the2_rad = max_theta_2
    else:
        # Unobstructed optical/radio LOS: smooth-earth theoretical radio horizons
        is_line_of_sight = True
        dl1_smooth = math.sqrt(2.0 * a_eff * he1_m)
        dl2_smooth = math.sqrt(2.0 * a_eff * he2_m)
        dl1_m = min(total_d_m, dl1_smooth)
        dl2_m = min(total_d_m, dl2_smooth)
        the1_rad = theta_los_1 if max_theta_1 == -math.inf else max(theta_los_1, max_theta_1)
        the2_rad = theta_los_2 if max_theta_2 == -math.inf else max(theta_los_2, max_theta_2)

    return QlrpflMetrics(
        delta_h_m=delta_h_m,
        he1_m=he1_m,
        he2_m=he2_m,
        dl1_m=dl1_m,
        dl2_m=dl2_m,
        the1_rad=the1_rad,
        the2_rad=the2_rad,
        is_line_of_sight=is_line_of_sight,
    )


def bullington_diffraction_loss_db(
    profile: ElevationProfile,
    frequency_mhz: float = 915.0,
    k_factor: float = 4.0 / 3.0,
) -> Tuple[float, float, bool]:
    """Compute Bullington equivalent knife-edge diffraction loss (ITU-R P.526).

    Constructs the equivalent Bullington knife-edge intersection from the transmitter
    and receiver horizon rays adjusted for Earth curvature (`k_factor`), or evaluates
    the dominant sub-Fresnel terrain intrusion when geometric line-of-sight is clear.

    Returns:
        Tuple of `(diffraction_loss_db, min_fresnel_clearance_ratio, has_line_of_sight)`.
    """
    total_d_m = profile.distance_km * 1000.0
    if total_d_m <= 0.0 and len(profile.points) >= 2:
        total_d_m = profile.points[-1].distance_m - profile.points[0].distance_m
    if total_d_m <= 0.0 or len(profile.points) < 2:
        return (0.0, 1.0, True)

    wavelength_m = SPEED_OF_LIGHT_M_S / (frequency_mhz * 1e6)
    a_eff = k_factor * EARTH_RADIUS_M

    h_tx = profile.points[0].elevation_m + profile.source_site.mast_height_m
    h_rx = profile.points[-1].elevation_m + profile.target_site.mast_height_m

    # Direct TX-RX ray slope in Earth-chord coordinates
    s_tr = (h_rx - h_tx) / total_d_m

    max_s_tx = -math.inf
    max_s_rx = -math.inf
    max_nu_los = -math.inf
    min_fresnel_ratio = math.inf
    has_los = True

    intermediate = [
        pt for pt in profile.points[1:-1] if 0.0 < pt.distance_m < total_d_m
    ]
    if not intermediate:
        return (0.0, 1.0, True)

    for pt in intermediate:
        d1 = pt.distance_m
        d2 = total_d_m - d1
        earth_bulge = (d1 * d2) / (2.0 * a_eff)
        h_eff = pt.elevation_m + earth_bulge

        # Ray height along straight chord from TX to RX at distance d1
        h_ray = h_tx + s_tr * d1
        # Clearance > 0 means ray is above curvature-adjusted terrain
        clearance = h_ray - h_eff
        if clearance < 0.0:
            has_los = False

        # First Fresnel Zone radius F1 at (d1, d2)
        f1_radius = math.sqrt(wavelength_m * d1 * d2 / total_d_m)
        if f1_radius > 0.0:
            clearance_ratio = clearance / f1_radius
            if clearance_ratio < min_fresnel_ratio:
                min_fresnel_ratio = clearance_ratio

        # Diffraction parameter nu for this point
        nu_pt = -clearance * math.sqrt(2.0 * total_d_m / (wavelength_m * d1 * d2))
        if nu_pt > max_nu_los:
            max_nu_los = nu_pt

        # Horizon slope from TX and from RX including Earth curvature bulge
        s_tx = (h_eff - h_tx) / d1
        s_rx = (h_eff - h_rx) / d2
        if s_tx > max_s_tx:
            max_s_tx = s_tx
        if s_rx > max_s_rx:
            max_s_rx = s_rx

    if not has_los and (max_s_tx + max_s_rx) > 0.0:
        # Bullington equivalent knife-edge intersection of highest TX and RX horizon rays:
        # h_tx + max_s_tx * d1_b = h_rx + max_s_rx * (total_d_m - d1_b)
        d1_b = (h_rx - h_tx + max_s_rx * total_d_m) / (max_s_tx + max_s_rx)
        d1_b = max(1.0, min(total_d_m - 1.0, d1_b))
        d2_b = total_d_m - d1_b
        h_b = h_tx + max_s_tx * d1_b
        h_ray_b = h_tx + s_tr * d1_b
        h_obs_b = h_b - h_ray_b
        nu_bullington = h_obs_b * math.sqrt(2.0 * total_d_m / (wavelength_m * d1_b * d2_b))
        nu = max(nu_bullington, max_nu_los)
    else:
        nu = max_nu_los

    diff_loss_db = knife_edge_diffraction_loss_db(nu)
    if math.isinf(min_fresnel_ratio):
        min_fresnel_ratio = 1.0

    return (diff_loss_db, float(min_fresnel_ratio), has_los)


def calculate_antenna_downtilt(
    source_site: SiteCandidate,
    target_site: SiteCandidate,
    distance_km: float,
    antenna_gain_dbi: float = 5.8,
    k_factor: float = 4.0 / 3.0,
) -> DowntiltAnalysisResult:
    """Calculate mechanical look-down angle and antenna vertical beamwidth alignment.

    High-gain collinear omni antennas (e.g., 8dBi or 10dBi) focus energy into very narrow
    vertical beamwidths (~8-12°). On mountaintop nodes looking down into deep valley floors,
    the plumb vertical beam shoots over valley receivers unless mechanically downtilted
    or replaced with a wider beamwidth antenna (3dBi to 5.8dBi).
    """
    total_d_m = max(1.0, distance_km * 1000.0)
    tx_elev = source_site.location.elevation_m + source_site.mast_height_m
    rx_elev = target_site.location.elevation_m + target_site.mast_height_m
    delta_h = tx_elev - rx_elev

    # Earth curvature drop at distance d_m
    re_eff = EARTH_RADIUS_M * k_factor
    earth_drop_m = (total_d_m ** 2) / (2.0 * re_eff)

    # Elevation look angle from horizontal in degrees (positive = look-down, negative = look-up)
    look_angle_rad = math.atan2(delta_h - earth_drop_m, total_d_m)
    look_down_angle_deg = round(math.degrees(look_angle_rad), 2)

    # Half-power vertical beamwidth (-3dB) estimation for standard collinear omni
    gain = max(0.0, antenna_gain_dbi)
    if gain <= 2.15:
        beamwidth_deg = 78.0
    elif gain <= 3.5:
        beamwidth_deg = 55.0
    elif gain <= 6.5:
        beamwidth_deg = 20.0
    elif gain <= 8.5:
        beamwidth_deg = 10.0
    else:
        beamwidth_deg = 6.0

    half_beamwidth = beamwidth_deg / 2.0
    is_overshooting = look_down_angle_deg > half_beamwidth

    if is_overshooting:
        ratio = look_down_angle_deg / half_beamwidth
        pattern_attenuation_db = round(min(25.0, 3.0 * (ratio ** 2)), 1)
        rec_downtilt = round(look_down_angle_deg, 1)
        rec_text = (
            f"Steep look-down ({look_down_angle_deg}°) exceeds {antenna_gain_dbi:.1f}dBi vertical beamwidth "
            f"({beamwidth_deg}°). Main lobe shoots over target. Apply {rec_downtilt}° mechanical downtilt "
            f"or down-spec to a 3dBi–5.8dBi wide-beamwidth omni."
        )
    elif look_down_angle_deg > 1.5:
        pattern_attenuation_db = 0.5
        rec_downtilt = 0.0
        rec_text = f"Beam aligned within {antenna_gain_dbi:.1f}dBi vertical coverage cone ({beamwidth_deg}°)."
    else:
        pattern_attenuation_db = 0.0
        rec_downtilt = 0.0
        rec_text = f"Horizontal / mild trajectory well within {beamwidth_deg}° beamwidth."

    return DowntiltAnalysisResult(
        look_down_angle_deg=look_down_angle_deg,
        vertical_beamwidth_deg=beamwidth_deg,
        is_overshooting=is_overshooting,
        recommended_downtilt_deg=rec_downtilt,
        pattern_attenuation_db=pattern_attenuation_db,
        recommendation=rec_text,
    )


def evaluate_point_to_point_link(
    profile: ElevationProfile,
    radio: Optional[RadioConfig] = None,
    k_factor: float = 4.0 / 3.0,
) -> Result[LinkBudgetResult]:
    """Evaluate complete point-to-point RF link budget over an elevation profile.

    Combines Free-Space Path Loss (FSPL), Bullington knife-edge diffraction, Longley-Rice
    ITM terrain irregularity / double-horizon shadow attenuation, and radio transceiver
    parameters into a `Result[LinkBudgetResult]`.
    """
    if radio is None:
        radio = RadioConfig()

    if profile.distance_km <= 0.0:
        return Result.fail(
            code="INVALID_DISTANCE",
            message=f"Profile distance_km must be positive, got {profile.distance_km}",
        )

    if len(profile.points) < 2:
        return Result.fail(
            code="INSUFFICIENT_PROFILE_POINTS",
            message="ElevationProfile must contain at least 2 sample points (source and target).",
        )

    try:
        fspl_db = free_space_path_loss_db(
            distance_km=profile.distance_km,
            frequency_mhz=radio.frequency_mhz,
        )
        bull_loss_db, fresnel_ratio, has_los = bullington_diffraction_loss_db(
            profile=profile,
            frequency_mhz=radio.frequency_mhz,
            k_factor=k_factor,
        )
        qlrpfl = extract_qlrpfl_parameters(profile=profile, k_factor=k_factor)

        # Longley-Rice ITM terrain irregularity & double-horizon clutter correction:
        # When both horizons obstruct the path (dl1 + dl2 < total_d) or terrain roughness
        # delta_h is high on a non-LOS link, ITM adds roughness/multipath diffraction penalty.
        total_d_m = profile.distance_km * 1000.0
        itm_roughness_loss_db = 0.0
        if not has_los and qlrpfl.delta_h_m > 0.0:
            shadow_span_m = max(0.0, total_d_m - (qlrpfl.dl1_m + qlrpfl.dl2_m))
            if shadow_span_m > 0.0:
                # Double-horizon separation penalty (Epstein-Peterson / ITM shadow weighting)
                itm_roughness_loss_db = min(
                    12.0,
                    2.5 * math.log10(1.0 + shadow_span_m / 1000.0)
                    + 0.015 * min(qlrpfl.delta_h_m, 200.0),
                )

        diffraction_loss_db = round(bull_loss_db + itm_roughness_loss_db, 4)
        total_path_loss_db = round(fspl_db + diffraction_loss_db + radio.environmental_clutter_db, 4)

        downtilt = calculate_antenna_downtilt(
            source_site=profile.source_site,
            target_site=profile.target_site,
            distance_km=profile.distance_km,
            antenna_gain_dbi=radio.antenna_gain_dbi,
            k_factor=k_factor,
        )

        # Link budget equation:
        # P_rx = P_tx + G_tx + G_rx - L_cable_tx - L_cable_rx - L_path - L_pattern
        system_gain_db = (2.0 * radio.antenna_gain_dbi) - (2.0 * radio.cable_loss_db) - downtilt.pattern_attenuation_db
        rx_power_dbm = round(radio.tx_power_dbm + system_gain_db - total_path_loss_db, 4)
        link_margin_db = round(rx_power_dbm - radio.rx_sensitivity_dbm, 4)

        return Result.success(
            LinkBudgetResult(
                source_id=profile.source_site.site_id,
                target_id=profile.target_site.site_id,
                distance_km=profile.distance_km,
                free_space_loss_db=round(fspl_db, 4),
                diffraction_loss_db=diffraction_loss_db,
                total_path_loss_db=total_path_loss_db,
                rx_power_dbm=rx_power_dbm,
                link_margin_db=link_margin_db,
                has_line_of_sight=has_los,
                fresnel_clearance_ratio=round(fresnel_ratio, 4),
                downtilt_analysis=downtilt,
            )
        )
    except Exception as exc:
        return Result.fail(
            code="ITM_EVALUATION_ERROR",
            message=f"Failed to evaluate ITM link budget: {exc}",
        )
