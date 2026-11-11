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
    warnings: List[str] = Field(default_factory=list, description="Advisory compliance warnings")
    disclaimer: str = Field(default=ADVISORY_DISCLAIMER, description="Statutory and engineering disclaimer")


CANADIAN_PROVINCE_CODES = {
    "QC", "ON", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU",
}


def detect_regulatory_domain(region_code: Optional[str] = None) -> RegulatoryDomain:
    """Detect regulatory domain based on regional or national identifier.

    If the region identifier matches Canada or any of the 13 Canadian provinces/territories,
    returns RegulatoryDomain.CA_ISED_RSS247; otherwise defaults to RegulatoryDomain.US_FCC_PART15.
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

    return RegulatoryDomain.US_FCC_PART15


def advise_eirp(
    tx_power_dbm: float,
    antenna_gain_dbi: float,
    cable_loss_db: float = 0.0,
    frequency_mhz: float = 915.0,
    domain: RegulatoryDomain = RegulatoryDomain.US_FCC_PART15,
) -> EirpAdvisoryReport:
    """Evaluate conducted power and EIRP against FCC Part 15.247 / ISED RSS-247 rules.

    Checks:
    - Net conducted power = tx_power_dbm - cable_loss_db.
    - EIRP = tx_power_dbm + antenna_gain_dbi - cable_loss_db.
    - Conducted ceiling is 30.0 dBm. If tx_power_dbm > 30.0, issues a warning.
    - Omnidirectional point-to-multipoint EIRP ceiling is 36.0 dBm.
      Antenna gain exceeding 6.0 dBi mandates a dB-for-dB reduction in conducted power:
        excess_gain = max(0.0, antenna_gain_dbi - 6.0)
        allowed_tx_conducted = 30.0 - excess_gain
        recommended_max_tx_dbm = min(30.0, allowed_tx_conducted)
      If eirp_dbm > 36.0 or antenna_gain_dbi > 6.0, issues a warning explaining
      the required dB-for-dB reduction.
    - Frequency check: validates 902.0 MHz <= frequency_mhz <= 928.0 MHz.
    - Line A and Line C cross-border coordination rules are explicitly excluded.
    """
    conducted_power_dbm = round(tx_power_dbm - cable_loss_db, 2)
    eirp_dbm = round(tx_power_dbm + antenna_gain_dbi - cable_loss_db, 2)

    excess_gain = max(0.0, antenna_gain_dbi - 6.0)
    allowed_tx_conducted = 30.0 - excess_gain
    recommended_max_tx_dbm = round(min(30.0, allowed_tx_conducted), 2)

    warnings: List[str] = []

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

    return EirpAdvisoryReport(
        domain=domain,
        tx_power_dbm=float(tx_power_dbm),
        antenna_gain_dbi=float(antenna_gain_dbi),
        cable_loss_db=float(cable_loss_db),
        frequency_mhz=float(frequency_mhz),
        conducted_power_dbm=conducted_power_dbm,
        eirp_dbm=eirp_dbm,
        conducted_limit_dbm=30.0,
        eirp_limit_dbm=36.0,
        recommended_max_tx_dbm=recommended_max_tx_dbm,
        warnings=warnings,
        disclaimer=ADVISORY_DISCLAIMER,
    )
