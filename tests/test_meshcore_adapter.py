"""Unit tests for MeshCore and Reticulum identity announce telemetry adapter.

Validates:
1. MeshCoreAnnounce Pydantic model validation (hex hash, coordinate bounds, defaults).
2. parse_meshcore_announces with JSON payloads and dictionaries.
3. Skipping announcements lacking geographic coordinates.
4. export_meshcore_announces serialization into standard Reticulum announce schema.
5. Roundtrip conversion and insertion into UnifiedTelemetryCache in SQLite memory mode.
"""

from __future__ import annotations

import json
import pytest
from pydantic import ValidationError

from meshscout.core.contracts import Coordinate, RegionalBounds
from meshscout.adapters.telemetry_cache import TelemetryNode, UnifiedTelemetryCache
from meshscout.adapters.meshcore import (
    MeshCoreAnnounce,
    export_meshcore_announces,
    parse_meshcore_announces,
)


def test_meshcore_announce_validation():
    """Verify MeshCoreAnnounce enforces valid hex hash and coordinate boundaries."""
    # 1. Valid 16-hex character destination hash
    announce1 = MeshCoreAnnounce(
        destination_hash="3b84f29a0f4e245a",
        name="Mansfield-RNS",
        interface="LoRaInterface",
        hops=1,
        coordinate=Coordinate(lat=44.5435, lon=-72.8140, elevation_m=1339.0),
        snr_db=12.4,
        rssi_dbm=-75.0,
        timestamp_iso="2026-10-30T12:00:00Z",
    )
    assert announce1.destination_hash == "3b84f29a0f4e245a"
    assert announce1.name == "Mansfield-RNS"
    assert announce1.interface == "LoRaInterface"
    assert announce1.hops == 1
    assert announce1.coordinate is not None
    assert announce1.coordinate.lat == pytest.approx(44.5435)

    # 2. Valid 32-hex character destination hash
    announce2 = MeshCoreAnnounce(
        destination_hash="3b84f29a0f4e245a8e1b2c3d4e5f6789",
        name="Burlington-Hub",
        lat=44.4759,
        lon=-73.2121,
        elevation_m=60.0,
    )
    assert announce2.coordinate is not None
    assert announce2.coordinate.elevation_m == 60.0

    # 3. Hash too short (< 16 hex characters)
    with pytest.raises(ValidationError):
        MeshCoreAnnounce(
            destination_hash="1234abcd",
            name="Short-Node",
            coordinate=Coordinate(lat=44.0, lon=-72.0),
        )

    # 4. Hash containing non-hex characters
    with pytest.raises(ValidationError):
        MeshCoreAnnounce(
            destination_hash="not_valid_hex_hash!!",
            name="Bad-Hex-Node",
            coordinate=Coordinate(lat=44.0, lon=-72.0),
        )

    # 5. Invalid latitude out of WGS84 range
    with pytest.raises(ValidationError):
        MeshCoreAnnounce(
            destination_hash="3b84f29a0f4e245a",
            name="OutOfBounds-Node",
            coordinate=Coordinate(lat=105.0, lon=-72.0),
        )


