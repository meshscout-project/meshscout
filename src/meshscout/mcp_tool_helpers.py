"""Helper handlers for regulatory EIRP and regional data-pack MCP tools.

Implements pure domain resolution and payload formatting (Functional Core) alongside
local registry/pack adapter orchestration (Imperative Shell) for the `advise_eirp`
and `list_region_packs` MCP tools. Placed outside `meshscout.core` to preserve the
Day-0 core AST capability invariant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from meshscout import commands
from meshscout.adapters.pack_client import PackClient
from meshscout.core.packs import list_installed_packs as core_list_installed_packs
from meshscout.core.regulatory import RegulatoryDomain
from meshscout.core.tower_registry import UnifiedTowerRegistry

DEFAULT_PACK_ATTRIBUTIONS: Dict[str, str] = {
    "fcc_asr": "FCC Antenna Structure Registration (Public Domain)",
    "ised_sms": "ISED TAFL (Open Government Licence - Canada 2.0)",
    "civic_osm": "© OpenStreetMap contributors (ODbL 1.0)",
}


def resolve_regulatory_domain(
    domain: Optional[str] = None,
    region: Optional[str] = None,
) -> RegulatoryDomain:
    """Resolve regulatory domain from explicit enum/code string or region identifier."""
    return commands.resolve_regulatory_domain(domain=domain, region=region)


def build_region_packs_payload(
    installed: List[Dict[str, Any]],
    available: List[Dict[str, Any]],
    manifest_error: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble standardized MCP response dictionary for regional data packs."""
    return {
        "ok": True,
        "installed": installed,
        "installed_count": len(installed),
        "available": available,
        "manifest_error": manifest_error,
        "attributions": dict(DEFAULT_PACK_ATTRIBUTIONS),
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
    return commands.advise_eirp(
        tx_power_dbm=tx_power_dbm,
        antenna_gain_dbi=antenna_gain_dbi,
        cable_loss_db=cable_loss_db,
        frequency_mhz=frequency_mhz,
        domain=domain,
        region=region,
    )


def list_region_packs(
    db_path: Optional[str] = None,
    include_available: bool = False,
) -> Dict[str, Any]:
    """List installed and available regional tower data packs with provenance and licensing metadata."""
    with UnifiedTowerRegistry(db_path=db_path) as reg:
        installed = core_list_installed_packs(reg)

    available: List[Dict[str, Any]] = []
    manifest_error: Optional[str] = None
    if include_available:
        try:
            client = PackClient()
            avail_res = client.list_available_packs()
            if avail_res.ok and avail_res.value is not None:
                available = [p.model_dump(mode="json") for p in avail_res.value]
            else:
                manifest_error = (
                    avail_res.error.message
                    if avail_res.error
                    else "Failed to retrieve manifest"
                )
        except (OSError, ValueError, RuntimeError) as exc:
            manifest_error = str(exc)

    return build_region_packs_payload(
        installed=installed,
        available=available,
        manifest_error=manifest_error,
    )


__all__ = [
    "DEFAULT_PACK_ATTRIBUTIONS",
    "advise_eirp",
    "build_region_packs_payload",
    "list_region_packs",
    "resolve_regulatory_domain",
]
