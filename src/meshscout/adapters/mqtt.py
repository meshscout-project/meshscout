"""Offline-safe Meshtastic MQTT JSON/NDJSON telemetry adapter and unobserved population gap analyzer.

Provides pure-function parsers for Meshtastic MQTT packet streams (JSON arrays and line-delimited
NDJSON), coordinate privacy fuzzing (~200m grid snap), and spatial gap analysis comparing
heard/active nodes against municipal centers and candidate repeater high sites.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from pydantic import BaseModel, Field

from meshscout.core.contracts import Coordinate, Result, SiteCandidate
from meshscout.core.fresnel import haversine_distance_km
from meshscout.core.registry import DeploymentStatus, RegisteredNode, _fuzz_coordinate

DEFAULT_MQTT_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "fixtures"
    / "vt_mqtt_live_sample.json"
)


class MQTTNodeTelemetry(BaseModel):
    """Telemetry report ingested from Meshtastic MQTT JSON/NDJSON packet stream."""

    node_id: str = Field(..., min_length=1, description="Meshtastic node ID (hex or string)")
    short_name: str = Field(..., description="Operator 4-character node alias")
    long_name: str = Field(..., description="Human-readable node description")
    coordinate: Coordinate = Field(..., description="Geodetic position (optionally privacy-fuzzed)")
    last_heard_iso: str = Field(..., description="ISO 8601 timestamp of last received packet")
    rssi_dbm: float = Field(..., description="Received signal strength in dBm")
    snr_db: float = Field(..., description="Signal-to-noise ratio in dB")
    channel: str = Field(default="LongFast", description="Primary Meshtastic channel name")
    is_synthetic: bool = Field(default=False, description="True if packet is from synthetic simulation fixture")


class UnobservedTownGap(BaseModel):
    """Identified municipal population center lacking heard MQTT telemetry or active repeaters."""

    town_name: str = Field(..., min_length=1, description="Name of the unobserved town or municipality")
    county: str = Field(..., min_length=1, description="County name")
    coordinate: Coordinate = Field(..., description="Geographic center of the municipality")
    population: Optional[int] = Field(default=None, ge=0, description="Estimated census population")
    nearest_observed_node_distance_km: float = Field(..., ge=0.0, description="Distance to closest observed node in km")
    recommended_bridge_sites: List[SiteCandidate] = Field(
        default_factory=list,
        description="Candidate repeater high sites that can bridge coverage to this gap",
    )


class UnobservedAreaReport(BaseModel):
    """Regional mesh telemetry gap assessment and candidate bridge site ranking."""

    total_towns_checked: int = Field(..., ge=0, description="Total municipal reference centers evaluated")
    observed_towns_count: int = Field(..., ge=0, description="Count of towns with heard or active node coverage")
    unobserved_towns_count: int = Field(..., ge=0, description="Count of towns lacking coverage within threshold radius")
    unobserved_gaps: List[UnobservedTownGap] = Field(
        default_factory=list, description="Detailed gap records for unobserved municipalities"
    )
    ranked_solution_sites: List[Dict[str, Any]] = Field(
        default_factory=list, description="High-site candidates ranked by number of unobserved gaps bridged"
    )


def _extract_packet_coordinate(raw_packet: Dict[str, Any]) -> Optional[Coordinate]:
    """Extract and validate WGS84 geodetic coordinate from various packet payload formats."""
    # 1. Nested Coordinate model or dict
    if "coordinate" in raw_packet:
        coord_val = raw_packet["coordinate"]
        if isinstance(coord_val, Coordinate):
            return coord_val
        if isinstance(coord_val, dict) and "lat" in coord_val and "lon" in coord_val:
            return Coordinate(
                lat=float(coord_val["lat"]),
                lon=float(coord_val["lon"]),
                elevation_m=float(coord_val.get("elevation_m", 0.0)),
            )

    # 2. Flat standard or alternate names
    lat = raw_packet.get("lat") if raw_packet.get("lat") is not None else raw_packet.get("latitude")
    lon = raw_packet.get("lon") if raw_packet.get("lon") is not None else raw_packet.get("longitude")
    elev = raw_packet.get("elevation_m") if raw_packet.get("elevation_m") is not None else raw_packet.get("altitude", 0.0)

    # 3. Meshtastic protobuf-to-JSON payload format (latitude_i / longitude_i in 1e-7 deg)
    if lat is None or lon is None:
        payload = raw_packet.get("payload")
        if isinstance(payload, dict):
            lat_i = payload.get("latitude_i")
            lon_i = payload.get("longitude_i")
            if lat_i is not None and lon_i is not None:
                lat = float(lat_i) / 1e7
                lon = float(lon_i) / 1e7
                elev = float(payload.get("altitude", 0.0))

    if lat is not None and lon is not None:
        return Coordinate(lat=float(lat), lon=float(lon), elevation_m=float(elev or 0.0))

    return None


def ingest_mqtt_packets(
    raw_text_or_json: str, apply_privacy_fuzz: bool = True
) -> Result[List[MQTTNodeTelemetry]]:
    """Parse JSON array or line-delimited NDJSON strings from Meshtastic MQTT streams.

    When `apply_privacy_fuzz=True`, snaps node coordinates to a ~200m grid using `_fuzz_coordinate`.
    """
    raw_text = raw_text_or_json.strip()
    if not raw_text:
        return Result.success([])

    packet_dicts: List[Dict[str, Any]] = []
    file_synthetic: bool = False

    # Attempt 1: Full JSON parse (array or object wrapper)
    try:
        parsed_data = json.loads(raw_text)
        if isinstance(parsed_data, list):
            packet_dicts = [p for p in parsed_data if isinstance(p, dict)]
        elif isinstance(parsed_data, dict):
            file_synthetic = bool(parsed_data.get("synthetic", False) or parsed_data.get("is_synthetic", False))
            if "packets" in parsed_data and isinstance(parsed_data["packets"], list):
                packet_dicts = [p for p in parsed_data["packets"] if isinstance(p, dict)]
            elif "data" in parsed_data and isinstance(parsed_data["data"], list):
                packet_dicts = [p for p in parsed_data["data"] if isinstance(p, dict)]
            else:
                packet_dicts = [parsed_data]
    except json.JSONDecodeError:
        # Attempt 2: Line-delimited NDJSON
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        for line_num, line in enumerate(lines, start=1):
            try:
                line_data = json.loads(line)
                if isinstance(line_data, dict):
                    packet_dicts.append(line_data)
                else:
                    return Result.fail(
                        code="NDJSON_INVALID_TYPE",
                        message=f"Line {line_num} does not contain a JSON object.",
                    )
            except json.JSONDecodeError as err:
                return Result.fail(
                    code="PARSE_ERROR",
                    message=f"Failed to parse JSON or NDJSON packet stream: {err}",
                    details={"line_number": line_num, "line_preview": line[:80]},
                )

    telemetry_records: List[MQTTNodeTelemetry] = []
    for idx, pkt in enumerate(packet_dicts, start=1):
        coord = _extract_packet_coordinate(pkt)
        if coord is None:
            return Result.fail(
                code="MISSING_COORDINATES",
                message=f"Packet at index {idx} lacks geographic coordinates.",
                details={"packet_id": pkt.get("packet_id", f"idx_{idx}")},
            )

        if apply_privacy_fuzz:
            coord = _fuzz_coordinate(coord)

        node_id_raw = (
            pkt.get("from_node_id")
            or pkt.get("node_id")
            or pkt.get("from")
            or pkt.get("sender")
            or pkt.get("packet_id")
            or f"node_{idx}"
        )
        node_id = str(node_id_raw)

        user_block = pkt.get("user") if isinstance(pkt.get("user"), dict) else {}
        short_name = str(
            pkt.get("sender_short_name")
            or pkt.get("short_name")
            or user_block.get("shortName")
            or (node_id[-4:] if len(node_id) >= 4 else node_id)
        )
        long_name = str(
            pkt.get("sender_long_name")
            or pkt.get("long_name")
            or user_block.get("longName")
            or short_name
        )

        timestamp_val = (
            pkt.get("timestamp_iso")
            or pkt.get("last_heard_iso")
            or pkt.get("timestamp")
            or pkt.get("time")
        )
        if isinstance(timestamp_val, (int, float)):
            ts_sec = timestamp_val / 1000.0 if timestamp_val > 1e11 else float(timestamp_val)
            last_heard_iso = datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()
        elif isinstance(timestamp_val, str) and timestamp_val.strip():
            last_heard_iso = timestamp_val.strip()
        else:
            last_heard_iso = datetime.now(timezone.utc).isoformat()

        rssi_val = pkt.get("rssi_dbm") if pkt.get("rssi_dbm") is not None else pkt.get("rssi", -100.0)
        snr_val = pkt.get("snr_db") if pkt.get("snr_db") is not None else pkt.get("snr", 0.0)
        channel_val = pkt.get("channel_name") or pkt.get("channel") or "LongFast"

        is_synthetic_val = bool(
            pkt.get("is_synthetic", pkt.get("synthetic", file_synthetic))
        )

        record = MQTTNodeTelemetry(
            node_id=node_id,
            short_name=short_name,
            long_name=long_name,
            coordinate=coord,
            last_heard_iso=last_heard_iso,
            rssi_dbm=float(rssi_val),
            snr_db=float(snr_val),
            channel=str(channel_val),
            is_synthetic=is_synthetic_val,
        )
        telemetry_records.append(record)

    return Result.success(telemetry_records)


def load_mqtt_fixture(
    fixture_path: Optional[Path] = None, apply_privacy_fuzz: bool = False
) -> Result[List[MQTTNodeTelemetry]]:
    """Load and ingest Meshtastic MQTT packets from a fixture JSON file."""
    path = fixture_path if fixture_path is not None else DEFAULT_MQTT_FIXTURE_PATH
    path = Path(path)
    if not path.is_file():
        return Result.fail(
            code="FILE_NOT_FOUND",
            message=f"MQTT fixture file not found: {path}",
            details={"path": str(path)},
        )

    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return Result.fail(
            code="IO_ERROR",
            message=f"Failed to read MQTT fixture file {path}: {exc}",
            details={"path": str(path)},
        )

    return ingest_mqtt_packets(raw_text, apply_privacy_fuzz=apply_privacy_fuzz)


def _extract_town_coordinate(town_data: Dict[str, Any]) -> Optional[Coordinate]:
    """Extract Coordinate from varied town dictionary representations."""
    if "coordinate" in town_data and isinstance(town_data["coordinate"], Coordinate):
        return town_data["coordinate"]
    if "coordinate" in town_data and isinstance(town_data["coordinate"], dict):
        c = town_data["coordinate"]
        return Coordinate(
            lat=float(c["lat"]),
            lon=float(c["lon"]),
            elevation_m=float(c.get("elevation_m", 0.0)),
        )

    lat = town_data.get("lat")
    lon = town_data.get("lon")
    elev = town_data.get("elevation_m", 0.0)
    if lat is not None and lon is not None:
        return Coordinate(lat=float(lat), lon=float(lon), elevation_m=float(elev or 0.0))

    if (
        "coordinates" in town_data
        and isinstance(town_data["coordinates"], (list, tuple))
        and len(town_data["coordinates"]) >= 2
    ):
        # GeoJSON convention: [lon, lat]
        lon_val, lat_val = town_data["coordinates"][:2]
        return Coordinate(lat=float(lat_val), lon=float(lon_val), elevation_m=float(elev or 0.0))

    if (
        "geometry" in town_data
        and isinstance(town_data["geometry"], dict)
        and "coordinates" in town_data["geometry"]
    ):
        coords = town_data["geometry"]["coordinates"]
        return Coordinate(lat=float(coords[1]), lon=float(coords[0]), elevation_m=float(elev or 0.0))

    return None


def analyze_unobserved_areas(
    heard_nodes: Sequence[MQTTNodeTelemetry],
    registry_active_nodes: Sequence[RegisteredNode],
    candidate_sites: Sequence[SiteCandidate],
    reference_towns: Dict[str, Dict[str, Any]],
    coverage_radius_km: float = 8.0,
) -> Result[UnobservedAreaReport]:
    """Analyze geographic mesh gaps comparing heard and active nodes against municipal reference towns.

    Uses 'unobserved' terminology to acknowledge that unmonitored offline nodes or isolated
    analog/digital cells may exist outside the MQTT network perimeter.
    """
    if coverage_radius_km <= 0.0:
        return Result.fail(
            code="INVALID_COVERAGE_RADIUS",
            message=f"coverage_radius_km must be strictly positive, got {coverage_radius_km}",
        )

    # 1. Combine heard nodes and active registry nodes
    active_observed_coords: List[Coordinate] = [node.coordinate for node in heard_nodes]

    has_explicit_active = any(
        getattr(r, "status", None) == DeploymentStatus.ACTIVE_ON_AIR for r in registry_active_nodes
    )
    for r in registry_active_nodes:
        status = getattr(r, "status", None)
        if status == DeploymentStatus.BLOCKED:
            continue
        if has_explicit_active:
            if status == DeploymentStatus.ACTIVE_ON_AIR:
                active_observed_coords.append(r.coordinate)
        else:
            # Caller passed unflagged or candidate registered nodes
            active_observed_coords.append(r.coordinate)

    # 2. Evaluate each municipal town center
    total_towns = len(reference_towns)
    observed_towns_count = 0
    unobserved_towns_count = 0
    unobserved_gaps: List[UnobservedTownGap] = []

    for town_key, town_data in reference_towns.items():
        town_coord = _extract_town_coordinate(town_data)
        if town_coord is None:
            continue

        town_name = str(town_data.get("name") or town_key)
        county = str(town_data.get("county") or "Unknown")
        population_raw = town_data.get("population")
        population: Optional[int] = None
        if population_raw is not None:
            try:
                population = int(population_raw)
            except (ValueError, TypeError):
                population = None

        if active_observed_coords:
            nearest_dist_km = min(
                haversine_distance_km(town_coord, oc) for oc in active_observed_coords
            )
        else:
            nearest_dist_km = float("inf")

        if nearest_dist_km <= coverage_radius_km:
            observed_towns_count += 1
        else:
            unobserved_towns_count += 1

            # Find candidate bridge sites within coverage radius or line-of-sight elevation reach
            bridge_sites_with_dist: List[Tuple[float, SiteCandidate]] = []
            for cand in candidate_sites:
                dist = haversine_distance_km(cand.location, town_coord)
                elev_diff = (cand.location.elevation_m + cand.mast_height_m) - town_coord.elevation_m

                # Repeater reach qualification: within radius, or high mountain peak overlooking valley
                within_radius = dist <= coverage_radius_km
                within_high_site_reach = (dist <= coverage_radius_km * 3.0) and (elev_diff >= 100.0)

                if within_radius or within_high_site_reach:
                    bridge_sites_with_dist.append((dist, cand))

            bridge_sites_with_dist.sort(key=lambda item: item[0])
            recommended_bridge_sites = [cand for _, cand in bridge_sites_with_dist]

            gap = UnobservedTownGap(
                town_name=town_name,
                county=county,
                coordinate=town_coord,
                population=population,
                nearest_observed_node_distance_km=round(nearest_dist_km, 2)
                if not math.isinf(nearest_dist_km)
                else 9999.0,
                recommended_bridge_sites=recommended_bridge_sites,
            )
            unobserved_gaps.append(gap)

    # 3. Rank solution sites across all unobserved gaps
    site_coverage_map: Dict[str, List[str]] = {}
    site_min_dist: Dict[str, float] = {}
    site_objects: Dict[str, SiteCandidate] = {}

    for gap in unobserved_gaps:
        for site in gap.recommended_bridge_sites:
            site_objects[site.site_id] = site
            if site.site_id not in site_coverage_map:
                site_coverage_map[site.site_id] = []
                site_min_dist[site.site_id] = float("inf")
            site_coverage_map[site.site_id].append(gap.town_name)
            d = haversine_distance_km(site.location, gap.coordinate)
            if d < site_min_dist[site.site_id]:
                site_min_dist[site.site_id] = d

    ranked_solution_sites: List[Dict[str, Any]] = []
    for site_id, towns_covered in site_coverage_map.items():
        cand = site_objects[site_id]
        ranked_solution_sites.append(
            {
                "site_id": cand.site_id,
                "name": cand.name,
                "site_type": cand.site_type.value if hasattr(cand.site_type, "value") else str(cand.site_type),
                "unobserved_towns_covered": towns_covered,
                "towns_covered_count": len(towns_covered),
                "nearest_gap_distance_km": round(site_min_dist[site_id], 2),
                "elevation_m": cand.location.elevation_m,
                "mast_height_m": cand.mast_height_m,
                "has_grid_power": cand.has_grid_power,
                "solar_exposure_pct": cand.solar_exposure_pct,
            }
        )

    ranked_solution_sites.sort(
        key=lambda s: (s["towns_covered_count"], -s["nearest_gap_distance_km"]),
        reverse=True,
    )

    report = UnobservedAreaReport(
        total_towns_checked=total_towns,
        observed_towns_count=observed_towns_count,
        unobserved_towns_count=unobserved_towns_count,
        unobserved_gaps=unobserved_gaps,
        ranked_solution_sites=ranked_solution_sites,
    )
    return Result.success(report)
