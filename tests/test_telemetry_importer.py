"""Unit tests for wardriving telemetry ingestion, log parsing, and ground-truth clutter calibration."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from meshscout.core.contracts import Coordinate, RadioConfig, SiteCandidate, SiteType
from meshscout.core.telemetry import (
    ClutterCalibrationResult,
    PacketCalibrationMatch,
    WardrivePacket,
    calibrate_ground_truth_clutter,
    parse_wardrive_log,
)


def _mansfield_site() -> SiteCandidate:
    """Fixture returning Mount Mansfield high-site candidate."""
    return SiteCandidate(
        site_id="VT-MANS-01",
        name="Mount Mansfield Summit Ridge",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=10.0,
    )


class TestWardriveParser:
    """Tests for parsing JSON and CSV wardrive logs into validated WardrivePacket models."""

    def test_parse_json_fixture_sample(self) -> None:
        fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "wardriving_sample.json"
        assert fixture_path.exists(), f"Missing fixture at {fixture_path}"

        raw_json = fixture_path.read_text(encoding="utf-8")
        res = parse_wardrive_log(raw_json, format_hint="json")

        assert res.ok is True
        assert res.value is not None
        packets = res.value

        assert 15 <= len(packets) <= 20
        assert len(packets) == 18

        first = packets[0]
        assert first.packet_id == "pkt_001"
        assert first.tx_node_id == "VT-MANS-01"
        assert first.rx_node_id == "VT-MOBI-01"
        assert first.rx_coordinate.lat == pytest.approx(44.4906)
        assert first.rx_coordinate.lon == pytest.approx(-73.1112)
        assert first.rx_coordinate.elevation_m == pytest.approx(108.0)
        assert first.rssi_dbm == pytest.approx(-99.0)
        assert first.snr_db == pytest.approx(-3.0)
        assert first.frequency_mhz == pytest.approx(915.0)
        assert first.hop_limit == 3

    def test_parse_csv_standard_format(self) -> None:
        csv_text = (
            "time,lat,lon,elevation,snr,rssi,from,to\n"
            "2026-10-26T14:00:00Z,44.4906,-73.1112,108.0,-2.5,-95.0,VT-MANS-01,VT-MOBI-01\n"
            "2026-10-26T14:05:00Z,44.5050,-72.9800,168.0,3.0,-88.5,VT-MANS-01,VT-MOBI-01\n"
            "2026-10-26T14:10:00Z,44.5275,-72.8950,215.0,6.5,-82.0,VT-MANS-01,VT-MOBI-01\n"
        )

        res_csv = parse_wardrive_log(csv_text, format_hint="csv")
        assert res_csv.ok is True
        assert res_csv.value is not None
        assert len(res_csv.value) == 3

        res_auto = parse_wardrive_log(csv_text, format_hint="auto")
        assert res_auto.ok is True
        assert res_auto.value is not None
        assert len(res_auto.value) == 3

        p2 = res_auto.value[1]
        assert p2.rx_coordinate.lat == pytest.approx(44.5050)
        assert p2.rx_coordinate.lon == pytest.approx(-72.9800)
        assert p2.rx_coordinate.elevation_m == pytest.approx(168.0)
        assert p2.rssi_dbm == pytest.approx(-88.5)
        assert p2.snr_db == pytest.approx(3.0)
        assert p2.tx_node_id == "VT-MANS-01"
        assert p2.rx_node_id == "VT-MOBI-01"

    def test_parse_csv_with_aliases_and_optional_fields(self) -> None:
        csv_text = (
            "timestamp,latitude,longitude,altitude,snr_db,rssi_dbm,sender,receiver,freq,hops,packet_id\n"
            "2026-10-26T15:00:00Z,44.5120,-73.0320,138.0,1.2,-91.0,NODE-A,NODE-B,915.0,2,custom_pkt_42\n"
        )

        res = parse_wardrive_log(csv_text)
        assert res.ok is True
        assert res.value is not None
        assert len(res.value) == 1

        pkt = res.value[0]
        assert pkt.packet_id == "custom_pkt_42"
        assert pkt.tx_node_id == "NODE-A"
        assert pkt.rx_node_id == "NODE-B"
        assert pkt.rssi_dbm == pytest.approx(-91.0)
        assert pkt.snr_db == pytest.approx(1.2)
        assert pkt.hop_limit == 2
        assert pkt.frequency_mhz == pytest.approx(915.0)

    def test_robust_handling_of_malformed_or_out_of_bounds_csv_rows(self) -> None:
        csv_with_errors = (
            "time,lat,lon,elevation,snr,rssi,from,to\n"
            "2026-10-26T14:00:00Z,44.4906,-73.1112,108.0,-2.5,-95.0,VT-MANS-01,VT-MOBI-01\n"
            "2026-10-26T14:01:00Z,bad_lat,-73.1000,110.0,-2.0,-94.0,VT-MANS-01,VT-MOBI-01\n"  # Non-numeric lat
            "2026-10-26T14:02:00Z,999.0,-73.0900,110.0,-2.0,-94.0,VT-MANS-01,VT-MOBI-01\n"   # Out-of-bounds lat > 90
            "2026-10-26T14:03:00Z,44.4950,-300.0,110.0,-2.0,-94.0,VT-MANS-01,VT-MOBI-01\n"   # Out-of-bounds lon < -180
            "2026-10-26T14:04:00Z,44.5000,-73.0800,115.0,nan,-92.0,VT-MANS-01,VT-MOBI-01\n"   # NaN SNR
            "2026-10-26T14:05:00Z,44.5050,-72.9800,168.0,3.0,-88.5,VT-MANS-01,VT-MOBI-01\n"  # Valid row
        )

        res = parse_wardrive_log(csv_with_errors, format_hint="csv")
        assert res.ok is True
        assert res.value is not None
        assert len(res.value) == 2
        assert res.value[0].rx_coordinate.lat == pytest.approx(44.4906)
        assert res.value[1].rx_coordinate.lat == pytest.approx(44.5050)

    def test_robust_handling_of_malformed_json_rows(self) -> None:
        json_data = [
            {
                "time": "2026-10-26T14:00:00Z",
                "lat": 44.4906,
                "lon": -73.1112,
                "elevation": 108.0,
                "snr": -2.0,
                "rssi": -95.0,
                "from": "VT-MANS-01",
                "to": "VT-MOBI-01",
            },
            {
                "time": "2026-10-26T14:01:00Z",
                "lat": 120.0,  # Out-of-bounds
                "lon": -73.1112,
                "rssi": -95.0,
                "snr": -2.0,
            },
            {
                "time": "2026-10-26T14:02:00Z",
                "lat": 44.5275,
                "lon": -72.8950,
                "elevation": 215.0,
                "snr": 5.0,
                "rssi": -83.0,
                "from": "VT-MANS-01",
                "to": "VT-MOBI-01",
            },
        ]

        res = parse_wardrive_log(json.dumps(json_data), format_hint="json")
        assert res.ok is True
        assert res.value is not None
        assert len(res.value) == 2

    def test_empty_and_invalid_inputs_return_error(self) -> None:
        res_empty = parse_wardrive_log("   \n  ")
        assert res_empty.ok is False
        assert res_empty.error is not None
        assert res_empty.error.code == "EMPTY_INPUT"

        res_malformed_json = parse_wardrive_log("{ broken json: [", format_hint="json")
        assert res_malformed_json.ok is False
        assert res_malformed_json.error is not None
        assert res_malformed_json.error.code == "PARSE_ERROR"

        header_only_csv = "time,lat,lon,elevation,snr,rssi,from,to\n"
        res_header_only = parse_wardrive_log(header_only_csv, format_hint="csv")
        assert res_header_only.ok is False
        assert res_header_only.error is not None
        assert res_header_only.error.code == "NO_VALID_PACKETS"


class TestClutterCalibration:
    """Tests for empirical clutter calibration against transmitter sites."""

    def test_calibration_against_mansfield_site(self) -> None:
        fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "wardriving_sample.json"
        packets_res = parse_wardrive_log(fixture_path.read_text(encoding="utf-8"))
        assert packets_res.ok is True
        assert packets_res.value is not None
        packets = packets_res.value

        site = _mansfield_site()
        cal_res = calibrate_ground_truth_clutter(packets=packets, transmitter_site=site)

        assert cal_res.ok is True
        assert cal_res.value is not None
        result: ClutterCalibrationResult = cal_res.value

        assert result.total_packets_ingested == len(packets)
        assert result.matched_packets_count == len(packets)
        assert len(result.matches) == len(packets)

        for match in result.matches:
            assert isinstance(match, PacketCalibrationMatch)
            assert match.packet.tx_node_id == "VT-MANS-01"
            assert match.distance_km > 0.0
            assert match.predicted_rx_power_dbm < 0.0
            assert match.error_db == pytest.approx(
                match.measured_rssi_dbm - match.predicted_rx_power_dbm, abs=1e-3
            )

        assert isinstance(result.mean_error_db, float)
        assert isinstance(result.rmse_db, float)
        assert result.rmse_db >= 0.0
        assert result.recommended_canopy_adjustment_db >= 0.0
        assert result.recommended_clutter_db_per_km >= 0.0

    def test_heavy_foliage_yields_positive_clutter_recommendation(self) -> None:
        """When field RSSI is systematically lower than free-space/ITM prediction,

        canopy adjustment and clutter loss per km must be strictly positive.
        """
        site = _mansfield_site()

        # Generate synthetic packets with heavy foliage loss (measured RSSI ~12-15 dB below ITM)
        heavy_foliage_packets = [
            WardrivePacket(
                packet_id=f"foliage_{i}",
                timestamp=f"2026-10-26T14:{i:02d}:00Z",
                rx_coordinate=Coordinate(
                    lat=44.4906 + i * 0.002,
                    lon=-73.1112 + i * 0.012,
                    elevation_m=110.0 + i * 5.0,
                ),
                tx_node_id="VT-MANS-01",
                rx_node_id="VT-MOBI-01",
                rssi_dbm=-108.0,  # Strongly attenuated
                snr_db=-5.0,
                frequency_mhz=915.0,
            )
            for i in range(10)
        ]

        cal_res = calibrate_ground_truth_clutter(
            packets=heavy_foliage_packets, transmitter_site=site
        )
        assert cal_res.ok is True
        assert cal_res.value is not None
        result = cal_res.value

        # Mean error must be negative (signal weaker than modeled)
        assert result.mean_error_db < -5.0
        assert result.rmse_db > 5.0
        # Recommended canopy and clutter adjustment must be positive
        assert result.recommended_canopy_adjustment_db > 5.0
        assert result.recommended_clutter_db_per_km > 0.0

    def test_unmatched_site_returns_error(self) -> None:
        site = SiteCandidate(
            site_id="VT-BUR-99",
            name="Unrelated Burlington Site",
            location=Coordinate(lat=44.4759, lon=-73.2121, elevation_m=65.0),
            site_type=SiteType.BUILDING_ROOFTOP,
        )

        sample_packets = [
            WardrivePacket(
                packet_id="pkt_test_1",
                timestamp="2026-10-26T14:00:00Z",
                rx_coordinate=Coordinate(lat=44.4906, lon=-73.1112, elevation_m=108.0),
                tx_node_id="VT-MANS-01",
                rx_node_id="VT-MOBI-01",
                rssi_dbm=-95.0,
                snr_db=-1.0,
            )
        ]

        cal_res = calibrate_ground_truth_clutter(packets=sample_packets, transmitter_site=site)
        assert cal_res.ok is False
        assert cal_res.error is not None
        assert cal_res.error.code == "NO_MATCHING_PACKETS"

    def test_calibration_with_custom_elevation_fn(self) -> None:
        site = _mansfield_site()

        def custom_dem(lat: float, lon: float) -> float:
            return 200.0 + (lat - 44.4) * 1000.0

        sample_packets = [
            WardrivePacket(
                packet_id="pkt_dem_1",
                timestamp="2026-10-26T14:00:00Z",
                rx_coordinate=Coordinate(lat=44.5000, lon=-73.0000, elevation_m=0.0),
                tx_node_id="VT-MANS-01",
                rx_node_id="VT-MOBI-01",
                rssi_dbm=-92.0,
                snr_db=1.0,
            )
        ]

        cal_res = calibrate_ground_truth_clutter(
            packets=sample_packets,
            transmitter_site=site,
            elevation_fn=custom_dem,
        )
        assert cal_res.ok is True
        assert cal_res.value is not None
        assert cal_res.value.matched_packets_count == 1
        assert cal_res.value.matches[0].distance_km > 0.0
