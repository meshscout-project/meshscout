"""Test suite for UnifiedTelemetryCache and TelemetryNode (TASK-1097)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from meshscout.adapters.telemetry_cache import TelemetryNode, UnifiedTelemetryCache
from meshscout.core.contracts import Coordinate, RegionalBounds


@pytest.fixture
def memory_cache() -> UnifiedTelemetryCache:
    """Fixture providing an ephemeral in-memory UnifiedTelemetryCache."""
    cache = UnifiedTelemetryCache(":memory:")
    yield cache
    cache.close()


@pytest.fixture
def sample_node() -> TelemetryNode:
    """Fixture providing a sample Meshtastic TelemetryNode."""
    return TelemetryNode(
        node_id="!24a1b001",
        protocol="meshtastic",
        short_name="BURL-1",
        long_name="Burlington Waterfront Gateway",
        coordinate=Coordinate(lat=44.4759, lon=-73.2121, elevation_m=60.0),
        battery_pct=95.0,
        voltage=4.12,
        snr_db=9.5,
        rssi_dbm=-78.0,
        hops_away=0,
        hardware_model="Heltec V3",
        channel="LongFast",
        last_heard_iso="2026-10-30T11:45:00Z",
    )


def test_telemetry_node_flat_coordinate_init() -> None:
    """Verify TelemetryNode validator accepts flat lat/lon/elevation_m dict inputs."""
    node = TelemetryNode.model_validate({
        "node_id": "test_node_flat",
        "protocol": "MeshCore",
        "short_name": "FLAT",
        "long_name": "Flat Coordinate Test",
        "lat": 44.5,
        "lon": -73.2,
        "elevation_m": 120.0,
        "last_heard_iso": "2026-10-30T12:00:00Z",
    })
    assert node.protocol == "meshcore"  # normalized to lowercase
    assert node.lat == 44.5
    assert node.lon == -73.2
    assert node.elevation_m == 120.0
    assert node.coordinate.lat == 44.5


def test_upsert_and_get_node(memory_cache: UnifiedTelemetryCache, sample_node: TelemetryNode) -> None:
    """Verify single node upsert and retrieval."""
    assert memory_cache.get_node(sample_node.node_id) is None

    success = memory_cache.upsert_node(sample_node)
    assert success is True

    retrieved = memory_cache.get_node(sample_node.node_id)
    assert retrieved is not None
    assert retrieved.node_id == sample_node.node_id
    assert retrieved.protocol == "meshtastic"
    assert retrieved.short_name == "BURL-1"
    assert retrieved.long_name == "Burlington Waterfront Gateway"
    assert retrieved.coordinate.lat == pytest.approx(44.4759)
    assert retrieved.coordinate.lon == pytest.approx(-73.2121)
    assert retrieved.coordinate.elevation_m == pytest.approx(60.0)
    assert retrieved.battery_pct == pytest.approx(95.0)
    assert retrieved.voltage == pytest.approx(4.12)
    assert retrieved.snr_db == pytest.approx(9.5)
    assert retrieved.rssi_dbm == pytest.approx(-78.0)
    assert retrieved.hops_away == 0
    assert retrieved.hardware_model == "Heltec V3"
    assert retrieved.channel == "LongFast"
    assert retrieved.last_heard_iso == "2026-10-30T11:45:00Z"


def test_update_existing_node(memory_cache: UnifiedTelemetryCache, sample_node: TelemetryNode) -> None:
    """Verify upserting an existing node updates fields in place without duplicates."""
    memory_cache.upsert_node(sample_node)

    updated_node = TelemetryNode(
        node_id=sample_node.node_id,
        protocol="meshtastic",
        short_name="BURL-1-UPD",
        long_name="Burlington Waterfront Gateway (Updated)",
        coordinate=Coordinate(lat=44.4760, lon=-73.2120, elevation_m=62.0),
        battery_pct=85.0,
        voltage=3.95,
        snr_db=11.2,
        rssi_dbm=-74.0,
        hops_away=1,
        hardware_model="Heltec V3",
        channel="LongFast",
        last_heard_iso="2026-10-30T12:15:00Z",
    )
    memory_cache.upsert_node(updated_node)

    retrieved = memory_cache.get_node(sample_node.node_id)
    assert retrieved is not None
    assert retrieved.short_name == "BURL-1-UPD"
    assert retrieved.battery_pct == pytest.approx(85.0)
    assert retrieved.last_heard_iso == "2026-10-30T12:15:00Z"

    # Confirm only one record in database
    all_nodes = memory_cache.query_nodes()
    assert len(all_nodes) == 1


def test_bulk_upsert_nodes(memory_cache: UnifiedTelemetryCache) -> None:
    """Verify bulk upserting multiple nodes."""
    nodes = [
        TelemetryNode(
            node_id=f"node_{i}",
            protocol="meshtastic" if i % 2 == 0 else "meshcore",
            short_name=f"N{i}",
            long_name=f"Node Number {i}",
            coordinate=Coordinate(lat=44.0 + (i * 0.05), lon=-73.0 - (i * 0.05), elevation_m=100.0),
            last_heard_iso=f"2026-10-30T11:{i:02d}:00Z",
        )
        for i in range(10)
    ]
    count = memory_cache.bulk_upsert_nodes(nodes)
    assert count == 10

    queried = memory_cache.query_nodes(limit=100)
    assert len(queried) == 10
    # Verified sorted descending by last_heard_iso
    assert queried[0].last_heard_iso == "2026-10-30T11:09:00Z"
    assert queried[-1].last_heard_iso == "2026-10-30T11:00:00Z"


def test_spatial_bounding_box_filtering(memory_cache: UnifiedTelemetryCache) -> None:
    """Verify queries with explicit RegionalBounds filter out-of-bounds nodes."""
    nodes = [
        TelemetryNode(
            node_id="inside_node",
            protocol="meshtastic",
            short_name="IN",
            long_name="Inside Region Node",
            coordinate=Coordinate(lat=44.5, lon=-73.0, elevation_m=100.0),
            last_heard_iso="2026-10-30T12:00:00Z",
        ),
        TelemetryNode(
            node_id="outside_lat_node",
            protocol="meshtastic",
            short_name="OUT_LAT",
            long_name="Outside Lat Node",
            coordinate=Coordinate(lat=46.5, lon=-73.0, elevation_m=100.0),
            last_heard_iso="2026-10-30T12:00:00Z",
        ),
        TelemetryNode(
            node_id="outside_lon_node",
            protocol="meshtastic",
            short_name="OUT_LON",
            long_name="Outside Lon Node",
            coordinate=Coordinate(lat=44.5, lon=-75.0, elevation_m=100.0),
            last_heard_iso="2026-10-30T12:00:00Z",
        ),
    ]
    memory_cache.bulk_upsert_nodes(nodes)

    bounds = RegionalBounds(
        name="Test_Box",
        min_lat=44.0,
        max_lat=45.0,
        min_lon=-73.5,
        max_lon=-72.5,
    )
    result = memory_cache.query_nodes(bounds=bounds)
    assert len(result) == 1
    assert result[0].node_id == "inside_node"


def test_regional_buffering_vt_cross_border(memory_cache: UnifiedTelemetryCache) -> None:
    """Verify regional buffering returns sites within 20km cross-border and excludes distant ones."""
    memory_cache.seed_from_sample_fixture()

    # Query with state_code='VT' and buffer_km=20.0
    buffered_nodes = memory_cache.query_nodes(state_code="VT", buffer_km=20.0, limit=200)
    buffered_node_ids = {node.node_id for node in buffered_nodes}

    # Cross-border sites within 20km:
    # Plattsburgh NY (!46c3d001) and Mont Sutton QC (!57d4e004) MUST be present
    assert "!46c3d001" in buffered_node_ids, "Plattsburgh NY should be included within 20km VT buffer"
    assert "!57d4e004" in buffered_node_ids, "Mont Sutton QC should be included within 20km VT buffer"

    # Distant NY and QC sites MUST be excluded:
    # Lake Placid NY (!46c3d002), Saranac Lake NY (!46c3d003), Montreal Mont Royal QC (!57d4e001)
    assert "!46c3d002" not in buffered_node_ids, "Lake Placid NY should be excluded outside 20km VT buffer"
    assert "!46c3d003" not in buffered_node_ids, "Saranac Lake NY should be excluded outside 20km VT buffer"
    assert "!57d4e001" not in buffered_node_ids, "Montreal Mont Royal should be excluded outside 20km VT buffer"

    # In unbuffered VT (buffer_km=0.0), Plattsburgh NY and Mont Sutton QC must NOT be included
    unbuffered_nodes = memory_cache.query_nodes(state_code="VT", buffer_km=0.0, limit=200)
    unbuffered_node_ids = {node.node_id for node in unbuffered_nodes}
    assert "!46c3d001" not in unbuffered_node_ids, "Plattsburgh NY should not be in unbuffered VT"
    assert "!57d4e004" not in unbuffered_node_ids, "Mont Sutton QC should not be in unbuffered VT"


def test_protocol_filtering_and_counts(memory_cache: UnifiedTelemetryCache) -> None:
    """Verify filtering by protocol ('meshtastic' vs 'meshcore') and protocol aggregation."""
    memory_cache.seed_from_sample_fixture()

    meshtastic_nodes = memory_cache.query_nodes(protocol="meshtastic", limit=100)
    assert len(meshtastic_nodes) > 0
    assert all(n.protocol == "meshtastic" for n in meshtastic_nodes)

    meshcore_nodes = memory_cache.query_nodes(protocol="meshcore", limit=100)
    assert len(meshcore_nodes) > 0
    assert all(n.protocol == "meshcore" for n in meshcore_nodes)

    # Case-insensitive protocol matching
    upper_meshtastic = memory_cache.query_nodes(protocol="MESHTASTIC", limit=100)
    assert len(upper_meshtastic) == len(meshtastic_nodes)

    # Protocol count aggregation
    counts = memory_cache.count_nodes_by_protocol()
    assert counts.get("meshtastic", 0) == 29
    assert counts.get("meshcore", 0) == 7
    assert sum(counts.values()) == 36


def test_seed_from_sample_fixture(tmp_path: Path) -> None:
    """Verify seeding from default fixture and custom fixture file."""
    db_file = tmp_path / "test_telemetry.db"
    cache = UnifiedTelemetryCache(db_file)

    try:
        count = cache.seed_from_sample_fixture()
        assert count == 36

        # Test seeding from a custom fixture file
        custom_fixture = tmp_path / "custom_nodes.json"
        custom_fixture.write_text(
            json.dumps([
                {
                    "node_id": "custom_1",
                    "protocol": "meshtastic",
                    "short_name": "CUST1",
                    "long_name": "Custom Test 1",
                    "lat": 44.1,
                    "lon": -72.8,
                    "elevation_m": 500.0,
                    "last_heard_iso": "2026-10-30T12:00:00Z",
                }
            ]),
            encoding="utf-8",
        )
        custom_count = cache.seed_from_sample_fixture(custom_fixture)
        assert custom_count == 1
        assert cache.get_node("custom_1") is not None

        # Test non-existent fixture
        with pytest.raises(FileNotFoundError):
            cache.seed_from_sample_fixture(tmp_path / "non_existent.json")
    finally:
        cache.close()


def test_context_manager_and_closure() -> None:
    """Verify context manager lifecycle and error on closed cache."""
    with UnifiedTelemetryCache(":memory:") as cache:
        cache.upsert_node(
            TelemetryNode(
                node_id="cm_1",
                protocol="meshtastic",
                short_name="CM",
                long_name="Context Manager Node",
                coordinate=Coordinate(lat=44.0, lon=-73.0, elevation_m=50.0),
                last_heard_iso="2026-10-30T12:00:00Z",
            )
        )
        assert cache.get_node("cm_1") is not None

    # After exiting context, connection is closed
    with pytest.raises(RuntimeError, match="Database connection is closed"):
        cache.query_nodes()
