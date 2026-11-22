"""Pure-Python LoRa airtime forecaster, population traffic exposure, and role advisor."""

from __future__ import annotations

import math
import shlex
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple
from pydantic import BaseModel, Field

from meshscout.core.contracts import ReachabilityState, Result, SiteCandidate, SiteType


_MESHTASTIC_BAND_PLANS: Dict[str, Tuple[float, float]] = {
    "US": (902.0, 928.0),
    "CA": (902.0, 928.0),
    "ANZ": (915.0, 928.0),
    "EU_868": (869.4, 869.65),
}


# ==============================================================================
# Protocol Roles & Backhaul Enums
# ==============================================================================

class MeshtasticRole(str, Enum):
    """Meshtastic device operational roles."""
    CLIENT = "CLIENT"
    CLIENT_BASE = "CLIENT_BASE"
    ROUTER = "ROUTER"
    ROUTER_LATE = "ROUTER_LATE"
    CLIENT_MUTE = "CLIENT_MUTE"


class MeshCoreRole(str, Enum):
    """MeshCore device operational roles."""
    REPEATER = "repeater"
    COMPANION = "companion"


class ReticulumRole(str, Enum):
    """Reticulum Network Stack interface forwarding roles."""
    TRANSPORT = "transport"
    ENDPOINT = "endpoint"


class BackhaulArchitecture(str, Enum):
    """Physical backhaul link topologies between high sites."""
    DIRECT_LORA = "direct_lora"
    DUAL_RADIO_PI_BRIDGE = "dual_radio_pi_bridge"
    MICROWAVE_IP_5_8GHZ = "microwave_ip_5_8ghz"


# ==============================================================================
# Data Models
# ==============================================================================

class AirtimeResult(BaseModel):
    """Detailed timing breakdown for a LoRa transmission per Semtech AN1200.13."""
    payload_bytes: int = Field(..., description="Payload size in bytes")
    sf: int = Field(..., ge=6, le=12, description="Spreading factor (6 to 12)")
    bw_hz: float = Field(..., gt=0.0, description="Bandwidth in Hz")
    cr: int = Field(..., ge=1, le=4, description="Coding rate denominator offset (1=4/5, 4=4/8)")
    symbol_time_ms: float = Field(..., description="Duration of a single LoRa symbol in milliseconds")
    preamble_time_ms: float = Field(..., description="Duration of the preamble in milliseconds")
    payload_time_ms: float = Field(..., description="Duration of the payload in milliseconds")
    total_airtime_ms: float = Field(..., description="Total packet duration on air in milliseconds")
    ldro_enabled: bool = Field(..., description="Whether Low Data Rate Optimization is active")


class ChannelUtilizationForecast(BaseModel):
    """Channel traffic load and unslotted Aloha contention forecast."""
    expected_nodes: int = Field(..., ge=0, description="Active broadcasting nodes within radio coverage")
    adoption_rate: float = Field(..., ge=0.0, description="Estimated population adoption fraction")
    packets_per_node_hour: float = Field(..., ge=0.0, description="Average packets transmitted per node per hour")
    total_airtime_sec_hour: float = Field(..., ge=0.0, description="Cumulative channel on-air seconds per hour")
    channel_utilization_pct: float = Field(..., ge=0.0, description="Duty cycle utilization percentage")
    aloha_collision_prob: float = Field(..., ge=0.0, le=1.0, description="Pure Aloha packet collision probability")
    exceeds_congestion_threshold: bool = Field(..., description="True if utilization exceeds target congestion cap")
    congestion_threshold_pct: float = Field(default=25.0, description="Target maximum acceptable channel utilization")


class NodeRoleRecommendation(BaseModel):
    """Operator guidance on node role, preset, and flood hazard mitigation."""
    site_id: str
    site_name: str
    recommended_role: str
    protocol_family: str
    town_killer_risk: bool = Field(..., description="True if configuration risks broadcast storm or starvation")
    risk_message: str = Field(..., description="Explanation of town-killer hazard or clearance rationale")
    cli_command: str = Field(..., description="Actionable vendor CLI command to configure role")
    coordination_required: bool = Field(..., description="True if role demands regional frequency/site coordination")
    recommended_preset: Optional[str] = Field(default=None, description="Recommended modem preset (e.g. MediumFast)")
    recommended_hop_limit: int = Field(default=3, description="Recommended packet hop limit ceiling")
    reachability_state: Optional[ReachabilityState] = Field(
        default=None,
        description="Resolved directional reachability state when provided or inferred",
    )
    downlink_margin_db: Optional[float] = Field(
        default=None,
        description="Directional tower-to-client downlink fade margin in dB",
    )
    uplink_margin_db: Optional[float] = Field(
        default=None,
        description="Directional client-to-tower uplink fade margin in dB",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Directional asymmetry or operational hazard warnings",
    )


