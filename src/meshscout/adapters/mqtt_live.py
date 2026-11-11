"""Live Meshtastic MQTT telemetry adapter and regional stream ingest worker.

Subscribes to regional Meshtastic MQTT JSON topic trees (e.g. msh/US/VT/2/json/#,
msh/CA/QC/2/json/#), parses geodetic positions and telemetry metrics, and persists
them into the unified regional offline cache.
Zero runtime dependencies beyond pydantic>=2.0.0 and standard library.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import socket
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from meshscout.adapters.telemetry_cache import TelemetryNode, UnifiedTelemetryCache
from meshscout.core.contracts import Coordinate
from meshscout.core.registry import _fuzz_coordinate

logger = logging.getLogger(__name__)


def get_regional_mqtt_topics(state_code: str) -> List[str]:
    """Return default public Meshtastic MQTT topic patterns for a given state or region code.

    Args:
        state_code: State or province code (e.g. 'VT', 'NH', 'ME', 'NY', 'CA_QC').

    Returns:
        List of MQTT topic filter strings covering JSON, protobuf/encrypted, and root channels.
    """
    raw_code = (state_code or "").strip().upper()
    if not raw_code:
        raw_code = "VT"

    # Normalize country and regional code
    if "/" in raw_code:
        country, region = raw_code.split("/", 1)
    elif "_" in raw_code:
        country, region = raw_code.split("_", 1)
    elif "-" in raw_code:
        country, region = raw_code.split("-", 1)
    elif raw_code in ("QC", "ON", "NB", "NS", "BC", "AB", "MB", "SK", "NL", "PE", "YT", "NT", "NU"):
        country, region = "CA", raw_code
    else:
        country, region = "US", raw_code

    return [
        f"msh/{country}/{region}/2/json/#",
        f"msh/{country}/{region}/2/e/#",
        "msh/2/json/#",
    ]


def parse_live_mqtt_packet(
    topic: str,
    payload_bytes_or_str: Union[bytes, str, Dict[str, Any]],
    apply_privacy_fuzz: bool = True,
) -> Optional[TelemetryNode]:
    """Parse a single Meshtastic MQTT packet into a normalized TelemetryNode.

    Extracts geodetic coordinates (supporting float degrees and 1e-7 deg integer format),
    device identifiers, signal metrics, battery status, and RF hop metadata.

    Args:
        topic: The MQTT topic on which the packet was published.
        payload_bytes_or_str: JSON byte string, text string, or pre-parsed dictionary.
        apply_privacy_fuzz: When True, applies ~200m grid privacy fuzzing.

    Returns:
        A validated TelemetryNode instance, or None if required geodetic coordinates are missing.
    """
    if isinstance(payload_bytes_or_str, (bytes, bytearray)):
        raw_str = payload_bytes_or_str.decode("utf-8", errors="replace")
        try:
            pkt = json.loads(raw_str)
        except Exception:
            return None
    elif isinstance(payload_bytes_or_str, str):
        raw_str = payload_bytes_or_str
        try:
            pkt = json.loads(raw_str)
        except Exception:
            return None
    elif isinstance(payload_bytes_or_str, dict):
        pkt = payload_bytes_or_str
        try:
            raw_str = json.dumps(pkt)
        except Exception:
            raw_str = "{}"
    else:
        return None

    if not isinstance(pkt, dict):
        return None

    # Payload blocks
    payload_obj = pkt.get("payload") if isinstance(pkt.get("payload"), dict) else {}
    pos_obj = pkt.get("position") if isinstance(pkt.get("position"), dict) else {}
    user_obj = pkt.get("user") if isinstance(pkt.get("user"), dict) else {}
    device_metrics = (
        payload_obj.get("device_metrics")
        if isinstance(payload_obj.get("device_metrics"), dict)
        else (pkt.get("device_metrics") if isinstance(pkt.get("device_metrics"), dict) else {})
    )

    # 1. Geodetic Coordinates (lat, lon, altitude)
    lat_i = (
        pkt.get("latitude_i")
        or payload_obj.get("latitude_i")
        or pos_obj.get("latitude_i")
    )
    lon_i = (
        pkt.get("longitude_i")
        or payload_obj.get("longitude_i")
        or pos_obj.get("longitude_i")
    )

    lat = (
        pkt.get("lat")
        or pkt.get("latitude")
        or payload_obj.get("lat")
        or payload_obj.get("latitude")
        or pos_obj.get("lat")
        or pos_obj.get("latitude")
    )
    lon = (
        pkt.get("lon")
        or pkt.get("longitude")
        or pkt.get("lng")
        or payload_obj.get("lon")
        or payload_obj.get("longitude")
        or payload_obj.get("lng")
        or pos_obj.get("lon")
        or pos_obj.get("longitude")
        or pos_obj.get("lng")
    )

    # Convert 1e-7 degree integer format if direct floats are not available
    if (lat is None or lon is None) and (lat_i is not None and lon_i is not None):
        try:
            lat = float(lat_i) / 1e7
            lon = float(lon_i) / 1e7
        except (ValueError, TypeError):
            pass

    if lat is None or lon is None:
        return None

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        return None

    # Reject null island / GPS uninitialized
    if lat_f == 0.0 and lon_f == 0.0:
        return None

    if lat_f < -90.0 or lat_f > 90.0 or lon_f < -180.0 or lon_f > 180.0:
        return None

    elev = (
        pkt.get("elevation_m")
        or pkt.get("altitude")
        or pkt.get("elevation")
        or pkt.get("alt")
        or payload_obj.get("elevation_m")
        or payload_obj.get("altitude")
        or payload_obj.get("elevation")
        or payload_obj.get("alt")
        or pos_obj.get("altitude")
        or pos_obj.get("elevation_m")
        or 0.0
    )
    try:
        elev_f = float(elev)
    except (ValueError, TypeError):
        elev_f = 0.0

    coord = Coordinate(lat=lat_f, lon=lon_f, elevation_m=elev_f)
    if apply_privacy_fuzz:
        coord = _fuzz_coordinate(coord)

    # 2. Node ID Extraction
    node_id_raw = (
        pkt.get("from_node_id")
        or pkt.get("node_id")
        or pkt.get("sender")
        or pkt.get("from")
        or payload_obj.get("id")
        or payload_obj.get("node_id")
        or pkt.get("packet_id")
    )

    if isinstance(node_id_raw, int):
        node_id = f"!{node_id_raw:08x}"
    elif isinstance(node_id_raw, str) and node_id_raw.strip():
        node_id = node_id_raw.strip()
    else:
        # Extract from MQTT topic tail (e.g. .../!28ab12cd)
        topic_parts = topic.split("/") if topic else []
        node_candidate = ""
        for part in reversed(topic_parts):
            if part.startswith("!"):
                node_candidate = part
                break
        node_id = node_candidate if node_candidate else "unknown_node"

    # 3. Call Signs & Names
    short_name = (
        pkt.get("sender_short_name")
        or pkt.get("short_name")
        or pkt.get("shortname")
        or payload_obj.get("short_name")
        or payload_obj.get("shortname")
        or user_obj.get("shortName")
        or user_obj.get("short_name")
    )
    if not short_name:
        short_name = node_id[-4:] if len(node_id) >= 4 else node_id
    short_name = str(short_name)

    long_name = (
        pkt.get("sender_long_name")
        or pkt.get("long_name")
        or pkt.get("longname")
        or payload_obj.get("long_name")
        or payload_obj.get("longname")
        or user_obj.get("longName")
        or user_obj.get("long_name")
        or short_name
    )
    long_name = str(long_name)

    # 4. Telemetry Metrics
    battery_val = (
        pkt.get("battery_pct")
        or pkt.get("battery_level")
        or payload_obj.get("battery_level")
        or payload_obj.get("battery_pct")
        or device_metrics.get("battery_level")
    )
    battery_pct: Optional[float] = None
    if battery_val is not None:
        try:
            battery_pct = float(battery_val)
        except (ValueError, TypeError):
            pass

    volt_val = (
        pkt.get("voltage")
        or payload_obj.get("voltage")
        or device_metrics.get("voltage")
    )
    voltage: Optional[float] = None
    if volt_val is not None:
        try:
            voltage = float(volt_val)
        except (ValueError, TypeError):
            pass

    snr_val = (
        pkt.get("snr_db")
        or pkt.get("snr")
        or payload_obj.get("snr_db")
        or payload_obj.get("snr")
    )
    snr_db: Optional[float] = None
    if snr_val is not None:
        try:
            snr_db = float(snr_val)
        except (ValueError, TypeError):
            pass

    rssi_val = (
        pkt.get("rssi_dbm")
        or pkt.get("rssi")
        or payload_obj.get("rssi_dbm")
        or payload_obj.get("rssi")
    )
    rssi_dbm: Optional[float] = None
    if rssi_val is not None:
        try:
            rssi_dbm = float(rssi_val)
        except (ValueError, TypeError):
            pass

    hops_val = pkt.get("hops_away")
    if hops_val is None:
        hops_val = payload_obj.get("hops_away")
    if hops_val is None:
        hops_val = pkt.get("hop_limit")
    if hops_val is None:
        hops_val = payload_obj.get("hop_limit")
    hops_away: Optional[int] = None
    if hops_val is not None:
        try:
            hops_away = int(hops_val)
        except (ValueError, TypeError):
            pass

    hw_val = (
        pkt.get("hardware_model")
        or pkt.get("hardware")
        or payload_obj.get("hardware_model")
        or payload_obj.get("hardware")
        or user_obj.get("hwModel")
    )
    hardware_model = str(hw_val) if hw_val is not None else None

    chan_val = (
        pkt.get("channel_name")
        or pkt.get("channel")
        or payload_obj.get("channel")
    )
    channel = str(chan_val) if chan_val is not None else None

    # 5. Timestamp
    ts_val = (
        pkt.get("timestamp_iso")
        or pkt.get("last_heard_iso")
        or pkt.get("timestamp")
        or pkt.get("time")
        or payload_obj.get("time")
    )
    if isinstance(ts_val, (int, float)):
        ts_sec = ts_val / 1000.0 if ts_val > 1e11 else float(ts_val)
        last_heard_iso = datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()
    elif isinstance(ts_val, str) and ts_val.strip():
        last_heard_iso = ts_val.strip()
    else:
        last_heard_iso = datetime.now(timezone.utc).isoformat()

    is_synthetic = bool(pkt.get("is_synthetic", pkt.get("synthetic", False)))

    try:
        return TelemetryNode(
            node_id=node_id,
            protocol="meshtastic",
            short_name=short_name,
            long_name=long_name,
            coordinate=coord,
            battery_pct=battery_pct,
            voltage=voltage,
            snr_db=snr_db,
            rssi_dbm=rssi_dbm,
            hops_away=hops_away,
            hardware_model=hardware_model,
            channel=channel,
            last_heard_iso=last_heard_iso,
            is_synthetic=is_synthetic,
            raw_payload=raw_str,
        )
    except Exception:
        return None


def _encode_mqtt_varint(value: int) -> bytes:
    """Encode an integer into MQTT v3.1.1 variable-byte Remaining Length."""
    out = bytearray()
    while True:
        encoded_byte = value % 128
        value //= 128
        if value > 0:
            encoded_byte |= 128
        out.append(encoded_byte)
        if value == 0:
            break
    return bytes(out)


def _decode_mqtt_varint(buf: Union[bytes, bytearray], offset: int = 1) -> Tuple[Optional[int], int]:
    """Decode MQTT v3.1.1 variable-byte Remaining Length.

    Args:
        buf: Buffer containing packet bytes.
        offset: Starting offset of Remaining Length field (default 1).

    Returns:
        (value, bytes_consumed) or (None, 0) if incomplete buffer.
    """
    multiplier = 1
    value = 0
    idx = offset
    while idx < len(buf):
        encoded_byte = buf[idx]
        idx += 1
        value += (encoded_byte & 127) * multiplier
        if (encoded_byte & 128) == 0:
            return value, idx - offset
        multiplier *= 128
        if multiplier > 128 * 128 * 128:
            raise ValueError("Malformed MQTT variable-length integer")
    return None, 0


def _build_mqtt_connect_packet(
    client_id: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> bytes:
    """Build a standard MQTT v3.1.1 CONNECT packet with optional credentials."""
    proto_name = b"MQTT"
    proto_level = 4
    flags = 0x02  # Clean session
    if username is not None:
        flags |= 0x80
    if password is not None:
        flags |= 0x40
    keepalive = 30

    var_header = (
        len(proto_name).to_bytes(2, "big")
        + proto_name
        + bytes([proto_level, flags])
        + keepalive.to_bytes(2, "big")
    )
    client_bytes = client_id.encode("utf-8")
    payload = bytearray(len(client_bytes).to_bytes(2, "big") + client_bytes)
    if username is not None:
        u_bytes = username.encode("utf-8")
        payload += len(u_bytes).to_bytes(2, "big") + u_bytes
    if password is not None:
        p_bytes = password.encode("utf-8")
        payload += len(p_bytes).to_bytes(2, "big") + p_bytes

    remaining_len = len(var_header) + len(payload)
    return bytes([0x10]) + _encode_mqtt_varint(remaining_len) + var_header + bytes(payload)


def _build_mqtt_subscribe_packet(packet_id: int, topic: str) -> bytes:
    """Build a standard MQTT v3.1.1 SUBSCRIBE packet for a single topic (QoS 0)."""
    var_header = packet_id.to_bytes(2, "big")
    topic_bytes = topic.encode("utf-8")
    payload = len(topic_bytes).to_bytes(2, "big") + topic_bytes + bytes([0x00])
    remaining_len = len(var_header) + len(payload)

    return bytes([0x82]) + _encode_mqtt_varint(remaining_len) + var_header + payload


def sync_telemetry_from_broker(
    broker_host: str = "mqtt.meshtastic.org",
    broker_port: int = 1883,
    state_code: str = "VT",
    topics: Optional[Sequence[str]] = None,
    cache: Optional[UnifiedTelemetryCache] = None,
    db_path: Optional[Union[str, Path]] = None,
    packets: Optional[Sequence[Union[Dict[str, Any], str, bytes]]] = None,
    timeout_seconds: float = 3.0,
    max_packets: int = 100,
    apply_privacy_fuzz: bool = True,
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_tls: bool = False,
) -> Dict[str, Any]:
    """Sync live telemetry from an MQTT broker into the regional SQLite cache.

    Provides a safe offline fallback: if the broker is unreachable or network errors
    occur, catches socket/connection errors without raising an exception and returns
    a diagnostic offline result.

    Args:
        broker_host: MQTT broker hostname or IP.
        broker_port: MQTT broker TCP port (default: 1883).
        state_code: State/region filter for default topics (default: 'VT').
        topics: Explicit list of MQTT topics to subscribe to. Defaults to regional topics.
        cache: Existing UnifiedTelemetryCache instance. If None, initialized with db_path.
        db_path: SQLite DB path if cache is None.
        packets: Pre-gathered packet sequence to ingest directly without network I/O.
        timeout_seconds: Socket timeout in seconds.
        max_packets: Maximum packets to collect in a single sync turn.
        apply_privacy_fuzz: When True, applies ~200m grid privacy fuzzing.
        username: Optional MQTT broker username for authentication.
        password: Optional MQTT broker password for authentication.
        use_tls: When True, wraps socket in TLS context.

    Returns:
        Dict with keys 'ok', 'count', 'offline', 'error'.
    """
    telemetry_cache = cache or UnifiedTelemetryCache(db_path=db_path)
    effective_topics = list(topics) if topics else get_regional_mqtt_topics(state_code)

    # 1. Direct packet sequence ingestion (e.g. testing or pipe ingestion)
    if packets is not None:
        ingested_nodes: List[TelemetryNode] = []
        default_topic = effective_topics[0] if effective_topics else "msh/2/json/#"
        for item in packets:
            node = parse_live_mqtt_packet(
                topic=default_topic,
                payload_bytes_or_str=item,
                apply_privacy_fuzz=apply_privacy_fuzz,
            )
            if node:
                ingested_nodes.append(node)

        count = telemetry_cache.bulk_upsert_nodes(ingested_nodes) if ingested_nodes else 0
        return {"ok": True, "count": count, "offline": False, "error": None}

    # 2. Live Broker Connection over Standard Library Socket
    sock: Optional[socket.socket] = None
    try:
        raw_sock = socket.create_connection((broker_host, int(broker_port)), timeout=timeout_seconds)
        if use_tls:
            import ssl

            ssl_ctx = ssl.create_default_context()
            sock = ssl_ctx.wrap_socket(raw_sock, server_hostname=broker_host)
        else:
            sock = raw_sock
    except (socket.timeout, OSError, ConnectionError) as err:
        logger.warning(
            "MQTT broker unreachable at %s:%s: %s (graceful offline fallback)",
            broker_host,
            broker_port,
            err,
        )
        return {
            "ok": False,
            "count": 0,
            "offline": True,
            "error": f"Broker unreachable at {broker_host}:{broker_port}: {err}",
        }

    collected_nodes: List[TelemetryNode] = []
    try:
        sock.settimeout(timeout_seconds)
        client_id = f"meshscout_{int(time.time())}"

        # Send CONNECT
        connect_pkt = _build_mqtt_connect_packet(client_id, username=username, password=password)
        sock.sendall(connect_pkt)

        # Read CONNACK (expecting 4 bytes: 0x20, 0x02, ...)
        connack = sock.recv(4)
        if len(connack) < 4 or connack[0] != 0x20 or connack[3] != 0x00:
            return {
                "ok": False,
                "count": 0,
                "offline": True,
                "error": f"Broker rejected connection (connack: {connack.hex()})",
            }

        # Send SUBSCRIBE packets
        pkt_id = 1
        for top in effective_topics:
            sub_pkt = _build_mqtt_subscribe_packet(pkt_id, top)
            sock.sendall(sub_pkt)
            pkt_id += 1

        # Read incoming packets until timeout or max_packets
        start_time = time.time()
        buf = bytearray()
        while len(collected_nodes) < max_packets and (time.time() - start_time) < timeout_seconds:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)

                # Process PUBLISH packets in buffer
                while len(buf) >= 2:
                    header = buf[0]
                    msg_type = (header >> 4) & 0x0F
                    qos = (header >> 1) & 0x03

                    rem_len, varint_bytes = _decode_mqtt_varint(buf, offset=1)
                    if rem_len is None:
                        break  # Incomplete remaining length field

                    total_len = 1 + varint_bytes + rem_len
                    if len(buf) < total_len:
                        break  # Incomplete packet

                    packet_bytes = buf[:total_len]
                    buf = buf[total_len:]

                    if msg_type == 3:  # PUBLISH
                        try:
                            payload_offset = 1 + varint_bytes
                            # Topic length
                            top_len = int.from_bytes(packet_bytes[payload_offset : payload_offset + 2], "big")
                            topic_start = payload_offset + 2
                            topic_str = packet_bytes[topic_start : topic_start + top_len].decode("utf-8", errors="replace")
                            data_start = topic_start + top_len
                            # If QoS > 0, 2-byte Packet Identifier precedes payload
                            if qos > 0:
                                data_start += 2
                            payload_data = packet_bytes[data_start:]
                            node = parse_live_mqtt_packet(
                                topic=topic_str,
                                payload_bytes_or_str=payload_data,
                                apply_privacy_fuzz=apply_privacy_fuzz,
                            )
                            if node:
                                collected_nodes.append(node)
                        except Exception:
                            pass
            except socket.timeout:
                break
            except Exception:
                break

    except Exception as exc:
        logger.debug("Error during MQTT live stream reading: %s", exc)
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    if collected_nodes:
        telemetry_cache.bulk_upsert_nodes(collected_nodes)

    return {
        "ok": True,
        "count": len(collected_nodes),
        "offline": False,
        "error": None,
    }