def test_parse_meshcore_announces_json_string():
    """Verify parsing valid JSON text payload with multiple announcement records."""
    raw_json = json.dumps([
        {
            "destination_hash": "e4a1b2c3d4e5f601",
            "name": "Burlington Reticulum Core Hub",
            "interface": "TCPClientInterface",
            "hops": 2,
            "coordinate": {"lat": 44.4780, "lon": -73.2140, "elevation_m": 55.0},
            "snr_db": 11.5,
            "rssi_dbm": -71.0,
            "timestamp_iso": "2026-10-30T11:53:00Z",
        },
        {
            "destination_hash": "9f8e7d6c5b4a3210deadbeef",
            "name": "Stowe",
            "interface": "AutoInterface",
            "hops": 0,
            "lat": 44.4654,
            "lon": -72.6874,
            "elevation_m": 250.0,
        },
    ])

    nodes = parse_meshcore_announces(raw_json, default_channel="Custom-MeshCore")
    assert len(nodes) == 2

    # Verify node 1
    n1 = nodes[0]
    assert n1.node_id == "mcore:e4a1b2c3d4e5f601"
    assert n1.protocol == "meshcore"
    assert n1.short_name == "Burlingt"  # Truncated to 8 chars
    assert n1.long_name == "Burlington Reticulum Core Hub"
    assert n1.coordinate.lat == pytest.approx(44.4780)
    assert n1.coordinate.lon == pytest.approx(-73.2140)
    assert n1.hops_away == 2
    assert n1.snr_db == 11.5
    assert n1.rssi_dbm == -71.0
    assert n1.hardware_model == "Reticulum / TCPClientInterface"
    assert n1.channel == "Custom-MeshCore"
    assert n1.last_heard_iso == "2026-10-30T11:53:00Z"

    # Verify node 2
    n2 = nodes[1]
    assert n2.node_id == "mcore:9f8e7d6c5b4a3210"
    assert n2.short_name == "Stowe"  # len <= 8 preserved
    assert n2.long_name == "Stowe"
    assert n2.hardware_model == "Reticulum / AutoInterface"
    assert n2.channel == "Custom-MeshCore"
    assert n2.last_heard_iso.endswith("Z") or "+" in n2.last_heard_iso


def test_parse_meshcore_announces_skips_missing_coordinates():
    """Verify announcements without geographic coordinates are skipped gracefully."""
    sample_data = [
        # Node with coordinate - should be retained
        {
            "destination_hash": "aabbccddeeff0011",
            "name": "Mt Washington RNS",
            "coordinate": {"lat": 44.2710, "lon": -71.3020, "elevation_m": 1915.0},
        },
        # Node missing coordinate altogether - should be skipped
        {
            "destination_hash": "1122334455667788",
            "name": "Headless Gateway",
            "interface": "LoRaInterface",
        },
        # Node with None coordinate - should be skipped
        {
            "destination_hash": "9988776655443322",
            "name": "Stationary Server",
            "coordinate": None,
        },
        # Malformed record (not a valid announce) - should be skipped
        {
            "destination_hash": "short",
            "name": "Invalid",
        },
    ]

    nodes = parse_meshcore_announces(sample_data)
    assert len(nodes) == 1
    assert nodes[0].node_id == "mcore:aabbccddeeff0011"
    assert nodes[0].long_name == "Mt Washington RNS"

    # Invalid string json returns empty list
    assert parse_meshcore_announces("not valid json") == []


def test_export_meshcore_announces_serialization():
    """Verify exporting cached TelemetryNode objects into standard Reticulum announce dicts."""
    nodes = [
        TelemetryNode(
            node_id="mcore:2233445566778899",
            protocol="meshcore",
            short_name="RNS-PLAT",
            long_name="Plattsburgh Reticulum Gateway",
            coordinate=Coordinate(lat=44.7010, lon=-73.4550, elevation_m=45.0),
            hops_away=1,
            snr_db=10.0,
            rssi_dbm=-74.0,
            hardware_model="Reticulum / LoRaInterface",
            channel="MeshCore-LoRa",
            last_heard_iso="2026-10-30T11:46:00Z",
        ),
        TelemetryNode(
            node_id="rns:feedfacecafe0042",
            protocol="meshcore",
            short_name="RNS-MTLR",
            long_name="Montreal Mont Royal Reticulum Node",
            coordinate=Coordinate(lat=45.5050, lon=-73.5850, elevation_m=230.0),
            hops_away=0,
            snr_db=11.2,
            rssi_dbm=-72.0,
            hardware_model="Reticulum / TCPClientInterface",
            channel="MeshCore-LoRa",
            last_heard_iso="2026-10-30T11:54:30Z",
        ),
    ]

    exported = export_meshcore_announces(nodes)
    assert len(exported) == 2

    # First exported dict
    e1 = exported[0]
    assert e1["destination_hash"] == "2233445566778899"
    assert e1["name"] == "Plattsburgh Reticulum Gateway"
    assert e1["interface"] == "LoRaInterface"
    assert e1["hops"] == 1
    assert e1["lat"] == pytest.approx(44.7010)
    assert e1["lon"] == pytest.approx(-73.4550)
    assert e1["coordinate"]["elevation_m"] == 45.0
    assert e1["snr_db"] == 10.0
    assert e1["rssi_dbm"] == -74.0
    assert e1["timestamp_iso"] == "2026-10-30T11:46:00Z"

    # Second exported dict
    e2 = exported[1]
    assert e2["destination_hash"] == "feedfacecafe0042"
    assert e2["name"] == "Montreal Mont Royal Reticulum Node"
    assert e2["interface"] == "TCPClientInterface"
    assert e2["hops"] == 0


