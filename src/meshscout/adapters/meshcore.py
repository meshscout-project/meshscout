"""MeshCore and Reticulum identity announcement telemetry adapter for MeshScout.

Parses Reticulum Network Stack (RNS) and MeshCore node announcements, normalizes
signal telemetry, geodetic coordinates, and identity hashes into unified TelemetryNode
representations for persistent caching and spatial workbench visualization.
Zero runtime dependencies beyond pydantic>=2.0.0 and standard library.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from meshscout.core.contracts import Coordinate
from meshscout.adapters.telemetry_cache import TelemetryNode


class MeshCoreAnnounce(BaseModel):
    """Normalized Reticulum Network Stack / MeshCore node announcement."""

    model_config = ConfigDict(extra="ignore")

    destination_hash: str = Field(
        ...,
        min_length=16,
        description="16-byte hex hash of the Reticulum identity",
    )
    name: str = Field(..., min_length=1, description="Broadcast display name or node handle")
    interface: str = Field(
        default="LoRaInterface",
        description="RNS transport interface (e.g. LoRaInterface, AutoInterface, TCPClientInterface)",
    )
    hops: int = Field(default=0, ge=0, description="Observed network hop count from announcing peer")
    coordinate: Optional[Coordinate] = Field(
        default=None, description="Optional geodetic coordinate advertised in announce"
    )
    snr_db: Optional[float] = Field(default=None, description="Observed SNR in dB at ingestion interface")
    rssi_dbm: Optional[float] = Field(default=None, description="Observed RSSI in dBm at ingestion interface")
    timestamp_iso: Optional[str] = Field(
        default=None, description="ISO 8601 timestamp string of the announce event"
    )

    @field_validator("destination_hash")
    @classmethod
    def validate_destination_hash(cls, v: str) -> str:
        """Validate destination hash is a valid hexadecimal string of at least 16 hex characters."""
        clean = v.strip().lower()
        if clean.startswith("0x"):
            clean = clean[2:]
        if len(clean) < 16:
            raise ValueError("destination_hash must be at least 16 hexadecimal characters")
        try:
            int(clean, 16)
        except ValueError as err:
            raise ValueError("destination_hash must contain valid hexadecimal characters") from err
        return clean

    @model_validator(mode="before")
    @classmethod
    def assemble_coordinate(cls, data: Any) -> Any:
        """Allow flat lat, lon, elevation_m in dictionary inputs to construct coordinate."""
        if isinstance(data, dict):
            if data.get("coordinate") is None and "lat" in data and "lon" in data:
                if data["lat"] is not None and data["lon"] is not None:
                    data = dict(data)
                    data["coordinate"] = Coordinate(
                        lat=float(data["lat"]),
                        lon=float(data["lon"]),
                        elevation_m=float(data.get("elevation_m", 0.0) or 0.0),
                    )
        return data


def parse_meshcore_announces(
    data_or_text: Union[str, Dict[str, Any], List[Any]],
    default_channel: str = "MeshCore-LoRa",
) -> List[TelemetryNode]:
    """Parse Reticulum and MeshCore announcement payloads into standardized TelemetryNodes.

    Handles JSON strings, single announcement dictionaries, or lists of announcement objects.
    Validates destination hashes and geodetic coordinates, skipping any announcement records
    without valid geographic coordinates.

    Args:
        data_or_text: Raw JSON payload string, announcement dictionary, or list of announces.
        default_channel: Default telemetry channel name to assign if unspecified.

    Returns:
        List of normalized TelemetryNode objects.
    """
    if isinstance(data_or_text, str):
        try:
            parsed = json.loads(data_or_text)
        except json.JSONDecodeError:
            return []
    elif isinstance(data_or_text, (dict, list)):
        parsed = data_or_text
    else:
        return []

    if isinstance(parsed, dict):
        if "announces" in parsed and isinstance(parsed["announces"], list):
            raw_items = parsed["announces"]
        elif "nodes" in parsed and isinstance(parsed["nodes"], list):
            raw_items = parsed["nodes"]
        else:
            raw_items = [parsed]
    elif isinstance(parsed, list):
        raw_items = parsed
    else:
        return []

    nodes: List[TelemetryNode] = []
    for item in raw_items:
        try:
            if isinstance(item, MeshCoreAnnounce):
                announce = item
            elif isinstance(item, dict):
                announce = MeshCoreAnnounce.model_validate(item)
            else:
                continue
        except Exception:
            continue

        # Skip announcements without geographic coordinates
        if announce.coordinate is None or not isinstance(announce.coordinate, Coordinate):
            continue

        # Normalize last heard timestamp
        last_heard = announce.timestamp_iso
        if not last_heard:
            last_heard = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        short_name = announce.name[:8] if len(announce.name) > 8 else announce.name
        dest_hex = announce.destination_hash[:16]
        node_id = f"mcore:{dest_hex}"

        node = TelemetryNode(
            node_id=node_id,
            protocol="meshcore",
            short_name=short_name,
            long_name=announce.name,
            coordinate=announce.coordinate,
            hops_away=announce.hops,
            snr_db=announce.snr_db,
            rssi_dbm=announce.rssi_dbm,
            hardware_model=f"Reticulum / {announce.interface}",
            channel=default_channel,
            last_heard_iso=last_heard,
        )
        nodes.append(node)

    return nodes


def export_meshcore_announces(nodes: Sequence[TelemetryNode]) -> List[Dict[str, Any]]:
    """Serialize cached TelemetryNode objects into standard Reticulum announce dict format.

    Args:
        nodes: Sequence of TelemetryNode instances to export.

    Returns:
        List of announcement dictionaries matching standard Reticulum announce schema.
    """
    announces: List[Dict[str, Any]] = []
    for node in nodes:
        node_id = node.node_id
        if node_id.startswith("mcore:"):
            dest_hash = node_id[len("mcore:"):]
        elif node_id.startswith("rns:"):
            dest_hash = node_id[len("rns:"):]
        else:
            dest_hash = node_id

        interface = "LoRaInterface"
        if node.hardware_model:
            if " / " in node.hardware_model:
                interface = node.hardware_model.split(" / ", 1)[1]
            else:
                interface = node.hardware_model

        announce_dict: Dict[str, Any] = {
            "destination_hash": dest_hash,
            "name": node.long_name,
            "interface": interface,
            "hops": node.hops_away if node.hops_away is not None else 0,
            "coordinate": {
                "lat": node.coordinate.lat,
                "lon": node.coordinate.lon,
                "elevation_m": node.coordinate.elevation_m,
            },
            "lat": node.coordinate.lat,
            "lon": node.coordinate.lon,
            "elevation_m": node.coordinate.elevation_m,
            "snr_db": node.snr_db,
            "rssi_dbm": node.rssi_dbm,
            "timestamp_iso": node.last_heard_iso,
        }
        announces.append(announce_dict)

    return announces