class BackhaulRecommendation(BaseModel):
    """Architecture and RF isolation parameters for linking two summit high sites."""
    source_site_id: str
    target_site_id: str
    distance_km: float
    architecture: BackhaulArchitecture
    recommended_radio_split: Optional[str] = Field(default=None, description="Suggested channel or band isolation")
    required_vertical_isolation_m: float = Field(default=3.0, description="Required vertical antenna separation")
    estimated_isolation_db: float = Field(default=30.0, description="Estimated decoupling isolation in dB")
    notes: List[str] = Field(default_factory=list, description="Engineering deployment guidance")
    reachability_state: Optional[ReachabilityState] = Field(
        default=None,
        description="Resolved directional reachability state for the inter-summit link",
    )
    downlink_margin_db: Optional[float] = Field(
        default=None,
        description="Forward (source -> target) fade margin in dB",
    )
    uplink_margin_db: Optional[float] = Field(
        default=None,
        description="Reverse (target -> source) fade margin in dB",
    )
    asymmetric_mitigation_required: bool = Field(
        default=False,
        description="True if directional link asymmetry or link budget deficit requires mitigation",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Directional asymmetry or link failure warnings",
    )


class ChannelSlotPlan(BaseModel):
    """Deterministic Meshtastic djb2 channel hash and ISM frequency slot plan."""
    channel_name: str
    region_code: str
    bandwidth_khz: float
    num_channels: int
    slot_index: int
    frequency_slot: int
    center_freq_mhz: float
    guard_band_mhz: float
    hash_uint32: int


class HiddenTerminalPair(BaseModel):
    """Hidden-terminal pair collision and capture-effect assessment for a hub node."""
    hub_site_id: str
    site_a_id: str
    site_b_id: str
    rx_a_dbm: float
    rx_b_dbm: float
    sir_db: float
    collision_destructive: bool
    captured_winner: Optional[str] = None


# ==============================================================================
# Pure Computational Functions
# ==============================================================================

def compute_lora_airtime_ms(
    payload_bytes: int,
    sf: int,
    bw_hz: float,
    cr: int = 1,
    preamble: int = 8,
    explicit_header: bool = True,
    crc: bool = True,
) -> AirtimeResult:
    """Calculate LoRa packet time on air in milliseconds following Semtech AN1200.13.

    Symbol duration:
        T_sym = 2^SF / BW

    LDRO (Low Data Rate Optimization):
        Mandated when symbol duration >= 16 ms (0.016 s).

    Preamble duration:
        T_preamble = (N_preamble + 4.25) * T_sym

    Payload symbols:
        N_payload = 8 + max(ceil((8*PL - 4*SF + 28 + 16*CRC - 20*H) / (4*(SF - 2*DE))) * (CR + 4), 0)
        where H=0 for explicit header, 1 for implicit header.
    """
    if sf < 6 or sf > 12:
        raise ValueError(f"Spreading factor must be between 6 and 12, got {sf}")
    if bw_hz <= 0:
        raise ValueError(f"Bandwidth must be positive, got {bw_hz}")
    if cr < 1 or cr > 4:
        raise ValueError(f"Coding rate denominator offset must be 1..4 (for 4/5..4/8), got {cr}")

    t_sym_s = (2 ** sf) / bw_hz
    t_sym_ms = t_sym_s * 1000.0

    # LDRO is required when symbol time >= 16 ms
    ldro_enabled = t_sym_s >= 0.016
    de_val = 1 if ldro_enabled else 0

    # Preamble duration
    preamble_symbols = preamble + 4.25
    preamble_time_ms = preamble_symbols * t_sym_ms

    # Payload calculation
    h_val = 0 if explicit_header else 1
    crc_val = 1 if crc else 0

    numerator = 8 * payload_bytes - 4 * sf + 28 + 16 * crc_val - 20 * h_val
    denominator = 4 * (sf - 2 * de_val)

    if denominator <= 0:
        raise ValueError("Invalid configuration resulting in non-positive symbol divisor")

    num_symbols_term = math.ceil(numerator / denominator) * (cr + 4)
    payload_symbols = 8 + max(0, num_symbols_term)
    payload_time_ms = payload_symbols * t_sym_ms

    total_airtime_ms = preamble_time_ms + payload_time_ms

    return AirtimeResult(
        payload_bytes=payload_bytes,
        sf=sf,
        bw_hz=bw_hz,
        cr=cr,
        symbol_time_ms=round(t_sym_ms, 4),
        preamble_time_ms=round(preamble_time_ms, 4),
        payload_time_ms=round(payload_time_ms, 4),
        total_airtime_ms=round(total_airtime_ms, 4),
        ldro_enabled=ldro_enabled,
    )


