"""Community site archetypes, deployment patterns, and cross-protocol translation engine.

Codifies community-validated engineering best practices across Meshtastic, MeshCore,
Reticulum, and Generic LoRa, preventing naive single-radio broadcast loops on elevated
summits while providing actionable configurations for valley infill and client nodes.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from meshscout.core.contracts import SiteCandidate, SiteType


class SiteArchetype(str, Enum):
    """Canonical community site deployment archetypes."""

    ALPINE_MEGA_SUMMIT = "alpine_mega_summit"
    CIVIC_VALLEY_INFILL = "civic_valley_infill"
    MEMBER_ROOFTOP_BASE = "member_rooftop_base"
    VEHICULAR_MOBILE = "vehicular_mobile"
    HANDHELD_CLIENT = "handheld_client"


class SplitHorizonStrategy(str, Enum):
    """Strategy used to prevent co-channel ping-pong broadcast loops."""

    HARDWARE_DUAL_RADIO = "hardware_dual_radio"
    NATIVE_LAYER3_ROUTING = "native_layer3_routing"
    MICROWAVE_OFFLOAD = "microwave_offload"
    CHANNEL_MASKING = "channel_masking"
    NONE_CLIENT_ONLY = "none_client_only"


class ProtocolRoleMapping(BaseModel):
    """Protocol-specific role, channel, and provisioning parameters for an archetype."""

    protocol_family: str = Field(..., description="Target network protocol (Meshtastic, MeshCore, Reticulum, GenericLoRa)")
    role_name: str = Field(..., description="Exact role identifier in target protocol")
    split_horizon_strategy: SplitHorizonStrategy = Field(..., description="Method used to prevent co-channel echoing")
    recommended_hop_limit: int = Field(default=2, ge=1, le=7, description="Enforced maximum hop ceiling")
    recommended_channels: Dict[str, str] = Field(default_factory=dict, description="Recommended channel and frequency assignments")
    cli_command_template: str = Field(..., description="Command-line syntax to provision this role")
    configuration_notes: List[str] = Field(default_factory=list, description="Authoritative configuration guidance")
    anti_pattern_warnings: List[str] = Field(default_factory=list, description="Strictly prohibited misconfigurations")


class SiteArchetypeSpec(BaseModel):
    """Authoritative community specification for a site deployment archetype."""

    archetype: SiteArchetype = Field(..., description="Archetype identifier")
    label: str = Field(..., description="Human-readable title")
    description: str = Field(..., description="Operational purpose and topological fit")
    eligibility_criteria: Dict[str, Any] = Field(default_factory=dict, description="Conditions classifying a site into this archetype")
    rf_mitigation_requirements: Dict[str, Any] = Field(default_factory=dict, description="Physical RF shielding and isolation standards")
    power_requirements: Dict[str, Any] = Field(default_factory=dict, description="Sub-zero battery and solar sizing recommendations")
    banned_anti_patterns: List[str] = Field(default_factory=list, description="Prohibited deployment anti-patterns")
    protocol_mappings: Dict[str, ProtocolRoleMapping] = Field(default_factory=dict, description="Concrete protocol configurations")


# =============================================================================
# Canonical Community Archetype Catalog
# =============================================================================

COMMUNITY_SITE_ARCHETYPES: Dict[SiteArchetype, SiteArchetypeSpec] = {
    SiteArchetype.ALPINE_MEGA_SUMMIT: SiteArchetypeSpec(
        archetype=SiteArchetype.ALPINE_MEGA_SUMMIT,
        label="Tier 1: Alpine Mega-Summit Backhaul",
        description="High-altitude mountain summits (>800m ASL or >40km optical line-of-sight) overlooking multiple valleys.",
        eligibility_criteria={
            "min_elevation_asl_m": 750.0,
            "min_optical_horizon_km": 40.0,
            "min_exposed_population": 15000,
        },
        rf_mitigation_requirements={
            "cavity_filter_required": True,
            "filter_spec": "902-928 MHz 4-cavity bandpass (>45 dB rejection @ 880 MHz)",
            "min_vertical_separation_m": 3.0,
            "min_antenna_isolation_db": 65.0,
            "coaxial_standard": "LDF4-50A Heliax or LMR-400 double-shielded",
        },
        power_requirements={
            "recommended_chemistry": "LTO (Lithium Titanate)",
            "subzero_charging_floor_c": -30.0,
            "min_panel_watts": 50.0,
            "recommended_tilt_deg": 60.0,
            "snow_shedding_mandate": True,
        },
        banned_anti_patterns=[
            "Single-radio co-channel public repeater (causes statewide channel collapse via co-channel ping-pong loops)",
            "Default hop limit >= 3 (causes multi-state ALOHA contention)",
            "LiFePO4 battery banks without active heating pads (leads to winter charge lockout)",
            "Unfiltered receiver directly co-located with high-power FM/TV or cellular emitters",
        ],
        protocol_mappings={
            "Meshtastic": ProtocolRoleMapping(
                protocol_family="Meshtastic",
                role_name="ROUTER_CLIENT (Dual-Radio Bridge)",
                split_horizon_strategy=SplitHorizonStrategy.HARDWARE_DUAL_RADIO,
                recommended_hop_limit=2,
                recommended_channels={
                    "radio_ingress_valley": "915.000 MHz (Public Client Access)",
                    "radio_egress_spine": "906.875 MHz (Dedicated Backbone Inter-Tie)",
                },
                cli_command_template="meshtastic --set lora.region US --set lora.hop_limit 2 --set device.role ROUTER_CLIENT",
                configuration_notes=[
                    "Deploy Raspberry Pi Zero 2W or CM4 bridging two distinct LoRa transceivers.",
                    "Radio A listens on 915.000 MHz; Radio B transmits across summits on 906.875 MHz.",
                    "Enforce split-horizon: never repeat an incoming packet back out on the ingress channel.",
                    "Maintain 3.0m vertical antenna separation on the mast for >65 dB isolation.",
                ],
                anti_pattern_warnings=[
                    "Do NOT configure device.role=REPEATER on public 915.000 MHz. It will flood the entire region.",
                ],
            ),
            "MeshCore": ProtocolRoleMapping(
                protocol_family="MeshCore",
                role_name="repeater (managed coordination)",
                split_horizon_strategy=SplitHorizonStrategy.NATIVE_LAYER3_ROUTING,
                recommended_hop_limit=3,
                recommended_channels={
                    "spinal_backbone": "915.000 MHz (BW 125 kHz, SF10, CR 4/5)",
                },
                cli_command_template='meshcore-cli repeater configure --freq 915.0 --bw 125.0 --sf 10 --role repeater --hop-limit 3 --coord-mode managed',
                configuration_notes=[
                    "MeshCore uses directed unicast and managed packet pacing, preventing flood collapse.",
                    "Operate in packet-forwarding repeater mode with strict duty cycle cap (<10%).",
                ],
                anti_pattern_warnings=[
                    "Do NOT disable rate limiting or flood broadcast beacons.",
                ],
            ),
            "Reticulum": ProtocolRoleMapping(
                protocol_family="Reticulum",
                role_name="rnsd_dual_interface_router",
                split_horizon_strategy=SplitHorizonStrategy.NATIVE_LAYER3_ROUTING,
                recommended_hop_limit=4,
                recommended_channels={
                    "interface_valley_access": "RNodeInterface @ 915.000 MHz (BW 125 kHz, SF8)",
                    "interface_spinal_backbone": "RNodeInterface @ 906.875 MHz (BW 125 kHz, SF11)",
                },
                cli_command_template="rnsd --service",
                configuration_notes=[
                    "Reticulum's rnsd provides native multi-interface Layer 3 destination-hash routing.",
                    "Zero broadcast ping-pong loops: split-horizon and path discovery are enforced by default.",
                ],
                anti_pattern_warnings=[
                    "Do NOT bridge interfaces at Layer 2; maintain cryptographic Layer 3 routing.",
                ],
            ),
            "GenericLoRa": ProtocolRoleMapping(
                protocol_family="GenericLoRa",
                role_name="split_channel_transceiver",
                split_horizon_strategy=SplitHorizonStrategy.HARDWARE_DUAL_RADIO,
                recommended_hop_limit=2,
                recommended_channels={
                    "rx_frequency": "915.000 MHz",
                    "tx_frequency": "906.875 MHz",
                },
                cli_command_template="lora-bridge --rx-freq 915.0 --tx-freq 906.875",
                configuration_notes=[
                    "Hardware frequency split is mandatory when running generic packet forwarding.",
                ],
                anti_pattern_warnings=[
                    "Never operate single-frequency half-duplex repeating from high mountain peaks.",
                ],
            ),
        },
    ),
    SiteArchetype.CIVIC_VALLEY_INFILL: SiteArchetypeSpec(
        archetype=SiteArchetype.CIVIC_VALLEY_INFILL,
        label="Tier 2: Civic Valley Infill & Micro-Repeater",
        description="Municipal water tanks, town halls, emergency towers, and silos (15–35m AGL) illuminating shadowed river valley floors.",
        eligibility_criteria={
            "max_elevation_asl_m": 750.0,
            "min_mast_height_m": 15.0,
            "target_zone": "Valley floor, downtown basin, or river trench",
        },
        rf_mitigation_requirements={
            "cavity_filter_required": False,
            "antenna_recommendation": "Collinear 3-5 dBi omnidirectional or sector with electrical downtilt",
            "downtilt_recommended_deg": 2.0,
        },
        power_requirements={
            "recommended_chemistry": "LiFePO4 with BMS low-temp cutoff or grid AC + UPS",
            "min_panel_watts": 30.0,
            "recommended_tilt_deg": 50.0,
        },
        banned_anti_patterns=[
            "High-gain horizontal pattern (>8 dBi) that overshoots the immediate valley streets",
            "Placing repeaters on mountain slopes that cannot see the downtown business district",
        ],
        protocol_mappings={
            "Meshtastic": ProtocolRoleMapping(
                protocol_family="Meshtastic",
                role_name="ROUTER_CLIENT",
                split_horizon_strategy=SplitHorizonStrategy.CHANNEL_MASKING,
                recommended_hop_limit=2,
                recommended_channels={"access": "915.000 MHz LongFast"},
                cli_command_template="meshtastic --set lora.region US --set lora.hop_limit 2 --set device.role ROUTER_CLIENT",
                configuration_notes=[
                    "Downtilted antenna illuminates local street canyons and feeds upwards to the mountain spine.",
                ],
                anti_pattern_warnings=[],
            ),
            "MeshCore": ProtocolRoleMapping(
                protocol_family="MeshCore",
                role_name="local_repeater",
                split_horizon_strategy=SplitHorizonStrategy.NATIVE_LAYER3_ROUTING,
                recommended_hop_limit=2,
                recommended_channels={"access": "915.000 MHz (BW 125 kHz)"},
                cli_command_template='meshcore-cli repeater configure --freq 915.0 --bw 125.0 --sf 10 --role repeater',
                configuration_notes=["Acts as an ingress feeder into the statewide spinal ring."],
                anti_pattern_warnings=[],
            ),
            "Reticulum": ProtocolRoleMapping(
                protocol_family="Reticulum",
                role_name="rnode_infill_router",
                split_horizon_strategy=SplitHorizonStrategy.NATIVE_LAYER3_ROUTING,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz (BW 125 kHz, SF8)"},
                cli_command_template="rnsd --service",
                configuration_notes=["Bridges local handhelds into regional backbone links."],
                anti_pattern_warnings=[],
            ),
            "GenericLoRa": ProtocolRoleMapping(
                protocol_family="GenericLoRa",
                role_name="infill_digipeater",
                split_horizon_strategy=SplitHorizonStrategy.CHANNEL_MASKING,
                recommended_hop_limit=2,
                recommended_channels={"access": "915.000 MHz"},
                cli_command_template="lora-repeater --freq 915.0",
                configuration_notes=["Local packet forwarding."],
                anti_pattern_warnings=[],
            ),
        },
    ),
    SiteArchetype.MEMBER_ROOFTOP_BASE: SiteArchetypeSpec(
        archetype=SiteArchetype.MEMBER_ROOFTOP_BASE,
        label="Tier 3: Community Member Rooftop Base",
        description="Residential chimney, mast, or pole installation (3–10m AGL) providing reliable household coverage.",
        eligibility_criteria={
            "max_mast_height_m": 12.0,
            "installation_type": "Residential or small commercial roof",
        },
        rf_mitigation_requirements={
            "cavity_filter_required": False,
            "antenna_recommendation": "3 to 5.8 dBi collinear fiberglass omni on chimney mount",
        },
        power_requirements={
            "recommended_chemistry": "USB mains power with internal 18650/LiPo backup",
        },
        banned_anti_patterns=[
            "Configuring residential base stations as ROUTER in dense neighborhoods (destroys local airtime)",
        ],
        protocol_mappings={
            "Meshtastic": ProtocolRoleMapping(
                protocol_family="Meshtastic",
                role_name="CLIENT (or CLIENT_MUTE)",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz LongFast"},
                cli_command_template="meshtastic --set lora.region US --set device.role CLIENT",
                configuration_notes=["Keeps channel clean while offering solid home coverage."],
                anti_pattern_warnings=["Do NOT set role to ROUTER unless in an isolated area with zero coverage."],
            ),
            "MeshCore": ProtocolRoleMapping(
                protocol_family="MeshCore",
                role_name="client",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz"},
                cli_command_template='meshcore-cli client configure --freq 915.0 --bw 125.0',
                configuration_notes=["Standard residential client."],
                anti_pattern_warnings=[],
            ),
            "Reticulum": ProtocolRoleMapping(
                protocol_family="Reticulum",
                role_name="nomadnet_node",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz"},
                cli_command_template="nomadnet",
                configuration_notes=["Household communications hub."],
                anti_pattern_warnings=[],
            ),
            "GenericLoRa": ProtocolRoleMapping(
                protocol_family="GenericLoRa",
                role_name="client_terminal",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz"},
                cli_command_template="lora-client",
                configuration_notes=["Household client."],
                anti_pattern_warnings=[],
            ),
        },
    ),
    SiteArchetype.VEHICULAR_MOBILE: SiteArchetypeSpec(
        archetype=SiteArchetype.VEHICULAR_MOBILE,
        label="Tier 4: Vehicular Mobile Node",
        description="Vehicle roof-mounted transceiver with magnetic-mount antenna for mobile operations and emergency transit.",
        eligibility_criteria={
            "installation_type": "Vehicle or mobile platform",
        },
        rf_mitigation_requirements={
            "cavity_filter_required": False,
            "antenna_recommendation": "1/4-wave roof magnetic mount with ground plane",
        },
        power_requirements={
            "recommended_chemistry": "12V vehicle electrical system with buck converter",
        },
        banned_anti_patterns=[
            "High-frequency stationary GPS beaconing that floods the mesh while parked",
        ],
        protocol_mappings={
            "Meshtastic": ProtocolRoleMapping(
                protocol_family="Meshtastic",
                role_name="TRACKER (Smart Position)",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz LongFast"},
                cli_command_template="meshtastic --set device.role TRACKER --set position.gps_update_interval 120 --set position.broadcast_smart_minimum_distance 100",
                configuration_notes=["Smart beaconing broadcasts only when the vehicle is in motion."],
                anti_pattern_warnings=["Do NOT beacon every 30 seconds when stationary."],
            ),
            "MeshCore": ProtocolRoleMapping(
                protocol_family="MeshCore",
                role_name="tracker",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz"},
                cli_command_template='meshcore-cli tracker configure --freq 915.0',
                configuration_notes=["Mobile telemetry terminal."],
                anti_pattern_warnings=[],
            ),
            "Reticulum": ProtocolRoleMapping(
                protocol_family="Reticulum",
                role_name="sideband_mobile",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz"},
                cli_command_template="sideband",
                configuration_notes=["Mobile messaging client."],
                anti_pattern_warnings=[],
            ),
            "GenericLoRa": ProtocolRoleMapping(
                protocol_family="GenericLoRa",
                role_name="aprs_tracker",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz"},
                cli_command_template="lora-tracker",
                configuration_notes=["Mobile beacon."],
                anti_pattern_warnings=[],
            ),
        },
    ),
    SiteArchetype.HANDHELD_CLIENT: SiteArchetypeSpec(
        archetype=SiteArchetype.HANDHELD_CLIENT,
        label="Tier 5: Handheld / Pedestrian Client",
        description="Pocket-portable device paired to smartphone over Bluetooth Low Energy (BLE).",
        eligibility_criteria={
            "installation_type": "Pocket or pedestrian handheld",
        },
        rf_mitigation_requirements={
            "cavity_filter_required": False,
            "antenna_recommendation": "Tuned stubby or flexible whip (0-2 dBi)",
        },
        power_requirements={
            "recommended_chemistry": "Single 18650 or LiPo cell with aggressive sleep cycling",
        },
        banned_anti_patterns=[
            "Enabling repeater or router mode on battery-operated pocket devices",
        ],
        protocol_mappings={
            "Meshtastic": ProtocolRoleMapping(
                protocol_family="Meshtastic",
                role_name="CLIENT",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz LongFast"},
                cli_command_template="meshtastic --set device.role CLIENT --set power.is_power_saving true",
                configuration_notes=["Optimized for long handheld battery life."],
                anti_pattern_warnings=[],
            ),
            "MeshCore": ProtocolRoleMapping(
                protocol_family="MeshCore",
                role_name="client",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz"},
                cli_command_template='meshcore-cli client configure --freq 915.0',
                configuration_notes=["Standard pedestrian terminal."],
                anti_pattern_warnings=[],
            ),
            "Reticulum": ProtocolRoleMapping(
                protocol_family="Reticulum",
                role_name="sideband_client",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz"},
                cli_command_template="sideband",
                configuration_notes=["Handheld messaging terminal."],
                anti_pattern_warnings=[],
            ),
            "GenericLoRa": ProtocolRoleMapping(
                protocol_family="GenericLoRa",
                role_name="handheld_terminal",
                split_horizon_strategy=SplitHorizonStrategy.NONE_CLIENT_ONLY,
                recommended_hop_limit=3,
                recommended_channels={"access": "915.000 MHz"},
                cli_command_template="lora-terminal",
                configuration_notes=["Pedestrian terminal."],
                anti_pattern_warnings=[],
            ),
        },
    ),
}


def classify_site_archetype(
    site: SiteCandidate,
    exposed_population: int = 0,
) -> SiteArchetype:
    """Classify a SiteCandidate into its canonical community deployment archetype."""
    elev = site.location.elevation_m
    mast = site.mast_height_m
    stype = site.site_type

    # 1. Mountain Peak or massive elevation -> Alpine Mega-Summit
    if stype == SiteType.MOUNTAIN_PEAK or elev >= 750.0 or (elev >= 500.0 and mast >= 30.0) or exposed_population >= 20000:
        return SiteArchetype.ALPINE_MEGA_SUMMIT

    # 2. Municipal infrastructure, water tanks, communications towers -> Civic Valley Infill
    if stype in (SiteType.WATER_TOWER, SiteType.COMMUNICATIONS_TOWER, SiteType.SILO) or mast >= 15.0:
        return SiteArchetype.CIVIC_VALLEY_INFILL

    # 3. Rooftop base
    if stype in (SiteType.BUILDING_ROOFTOP, SiteType.CUSTOM) or mast >= 3.0:
        return SiteArchetype.MEMBER_ROOFTOP_BASE

    # Default fallback
    return SiteArchetype.CIVIC_VALLEY_INFILL


def get_archetype_recommendation(
    archetype: SiteArchetype,
    protocol_family: str = "Meshtastic",
) -> Dict[str, Any]:
    """Retrieve the authoritative community recommendation for an archetype and protocol."""
    spec = COMMUNITY_SITE_ARCHETYPES.get(archetype)
    if not spec:
        spec = COMMUNITY_SITE_ARCHETYPES[SiteArchetype.CIVIC_VALLEY_INFILL]

    # Normalize protocol family
    norm_family = "Meshtastic"
    low = protocol_family.strip().lower()
    if "meshcore" in low:
        norm_family = "MeshCore"
    elif "reticulum" in low:
        norm_family = "Reticulum"
    elif "generic" in low or "lora" in low:
        norm_family = "GenericLoRa"

    proto_map = spec.protocol_mappings.get(norm_family, spec.protocol_mappings["Meshtastic"])

    return {
        "archetype": spec.archetype.value,
        "label": spec.label,
        "description": spec.description,
        "rf_mitigation_requirements": spec.rf_mitigation_requirements,
        "power_requirements": spec.power_requirements,
        "banned_anti_patterns": spec.banned_anti_patterns,
        "selected_protocol": norm_family,
        "role_mapping": proto_map.model_dump(),
    }
