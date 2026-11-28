"""Advisory EIRP and regulatory reference checks for MeshScout.

Implements advisory RF compliance evaluations under FCC Part 15.247
(United States) and ISED RSS-247 (Canada) for 902-928 MHz ISM band
deployments.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

ADVISORY_DISCLAIMER: str = (
    "This calculation is advisory only and does not constitute formal legal "
    "or regulatory certification. Single-channel LoRa transmissions may not "
    "qualify for full DTS (Digital Transmission System) or FHSS "
    "(Frequency Hopping Spread Spectrum) power allowances under FCC Part 15.247 "
    "or ISED RSS-247. Equipment operators and deployment engineers must "
    "confirm equipment compliance and operational authorization with the "
    "applicable local regulatory authority."
)


class RegulatoryDomain(str, Enum):
    """Supported regulatory domains for ISM band operations."""

    US_FCC_PART15 = "US_FCC_PART15"
    CA_ISED_RSS247 = "CA_ISED_RSS247"
    EU_ETSI_EN300220 = "EU_ETSI_EN300220"
    AU_ACMA_LIPD = "AU_ACMA_LIPD"


class TransmissionMode(str, Enum):
    """Deployment antenna topology for regulatory power limit checks."""

    OMNI_P2MP = "omni_p2mp"
    DIRECTIONAL_P2P = "directional_p2p"


class EirpAdvisoryReport(BaseModel):
    """Advisory RF emission and regulatory compliance evaluation."""

    domain: RegulatoryDomain = Field(..., description="Active regulatory domain")
    tx_power_dbm: float = Field(..., description="Transmitter conducted output power in dBm")
    antenna_gain_dbi: float = Field(..., description="Antenna gain in dBi")
    cable_loss_db: float = Field(default=0.0, description="Coaxial/connector insertion loss in dB")
    frequency_mhz: float = Field(default=915.0, description="Operating frequency in MHz")
    conducted_power_dbm: float = Field(..., description="Net conducted power delivered to antenna (dBm)")
    eirp_dbm: float = Field(..., description="Effective Isotropic Radiated Power in dBm")
    conducted_limit_dbm: float = Field(default=30.0, description="Maximum conducted power ceiling (dBm)")
    eirp_limit_dbm: float = Field(default=36.0, description="Maximum omnidirectional P2MP EIRP ceiling (dBm)")
    recommended_max_tx_dbm: float = Field(..., description="Recommended maximum conducted Tx power (dBm)")
    transmission_mode: TransmissionMode = Field(
        default=TransmissionMode.OMNI_P2MP,
        description="Deployment antenna topology mode",
    )
    bandwidth_khz: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Optional channel bandwidth in kHz for DTS compliance checks",
    )
    warnings: List[str] = Field(default_factory=list, description="Advisory compliance warnings")
    disclaimer: str = Field(default=ADVISORY_DISCLAIMER, description="Statutory and engineering disclaimer")


CANADIAN_PROVINCE_CODES = {
    "QC", "ON", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU",
}


EU_REGION_TOKENS = {"EU", "EU_868", "ETSI"}
AU_REGION_TOKENS = {"AU", "ANZ", "ACMA"}


def detect_regulatory_domain(region_code: Optional[str] = None) -> RegulatoryDomain:
    """Detect regulatory domain based on regional or national identifier.

    Maps Canadian identifiers to CA_ISED_RSS247, explicit EU/ETSI tokens to
    EU_ETSI_EN300220, explicit AU/ANZ/ACMA tokens to AU_ACMA_LIPD, and
    defaults to US_FCC_PART15.
    """
    if not region_code:
        return RegulatoryDomain.US_FCC_PART15

    cleaned = region_code.strip().upper()
    if (
        cleaned in CANADIAN_PROVINCE_CODES
        or cleaned.removeprefix("CA_").removeprefix("CA-") in CANADIAN_PROVINCE_CODES
        or cleaned.startswith("CA_")
        or cleaned.startswith("CA-")
        or cleaned == "CA"
        or "CANADA" in cleaned
    ):
        return RegulatoryDomain.CA_ISED_RSS247

    if cleaned in EU_REGION_TOKENS:
        return RegulatoryDomain.EU_ETSI_EN300220

    if cleaned in AU_REGION_TOKENS:
        return RegulatoryDomain.AU_ACMA_LIPD

    return RegulatoryDomain.US_FCC_PART15


def _append_ceiling_warnings(
    warnings: List[str],
    tx_power_dbm: float,
    eirp_dbm: float,
    conducted_limit_dbm: float,
    eirp_limit_dbm: float,
    recommended_max_tx_dbm: float,
    standard_label: str,
) -> None:
    """Append conducted and EIRP ceiling warnings for ETSI EN 300 220 and ACMA LIPD."""
    if tx_power_dbm > conducted_limit_dbm:
        warnings.append(
            f"Transmitter power ({tx_power_dbm:.2f} dBm) exceeds the {conducted_limit_dbm:.2f} dBm "
            f"conducted reference ceiling under {standard_label}."
        )
    if eirp_dbm > eirp_limit_dbm:
        warnings.append(
            f"EIRP ({eirp_dbm:.2f} dBm) exceeds the {eirp_limit_dbm:.2f} dBm radiated ceiling "
            f"under {standard_label}. Maximum recommended transmitter power is "
            f"{recommended_max_tx_dbm:.2f} dBm."
        )


def advise_eirp(
    tx_power_dbm: float,
    antenna_gain_dbi: float,
    cable_loss_db: float = 0.0,
    frequency_mhz: float = 915.0,
    domain: RegulatoryDomain = RegulatoryDomain.US_FCC_PART15,
    transmission_mode: TransmissionMode = TransmissionMode.OMNI_P2MP,
    bandwidth_khz: Optional[float] = None,
) -> EirpAdvisoryReport:
    """Evaluate conducted power and EIRP against regional ISM regulatory rules.

    Supports FCC Part 15.247 (US), ISED RSS-247 (Canada), ETSI EN 300 220 (EU),
    and ACMA LIPD Class Licence (Australia). Line A and Line C cross-border
    coordination rules are explicitly excluded.
    """
    conducted_power_dbm = round(tx_power_dbm - cable_loss_db, 2)
    eirp_dbm = round(tx_power_dbm + antenna_gain_dbi - cable_loss_db, 2)
    warnings: List[str] = []

    if domain in (RegulatoryDomain.US_FCC_PART15, RegulatoryDomain.CA_ISED_RSS247):
        conducted_limit_dbm = 30.0
        eirp_limit_dbm = 36.0
        excess_gain = max(0.0, antenna_gain_dbi - 6.0)
        allowed_tx_conducted = 30.0 - excess_gain
        recommended_max_tx_dbm = round(min(30.0, allowed_tx_conducted), 2)

        # 1. Conducted power ceiling check (30 dBm / 1 W)
        if tx_power_dbm > 30.0:
            warnings.append(
                f"Transmitter power ({tx_power_dbm:.2f} dBm) exceeds the maximum conducted "
                "limit of 30.00 dBm (1.0 W) for intentional radiators under FCC Part 15.247 / ISED RSS-247."
            )

        # 2. Antenna gain and omnidirectional P2MP EIRP ceiling check (36 dBm / 4 W)
        if eirp_dbm > 36.0 or antenna_gain_dbi > 6.0:
            warnings.append(
                f"Antenna gain ({antenna_gain_dbi:.2f} dBi) exceeds the 6.00 dBi omnidirectional threshold "
                f"or EIRP ({eirp_dbm:.2f} dBm) exceeds the 36.00 dBm ceiling. Under FCC Part 15.247(b)(4) "
                "and ISED RSS-247 5.4(d), point-to-multipoint systems require a 1 dB reduction in maximum "
                f"conducted output power for every 1 dB antenna gain exceeds 6 dBi. "
                f"Maximum recommended transmitter power is {recommended_max_tx_dbm:.2f} dBm."
            )

        # 3. Frequency band check (902 - 928 MHz ISM)
        if frequency_mhz < 902.0 or frequency_mhz > 928.0:
            warnings.append(
                f"Operating frequency ({frequency_mhz:.2f} MHz) falls outside the 902.0 - 928.0 MHz "
                "ISM band governed by FCC Part 15.247 and ISED RSS-247."
            )

        # 4. Fixed P2P 3:1 allowance scope notice in 902 - 928 MHz
        if (
            transmission_mode == TransmissionMode.DIRECTIONAL_P2P
            and antenna_gain_dbi > 6.0
            and 902.0 <= frequency_mhz <= 928.0
        ):
            warnings.append(
                "47 CFR 15.247(c)(1)(i) and ISED RSS-247 5.4(e) restrict the 3:1 fixed point-to-point "
                "antenna gain allowance to 2400-2483.5 MHz; 902-928 MHz deployments remain subject to "
                "the 1:1 conducted power reduction above 6.00 dBi."
            )

        # 5. DTS minimum 500 kHz 6 dB bandwidth advisory
        if bandwidth_khz is not None and bandwidth_khz < 500.0:
            warnings.append(
                f"Channel bandwidth ({bandwidth_khz:.1f} kHz) is below the 500.0 kHz minimum 6 dB "
                "bandwidth required for DTS operation under FCC Part 15.247(a)(2) and ISED RSS-247 5.2(a)."
            )

    elif domain == RegulatoryDomain.EU_ETSI_EN300220:
        if 869.4 <= frequency_mhz <= 869.65:
            conducted_limit_dbm = 29.15
            eirp_limit_dbm = 29.15
        elif 868.0 <= frequency_mhz <= 868.6:
            conducted_limit_dbm = 16.15
            eirp_limit_dbm = 16.15
        else:
            conducted_limit_dbm = 16.15
            eirp_limit_dbm = 16.15
            warnings.append(
                f"Operating frequency ({frequency_mhz:.2f} MHz) falls outside the ETSI EN 300 220 "
                "EU868 sub-bands (868.0 - 868.6 MHz and 869.4 - 869.65 MHz); clamping limits to 16.15 dBm."
            )

        recommended_max_tx_dbm = round(
            min(conducted_limit_dbm, eirp_limit_dbm - antenna_gain_dbi + cable_loss_db),
            2,
        )
        _append_ceiling_warnings(
            warnings,
            tx_power_dbm,
            eirp_dbm,
            conducted_limit_dbm,
            eirp_limit_dbm,
            recommended_max_tx_dbm,
            "ETSI EN 300 220",
        )

    elif domain == RegulatoryDomain.AU_ACMA_LIPD:
        conducted_limit_dbm = 30.0
        eirp_limit_dbm = 30.0
        recommended_max_tx_dbm = round(
            min(30.0, 30.0 - antenna_gain_dbi + cable_loss_db),
            2,
        )
        _append_ceiling_warnings(
            warnings,
            tx_power_dbm,
            eirp_dbm,
            conducted_limit_dbm,
            eirp_limit_dbm,
            recommended_max_tx_dbm,
            "ACMA LIPD",
        )
        if frequency_mhz < 915.0 or frequency_mhz > 928.0:
            warnings.append(
                f"Operating frequency ({frequency_mhz:.2f} MHz) falls outside the 915.0 - 928.0 MHz "
                "band governed by the ACMA LIPD Class Licence."
            )

    else:
        raise ValueError(f"Unsupported regulatory domain: {domain}")

    return EirpAdvisoryReport(
        domain=domain,
        tx_power_dbm=float(tx_power_dbm),
        antenna_gain_dbi=float(antenna_gain_dbi),
        cable_loss_db=float(cable_loss_db),
        frequency_mhz=float(frequency_mhz),
        conducted_power_dbm=conducted_power_dbm,
        eirp_dbm=eirp_dbm,
        conducted_limit_dbm=conducted_limit_dbm,
        eirp_limit_dbm=eirp_limit_dbm,
        recommended_max_tx_dbm=recommended_max_tx_dbm,
        transmission_mode=transmission_mode,
        bandwidth_khz=bandwidth_khz,
        warnings=warnings,
        disclaimer=ADVISORY_DISCLAIMER,
    )