def compute_lora_sensitivity_dbm(
    sf: int,
    bw_hz: float,
    nf_db: float = 6.0,
) -> float:
    """Calculate LoRa receiver sensitivity threshold in dBm.

    Formula:
        S = -174 + 10 * log10(BW) + NF + SNR_min(SF)
    where SNR_min(SF) follows standard Semtech SX126x/SX127x specs:
        SF6: -5.0 dB
        SF7: -7.5 dB
        SF8: -10.0 dB
        SF9: -12.5 dB
        SF10: -15.0 dB
        SF11: -17.5 dB
        SF12: -20.0 dB
    """
    if sf < 6 or sf > 12:
        raise ValueError(f"Spreading factor must be between 6 and 12, got {sf}")
    if bw_hz <= 0:
        raise ValueError(f"Bandwidth must be positive, got {bw_hz}")

    # Standard Semtech SNR limit: SNR_min(SF) = -7.5 - 2.5 * (SF - 7)
    snr_min = -7.5 - 2.5 * (sf - 7)
    thermal_noise = -174.0 + 10.0 * math.log10(bw_hz)
    sensitivity = thermal_noise + nf_db + snr_min
    return round(sensitivity, 2)


def compute_antenna_isolation_db(
    vertical_sep_m: float = 0.0,
    horizontal_sep_m: float = 0.0,
    frequency_mhz: float = 915.0,
) -> float:
    """Calculate antenna decoupling isolation in dB based on physical spatial separation.

    Formulas (Land Mobile Radio / ARRL collinear dipole isolation):
        Vertical isolation (dB):   I_v = 28 + 40 * log10(s / lambda)
        Horizontal isolation (dB): I_h = 22 + 20 * log10(d / lambda)
    """
    if vertical_sep_m <= 0.0 and horizontal_sep_m <= 0.0:
        return 0.0

    c = 299792458.0
    wavelength_m = c / (frequency_mhz * 1e6)

    iso_v = 0.0
    if vertical_sep_m > 0.0:
        ratio_v = max(vertical_sep_m / wavelength_m, 0.1)
        iso_v = max(0.0, 28.0 + 40.0 * math.log10(ratio_v))

    iso_h = 0.0
    if horizontal_sep_m > 0.0:
        ratio_h = max(horizontal_sep_m / wavelength_m, 0.1)
        iso_h = max(0.0, 22.0 + 20.0 * math.log10(ratio_h))

    if vertical_sep_m > 0.0 and horizontal_sep_m > 0.0:
        return round(max(iso_v, iso_h), 2)
    elif vertical_sep_m > 0.0:
        return round(iso_v, 2)
    else:
        return round(iso_h, 2)


def forecast_channel_utilization(
    exposed_population: int = 0,
    adoption_rate: float = 0.001,
    packets_per_node_hour: float = 4.0,
    airtime_ms: float = 41.2,
    hop_limit: int = 3,
    threshold_pct: float = 25.0,
    expected_nodes: Optional[int] = None,
) -> ChannelUtilizationForecast:
    """Forecast channel traffic duty cycle and pure Aloha collision probability.

    Total packet transmissions per hour accounts for originator transmission plus
    mesh relays up to hop_limit:
        Transmissions_per_packet = 1 + hop_limit
        Total_transmissions_hr = Nodes * packets_per_node_hour * Transmissions_per_packet
        Utilization = (Total_transmissions_hr * (airtime_ms / 1000)) / 3600
        Aloha P_coll = 1 - e^(-2 * G)
    """
    if expected_nodes is not None:
        nodes = expected_nodes
    else:
        nodes = max(0, int(round(exposed_population * adoption_rate)))

    transmissions_per_packet = 1 + max(0, hop_limit)
    total_tx_hour = nodes * packets_per_node_hour * transmissions_per_packet
    total_airtime_sec_hour = total_tx_hour * (airtime_ms / 1000.0)

    channel_utilization_pct = (total_airtime_sec_hour / 3600.0) * 100.0

    # Offered channel traffic G in Erlangs
    g = total_airtime_sec_hour / 3600.0
    if g <= 0.0:
        aloha_collision_prob = 0.0
    else:
        aloha_collision_prob = min(1.0, max(0.0, 1.0 - math.exp(-2.0 * g)))

    exceeds = channel_utilization_pct > threshold_pct

    return ChannelUtilizationForecast(
        expected_nodes=nodes,
        adoption_rate=adoption_rate,
        packets_per_node_hour=packets_per_node_hour,
        total_airtime_sec_hour=round(total_airtime_sec_hour, 4),
        channel_utilization_pct=round(channel_utilization_pct, 4),
        aloha_collision_prob=round(aloha_collision_prob, 4),
        exceeds_congestion_threshold=exceeds,
        congestion_threshold_pct=threshold_pct,
    )


