"""Unit tests for Meshtastic MQTT telemetry adapter and unobserved population gap analyzer."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from meshscout.core.contracts import Coordinate, SiteCandidate, SiteType
from meshscout.core.registry import DeploymentStatus, RegisteredNode, _fuzz_coordinate
from meshscout.adapters.mqtt import (
    MQTTNodeTelemetry,
    UnobservedAreaReport,
    UnobservedTownGap,
    analyze_unobserved_areas,
    ingest_mqtt_packets,
    load_mqtt_fixture,
)


def _sample_candidate_sites() -> list[SiteCandidate]:
    """Sample candidate repeater sites for gap bridging tests."""
    return [
        SiteCandidate(
            site_id="VT-MANS-01",
            name="Mount Mansfield Summit Ridge",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=10.0,
            has_grid_power=False,
            solar_exposure_pct=95.0,
        ),
        SiteCandidate(
            site_id="VT-BOLT-01",
            name="Bolton Mountain Peak",
            location=Coordinate(lat=44.4890, lon=-72.8870, elevation_m=1120.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=8.0,
            has_grid_power=False,
            solar_exposure_pct=90.0,
        ),
        SiteCandidate(
            site_id="VT-SMUG-01",
            name="Smugglers Notch Pass Ridge",
            location=Coordinate(lat=44.5550, lon=-72.7950, elevation_m=660.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=6.0,
            has_grid_power=False,
            solar_exposure_pct=85.0,
        ),
    ]


def _sample_reference_towns() -> dict[str, dict]:
    """Sample reference towns covering both observed clusters and unobserved valley corridors."""
    return {
        # Observed cluster towns (have nearby heard telemetry in fixture)
        "Burlington": {
            "name": "Burlington",
            "county": "Chittenden",
            "lat": 44.4759,
            "lon": -73.2121,
            "elevation_m": 61.0,
            "population": 44743,
        },
        "South Burlington": {
            "name": "South Burlington",
            "county": "Chittenden",
            "lat": 44.4670,
            "lon": -73.1710,
            "elevation_m": 100.0,
            "population": 20292,
        },
        "Essex Junction": {
            "name": "Essex Junction",
            "county": "Chittenden",
            "lat": 44.4906,
            "lon": -73.1112,
            "elevation_m": 108.0,
            "population": 10590,
        },
        "Williston": {
            "name": "Williston",
            "county": "Chittenden",
            "lat": 44.4375,
            "lon": -73.0685,
            "elevation_m": 132.0,
            "population": 10103,
        },
        "Stowe": {
            "name": "Stowe",
            "county": "Lamoille",
            "lat": 44.4654,
            "lon": -72.6874,
            "elevation_m": 220.0,
            "population": 5223,
        },
        "Montpelier": {
            "name": "Montpelier",
            "county": "Washington",
            "lat": 44.2601,
            "lon": -72.5754,
            "elevation_m": 160.0,
            "population": 8074,
        },
        # Unobserved rural valley corridors (no heard nodes in sample fixture)
        "Jeffersonville": {
            "name": "Jeffersonville",
            "county": "Lamoille",
            "lat": 44.6436,
            "lon": -72.8270,
            "elevation_m": 145.0,
            "population": 729,
        },
        "Cambridge": {
            "name": "Cambridge",
            "county": "Lamoille",
            "lat": 44.6420,
            "lon": -72.8680,
            "elevation_m": 140.0,
            "population": 3839,
        },
        "Huntington": {
            "name": "Huntington",
            "county": "Chittenden",
            "lat": 44.3189,
            "lon": -72.9904,
            "elevation_m": 190.0,
            "population": 1934,
        },
        "Northfield Falls": {
            "name": "Northfield Falls",
            "county": "Washington",
            "lat": 44.1750,
            "lon": -72.6500,
            "elevation_m": 200.0,
            "population": 250,
        },
    }


class TestMQTTParser:
    """Tests for pure-function ingestion of JSON arrays and NDJSON Meshtastic telemetry."""

    def test_parse_json_array(self) -> None:
        payload = [
            {
                "packet_id": "pkt_01",
                "from_node_id": "!4401a01",
                "sender_short_name": "BURL1",
                "sender_long_name": "Burlington Waterfront",
                "lat": 44.4759,
                "lon": -73.2121,
                "elevation_m": 61.0,
                "rssi_dbm": -82.0,
                "snr_db": 8.0,
                "timestamp_iso": "2026-10-28T12:00:00Z",
                "channel_name": "LongFast",
                "hop_limit": 3,
            }
        ]
        res = ingest_mqtt_packets(json.dumps(payload), apply_privacy_fuzz=False)
        assert res.ok is True
        assert res.value is not None
        records = res.value
        assert len(records) == 1
        item = records[0]
        assert item.node_id == "!4401a01"
        assert item.short_name == "BURL1"
        assert item.long_name == "Burlington Waterfront"
        assert item.coordinate.lat == 44.4759
        assert item.coordinate.lon == -73.2121
        assert item.coordinate.elevation_m == 61.0
        assert item.rssi_dbm == -82.0
        assert item.snr_db == 8.0
        assert item.channel == "LongFast"
        assert item.is_synthetic is False

    def test_parse_ndjson_stream(self) -> None:
        ndjson_lines = (
            '{"packet_id": "p1", "from_node_id": "!1", "sender_short_name": "N1", "lat": 44.49, "lon": -73.11, "rssi_dbm": -80.0, "snr_db": 9.0}\n'
            '{"packet_id": "p2", "from_node_id": "!2", "sender_short_name": "N2", "lat": 44.47, "lon": -73.17, "rssi_dbm": -85.0, "snr_db": 7.0}\n'
        )
        res = ingest_mqtt_packets(ndjson_lines, apply_privacy_fuzz=False)
        assert res.ok is True
        assert res.value is not None
        records = res.value
        assert len(records) == 2
        assert records[0].node_id == "!1"
        assert records[1].node_id == "!2"

    def test_coordinate_privacy_fuzzing(self) -> None:
        payload = [
            {
                "packet_id": "p_fuzz",
                "from_node_id": "!priv01",
                "sender_short_name": "PRIV",
                "lat": 44.476123,
                "lon": -73.212789,
                "elevation_m": 61.4,
                "rssi_dbm": -85.0,
                "snr_db": 6.0,
            }
        ]
        # Unfuzzed
        res_raw = ingest_mqtt_packets(json.dumps(payload), apply_privacy_fuzz=False)
        assert res_raw.ok is True
        assert res_raw.value is not None
        raw_rec = res_raw.value[0]
        assert raw_rec.coordinate.lat == 44.476123
        assert raw_rec.coordinate.lon == -73.212789

        # Fuzzed (~200m grid snap)
        res_fuzzed = ingest_mqtt_packets(json.dumps(payload), apply_privacy_fuzz=True)
        assert res_fuzzed.ok is True
        assert res_fuzzed.value is not None
        fuzzed_rec = res_fuzzed.value[0]
        expected_fuzzed = _fuzz_coordinate(Coordinate(lat=44.476123, lon=-73.212789, elevation_m=61.4))
        assert fuzzed_rec.coordinate.lat == expected_fuzzed.lat
        assert fuzzed_rec.coordinate.lon == expected_fuzzed.lon
        assert fuzzed_rec.coordinate.elevation_m == expected_fuzzed.elevation_m

    def test_parse_empty_and_whitespace(self) -> None:
        res = ingest_mqtt_packets("   \n   \t  ")
        assert res.ok is True
        assert res.value == []

    def test_parse_invalid_ndjson_error(self) -> None:
        bad_stream = '{"valid": 1}\n{not valid json}'
        res = ingest_mqtt_packets(bad_stream)
        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "PARSE_ERROR"

    def test_parse_missing_coordinates_error(self) -> None:
        payload = [{"packet_id": "p_no_coord", "from_node_id": "!nocoord"}]
        res = ingest_mqtt_packets(json.dumps(payload))
        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "MISSING_COORDINATES"


class TestMQTTFixture:
    """Tests for loading and validating the synthetic Vermont live sample fixture."""

    def test_load_mqtt_fixture_default(self) -> None:
        res = load_mqtt_fixture()
        assert res.ok is True, f"Failed loading fixture: {res.error}"
        assert res.value is not None
        packets = res.value

        # Requirement: 25-35 packets
        assert 25 <= len(packets) <= 35
        assert len(packets) == 30

        # Requirement: all packets must have is_synthetic=True
        assert all(p.is_synthetic is True for p in packets)

        # Check coverage across key towns
        node_ids = {p.node_id for p in packets}
        assert len(node_ids) == 30  # All unique nodes

        # Verify presence of nodes from distinct clusters
        short_names = [p.short_name for p in packets]
        assert any(s.startswith("BURL") for s in short_names)
        assert any(s.startswith("SBUR") for s in short_names)
        assert any(s.startswith("ESX") for s in short_names)
        assert any(s.startswith("WLL") for s in short_names)
        assert any(s.startswith("STW") for s in short_names)
        assert any(s.startswith("MON") for s in short_names)

    def test_load_mqtt_fixture_custom_path(self, tmp_path: Path) -> None:
        custom_file = tmp_path / "custom_mqtt.json"
        custom_content = {
            "synthetic": True,
            "packets": [
                {
                    "packet_id": "custom_1",
                    "from_node_id": "!cust01",
                    "sender_short_name": "CUST",
                    "lat": 44.5,
                    "lon": -73.0,
                    "elevation_m": 150.0,
                    "rssi_dbm": -80.0,
                    "snr_db": 5.0,
                }
            ],
        }
        custom_file.write_text(json.dumps(custom_content), encoding="utf-8")
        res = load_mqtt_fixture(custom_file)
        assert res.ok is True
        assert res.value is not None
        assert len(res.value) == 1
        assert res.value[0].is_synthetic is True

    def test_load_mqtt_fixture_not_found(self) -> None:
        res = load_mqtt_fixture(Path("nonexistent_path_xyz.json"))
        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "FILE_NOT_FOUND"


class TestUnobservedGapAnalysis:
    """Tests for spatial gap analysis and candidate bridge site ranking."""

    def test_analyze_unobserved_valley_gaps(self) -> None:
        # Load heard telemetry from synthetic fixture (covers Burlington, S. Burlington, Essex, Williston, Stowe, Montpelier)
        fixture_res = load_mqtt_fixture()
        assert fixture_res.ok is True
        heard_nodes = fixture_res.value or []

        candidate_sites = _sample_candidate_sites()
        ref_towns = _sample_reference_towns()

        res = analyze_unobserved_areas(
            heard_nodes=heard_nodes,
            registry_active_nodes=[],
            candidate_sites=candidate_sites,
            reference_towns=ref_towns,
            coverage_radius_km=8.0,
        )

        assert res.ok is True
        assert res.value is not None
        report = res.value

        assert report.total_towns_checked == 10
        assert report.observed_towns_count == 6
        assert report.unobserved_towns_count == 4

        unobserved_names = {gap.town_name for gap in report.unobserved_gaps}
        assert "Jeffersonville" in unobserved_names
        assert "Cambridge" in unobserved_names
        assert "Huntington" in unobserved_names
        assert "Northfield Falls" in unobserved_names

        # Verified valley gap details
        jeff_gap = next(g for g in report.unobserved_gaps if g.town_name == "Jeffersonville")
        assert jeff_gap.county == "Lamoille"
        assert jeff_gap.nearest_observed_node_distance_km > 8.0
        assert len(jeff_gap.recommended_bridge_sites) > 0

        # Mount Mansfield should bridge Jeffersonville basin
        bridge_ids = {s.site_id for s in jeff_gap.recommended_bridge_sites}
        assert "VT-MANS-01" in bridge_ids

        # Ranked solution sites should list Mansfield as a top bridge repeater
        assert len(report.ranked_solution_sites) > 0
        top_site = report.ranked_solution_sites[0]
        assert "VT-MANS-01" in [s["site_id"] for s in report.ranked_solution_sites]
        assert top_site["towns_covered_count"] >= 1

    def test_active_registry_node_prevents_unobserved_flag(self) -> None:
        """Active registry repeater in Jeffersonville covers the town so it is not flagged."""
        # Create an active registered node deployed directly in Jeffersonville
        active_jeff_node = RegisteredNode(
            site_id="NODE-JEFF-01",
            name="Jeffersonville Community Repeater",
            coordinate=Coordinate(lat=44.6436, lon=-72.8270, elevation_m=150.0),
            height_agl_m=12.0,
            status=DeploymentStatus.ACTIVE_ON_AIR,
            updated_at="2026-10-28T10:00:00Z",
        )

        ref_towns = {
            "Jeffersonville": {
                "name": "Jeffersonville",
                "county": "Lamoille",
                "lat": 44.6436,
                "lon": -72.8270,
                "elevation_m": 145.0,
            }
        }

        # Case 1: No heard nodes and no active registry nodes -> flagged unobserved
        res_no_nodes = analyze_unobserved_areas(
            heard_nodes=[],
            registry_active_nodes=[],
            candidate_sites=[],
            reference_towns=ref_towns,
            coverage_radius_km=8.0,
        )
        assert res_no_nodes.ok is True
        assert res_no_nodes.value.unobserved_towns_count == 1
        assert res_no_nodes.value.observed_towns_count == 0

        # Case 2: Active registered node present -> observed!
        res_with_active = analyze_unobserved_areas(
            heard_nodes=[],
            registry_active_nodes=[active_jeff_node],
            candidate_sites=[],
            reference_towns=ref_towns,
            coverage_radius_km=8.0,
        )
        assert res_with_active.ok is True
        assert res_with_active.value.unobserved_towns_count == 0
        assert res_with_active.value.observed_towns_count == 1
        assert len(res_with_active.value.unobserved_gaps) == 0

    def test_blocked_registry_node_does_not_count_as_active(self) -> None:
        """Blocked or decommissioned registry node must NOT provide coverage."""
        blocked_node = RegisteredNode(
            site_id="NODE-JEFF-BLOCKED",
            name="Offline Decommissioned Site",
            coordinate=Coordinate(lat=44.6436, lon=-72.8270, elevation_m=150.0),
            height_agl_m=12.0,
            status=DeploymentStatus.BLOCKED,
            updated_at="2026-10-28T10:00:00Z",
        )

        ref_towns = {
            "Jeffersonville": {
                "name": "Jeffersonville",
                "county": "Lamoille",
                "lat": 44.6436,
                "lon": -72.8270,
                "elevation_m": 145.0,
            }
        }

        res = analyze_unobserved_areas(
            heard_nodes=[],
            registry_active_nodes=[blocked_node],
            candidate_sites=[],
            reference_towns=ref_towns,
            coverage_radius_km=8.0,
        )
        assert res.ok is True
        assert res.value.unobserved_towns_count == 1
        assert res.value.observed_towns_count == 0

    def test_invalid_coverage_radius(self) -> None:
        res = analyze_unobserved_areas(
            heard_nodes=[],
            registry_active_nodes=[],
            candidate_sites=[],
            reference_towns={},
            coverage_radius_km=-5.0,
        )
        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "INVALID_COVERAGE_RADIUS"
