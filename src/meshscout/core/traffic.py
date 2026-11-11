"""Pure-Python LoRa airtime forecaster, population traffic exposure, and role advisor."""

from __future__ import annotations

import math
import shlex
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from meshscout.core.contracts import SiteCandidate, SiteType


# ==============================================================================
# Protocol Roles & Backhaul Enums
# ==============================================================================

class MeshtasticRole(str, Enum):
    """Meshtastic device operational roles."""
    CLIENT = "CLIENT"
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


def advise_node_role(
    site: SiteCandidate,
    viewshed_area_sq_km: float = 0.0,
    exposed_population: int = 0,
    overlapping_router_count: int = 0,
    protocol_family: str = "Meshtastic",
    requested_role: Optional[str] = None,
) -> NodeRoleRecommendation:
    """Recommend optimal network role and detect Town-Killer flood risks.

    Invariants:
        1. Low-elevation / residential nodes requesting ROUTER role are demoted to CLIENT
           with town_killer_risk = True.
        2. Prominent summit high sites with 0 overlapping routers get ROUTER role.
        3. Summit high sites with >= 2 overlapping routers get ROUTER_LATE role with
           town_killer_risk = True to prevent broadcast storm collapse.
        4. Summit high sites are NEVER recommended CLIENT_MUTE.
        5. High load environments (exposed pop >= 20,000 or viewshed >= 500 km^2) recommend
           faster preset MediumFast and lower hop limit (2).
    """
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
        if is_summit and not is_residential_context:
            role = MeshCoreRole.REPEATER.value
            coord = True
            cli = f"meshcore --set-role repeater --node '{site.name}'"
        else:
            role = MeshCoreRole.COMPANION.value
            coord = False
            cli = f"meshcore --set-role companion --node '{site.name}'"
        return NodeRoleRecommendation(
            site_id=site.site_id,
            site_name=site.name,
            recommended_role=role,
            protocol_family=protocol_family,
            town_killer_risk=False,
            risk_message="",
            cli_command=cli,
            coordination_required=coord,
            recommended_preset="default",
            recommended_hop_limit=rec_hop_limit,
        )

    elif family in ("reticulum", "rns"):
        if is_summit and not is_residential_context:
            role = ReticulumRole.TRANSPORT.value
            coord = True
            cli = f"rnsd --transport --interface-name '{site.name}'"
        else:
            role = ReticulumRole.ENDPOINT.value
            coord = False
            cli = f"rnsd --no-transport --interface-name '{site.name}'"
        return NodeRoleRecommendation(
            site_id=site.site_id,
            site_name=site.name,
            recommended_role=role,
            protocol_family=protocol_family,
            town_killer_risk=False,
            risk_message="",
            cli_command=cli,
            coordination_required=coord,
            recommended_preset="default",
            recommended_hop_limit=rec_hop_limit,
        )

    else:
        # Default: Meshtastic
        safe_name = shlex.quote(site.name)
        if is_residential_context or (not is_summit):
            # Residential or low mast attempting ROUTER causes town-killer hidden node collisions
            wants_router = requested_role in ("ROUTER", "ROUTER_LATE", "ROUTER_CLIENT")
            if wants_router:
                role = MeshtasticRole.CLIENT.value
                risk = True
                msg = (
                    "TOWN_KILLER_RISK: Residential or low mast (<10m AGL) node configured as ROUTER "
                    "causes hidden-node packet starvation, unnecessary retransmissions, and ACK storms."
                )
                cli = f"meshtastic --set-owner {safe_name} --set device.role CLIENT"
                coord = False
            else:
                role = MeshtasticRole.CLIENT.value
                risk = False
                msg = ""
                cli = f"meshtastic --set-owner {safe_name} --set device.role CLIENT"
                coord = False
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
        )


def recommend_summit_backhaul(
    site_a: SiteCandidate,
    site_b: SiteCandidate,
    distance_km: float,
    line_of_sight: bool,
    channel_utilization_pct: float = 10.0,
) -> BackhaulRecommendation:
    """Recommend point-to-point backhaul topology between summit nodes."""
    notes: List[str] = []

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
    )