def _validate_directional_margin(name: str, value: Optional[float]) -> Optional[float]:
    """Validate optional directional fade margin is finite when provided."""
    if value is None:
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be a finite number, got {value}")
    return numeric


def _coerce_reachability_state(value: ReachabilityState | str) -> ReachabilityState:
    """Validate and normalize a ReachabilityState enum or string representation."""
    if isinstance(value, ReachabilityState):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        for member in ReachabilityState:
            if cleaned.lower() == member.value or cleaned.upper() == member.name:
                return member
    raise ValueError(
        f"Invalid reachability_state {value!r}; expected one of {[m.value for m in ReachabilityState]}"
    )


def _resolve_reachability_state(
    reachability_state: Optional[ReachabilityState],
    downlink_margin_db: Optional[float],
    uplink_margin_db: Optional[float],
) -> Optional[ReachabilityState]:
    """Resolve bidirectional ReachabilityState from explicit enum and/or directional margins.

    Returns None when all directional inputs are omitted (preserving legacy symmetric mode).
    """
    if reachability_state is None and downlink_margin_db is None and uplink_margin_db is None:
        return None

    implied: Optional[ReachabilityState] = None
    if downlink_margin_db is not None or uplink_margin_db is not None:
        dl_ok = True if downlink_margin_db is None else (downlink_margin_db >= 0.0)
        ul_ok = True if uplink_margin_db is None else (uplink_margin_db >= 0.0)
        if dl_ok and ul_ok:
            implied = ReachabilityState.TWO_WAY
        elif dl_ok and not ul_ok:
            implied = ReachabilityState.HEAR_ONLY_ALLIGATOR
        elif ul_ok and not dl_ok:
            implied = ReachabilityState.UPLINK_ONLY
        else:
            implied = ReachabilityState.UNREACHABLE

    if reachability_state is None:
        return implied

    explicit = _coerce_reachability_state(reachability_state)
    if explicit == ReachabilityState.TWO_WAY and implied is not None and implied != ReachabilityState.TWO_WAY:
        return implied
    return explicit


def _format_margin_summary(
    downlink_margin_db: Optional[float],
    uplink_margin_db: Optional[float],
) -> str:
    """Format directional margin values for human-readable engineering rationale."""
    parts: List[str] = []
    if downlink_margin_db is not None:
        parts.append(f"downlink={downlink_margin_db:+.1f} dB")
    if uplink_margin_db is not None:
        parts.append(f"uplink={uplink_margin_db:+.1f} dB")
    if not parts:
        return ""
    return f" ({', '.join(parts)})"


def _build_role_asymmetry_hazard(
    state: ReachabilityState,
    downlink_margin_db: Optional[float],
    uplink_margin_db: Optional[float],
) -> str:
    """Generate Town-Killer hazard rationale for asymmetric or unreachable node links."""
    margin_detail = _format_margin_summary(downlink_margin_db, uplink_margin_db)
    if state == ReachabilityState.HEAR_ONLY_ALLIGATOR:
        return (
            f"TOWN_KILLER_RISK: Asymmetric HEAR_ONLY_ALLIGATOR reachability{margin_detail}. "
            "Alligator site transmits strong downlink beacons that clients hear while failing to decode "
            "client uplink packets, causing blackhole routing, hidden-node collisions, and retry storms. "
            "Demoted from repeater/ROUTER role until bandpass cavity filter + LNA or TX power balance restores TWO_WAY closure."
        )
    if state == ReachabilityState.UPLINK_ONLY:
        return (
            f"TOWN_KILLER_RISK: Asymmetric UPLINK_ONLY reachability{margin_detail}. "
            "Site receives client uplinks but fails to close the return downlink path, triggering "
            "unacknowledged client retransmissions and wasted airtime. "
            "Demoted from repeater/ROUTER role until feedline loss, antenna downtilt, or downlink EIRP is remediated."
        )
    return (
        f"TOWN_KILLER_RISK: UNREACHABLE bidirectional link budget{margin_detail}. "
        "Neither downlink nor uplink closes above receiver sensitivity. "
        "Do not promote to repeater/ROUTER role; increase mast height, relocate to higher prominence, "
        "or insert an intermediate relay hop."
    )


