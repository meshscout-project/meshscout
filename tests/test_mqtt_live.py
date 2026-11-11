"""Unit tests for live Meshtastic MQTT telemetry adapter and sync CLI.

Tests topic helpers, packet parsers for both integer and float coordinates,
missing coordinate handling, graceful offline broker fallback, and CLI sync subcommand.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Generator
import pytest

from meshscout.adapters.mqtt_live import (
    get_regional_mqtt_topics,
    parse_live_mqtt_packet,
    sync_telemetry_from_broker,
)
from meshscout.adapters.telemetry_cache import TelemetryNode, UnifiedTelemetryCache
from meshscout.cli import main


@pytest.fixture
def temp_cache_db() -> Generator[Path, None, None]:
    """Provide a temporary database path and clean up on teardown."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_telemetry.db"
        yield db_path


def test_get_regional_mqtt_topics() -> None:
    """Test regional MQTT topic pattern generation for VT, NH, and CA_QC."""
    vt_topics = get_regional_mqtt_topics("VT")
    assert vt_topics == ["msh/US/VT/2/json/#", "msh/US/VT/2/e/#", "msh/2/json/#"]

    nh_topics = get_regional_mqtt_topics("NH")
    assert nh_topics == ["msh/US/NH/2/json/#", "msh/US/NH/2/e/#", "msh/2/json/#"]

    qc_topics = get_regional_mqtt_topics("CA_QC")
    assert qc_topics == ["msh/CA/QC/2/json/#", "msh/CA/QC/2/e/#", "msh/2/json/#"]

    # Province direct shorthand
    qc_direct = get_regional_mqtt_topics("QC")
    assert qc_direct == ["msh/CA/QC/2/json/#", "msh/CA/QC/2/e/#", "msh/2/json/#"]


def test_parse_live_mqtt_packet_integer_coordinates() -> None:
    """Test parsing Meshtastic JSON with integer 1e-7 deg coordinates."""
    payload = {
        "from": "!4401a01",
        "sender": "!4401a01",
        "type": "position",
        "payload": {
            "latitude_i": 445000000,
            "longitude_i": -731000000,
            "altitude": 145,
            "time": 1730000000,
        },
        "sender_short_name": "NODE1",
        "sender_long_name": "Node One High Site",
        "battery_level": 88.0,
        "voltage": 4.12,
        "snr": 9.5,
        "rssi": -81.0,
        "hops_away": 2,
    }

    # Test without privacy fuzz for exact coord match
    node = parse_live_mqtt_packet(
        topic="msh/US/VT/2/json/!4401a01",
        payload_bytes_or_str=json.dumps(payload),
        apply_privacy_fuzz=False,
    )

    assert node is not None
    assert isinstance(node, TelemetryNode)
    assert node.node_id == "!4401a01"
    assert node.protocol == "meshtastic"
    assert node.short_name == "NODE1"
    assert node.long_name == "Node One High Site"
    assert pytest.approx(node.lat, 1e-4) == 44.5
    assert pytest.approx(node.lon, 1e-4) == -73.1
    assert pytest.approx(node.elevation_m, 1e-1) == 145.0
    assert node.battery_pct == 88.0
    assert node.voltage == 4.12
    assert node.snr_db == 9.5
    assert node.rssi_dbm == -81.0
    assert node.hops_away == 2


def test_parse_live_mqtt_packet_standard_float_coordinates() -> None:
    """Test parsing Meshtastic JSON with standard float coordinates."""
    payload = {
        "node_id": "!28ab34cd",
        "short_name": "BURL",
        "long_name": "Burlington Waterfront",
        "lat": 44.4759,
        "lon": -73.2121,
        "elevation_m": 61.0,
        "snr_db": 8.0,
        "rssi_dbm": -82.0,
        "channel_name": "LongFast",
    }

    node = parse_live_mqtt_packet(
        topic="msh/US/VT/2/json/!28ab34cd",
        payload_bytes_or_str=payload,
        apply_privacy_fuzz=False,
    )

    assert node is not None
    assert node.node_id == "!28ab34cd"
    assert node.short_name == "BURL"
    assert pytest.approx(node.lat, 1e-4) == 44.4759
    assert pytest.approx(node.lon, 1e-4) == -73.2121
    assert node.channel == "LongFast"


