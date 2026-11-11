"""Wardriving telemetry ingestion, log parsing, and ground-truth RF clutter calibration.

Provides pure-function parsers for Meshtastic wardriving logs (CSV and JSON) and
point-to-point ITM calibration against real-world measured RSSI.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Union
from pydantic import BaseModel, Field, ValidationError

from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RadioConfig,
    Result,
    SiteCandidate,
    SiteType,
)
from meshscout.core.fresnel import haversine_distance_km
from meshscout.core.itm import (
    evaluate_point_to_point_link,
    free_space_path_loss_db,
)
from meshscout.core.viewshed import sample_transect_points


class WardrivePacket(BaseModel):
    """Normalized field test packet from wardriving or drive-test logs."""

    packet_id: str = Field(..., min_length=1, description="Unique packet identifier")
    timestamp: str = Field(..., description="ISO 8601 or logging timestamp string")
    rx_coordinate: Coordinate = Field(..., description="Receiver location coordinate")
    tx_coordinate: Optional[Coordinate] = Field(
        default=None, description="Optional transmitter location coordinate"
    )
    tx_node_id: str = Field(..., min_length=1, description="Transmitting node ID")
    rx_node_id: str = Field(..., min_length=1, description="Receiving node ID")
    rssi_dbm: float = Field(..., description="Measured Received Signal Strength Indicator in dBm")
    snr_db: float = Field(..., description="Measured Signal-to-Noise Ratio in dB")
    frequency_mhz: float = Field(
        default=915.0, gt=0.0, description="Carrier frequency in MHz (default US915: 915.0)"
    )
    hop_limit: Optional[int] = Field(
        default=None, ge=0, description="Meshtastic hop limit or remaining hops"
    )


class PacketCalibrationMatch(BaseModel):
    """Comparison of modeled Longley-Rice ITM propagation against measured packet RSSI."""

    packet: WardrivePacket
    predicted_rx_power_dbm: float = Field(..., description="Modeled link budget RX power in dBm")
    predicted_link_margin_db: float = Field(..., description="Modeled link margin above sensitivity in dB")
    measured_rssi_dbm: float = Field(..., description="Actual measured RSSI in dBm")
    error_db: float = Field(
        ...,
        description="Measured minus predicted RX power (dB). Negative values denote excess attenuation.",
    )
    distance_km: float = Field(..., ge=0.0, description="Great circle path distance in kilometers")
    has_line_of_sight: bool = Field(..., description="Line-of-Sight status between transmitter and receiver")


class ClutterCalibrationResult(BaseModel):
    """Aggregated ground-truth empirical calibration statistics for clutter and foliage tuning."""

    total_packets_ingested: int = Field(..., ge=0)
    matched_packets_count: int = Field(..., ge=0)
    mean_error_db: float = Field(..., description="Mean difference between measured RSSI and modeled power (dB)")
    rmse_db: float = Field(..., ge=0.0, description="Root Mean Square Error of model prediction (dB)")
    recommended_canopy_adjustment_db: float = Field(
        ..., ge=0.0, description="Recommended bulk canopy attenuation penalty in dB"
    )
    recommended_clutter_db_per_km: float = Field(
        ..., ge=0.0, description="Recommended distance-scaled clutter attenuation loss in dB/km"
    )
    matches: List[PacketCalibrationMatch] = Field(default_factory=list)


def _safe_float(val: Any) -> Optional[float]:
    """Convert input to float safely, returning None if invalid."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    """Convert input to int safely, returning None if invalid."""
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _parse_packet_dict(item: Dict[str, Any], default_idx: int = 1) -> Optional[WardrivePacket]:
    """Parse and validate a dictionary item into a WardrivePacket, returning None on invalid data."""
    if not isinstance(item, dict):
        return None

    # Handle direct WardrivePacket model structure if present
    if "rx_coordinate" in item and isinstance(item["rx_coordinate"], dict):
        try:
            return WardrivePacket.model_validate(item)
        except ValidationError:
            pass

    # Extract coordinates (support flat and nested keys)
    rx_lat = _safe_float(
        item.get("lat")
        or item.get("latitude")
        or (item.get("rx_coordinate", {}).get("lat") if isinstance(item.get("rx_coordinate"), dict) else None)
    )
    rx_lon = _safe_float(
        item.get("lon")
        or item.get("lng")
        or item.get("long")
        or item.get("longitude")
        or (item.get("rx_coordinate", {}).get("lon") if isinstance(item.get("rx_coordinate"), dict) else None)
    )
    rx_elev = _safe_float(
        item.get("elevation")
        or item.get("altitude")
        or item.get("elevation_m")
        or item.get("alt")
        or (item.get("rx_coordinate", {}).get("elevation_m") if isinstance(item.get("rx_coordinate"), dict) else None)
    ) or 0.0

    if rx_lat is None or rx_lon is None:
        return None
    if rx_lat < -90.0 or rx_lat > 90.0 or rx_lon < -180.0 or rx_lon > 180.0:
        return None

    try:
        rx_coord = Coordinate(lat=rx_lat, lon=rx_lon, elevation_m=rx_elev)
    except ValidationError:
        return None

    # Optional tx coordinate
    tx_coord: Optional[Coordinate] = None
    tx_lat = _safe_float(
        item.get("tx_lat")
        or (item.get("tx_coordinate", {}).get("lat") if isinstance(item.get("tx_coordinate"), dict) else None)
    )
    tx_lon = _safe_float(
        item.get("tx_lon")
        or (item.get("tx_coordinate", {}).get("lon") if isinstance(item.get("tx_coordinate"), dict) else None)
    )
    if tx_lat is not None and tx_lon is not None:
        if -90.0 <= tx_lat <= 90.0 and -180.0 <= tx_lon <= 180.0:
            tx_elev = _safe_float(
                item.get("tx_elevation")
                or (item.get("tx_coordinate", {}).get("elevation_m") if isinstance(item.get("tx_coordinate"), dict) else None)
            ) or 0.0
            tx_coord = Coordinate(lat=tx_lat, lon=tx_lon, elevation_m=tx_elev)

    # RSSI and SNR
    rssi = _safe_float(item.get("rssi_dbm") if item.get("rssi_dbm") is not None else item.get("rssi"))
    snr = _safe_float(item.get("snr_db") if item.get("snr_db") is not None else item.get("snr"))
    if rssi is None or snr is None:
        return None

    # Node IDs
    tx_node = str(item.get("tx_node_id") or item.get("from") or item.get("sender") or "").strip()
    rx_node = str(item.get("rx_node_id") or item.get("to") or item.get("receiver") or "").strip()
    if not tx_node:
        tx_node = "unknown_tx"
    if not rx_node:
        rx_node = "unknown_rx"

    pkt_id = str(item.get("packet_id") or item.get("id") or item.get("msg_id") or f"pkt_{default_idx}").strip()
    ts = str(item.get("timestamp") or item.get("time") or item.get("datetime") or "1970-01-01T00:00:00Z").strip()

    freq = _safe_float(item.get("frequency_mhz") or item.get("frequency") or item.get("freq")) or 915.0
    if freq <= 0.0:
        freq = 915.0

    raw_hops = item.get("hop_limit")
    if raw_hops is None:
        raw_hops = item.get("hops")
    if raw_hops is None:
        raw_hops = item.get("hop_count")
    hops = _safe_int(raw_hops)

    try:
        return WardrivePacket(
            packet_id=pkt_id,
            timestamp=ts,
            rx_coordinate=rx_coord,
            tx_coordinate=tx_coord,
            tx_node_id=tx_node,
            rx_node_id=rx_node,
            rssi_dbm=round(rssi, 2),
            snr_db=round(snr, 2),
            frequency_mhz=freq,
            hop_limit=hops,
        )
    except ValidationError:
        return None


def parse_wardrive_log(
    raw_text_or_json: str, format_hint: str = "auto"
) -> Result[List[WardrivePacket]]:
    """Parse standard Meshtastic wardriving CSV or JSON export into validated List[WardrivePacket].

    Supported formats:
    - CSV: columns `time,lat,lon,elevation,snr,rssi,from,to` (or case-insensitive aliases)
    - JSON: list of packet objects or wrapper object with key `packets`, `records`, or `data`.

    Args:
        raw_text_or_json: Log file text content.
        format_hint: Format detector hint ('auto', 'json', 'csv').

    Returns:
        Result containing validated WardrivePacket list, or failure error.
    """
    clean_text = raw_text_or_json.strip()
    if not clean_text:
        return Result.fail(code="EMPTY_INPUT", message="Wardrive input text is empty.")

    hint = format_hint.strip().lower()
    is_json = hint == "json" or (hint == "auto" and clean_text.startswith(("[", "{")))

    if is_json:
        try:
            data = json.loads(clean_text)
        except Exception as exc:
            return Result.fail(code="PARSE_ERROR", message=f"Malformed JSON in wardrive log: {exc}")

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for candidate_key in ("packets", "records", "data", "rows", "items"):
                if candidate_key in data and isinstance(data[candidate_key], list):
                    items = data[candidate_key]
                    break
            else:
                items = [data]
        else:
            return Result.fail(
                code="INVALID_STRUCTURE", message="JSON root must be an object or array."
            )

        packets: List[WardrivePacket] = []
        for idx, itm in enumerate(items):
            pkt = _parse_packet_dict(itm, default_idx=idx + 1)
            if pkt is not None:
                packets.append(pkt)

        if not packets and items:
            return Result.fail(
                code="NO_VALID_PACKETS",
                message="No valid wardrive packets could be extracted from JSON data.",
            )
        return Result.success(packets)

    # Process as CSV
    try:
        stream = io.StringIO(clean_text)
        reader = csv.reader(stream)
        raw_rows = [r for r in reader if r and any(cell.strip() for cell in r)]
    except Exception as exc:
        return Result.fail(code="PARSE_ERROR", message=f"Malformed CSV in wardrive log: {exc}")

    if not raw_rows:
        return Result.fail(code="EMPTY_CSV", message="CSV log contains no records.")

    # Parse header
    header = [c.strip().lower() for c in raw_rows[0]]
    col_map = {col: i for i, col in enumerate(header)}

    # Field resolver helper
    def get_cell(row: List[str], *aliases: str) -> Optional[str]:
        for alias in aliases:
            idx = col_map.get(alias.lower())
            if idx is not None and idx < len(row):
                val = row[idx].strip()
                if val:
                    return val
        return None

    packets = []
    for row_idx, row in enumerate(raw_rows[1:], start=1):
        try:
            lat_str = get_cell(row, "lat", "latitude")
            lon_str = get_cell(row, "lon", "lng", "long", "longitude")
            elev_str = get_cell(row, "elevation", "altitude", "alt", "elev", "elevation_m") or "0.0"
            rssi_str = get_cell(row, "rssi", "rssi_dbm")
            snr_str = get_cell(row, "snr", "snr_db")
            from_str = get_cell(row, "from", "sender", "tx_node_id", "tx_id", "source") or "unknown_tx"
            to_str = get_cell(row, "to", "receiver", "rx_node_id", "rx_id", "destination") or "unknown_rx"
            time_str = get_cell(row, "time", "timestamp", "datetime", "date") or "1970-01-01T00:00:00Z"
            id_str = get_cell(row, "packet_id", "id", "msg_id") or f"csv_pkt_{row_idx}"
            freq_str = get_cell(row, "frequency_mhz", "frequency", "freq", "freq_mhz") or "915.0"
            hops_str = get_cell(row, "hop_limit", "hops", "hop_count")

            dict_repr = {
                "packet_id": id_str,
                "timestamp": time_str,
                "lat": lat_str,
                "lon": lon_str,
                "elevation": elev_str,
                "rssi": rssi_str,
                "snr": snr_str,
                "tx_node_id": from_str,
                "rx_node_id": to_str,
                "frequency_mhz": freq_str,
                "hop_limit": hops_str,
            }
            pkt = _parse_packet_dict(dict_repr, default_idx=row_idx)
            if pkt is not None:
                packets.append(pkt)
        except Exception:
            continue

    if not packets:
        return Result.fail(
            code="NO_VALID_PACKETS",
            message="No valid wardrive packets could be extracted from CSV data.",
        )
    return Result.success(packets)


def _matches_site(packet: WardrivePacket, site: SiteCandidate) -> bool:
    """Check if a packet originated from or was sent to the candidate site."""
    tx_id = packet.tx_node_id.strip().lower()
    rx_id = packet.rx_node_id.strip().lower()
    site_id = site.site_id.strip().lower()
    site_name = site.name.strip().lower()

    if site_id and (tx_id == site_id or rx_id == site_id):
        return True
    if site_name and (tx_id == site_name or rx_id == site_name):
        return True

    if packet.tx_coordinate is not None:
        if haversine_distance_km(packet.tx_coordinate, site.location) < 0.1:
            return True

    return False


def calibrate_ground_truth_clutter(
    packets: Sequence[WardrivePacket],
    transmitter_site: SiteCandidate,
    radio: Optional[RadioConfig] = None,
    elevation_fn: Optional[Callable[[float, float], float]] = None,
) -> Result[ClutterCalibrationResult]:
    """Calibrate ITM propagation against ground-truth wardriving packet measurements.

    Compares modeled Longley-Rice / Bullington link power with field-measured RSSI.
    Calculates residual offset (mean error) and RMSE, deriving recommended bulk canopy
    attenuation and per-km clutter loss adjustments.

    Args:
        packets: Sequence of field-recorded packets.
        transmitter_site: Candidate transmitter high-site location.
        radio: Optional radio transceiver parameters (defaults to 915 MHz, 20 dBm).
        elevation_fn: Optional pure function `(lat, lon) -> elevation_m` for DEM sampling.

    Returns:
        Result containing ClutterCalibrationResult or failure error.
    """
    if radio is None:
        radio = RadioConfig()

    matched_packets = [pkt for pkt in packets if _matches_site(pkt, transmitter_site)]
    if not matched_packets:
        return Result.fail(
            code="NO_MATCHING_PACKETS",
            message=f"No packets in log matched transmitter site '{transmitter_site.site_id}'.",
            details={
                "transmitter_site_id": transmitter_site.site_id,
                "total_packets": len(packets),
            },
        )

    # If transmitter elevation is zero and DEM function provided, evaluate elevation
    tx_location = transmitter_site.location
    if tx_location.elevation_m == 0.0 and elevation_fn is not None:
        tx_elev = float(elevation_fn(tx_location.lat, tx_location.lon))
        tx_location = Coordinate(lat=tx_location.lat, lon=tx_location.lon, elevation_m=tx_elev)
        transmitter_site = transmitter_site.model_copy(update={"location": tx_location})

    matches: List[PacketCalibrationMatch] = []

    for pkt in matched_packets:
        rx_coord = pkt.rx_coordinate
        if rx_coord.elevation_m == 0.0 and elevation_fn is not None:
            elev = float(elevation_fn(rx_coord.lat, rx_coord.lon))
            rx_coord = Coordinate(lat=rx_coord.lat, lon=rx_coord.lon, elevation_m=elev)

        dist_km = haversine_distance_km(transmitter_site.location, rx_coord)
        dist_km = max(dist_km, 0.001)

        mobile_site = SiteCandidate(
            site_id=pkt.rx_node_id if pkt.rx_node_id else "wardrive_rx",
            name=f"Mobile RX at {rx_coord.lat:.4f},{rx_coord.lon:.4f}",
            location=rx_coord,
            site_type=SiteType.CUSTOM,
            mast_height_m=1.5,
        )

        transect = sample_transect_points(
            source_coord=transmitter_site.location,
            target_coord=rx_coord,
            elevation_fn=elevation_fn,
            num_samples=15,
        )

        profile = ElevationProfile(
            source_site=transmitter_site,
            target_site=mobile_site,
            distance_km=dist_km,
            points=transect,
        )

        # Set packet carrier frequency if divergent
        eval_radio = radio
        if pkt.frequency_mhz != radio.frequency_mhz:
            eval_radio = radio.model_copy(update={"frequency_mhz": pkt.frequency_mhz})

        link_res = evaluate_point_to_point_link(profile=profile, radio=eval_radio)
        if link_res.ok and link_res.value is not None:
            pred_rx = link_res.value.rx_power_dbm
            pred_margin = link_res.value.link_margin_db
            has_los = link_res.value.has_line_of_sight
            calc_dist_km = link_res.value.distance_km
        else:
            fspl = free_space_path_loss_db(dist_km, eval_radio.frequency_mhz)
            sys_gain = (2.0 * eval_radio.antenna_gain_dbi) - (2.0 * eval_radio.cable_loss_db)
            pred_rx = round(eval_radio.tx_power_dbm + sys_gain - fspl, 4)
            pred_margin = round(pred_rx - eval_radio.rx_sensitivity_dbm, 4)
            has_los = True
            calc_dist_km = dist_km

        error_db = round(pkt.rssi_dbm - pred_rx, 4)

        matches.append(
            PacketCalibrationMatch(
                packet=pkt,
                predicted_rx_power_dbm=pred_rx,
                predicted_link_margin_db=pred_margin,
                measured_rssi_dbm=pkt.rssi_dbm,
                error_db=error_db,
                distance_km=round(calc_dist_km, 4),
                has_line_of_sight=has_los,
            )
        )

    matched_count = len(matches)
    errors = [m.error_db for m in matches]
    mean_err = round(sum(errors) / matched_count, 4)
    rmse = round(math.sqrt(sum(e**2 for e in errors) / matched_count), 4)

    # When measured signals are lower than predicted (mean_err < 0), excess clutter/canopy loss is indicated
    if mean_err < 0:
        recommended_canopy_adjustment = round(abs(mean_err), 4)
        avg_dist = sum(m.distance_km for m in matches) / matched_count
        recommended_clutter_per_km = (
            round(recommended_canopy_adjustment / avg_dist, 4) if avg_dist > 0.0 else 0.0
        )
    else:
        recommended_canopy_adjustment = 0.0
        recommended_clutter_per_km = 0.0

    return Result.success(
        ClutterCalibrationResult(
            total_packets_ingested=len(packets),
            matched_packets_count=matched_count,
            mean_error_db=mean_err,
            rmse_db=rmse,
            recommended_canopy_adjustment_db=recommended_canopy_adjustment,
            recommended_clutter_db_per_km=recommended_clutter_per_km,
            matches=matches,
        )
    )