def advise_node_role(
    site: SiteCandidate,
    viewshed_area_sq_km: float = 0.0,
    exposed_population: int = 0,
    overlapping_router_count: int = 0,
    protocol_family: str = "Meshtastic",
    requested_role: Optional[str] = None,
    reachability_state: Optional[ReachabilityState] = None,
    downlink_margin_db: Optional[float] = None,
    uplink_margin_db: Optional[float] = None,
) -> NodeRoleRecommendation:
    """Recommend optimal network role and detect Town-Killer flood and asymmetry risks.

    Invariants:
        1. Low-elevation / residential nodes requesting ROUTER role are demoted to CLIENT
           with town_killer_risk = True.
        2. Prominent summit high sites with 0 overlapping routers get ROUTER role (when symmetric/TWO_WAY).
        3. Summit high sites with >= 2 overlapping routers get ROUTER_LATE role with
           town_killer_risk = True to prevent broadcast storm collapse.
        4. Summit high sites are NEVER recommended CLIENT_MUTE.
        5. High load environments (exposed pop >= 20,000 or viewshed >= 500 km^2) recommend
           faster preset MediumFast and lower hop limit (2).
        6. Asymmetric or failed directional links (HEAR_ONLY_ALLIGATOR, UPLINK_ONLY, UNREACHABLE,
           or negative directional margin) trigger town_killer_risk = True, surface hazard warnings,
           and prevent blind promotion to ROUTER/repeater/transport roles.
    """
    dl_margin = _validate_directional_margin("downlink_margin_db", downlink_margin_db)
    ul_margin = _validate_directional_margin("uplink_margin_db", uplink_margin_db)
    resolved_state = _resolve_reachability_state(reachability_state, dl_margin, ul_margin)
    is_directional_hazard = resolved_state in (
        ReachabilityState.HEAR_ONLY_ALLIGATOR,
        ReachabilityState.UPLINK_ONLY,
        ReachabilityState.UNREACHABLE,
    )
    warnings: List[str] = []
    hazard_msg = ""
    if is_directional_hazard and resolved_state is not None:
        hazard_msg = _build_role_asymmetry_hazard(resolved_state, dl_margin, ul_margin)
        warnings.append(hazard_msg)

    family = protocol_family.strip().lower()

    # Identify whether the site is a prominent summit or commercial tower
    name_lower = site.name.lower()
    is_summit_type = site.site_type in (
        SiteType.MOUNTAIN_PEAK,
        SiteType.FIRE_LOOKOUT,
        SiteType.COMMUNICATIONS_TOWER,
    )
    is_high_prominence = site.location.elevation_m >= 300.0 or site.mast_height_m >= 25.0
    has_summit_keyword = any(k in name_lower for k in ("summit", "peak", "mountain", "ridge", "mt.", "mt "))
    is_summit = is_summit_type or is_high_prominence or has_summit_keyword

    # Check for residential / low mast constraints
    is_low_mast = site.mast_height_m < 10.0
    is_residential_context = (
        not is_summit
        or "home" in name_lower
        or "residential" in name_lower
        or site.site_type in (SiteType.BUILDING_ROOFTOP, SiteType.CUSTOM)
    ) and is_low_mast

    # Determine load tier
    is_high_load = exposed_population >= 20000 or viewshed_area_sq_km >= 500.0
    rec_preset = "MediumFast" if is_high_load else "LongFast"
    rec_hop_limit = 2 if is_high_load else 3

    if family in ("meshcore", "mesh_core"):
        if is_summit and not is_residential_context and not is_directional_hazard:
            role = MeshCoreRole.REPEATER.value
            coord = True
            cli = f"meshcore --set-role repeater --node '{site.name}'"
        else:
            role = MeshCoreRole.COMPANION.value
            coord = is_summit and not is_residential_context
            cli = f"meshcore --set-role companion --node '{site.name}'"
        return NodeRoleRecommendation(
            site_id=site.site_id,
            site_name=site.name,
            recommended_role=role,
            protocol_family=protocol_family,
            town_killer_risk=is_directional_hazard,
            risk_message=hazard_msg,
            cli_command=cli,
            coordination_required=coord,
            recommended_preset="default",
            recommended_hop_limit=rec_hop_limit,
            reachability_state=resolved_state,
            downlink_margin_db=dl_margin,
            uplink_margin_db=ul_margin,
            warnings=warnings,
        )

    elif family in ("reticulum", "rns"):
        if is_summit and not is_residential_context and not is_directional_hazard:
            role = ReticulumRole.TRANSPORT.value
            coord = True
            cli = f"rnsd --transport --interface-name '{site.name}'"
        else:
            role = ReticulumRole.ENDPOINT.value
            coord = is_summit and not is_residential_context
            cli = f"rnsd --no-transport --interface-name '{site.name}'"
        return NodeRoleRecommendation(
            site_id=site.site_id,
            site_name=site.name,
            recommended_role=role,
            protocol_family=protocol_family,
            town_killer_risk=is_directional_hazard,
            risk_message=hazard_msg,
            cli_command=cli,
            coordination_required=coord,
            recommended_preset="default",
            recommended_hop_limit=rec_hop_limit,
            reachability_state=resolved_state,
            downlink_margin_db=dl_margin,
            uplink_margin_db=ul_margin,
            warnings=warnings,
        )

    else:
        # Default: Meshtastic
        safe_name = shlex.quote(site.name)
        req_role = requested_role.strip().upper() if requested_role else None
        if req_role == MeshtasticRole.CLIENT_BASE.value:
            # CLIENT_BASE is permitted on rooftops and low masts without Town-Killer ROUTER demotion
            role = MeshtasticRole.CLIENT_BASE.value
            risk = is_directional_hazard
            msg = hazard_msg
            cli = f"meshtastic --set-owner {safe_name} --set device.role CLIENT_BASE"
            coord = False
        elif is_residential_context or (not is_summit):
            # Residential or low mast attempting ROUTER causes town-killer hidden node collisions
            wants_router = req_role in ("ROUTER", "ROUTER_LATE", "ROUTER_CLIENT")
            if wants_router:
                role = MeshtasticRole.CLIENT.value
                risk = True
                res_msg = (
                    "TOWN_KILLER_RISK: Residential or low mast (<10m AGL) node configured as ROUTER "
                    "causes hidden-node packet starvation, unnecessary retransmissions, and ACK storms."
                )
                msg = f"{res_msg} {hazard_msg}".strip() if hazard_msg else res_msg
                cli = f"meshtastic --set-owner {safe_name} --set device.role CLIENT"
                coord = False
            else:
                role = MeshtasticRole.CLIENT.value
                risk = is_directional_hazard
                msg = hazard_msg
                cli = f"meshtastic --set-owner {safe_name} --set device.role CLIENT"
                coord = False
        elif is_directional_hazard:
            # Summit site with asymmetric alligator/one-way or unreachable link: do not blindly promote to ROUTER
            role = MeshtasticRole.CLIENT.value
            risk = True
            msg = hazard_msg
            cli = f"meshtastic --set-owner {safe_name} --set device.role CLIENT"
            coord = True
        else:
            # Active summit repeater
            if overlapping_router_count == 0:
                role = MeshtasticRole.ROUTER.value
                risk = False
                msg = ""
                cli = f"meshtastic --set-owner {safe_name} --set device.role ROUTER"
                coord = True
            elif overlapping_router_count >= 2:
                role = MeshtasticRole.ROUTER_LATE.value
                risk = True
                msg = (
                    f"TOWN_KILLER_RISK: Summit site with {overlapping_router_count} overlapping routers. "
                    "Assigned ROUTER_LATE with randomized back-off to prevent catastrophic packet storms."
                )
                cli = f"meshtastic --set-owner {safe_name} --set device.role ROUTER_LATE"
                coord = True
            else:
                role = MeshtasticRole.ROUTER_LATE.value
                risk = False
                msg = "Secondary summit repeater: assigned ROUTER_LATE to defer to primary repeater."
                cli = f"meshtastic --set-owner {safe_name} --set device.role ROUTER_LATE"
                coord = True

        return NodeRoleRecommendation(
            site_id=site.site_id,
            site_name=site.name,
            recommended_role=role,
            protocol_family=protocol_family,
            town_killer_risk=risk,
            risk_message=msg,
            cli_command=cli,
            coordination_required=coord,
            recommended_preset=rec_preset,
            recommended_hop_limit=rec_hop_limit,
            reachability_state=resolved_state,
            downlink_margin_db=dl_margin,
            uplink_margin_db=ul_margin,
            warnings=warnings,
        )


