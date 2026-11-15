"""FastAPI /api/v1 sub-router for attribution, North American regions, and regulatory EIRP."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from meshscout.adapters.regions import list_north_america_regions
from meshscout.adapters.source_fetch import load_source_catalog
from meshscout.core.regulatory import (
    RegulatoryDomain,
    advise_eirp as core_advise_eirp,
    detect_regulatory_domain,
)


def build_attribution_payload(sources: Dict[str, Any]) -> Dict[str, Any]:
    """Construct the JSON payload for dataset licensing and attribution metadata."""
    return {
        "ok": True,
        "sources": sources,
        "count": len(sources),
    }


def build_north_america_regions_payload(regions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Construct the JSON payload for the North American regional catalog."""
    return {
        "ok": True,
        "count": len(regions),
        "regions": regions,
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


def evaluate_regulatory_eirp_payload(
    tx_power_dbm: float = 20.0,
    antenna_gain_dbi: float = 3.0,
    cable_loss_db: float = 0.0,
    frequency_mhz: float = 915.0,
    domain: Optional[str] = None,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate conducted power and EIRP compliance and return a JSON-ready payload."""
    reg_domain = resolve_regulatory_domain(domain=domain, region=region)
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


def build_regulatory_router() -> APIRouter:
    """Create the stateless /api/v1 regulatory, region catalog, and attribution APIRouter."""
    sub_router = APIRouter()

    @sub_router.get("/api/v1/attribution")
    def get_attribution_endpoint() -> Dict[str, Any]:
        """Return dataset licensing and attribution metadata from sources.json."""
        sources = load_source_catalog()
        return build_attribution_payload(sources)

    @sub_router.get("/api/v1/regions/north-america")
    def get_north_america_regions_endpoint(
        country: Optional[str] = Query(
            default=None,
            description="Optional country filter ('US' or 'CA')",
        ),
    ) -> Dict[str, Any]:
        """List regional states, provinces, and territories across North America."""
        regions = list_north_america_regions(country=country)
        return build_north_america_regions_payload(regions)

    @sub_router.get("/api/v1/regulatory/eirp")
    def get_regulatory_eirp_endpoint(
        tx_power_dbm: float = Query(
            default=20.0,
            description="Transmitter conducted power in dBm",
        ),
        antenna_gain_dbi: float = Query(
            default=3.0,
            description="Antenna gain in dBi",
        ),
        cable_loss_db: float = Query(
            default=0.0,
            description="Cable/connector loss in dB",
        ),
        frequency_mhz: float = Query(
            default=915.0,
            description="Operating frequency in MHz",
        ),
        domain: Optional[str] = Query(
            default=None,
            description="Regulatory domain (US_FCC_PART15 or CA_ISED_RSS247)",
        ),
        region: Optional[str] = Query(
            default=None,
            description="Region code (e.g. VT, CA_QC) for domain detection",
        ),
    ) -> Dict[str, Any]:
        """Evaluate conducted power and EIRP compliance under FCC Part 15.247 / ISED RSS-247 rules."""
        return evaluate_regulatory_eirp_payload(
            tx_power_dbm=tx_power_dbm,
            antenna_gain_dbi=antenna_gain_dbi,
            cable_loss_db=cable_loss_db,
            frequency_mhz=frequency_mhz,
            domain=domain,
            region=region,
        )

    return sub_router


router: APIRouter = build_regulatory_router()

__all__ = [
    "build_attribution_payload",
    "build_north_america_regions_payload",
    "build_regulatory_router",
    "evaluate_regulatory_eirp_payload",
    "resolve_regulatory_domain",
    "router",
]