def test_roundtrip_conversion_and_cache_insertion():
    """Verify end-to-end roundtrip parsing, export, and UnifiedTelemetryCache SQLite persistence."""
    announces = [
        {
            "destination_hash": "3344556677889900",
            "name": "Sherbrooke Eastern Townships RNS Repeater",
            "interface": "LoRaInterface",
            "hops": 1,
            "coordinate": {"lat": 45.4050, "lon": -71.8910, "elevation_m": 185.0},
            "snr_db": 7.8,
            "rssi_dbm": -82.0,
            "timestamp_iso": "2026-10-30T11:42:30Z",
        },
        {
            "destination_hash": "aabb112233445566",
            "name": "Waterbury RNS Node",
            "interface": "AutoInterface",
            "hops": 0,
            "coordinate": {"lat": 44.3378, "lon": -72.7562, "elevation_m": 140.0},
            "snr_db": 14.1,
            "rssi_dbm": -66.0,
            "timestamp_iso": "2026-10-30T11:48:00Z",
        },
    ]

    # 1. Parse into TelemetryNodes
    parsed_nodes = parse_meshcore_announces(announces)
    assert len(parsed_nodes) == 2

    # 2. Export into announce dicts
    exported = export_meshcore_announces(parsed_nodes)
    assert len(exported) == 2

    # 3. Re-parse exported dictionaries
    reloaded_nodes = parse_meshcore_announces(exported)
    assert len(reloaded_nodes) == 2
    for orig, reloaded in zip(parsed_nodes, reloaded_nodes):
        assert orig.node_id == reloaded.node_id
        assert orig.protocol == reloaded.protocol == "meshcore"
        assert orig.coordinate.lat == pytest.approx(reloaded.coordinate.lat)
        assert orig.coordinate.lon == pytest.approx(reloaded.coordinate.lon)
        assert orig.hops_away == reloaded.hops_away
        assert orig.hardware_model == reloaded.hardware_model

    # 4. Insert into UnifiedTelemetryCache in SQLite :memory: mode
    cache = UnifiedTelemetryCache(db_path=":memory:")
    inserted_count = cache.bulk_upsert_nodes(parsed_nodes)
    assert inserted_count == 2

    # Query back nodes filtered by protocol="meshcore"
    stored_nodes = cache.query_nodes(protocol="meshcore")
    assert len(stored_nodes) == 2
    node_ids = {n.node_id for n in stored_nodes}
    assert "mcore:3344556677889900" in node_ids
    assert "mcore:aabb112233445566" in node_ids

    # Query with spatial bounds around Waterbury VT
    waterbury_bounds = RegionalBounds(
        name="Waterbury Area",
        min_lat=44.20,
        max_lat=44.40,
        min_lon=-72.90,
        max_lon=-72.60,
    )
    waterbury_nodes = cache.query_nodes(bounds=waterbury_bounds, protocol="meshcore")
    assert len(waterbury_nodes) == 1
    assert waterbury_nodes[0].node_id == "mcore:aabb112233445566"
    assert waterbury_nodes[0].short_name == "Waterbur"

    cache.close()