def recommend_summit_backhaul(
    site_a: SiteCandidate,
    site_b: SiteCandidate,
    distance_km: float,
    line_of_sight: bool,
    channel_utilization_pct: float = 10.0,
    downlink_margin_db: Optional[float] = None,
    uplink_margin_db: Optional[float] = None,
    reachability_state: Optional[ReachabilityState] = None,
) -> BackhaulRecommendation:
    """Recommend point-to-point backhaul topology between summit nodes."""
    dl_margin = _validate_directional_margin("downlink_margin_db", downlink_margin_db)
    ul_margin = _validate_directional_margin("uplink_margin_db", uplink_margin_db)
    resolved_state = _resolve_reachability_state(reachability_state, dl_margin, ul_margin)
    is_asymmetric_or_failed = resolved_state in (
        ReachabilityState.HEAR_ONLY_ALLIGATOR,
        ReachabilityState.UPLINK_ONLY,
        ReachabilityState.UNREACHABLE,
    )

    notes: List[str] = []
    warnings: List[str] = []

    if channel_utilization_pct > 25.0:
        if line_of_sight:
            arch = BackhaulArchitecture.MICROWAVE_IP_5_8GHZ
            split = "5.8GHz IP microwave link + 915MHz client access"
            notes.append(
                f"Severe channel congestion ({channel_utilization_pct:.1f}% > 25% threshold). "
                "Dedicated 5.8 GHz microwave IP link required to isolate backbone traffic from access channel."
            )
            notes.append(f"Clear Line-Of-Sight confirmed over {distance_km:.1f} km link.")
        else:
            arch = BackhaulArchitecture.DUAL_RADIO_PI_BRIDGE
            split = "Dual-radio 915MHz client / 433MHz backhaul bridge"
            notes.append(
                "High congestion but microwave line of sight is obstructed. "
                "Deploy cross-band dual-radio bridge (915 MHz client / 433 MHz transit)."
            )
    elif is_asymmetric_or_failed and resolved_state is not None:
        arch = BackhaulArchitecture.DUAL_RADIO_PI_BRIDGE
        if resolved_state == ReachabilityState.HEAR_ONLY_ALLIGATOR:
            split = "Dedicated directional backhaul bridge + bandpass cavity filter/LNA for uplink recovery"
        elif resolved_state == ReachabilityState.UPLINK_ONLY:
            split = "Dedicated directional backhaul bridge + downlink EIRP/filter remediation"
        else:
            split = "Cross-band / high-gain directional relay bridge (intermediate hop recommended)"
    elif channel_utilization_pct > 15.0 or distance_km > 35.0:
        arch = BackhaulArchitecture.DUAL_RADIO_PI_BRIDGE
        split = "Primary 915MHz access + secondary 915MHz dedicated backbone channel"
        notes.append(
            f"Moderate channel utilization ({channel_utilization_pct:.1f}%). "
            "Deploy dual-radio Raspberry Pi bridge to decouple local repeaters from inter-summit transit."
        )
    else:
        arch = BackhaulArchitecture.DIRECT_LORA
        split = "Single radio shared LoRa channel"
        notes.append(
            f"Low channel utilization ({channel_utilization_pct:.1f}%). Direct LoRa packet routing is viable."
        )

    if resolved_state is not None:
        margin_detail = _format_margin_summary(dl_margin, ul_margin)
        if resolved_state == ReachabilityState.TWO_WAY:
            notes.append(
                f"Bidirectional TWO_WAY reachability verified{margin_detail}."
            )
        elif resolved_state == ReachabilityState.HEAR_ONLY_ALLIGATOR:
            guidance = (
                f"Asymmetric HEAR_ONLY_ALLIGATOR link detected{margin_detail}: forward downlink closes "
                f"({site_a.site_id} -> {site_b.site_id}) while reverse uplink fails. "
                "Avoid naive single-radio DIRECT_LORA; deploy directional Yagi backhaul antenna, "
                "install bandpass cavity filter + LNA on the deaf receiver, and balance TX power."
            )
            notes.append(guidance)
            warnings.append(guidance)
        elif resolved_state == ReachabilityState.UPLINK_ONLY:
            guidance = (
                f"Asymmetric UPLINK_ONLY link detected{margin_detail}: reverse uplink closes "
                f"({site_b.site_id} -> {site_a.site_id}) while forward downlink fails. "
                "Avoid naive single-radio DIRECT_LORA; deploy directional Yagi backhaul bridge, "
                "inspect source feedline/downtilt loss, and add bandpass cavity filter + LNA at the target site."
            )
            notes.append(guidance)
            warnings.append(guidance)
        elif resolved_state == ReachabilityState.UNREACHABLE:
            guidance = (
                f"Bidirectional UNREACHABLE link budget deficit{margin_detail}: neither forward nor reverse "
                "LoRa path closes. Avoid naive DIRECT_LORA; insert an intermediate relay hop, deploy a "
                "high-gain directional / cross-band dual-radio bridge, or transition to dedicated 5.8 GHz IP "
                "microwave backhaul if clear line-of-sight is available."
            )
            notes.append(guidance)
            warnings.append(guidance)

    iso_db = compute_antenna_isolation_db(vertical_sep_m=3.0, horizontal_sep_m=0.0)
    notes.append(
        f"Vertical mast separation of 3.0m provides estimated {iso_db:.1f} dB antenna decoupling isolation."
    )

    return BackhaulRecommendation(
        source_site_id=site_a.site_id,
        target_site_id=site_b.site_id,
        distance_km=distance_km,
        architecture=arch,
        recommended_radio_split=split,
        required_vertical_isolation_m=3.0,
        estimated_isolation_db=round(iso_db, 1),
        notes=notes,
        reachability_state=resolved_state,
        downlink_margin_db=dl_margin,
        uplink_margin_db=ul_margin,
        asymmetric_mitigation_required=is_asymmetric_or_failed,
        warnings=warnings,
    )