def test_parse_live_mqtt_packet_ignores_missing_coordinates() -> None:
    """Verify packets lacking coordinates (e.g. text message or telemetry-only) return None."""
    # Text message packet
    text_pkt = {
        "from": "!4401a01",
        "type": "text",
        "payload": {"text": "Hello mesh world"},
    }
    assert parse_live_mqtt_packet("msh/2/json/#", text_pkt) is None

    # Telemetry packet with battery only
    telemetry_pkt = {
        "from": "!4401a01",
        "type": "telemetry",
        "payload": {"battery_level": 92, "voltage": 4.18},
    }
    assert parse_live_mqtt_packet("msh/2/json/#", telemetry_pkt) is None

    # Null Island GPS lock failure
    null_island_pkt = {
        "from": "!4401a01",
        "payload": {"latitude_i": 0, "longitude_i": 0},
    }
    assert parse_live_mqtt_packet("msh/2/json/#", null_island_pkt) is None

    # Invalid JSON string
    assert parse_live_mqtt_packet("msh/2/json/#", "not valid json {") is None


def test_sync_telemetry_from_broker_offline_graceful_failure() -> None:
    """Verify graceful offline fallback when broker is unreachable (127.0.0.1:59999)."""
    result = sync_telemetry_from_broker(
        broker_host="127.0.0.1",
        broker_port=59999,
        timeout_seconds=0.5,
    )

    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["count"] == 0
    assert result["offline"] is True
    assert "unreachable" in result["error"].lower() or "connection" in result["error"].lower() or "timed out" in result["error"].lower()


def test_sync_telemetry_from_broker_direct_packets(temp_cache_db: Path) -> None:
    """Test sync_telemetry_from_broker directly with in-memory packet list."""
    cache = UnifiedTelemetryCache(db_path=temp_cache_db)
    try:
        packets = [
            {
                "from": "!test01",
                "lat": 44.50,
                "lon": -73.20,
                "short_name": "T1",
                "long_name": "Test Node 1",
            },
            {
                "from": "!test02",
                "lat": 44.55,
                "lon": -73.25,
                "short_name": "T2",
                "long_name": "Test Node 2",
            },
        ]
        result = sync_telemetry_from_broker(
            cache=cache,
            packets=packets,
            apply_privacy_fuzz=False,
        )
        assert result["ok"] is True
        assert result["count"] == 2
        assert result["offline"] is False

        # Query cache to verify persistence
        nodes = cache.query_nodes()
        assert len(nodes) == 2
        ids = {n.node_id for n in nodes}
        assert "!test01" in ids
        assert "!test02" in ids
    finally:
        cache.close()


