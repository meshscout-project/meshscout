"""Radio hardware presets, protocol profiles (Meshtastic & MeshCore), and seasonal foliage catalogs.

Provides authoritative equipment and RF profiles for Vermont & New England mesh network planning,
bridging user-friendly presets to the core Longley-Rice ITM `RadioConfig` contract.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Tuple
from pydantic import BaseModel, Field

from meshscout.core.contracts import AntennaPattern, RadiationClass, RadioConfig, Result, SiteRadioProfile, SiteType


class HardwarePreset(BaseModel):
    """Curated transceiver, feedline, and antenna hardware profile."""

    preset_id: str = Field(..., min_length=1, description="Unique identifier for the hardware preset")
    label: str = Field(..., min_length=1, description="Human-readable hardware configuration label")
    description: str = Field(..., min_length=1, description="Detailed description of transceiver and antenna setup")
    tx_power_dbm: float = Field(..., description="Transmit power in dBm")
    antenna_gain_dbi: float = Field(..., description="Antenna isotropic gain in dBi")
    cable_loss_db: float = Field(..., ge=0.0, description="Coaxial feedline and connector loss in dB")
    typical_power_draw_mw: float = Field(..., gt=0.0, description="Typical continuous/average power draw in milliwatts")
    solar_friendly: bool = Field(..., description="Whether suitable for small off-grid winter solar deployments")


class ProtocolProfile(BaseModel):
    """LoRa modulation and receiver sensitivity profile for Meshtastic, MeshCore, Reticulum, or GenericLoRa."""

    profile_id: str = Field(..., min_length=1, description="Unique identifier for the protocol profile")
    network_family: Literal["Meshtastic", "MeshCore", "Reticulum", "GenericLoRa"] = Field(
        ..., description="Mesh protocol ecosystem ('Meshtastic', 'MeshCore', 'Reticulum', or 'GenericLoRa')"
    )
    label: str = Field(..., min_length=1, description="Human-readable modulation preset name")
    frequency_mhz: float = Field(default=915.0, gt=0.0, description="US915 ISM center frequency in MHz")
    bandwidth_khz: float = Field(..., gt=0.0, description="LoRa channel bandwidth in kHz")
    spreading_factor: int = Field(..., ge=5, le=12, description="LoRa spreading factor (SF5-SF12)")
    rx_sensitivity_dbm: float = Field(..., description="Receiver sensitivity floor in dBm")


class SeasonalFoliageProfile(BaseModel):
    """Seasonal deciduous canopy RF attenuation profile for northern New England."""

    season_id: Literal["WINTER_LEAF_OFF", "SUMMER_LEAF_ON"] = Field(
        ..., description="Unique seasonal identifier"
    )
    label: str = Field(..., min_length=1, description="Human-readable season label")
    canopy_loss_db: float = Field(..., ge=0.0, description="Total path foliage attenuation penalty in dB")
    description: str = Field(..., min_length=1, description="RF propagation impact of seasonal canopy state")


class ClientEnvironmentProfile(BaseModel):
    """Client endpoint clutter attenuation and typical operating height profile."""

    env_id: str = Field(..., min_length=1, description="Unique client environment profile identifier")
    label: str = Field(..., min_length=1, description="Human-readable operating environment label")
    clutter_loss_db: float = Field(..., ge=0.0, description="Local client clutter/body/enclosure loss in dB")
    default_agl_m: float = Field(..., ge=0.0, description="Default antenna height above ground in meters")
    description: str = Field(..., min_length=1, description="RF propagation impact of client operating environment")


HARDWARE_PRESETS: Dict[str, HardwarePreset] = {
    "RAK4631_SOLAR": HardwarePreset(
        preset_id="RAK4631_SOLAR",
        label="RAK4631 WisBlock Solar Node + Rokland 5.8dBi fiberglass omni",
        description="nRF52840 + SX1262 ultra-low-power solar mountain/tree repeater with 5.8dBi outdoor fiberglass omni.",
        tx_power_dbm=22.0,
        antenna_gain_dbi=5.8,
        cable_loss_db=0.5,
        typical_power_draw_mw=45.0,
        solar_friendly=True,
    ),
    "STATION_G2_BACKBONE": HardwarePreset(
        preset_id="STATION_G2_BACKBONE",
        label="B&Q Station G2 High-Power Repeater + 8dBi Omni + Cavity Filter",
        description="High-power commercial-grade repeater with 8dBi collinear omni and bandpass cavity filter.",
        tx_power_dbm=28.0,
        antenna_gain_dbi=8.0,
        cable_loss_db=1.2,
        typical_power_draw_mw=1800.0,
        solar_friendly=False,
    ),
    "HELTEC_V3_HOME": HardwarePreset(
        preset_id="HELTEC_V3_HOME",
        label="Heltec V3 Indoor/Window Node + 3dBi Whip",
        description="ESP32-S3 + SX1262 desktop or window-sill residential node with compact 3dBi rubber duck whip.",
        tx_power_dbm=22.0,
        antenna_gain_dbi=3.0,
        cable_loss_db=0.3,
        typical_power_draw_mw=450.0,
        solar_friendly=False,
    ),
    "SENSECAP_T1000E": HardwarePreset(
        preset_id="SENSECAP_T1000E",
        label="Seeed SenseCAP T1000-E Pocket Tracker",
        description="Credit-card sized IP65 pocket/hiker tracker with internal PCB antenna (nRF52840 + LR1110).",
        tx_power_dbm=20.0,
        antenna_gain_dbi=1.5,
        cable_loss_db=0.0,
        typical_power_draw_mw=25.0,
        solar_friendly=True,
    ),
    "STATION_G3_REPEATER": HardwarePreset(
        preset_id="STATION_G3_REPEATER",
        label="Station G3 High-Power Repeater + 8dBi Omni + Cavity",
        description="High-power commercial repeater with front-end cavity filter and FEM PA.",
        tx_power_dbm=30.0,
        antenna_gain_dbi=8.0,
        cable_loss_db=1.0,
        typical_power_draw_mw=1900.0,
        solar_friendly=False,
    ),
    "HELTEC_V4_PA": HardwarePreset(
        preset_id="HELTEC_V4_PA",
        label="Heltec V4 + PA (28dBm) + 5dBi Omni",
        description="ESP32-S3 LoRa gateway node with integrated power amplifier.",
        tx_power_dbm=28.0,
        antenna_gain_dbi=5.0,
        cable_loss_db=0.5,
        typical_power_draw_mw=620.0,
        solar_friendly=False,
    ),
    "HELTEC_T114_PORTABLE": HardwarePreset(
        preset_id="HELTEC_T114_PORTABLE",
        label="Heltec Mesh Node T114 Portable (nRF52840)",
        description="Low-draw nRF52840 portable tracker/relay with 2dBi stubby antenna.",
        tx_power_dbm=22.0,
        antenna_gain_dbi=2.0,
        cable_loss_db=0.2,
        typical_power_draw_mw=42.0,
        solar_friendly=True,
    ),
    "SEEED_XIAO_NRF52_SOLAR": HardwarePreset(
        preset_id="SEEED_XIAO_NRF52_SOLAR",
        label="Seeed XIAO nRF52840 + SX1262 Micro Solar",
        description="Ultra-low quiescent micro-repeater for compact canopy/ridge packs.",
        tx_power_dbm=22.0,
        antenna_gain_dbi=5.8,
        cable_loss_db=0.5,
        typical_power_draw_mw=38.0,
        solar_friendly=True,
    ),
}


PROTOCOL_PROFILES: Dict[str, ProtocolProfile] = {
    "MESHTASTIC_LONGFAST": ProtocolProfile(
        profile_id="MESHTASTIC_LONGFAST",
        network_family="Meshtastic",
        label="Meshtastic LongFast",
        frequency_mhz=915.0,
        bandwidth_khz=250.0,
        spreading_factor=11,
        rx_sensitivity_dbm=-134.0,
    ),
    "MESHTASTIC_MEDIUMFAST": ProtocolProfile(
        profile_id="MESHTASTIC_MEDIUMFAST",
        network_family="Meshtastic",
        label="Meshtastic MediumFast",
        frequency_mhz=915.0,
        bandwidth_khz=250.0,
        spreading_factor=9,
        rx_sensitivity_dbm=-129.0,
    ),
    "MESHCORE_NARROW": ProtocolProfile(
        profile_id="MESHCORE_NARROW",
        network_family="MeshCore",
        label="MeshCore Narrow Repeater Backbone",
        frequency_mhz=915.0,
        bandwidth_khz=62.5,
        spreading_factor=11,
        rx_sensitivity_dbm=-139.0,
    ),
    "MESHCORE_STANDARD": ProtocolProfile(
        profile_id="MESHCORE_STANDARD",
        network_family="MeshCore",
        label="MeshCore Standard",
        frequency_mhz=915.0,
        bandwidth_khz=125.0,
        spreading_factor=10,
        rx_sensitivity_dbm=-135.0,
    ),
    "RETICULUM_RNODE_LONG": ProtocolProfile(
        profile_id="RETICULUM_RNODE_LONG",
        network_family="Reticulum",
        label="Reticulum RNode Long-Range",
        frequency_mhz=915.0,
        bandwidth_khz=125.0,
        spreading_factor=11,
        rx_sensitivity_dbm=-134.5,
    ),
    "RETICULUM_RNODE_FAST": ProtocolProfile(
        profile_id="RETICULUM_RNODE_FAST",
        network_family="Reticulum",
        label="Reticulum RNode High-Speed",
        frequency_mhz=915.0,
        bandwidth_khz=250.0,
        spreading_factor=8,
        rx_sensitivity_dbm=-124.0,
    ),
    "GENERIC_LORA_WIDE_500": ProtocolProfile(
        profile_id="GENERIC_LORA_WIDE_500",
        network_family="GenericLoRa",
        label="Generic LoRa 500 kHz High-Rate Trunk",
        frequency_mhz=915.0,
        bandwidth_khz=500.0,
        spreading_factor=7,
        rx_sensitivity_dbm=-120.5,
    ),
    "GENERIC_LORA_LONG_62K5": ProtocolProfile(
        profile_id="GENERIC_LORA_LONG_62K5",
        network_family="GenericLoRa",
        label="Generic LoRa 62.5 kHz Long-Range",
        frequency_mhz=915.0,
        bandwidth_khz=62.5,
        spreading_factor=12,
        rx_sensitivity_dbm=-141.5,
    ),
}

MESHTASTIC_BAND_PLANS: Dict[str, Tuple[float, float]] = {
    "US": (902.0, 928.0),
    "CA": (902.0, 928.0),
    "ANZ": (915.0, 928.0),
    "EU_868": (869.4, 869.65),
}


SEASONAL_PROFILES: Dict[str, SeasonalFoliageProfile] = {
    "WINTER_LEAF_OFF": SeasonalFoliageProfile(
        season_id="WINTER_LEAF_OFF",
        label="Bare Hardwoods / Winter",
        canopy_loss_db=0.0,
        description="Dormant winter hardwood canopy (November-April); minimal 915 MHz foliage absorption.",
    ),
    "SUMMER_LEAF_ON": SeasonalFoliageProfile(
        season_id="SUMMER_LEAF_ON",
        label="Full Deciduous Canopy / Summer",
        canopy_loss_db=8.5,
        description="Dense wet-leaf northern hardwood canopy (May-October); ~8.5 dB additional 915 MHz path attenuation.",
    ),
}

SEASON_ALIASES: Dict[str, str] = {
    "SUMMER_FOLIAGE": "SUMMER_LEAF_ON",
    "WINTER_DORMANT": "WINTER_LEAF_OFF",
}

CLIENT_ENVIRONMENT_PROFILES: Dict[str, ClientEnvironmentProfile] = {
    "OUTDOOR_CLEAR": ClientEnvironmentProfile(
        env_id="OUTDOOR_CLEAR",
        label="Outdoor Clear Sightline",
        clutter_loss_db=0.0,
        default_agl_m=1.5,
        description="Handheld or tripod-mounted client node in open outdoor terrain without body or cabin shielding.",
    ),
    "BODY_WORN_POCKET": ClientEnvironmentProfile(
        env_id="BODY_WORN_POCKET",
        label="Body-Worn / Pocket Tracker",
        clutter_loss_db=4.0,
        default_agl_m=1.2,
        description="Pocket or pack-strap portable tracker subject to human-body dielectric absorption at 915 MHz.",
    ),
    "VEHICLE_CABIN": ClientEnvironmentProfile(
        env_id="VEHICLE_CABIN",
        label="Inside Vehicle Cabin",
        clutter_loss_db=6.0,
        default_agl_m=1.5,
        description="Dashboard or console-mounted radio attenuated by automotive pillars and metallic window tint.",
    ),
    "INDOOR_WINDOW": ClientEnvironmentProfile(
        env_id="INDOOR_WINDOW",
        label="Indoor Window Sill",
        clutter_loss_db=8.0,
        default_agl_m=2.0,
        description="Residential window-sill node attenuated by framing, insect screens, and low-E glazing.",
    ),
    "ROOFTOP_MAST": ClientEnvironmentProfile(
        env_id="ROOFTOP_MAST",
        label="Exterior Rooftop / Eave Mast",
        clutter_loss_db=0.0,
        default_agl_m=6.0,
        description="Fixed outdoor rooftop or gable mast installation clear of near-field residential clutter.",
    ),
}

SITE_NOISE_PENALTIES_DB: Dict[SiteType, float] = {
    SiteType.COMMUNICATIONS_TOWER: 6.0,
    SiteType.MOUNTAIN_PEAK: 3.0,
    SiteType.WATER_TOWER: 1.0,
    SiteType.SILO: 1.0,
    SiteType.FIRE_LOOKOUT: 1.0,
    SiteType.BUILDING_ROOFTOP: 1.0,
    SiteType.RESEARCH_TOWER: 1.0,
    SiteType.CUSTOM: 1.0,
}

ANTENNA_PATTERN_PRESETS: Dict[str, AntennaPattern] = {
    "OMNI_360": AntennaPattern(
        radiation_class=RadiationClass.OMNI,
        azimuth_deg=0.0,
        h_beamwidth_deg=360.0,
        v_beamwidth_deg=None,
        downtilt_deg=0.0,
        front_to_back_db=0.0,
    ),
    "SECTOR_VALLEY_120": AntennaPattern(
        radiation_class=RadiationClass.SECTOR,
        azimuth_deg=0.0,
        h_beamwidth_deg=120.0,
        v_beamwidth_deg=18.0,
        downtilt_deg=2.0,
        front_to_back_db=18.0,
    ),
    "SECTOR_CORRIDOR_90": AntennaPattern(
        radiation_class=RadiationClass.SECTOR,
        azimuth_deg=0.0,
        h_beamwidth_deg=90.0,
        v_beamwidth_deg=16.0,
        downtilt_deg=1.5,
        front_to_back_db=20.0,
    ),
    "YAGI_BACKHAUL_65": AntennaPattern(
        radiation_class=RadiationClass.DIRECTIONAL,
        azimuth_deg=0.0,
        h_beamwidth_deg=65.0,
        v_beamwidth_deg=55.0,
        downtilt_deg=0.0,
        front_to_back_db=16.0,
    ),
    "YAGI_HIGHGAIN_38": AntennaPattern(
        radiation_class=RadiationClass.DIRECTIONAL,
        azimuth_deg=0.0,
        h_beamwidth_deg=38.0,
        v_beamwidth_deg=34.0,
        downtilt_deg=0.0,
        front_to_back_db=22.0,
    ),
}


def get_site_noise_penalty_db(site_type: SiteType) -> float:
    """Return local RF noise floor degradation penalty in dB for a high-site category."""
    return SITE_NOISE_PENALTIES_DB.get(site_type, 1.0)


def build_radio_config(
    hardware_id: str = "RAK4631_SOLAR",
    protocol_id: str = "MESHTASTIC_LONGFAST",
    season_id: str = "WINTER_LEAF_OFF",
    antenna_preset_id: Optional[str] = None,
    azimuth_deg: float = 0.0,
    downtilt_deg: Optional[float] = None,
) -> Result[RadioConfig]:
    """Build a unified `RadioConfig` from hardware, protocol, seasonal, and optional antenna presets."""
    hw_key = hardware_id.strip().upper()
    if hw_key not in HARDWARE_PRESETS:
        return Result.fail(
            code="UNKNOWN_HARDWARE_PRESET",
            message=f"Unknown hardware preset '{hardware_id}'. Available: {sorted(HARDWARE_PRESETS.keys())}",
        )

    proto_key = protocol_id.strip().upper()
    if proto_key not in PROTOCOL_PROFILES:
        return Result.fail(
            code="UNKNOWN_PROTOCOL_PROFILE",
            message=f"Unknown protocol profile '{protocol_id}'. Available: {sorted(PROTOCOL_PROFILES.keys())}",
        )

    raw_season_key = season_id.strip().upper()
    season_key = SEASON_ALIASES.get(raw_season_key, raw_season_key)
    if season_key not in SEASONAL_PROFILES:
        return Result.fail(
            code="UNKNOWN_SEASONAL_PROFILE",
            message=f"Unknown seasonal profile '{season_id}'. Available: {sorted(SEASONAL_PROFILES.keys())}",
        )

    antenna_pattern: Optional[AntennaPattern] = None
    if antenna_preset_id is not None:
        antenna_key = antenna_preset_id.strip().upper()
        if antenna_key not in ANTENNA_PATTERN_PRESETS:
            return Result.fail(
                code="UNKNOWN_ANTENNA_PRESET",
                message=f"Unknown antenna preset '{antenna_preset_id}'. Available: {sorted(ANTENNA_PATTERN_PRESETS.keys())}",
            )
        base = ANTENNA_PATTERN_PRESETS[antenna_key]
        updates: Dict[str, Any] = {"azimuth_deg": float(azimuth_deg) % 360.0}
        if downtilt_deg is not None:
            updates["downtilt_deg"] = float(downtilt_deg)
        antenna_pattern = base.model_copy(update=updates)

    hw = HARDWARE_PRESETS[hw_key]
    proto = PROTOCOL_PROFILES[proto_key]
    season = SEASONAL_PROFILES[season_key]

    return Result.success(
        RadioConfig(
            frequency_mhz=proto.frequency_mhz,
            tx_power_dbm=hw.tx_power_dbm,
            rx_sensitivity_dbm=proto.rx_sensitivity_dbm,
            antenna_gain_dbi=hw.antenna_gain_dbi,
            cable_loss_db=hw.cable_loss_db,
            environmental_clutter_db=season.canopy_loss_db,
            antenna_pattern=antenna_pattern,
        )
    )


def resolve_site_radio_profile(
    site_type: SiteType,
    hardware_id: str = "RAK4631_SOLAR",
    protocol_id: str = "MESHTASTIC_LONGFAST",
    season_id: str = "SUMMER_FOLIAGE",
    noise_override_db: Optional[float] = None,
) -> Result[SiteRadioProfile]:
    """Resolve a high-site `SiteRadioProfile` combining radio presets and site RF noise penalty."""
    if noise_override_db is not None and noise_override_db < 0.0:
        return Result.fail(
            code="INVALID_NOISE_OVERRIDE",
            message=f"noise_override_db must be non-negative, got {noise_override_db}",
        )

    radio_res = build_radio_config(
        hardware_id=hardware_id,
        protocol_id=protocol_id,
        season_id=season_id,
    )
    if not radio_res.ok or radio_res.value is None:
        err = radio_res.error
        return Result.fail(
            code=err.code if err is not None else "RADIO_CONFIG_ERROR",
            message=err.message if err is not None else "Failed to resolve radio config.",
            details=err.details if err is not None else None,
        )

    noise_db = (
        float(noise_override_db)
        if noise_override_db is not None
        else get_site_noise_penalty_db(site_type)
    )
    return Result.success(
        SiteRadioProfile(
            radio=radio_res.value,
            noise_penalty_db=noise_db,
            hardware_preset=hardware_id.strip().upper(),
        )
    )


def list_all_presets() -> Dict[str, Any]:
    """Return a JSON-serializable dictionary of all hardware, protocol, seasonal, antenna, and client presets."""
    return {
        "hardware_presets": {k: v.model_dump() for k, v in HARDWARE_PRESETS.items()},
        "protocol_profiles": {k: v.model_dump() for k, v in PROTOCOL_PROFILES.items()},
        "seasonal_profiles": {k: v.model_dump() for k, v in SEASONAL_PROFILES.items()},
        "antenna_pattern_presets": {
            k: v.model_dump() for k, v in ANTENNA_PATTERN_PRESETS.items()
        },
        "client_environment_profiles": {
            k: v.model_dump() for k, v in CLIENT_ENVIRONMENT_PROFILES.items()
        },
        "site_noise_penalties_db": {
            k.value: v for k, v in SITE_NOISE_PENALTIES_DB.items()
        },
        "meshtastic_band_plans": dict(MESHTASTIC_BAND_PLANS),
    }