def compute_meshtastic_channel_slot(
    channel_name: str = "LongFast",
    region_code: str = "US",
    bandwidth_khz: float = 250.0,
    explicit_channel_num: int = 0,
) -> Result[ChannelSlotPlan]:
    """Compute Meshtastic djb2 channel hash, 1-indexed frequency slot, and center frequency."""
    region_key = region_code.strip().upper()
    if region_key not in _MESHTASTIC_BAND_PLANS or not math.isfinite(bandwidth_khz) or bandwidth_khz <= 0.0:
        return Result.fail(
            code="INVALID_CHANNEL_PARAMS",
            message=f"Invalid channel parameters: region_code={region_code!r}, bandwidth_khz={bandwidth_khz!r}",
        )

    f_start, f_end = _MESHTASTIC_BAND_PLANS[region_key]
    h = 5381
    for b in channel_name.encode("utf-8"):
        h = ((h << 5) + h + b) & 0xFFFFFFFF

    bw_mhz = bandwidth_khz / 1000.0
    num_channels = max(1, int(math.floor((f_end - f_start) / bw_mhz)))
    if explicit_channel_num < 0 or explicit_channel_num > num_channels:
        return Result.fail(
            code="INVALID_CHANNEL_PARAMS",
            message=(
                f"explicit_channel_num ({explicit_channel_num}) must be between 0 and {num_channels} "
                f"for region '{region_key}' at {bandwidth_khz} kHz"
            ),
        )

    slot_index = (explicit_channel_num - 1) if explicit_channel_num > 0 else (h % num_channels)
    frequency_slot = slot_index + 1
    center_freq_mhz = round(f_start + (bandwidth_khz / 2000.0) + slot_index * bw_mhz, 6)
    guard_band_mhz = round((f_end - f_start) - num_channels * bw_mhz, 6)

    return Result.success(
        ChannelSlotPlan(
            channel_name=channel_name,
            region_code=region_key,
            bandwidth_khz=bandwidth_khz,
            num_channels=num_channels,
            slot_index=slot_index,
            frequency_slot=frequency_slot,
            center_freq_mhz=center_freq_mhz,
            guard_band_mhz=guard_band_mhz,
            hash_uint32=h,
        )
    )