def test_cli_sync_telemetry_sample(temp_cache_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test CLI subcommand 'sync-telemetry' with sample fixture seeding."""
    exit_code = main(
        [
            "sync-telemetry",
            "--region",
            "VT",
            "--source",
            "sample",
            "--buffer-km",
            "20.0",
            "--db-path",
            str(temp_cache_db),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "MeshScout Telemetry Cache Sync Summary" in captured.out
    assert "Total Cached:" in captured.out
    assert "Meshtastic" in captured.out
    assert "Meshcore" in captured.out


def test_cli_sync_telemetry_json_output(temp_cache_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test CLI subcommand 'sync-telemetry' with --json flag."""
    exit_code = main(
        [
            "sync-telemetry",
            "--region",
            "VT",
            "--source",
            "sample",
            "--db-path",
            str(temp_cache_db),
            "--json",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["source"] == "sample"
    assert data["region"] == "VT"
    assert data["total_cached"] > 0
    assert "meshtastic" in data["by_protocol"]
    assert "meshcore" in data["by_protocol"]


def test_mqtt_varint_roundtrip() -> None:
    """Verify MQTT v3.1.1 variable-byte integer encoding and decoding."""
    from meshscout.adapters.mqtt_live import _decode_mqtt_varint, _encode_mqtt_varint

    test_values = [0, 1, 127, 128, 129, 255, 16383, 16384, 65535, 2097151]
    for val in test_values:
        encoded = _encode_mqtt_varint(val)
        decoded, consumed = _decode_mqtt_varint(encoded, offset=0)
        assert decoded == val, f"Decoded mismatch for {val}: got {decoded}"
        assert consumed == len(encoded)


def test_mqtt_connect_packet_with_credentials() -> None:
    """Verify CONNECT packet construction with username and password flags."""
    from meshscout.adapters.mqtt_live import _build_mqtt_connect_packet

    pkt_anon = _build_mqtt_connect_packet("client123")
    assert pkt_anon[0] == 0x10
    # Anon connect flags byte: index 9 should be 0x02 (clean session only)
    assert pkt_anon[9] == 0x02

    pkt_auth = _build_mqtt_connect_packet("client123", username="testuser", password="secretpassword")
    assert pkt_auth[0] == 0x10
    # Flags byte with username (0x80) and password (0x40) + clean session (0x02) = 0xC2
    assert pkt_auth[9] == 0xC2
    assert b"testuser" in pkt_auth
    assert b"secretpassword" in pkt_auth


def test_parse_live_mqtt_packet_preserves_zero_hops() -> None:
    """Verify hops_away=0 is preserved and not shadowed by falsy fallback."""
    payload = {
        "node_id": "!direct01",
        "lat": 44.5,
        "lon": -73.0,
        "elevation_m": 120.0,
        "hops_away": 0,
        "hop_limit": 3,
    }
    node = parse_live_mqtt_packet("msh/2/json/#", payload, apply_privacy_fuzz=False)
    assert node is not None
    assert node.hops_away == 0


def test_sync_telemetry_packet_framing_large_payload_and_qos() -> None:
    """Verify parsing MQTT stream buffer with payload >= 128 bytes and QoS 1 framing."""
    from meshscout.adapters.mqtt_live import _decode_mqtt_varint, _encode_mqtt_varint

    # Build large JSON payload (> 128 bytes)
    node_payload = {
        "node_id": "!large01",
        "short_name": "BIG",
        "long_name": "A" * 150,  # Ensure payload > 128 bytes
        "lat": 44.4759,
        "lon": -73.2121,
        "elevation_m": 85.0,
        "hops_away": 1,
    }
    payload_bytes = json.dumps(node_payload).encode("utf-8")
    assert len(payload_bytes) > 128

    topic_bytes = b"msh/US/VT/2/json/!large01"
    topic_len = len(topic_bytes)

    # QoS 1 packet: Header 0x32 (type 3, QoS 1)
    packet_id = 42
    var_header = topic_len.to_bytes(2, "big") + topic_bytes + packet_id.to_bytes(2, "big")
    rem_len = len(var_header) + len(payload_bytes)
    pkt1 = bytes([0x32]) + _encode_mqtt_varint(rem_len) + var_header + payload_bytes

    # Second packet QoS 0
    node2_payload = {
        "node_id": "!small02",
        "lat": 44.5000,
        "lon": -73.1000,
        "elevation_m": 90.0,
    }
    payload2_bytes = json.dumps(node2_payload).encode("utf-8")
    var_header2 = topic_len.to_bytes(2, "big") + topic_bytes
    rem_len2 = len(var_header2) + len(payload2_bytes)
    pkt2 = bytes([0x30]) + _encode_mqtt_varint(rem_len2) + var_header2 + payload2_bytes

    # Stream concatenation
    stream_buf = pkt1 + pkt2

    # Simulate packet parsing loop directly
    from meshscout.adapters.mqtt_live import _decode_mqtt_varint
    buf = bytearray(stream_buf)
    collected = []
    while len(buf) >= 2:
        header = buf[0]
        msg_type = (header >> 4) & 0x0F
        qos = (header >> 1) & 0x03

        rem_len_val, varint_bytes = _decode_mqtt_varint(buf, offset=1)
        if rem_len_val is None:
            break
        total_len = 1 + varint_bytes + rem_len_val
        if len(buf) < total_len:
            break

        packet_bytes = buf[:total_len]
        buf = buf[total_len:]

        if msg_type == 3:
            payload_offset = 1 + varint_bytes
            top_len = int.from_bytes(packet_bytes[payload_offset : payload_offset + 2], "big")
            topic_start = payload_offset + 2
            topic_str = packet_bytes[topic_start : topic_start + top_len].decode("utf-8", errors="replace")
            data_start = topic_start + top_len
            if qos > 0:
                data_start += 2
            p_data = packet_bytes[data_start:]
            node = parse_live_mqtt_packet(topic=topic_str, payload_bytes_or_str=p_data, apply_privacy_fuzz=False)
            if node:
                collected.append(node)

    assert len(collected) == 2
    assert collected[0].node_id == "!large01"
    assert collected[0].long_name == "A" * 150
    assert collected[1].node_id == "!small02"