def evaluate_hidden_terminal_matrix(
    site_ids: Sequence[str],
    pairwise_rx_dbm: Dict[Tuple[str, str], float],
    rx_sensitivity_dbm: float = -134.0,
    capture_threshold_db: float = 6.0,
) -> List[HiddenTerminalPair]:
    """Identify hidden-terminal pairs relative to each hub and evaluate LoRa capture effect."""
    results: List[HiddenTerminalPair] = []
    for hub in site_ids:
        others = sorted({s for s in site_ids if s != hub})
        for idx, a in enumerate(others):
            for b in others[idx + 1 :]:
                rx_a = pairwise_rx_dbm.get((a, hub), -999.0)
                rx_b = pairwise_rx_dbm.get((b, hub), -999.0)
                if rx_a < rx_sensitivity_dbm or rx_b < rx_sensitivity_dbm:
                    continue
                if max(pairwise_rx_dbm.get((a, b), -999.0), pairwise_rx_dbm.get((b, a), -999.0)) >= rx_sensitivity_dbm:
                    continue
                sir_db = round(abs(rx_a - rx_b), 3)
                collision_destructive = sir_db < capture_threshold_db
                captured_winner = None if collision_destructive else (a if rx_a > rx_b else b)
                results.append(
                    HiddenTerminalPair(
                        hub_site_id=hub,
                        site_a_id=a,
                        site_b_id=b,
                        rx_a_dbm=rx_a,
                        rx_b_dbm=rx_b,
                        sir_db=sir_db,
                        collision_destructive=collision_destructive,
                        captured_winner=captured_winner,
                    )
                )
    return results
