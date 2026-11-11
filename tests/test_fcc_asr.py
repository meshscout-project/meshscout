"""Unit tests for FCC ASR Pipe-Delimited Regional Adapter and DMS Coordinate Converter."""

from __future__ import annotations

from pathlib import Path
import time
import pytest

from meshscout.adapters.base import BaseRegionalAdapter
from meshscout.adapters.fcc_asr import (
    DEFAULT_FCC_ASR_FIXTURE_PATH,
    FEET_TO_METERS,
    FCCASRAdapter,
    dms_to_decimal,
    feet_to_meters,
    parse_asr_buffer,
    parse_asr_files,
)
from meshscout.core.contracts import (
    AccessDifficulty,
    RegionalBounds,
    SiteType,
)


class TestDMSToDecimal:
    """Tests for dms_to_decimal coordinate conversion."""

    def test_standard_fcc_latitude_north(self) -> None:
        # 44 + 32/60 + 15.0/3600 = 44 + 0.5333333333333333 + 0.004166666666666667 = 44.5375
        val = dms_to_decimal("44-32-15.0 N")
        assert val == pytest.approx(44.5375, abs=1e-7)

    def test_standard_fcc_longitude_west(self) -> None:
        # -(72 + 48/60 + 52.0/3600) = -(72 + 0.8 + 0.014444444444444444) = -72.81444444
        val = dms_to_decimal("072-48-52.0 W")
        assert val == pytest.approx(-72.81444444444445, abs=1e-7)

    def test_compact_dms_strings(self) -> None:
        assert dms_to_decimal("44-32-15.0N") == pytest.approx(44.5375, abs=1e-7)
        assert dms_to_decimal("072-48-52.0W") == pytest.approx(-72.81444444, abs=1e-6)
        assert dms_to_decimal("44:32:15.0 N") == pytest.approx(44.5375, abs=1e-7)
        assert dms_to_decimal("44 32 15.0 N") == pytest.approx(44.5375, abs=1e-7)
        assert dms_to_decimal("44°32'15.0\" N") == pytest.approx(44.5375, abs=1e-7)

    def test_south_and_east_hemispheres(self) -> None:
        assert dms_to_decimal("33-51-54.0 S") == pytest.approx(-(33 + 51 / 60 + 54 / 3600), abs=1e-7)
        assert dms_to_decimal("151-12-36.0 E") == pytest.approx(151 + 12 / 60 + 36 / 3600, abs=1e-7)

    def test_multi_argument_calls(self) -> None:
        assert dms_to_decimal("44-32-15.0", "N") == pytest.approx(44.5375, abs=1e-7)
        assert dms_to_decimal("072-48-52.0", "W") == pytest.approx(-72.81444444, abs=1e-6)
        assert dms_to_decimal(44, 32, 15.0, "N") == pytest.approx(44.5375, abs=1e-7)
        assert dms_to_decimal(72, 48, 52.0, "W") == pytest.approx(-72.81444444, abs=1e-6)
        assert dms_to_decimal(44, 30.0, direction="S") == pytest.approx(-44.5, abs=1e-7)

    def test_signed_decimal_passthrough(self) -> None:
        assert dms_to_decimal("44.5375") == pytest.approx(44.5375, abs=1e-7)
        assert dms_to_decimal("-72.8144") == pytest.approx(-72.8144, abs=1e-7)
        assert dms_to_decimal(-73.125) == pytest.approx(-73.125, abs=1e-7)

    def test_invalid_inputs_and_out_of_range_rejections(self) -> None:
        with pytest.raises(ValueError):
            dms_to_decimal(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            dms_to_decimal("")
        with pytest.raises(ValueError):
            dms_to_decimal("   ")
        with pytest.raises(ValueError):
            dms_to_decimal("invalid-coord")
        with pytest.raises(ValueError, match="Minutes component"):
            dms_to_decimal("44-60-00.0 N")
        with pytest.raises(ValueError, match="Seconds component"):
            dms_to_decimal("44-30-60.0 N")
        with pytest.raises(ValueError, match="out of bounds"):
            dms_to_decimal("91-00-00.0 N")
        with pytest.raises(ValueError, match="out of bounds"):
            dms_to_decimal("181-00-00.0 W")
        with pytest.raises(ValueError, match="Conflicting hemisphere"):
            dms_to_decimal("44-32-15.0 N", "S")


class TestFeetToMeters:
    """Tests for feet_to_meters conversion."""

    def test_feet_to_meters_conversion_accuracy(self) -> None:
        assert FEET_TO_METERS == 0.3048
        assert feet_to_meters(100.0) == pytest.approx(30.48, abs=1e-6)
        assert feet_to_meters(195.0) == pytest.approx(59.436, abs=1e-6)
        assert feet_to_meters("4390.0") == pytest.approx(1338.072, abs=1e-6)
        assert feet_to_meters(0) == 0.0


class TestFCCASRAdapter:
    """Tests for FCCASRAdapter and pipe-delimited parsing."""

    def test_protocol_conformance(self) -> None:
        adapter = FCCASRAdapter()
        assert isinstance(adapter, BaseRegionalAdapter)
        assert adapter.adapter_name == "fcc_asr"

        hc = adapter.health_check()
        assert hc.ok is True
        assert hc.value is True

    def test_parse_vt_fixture_53_active_records_under_200ms(self) -> None:
        assert DEFAULT_FCC_ASR_FIXTURE_PATH.exists()

        adapter = FCCASRAdapter(fixture_path=DEFAULT_FCC_ASR_FIXTURE_PATH)
        t0 = time.perf_counter()
        result = adapter.fetch_sites()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert result.ok is True
        assert result.value is not None
        sites = result.value

        # Fixture has 54 ANT records, but 1010008 (UVM Underhill) was dismantled on 07/20/2022
        # Parser must drop dismantled records yielding 53 active sites
        assert len(sites) == 53
        assert all(s.site_id != "ASR_1010008" for s in sites)
        assert elapsed_ms < 200.0, f"Parsing took {elapsed_ms:.2f}ms, exceeding 200ms threshold"

        # Verify first record (Burlington ASR 1010001)
        burlington = next(s for s in sites if s.site_id == "ASR_1010001")
        assert burlington.name == "American Tower Management LLC - Burlington"
        assert burlington.site_type == SiteType.COMMUNICATIONS_TOWER
        assert burlington.location.lat == pytest.approx(dms_to_decimal("44-28-33.0 N"), abs=1e-6)
        assert burlington.location.lon == pytest.approx(dms_to_decimal("073-12-45.0 W"), abs=1e-6)
        assert burlington.location.elevation_m == pytest.approx(round(320.0 * 0.3048, 1), abs=1e-5)
        assert burlington.mast_height_m == pytest.approx(round(195.0 * 0.3048, 2), abs=1e-5)
        assert burlington.has_grid_power is True
        assert burlington.access_difficulty == AccessDifficulty.DRIVE_UP
        assert burlington.notes is not None
        assert "American Tower Management LLC" in burlington.notes
        assert "Chittenden Co." in burlington.notes

    def test_dismantled_and_cancelled_status_filtering(self) -> None:
        raw_buffer = "\n".join([
            "OWN|8880001|Active Tower LLC|1 Main St|Burlington|VT|05401|8025550001|0008880001",
            "ANT|8880001|A0888001|44-28-33.0 N|073-12-45.0 W|TOWER|150.0|300.0|450.0|Burlington|VT|Chittenden|CONSTRUCTED",
            "OWN|8880002|Dismantled Mast LLC|2 Main St|Underhill|VT|05489|8025550002|0008880002",
            "ANT|8880002|A0888002|44-32-15.0 N|072-48-52.0 W|MAST|100.0|400.0|500.0|Underhill|VT|Chittenden|DISMANTLED",
            "OWN|8880003|Cancelled Pole LLC|3 Main St|Jericho|VT|05465|8025550003|0008880003",
            "ANT|8880003|A0888003|44-30-00.0 N|072-59-00.0 W|POLE|80.0|300.0|380.0|Jericho|VT|Chittenden|CANCELLED",
            "OWN|8880004|Terminated Array LLC|4 Main St|Essex|VT|05452|8025550004|0008880004",
            "ANT|8880004|A0888004|44-29-00.0 N|073-05-00.0 W|TOWER|120.0|300.0|420.0|Essex|VT|Chittenden|TERMINATED",
        ])
        sites = parse_asr_buffer(raw_buffer)
        assert len(sites) == 1
        assert sites[0].site_id == "ASR_8880001"
        assert sites[0].name == "Active Tower LLC - Burlington"

    def test_ant_and_own_join_by_registration_number(self) -> None:
        raw_buffer = "\n".join([
            "OWN|9990001|Green Mountain Broadband Corp|100 Main St|Montpelier|VT|05602|8025551234|0009990001",
            "ANT|9990001|A0999001|44-15-36.0 N|072-34-32.0 W|TOWER|200.0|500.0|700.0|Montpelier|VT|Washington|CONSTRUCTED",
            "ANT|9990002|A0999002|44-28-33.0 N|073-12-45.0 W|POLE|100.0|300.0|400.0|Burlington|VT|Chittenden|CONSTRUCTED",
        ])
        sites = parse_asr_buffer(raw_buffer)
        assert len(sites) == 2

        s1 = next(s for s in sites if s.site_id == "ASR_9990001")
        assert s1.name == "Green Mountain Broadband Corp - Montpelier"
        assert s1.notes is not None and "Owner: Green Mountain Broadband Corp" in s1.notes
        assert s1.mast_height_m == pytest.approx(60.96, abs=1e-4)

        # Unmatched OWN record still produces a valid SiteCandidate with fallback name
        s2 = next(s for s in sites if s.site_id == "ASR_9990002")
        assert s2.name == "ASR Tower 9990002 - Burlington"
        assert s2.mast_height_m == pytest.approx(30.48, abs=1e-4)

    def test_regional_bounds_filtering_chittenden_vs_vermont(self) -> None:
        chittenden_bounds = RegionalBounds(
            name="Chittenden County",
            min_lat=44.24,
            max_lat=44.62,
            min_lon=-73.30,
            max_lon=-72.80,
        )
        vermont_bounds = RegionalBounds(
            name="Vermont",
            min_lat=42.70,
            max_lat=45.05,
            min_lon=-73.45,
            max_lon=-71.45,
        )

        adapter = FCCASRAdapter()
        vt_res = adapter.fetch_sites(bounds=vermont_bounds)
        chit_res = adapter.fetch_sites(bounds=chittenden_bounds)

        assert vt_res.ok and vt_res.value is not None
        assert chit_res.ok and chit_res.value is not None

        assert len(vt_res.value) == 53
        assert 10 <= len(chit_res.value) < len(vt_res.value)
        for site in chit_res.value:
            assert chittenden_bounds.contains(site.location)

    def test_parse_asr_files_and_missing_file_handling(self, tmp_path: Path) -> None:
        ant_file = tmp_path / "ANT.dat"
        own_file = tmp_path / "OWN.dat"

        ant_file.write_text(
            "ANT|2000001|A0200001|44-32-15.0 N|072-48-52.0 W|MAST|100.0|4000.0|4100.0|Underhill|VT|Chittenden|CONSTRUCTED\n",
            encoding="utf-8",
        )
        own_file.write_text(
            "OWN|2000001|Mount Mansfield Repeater Group|1 Peak Rd|Stowe|VT|05672|8025559999|0001112223\n",
            encoding="utf-8",
        )

        sites = parse_asr_files(ant_file, own_path=own_file)
        assert len(sites) == 1
        assert sites[0].site_id == "ASR_2000001"
        assert sites[0].name == "Mount Mansfield Repeater Group - Underhill"

        adapter = FCCASRAdapter(ant_file=ant_file, own_file=own_file)
        res = adapter.fetch_sites()
        assert res.ok and res.value is not None
        assert len(res.value) == 1

        # Missing file handling
        missing_adapter = FCCASRAdapter(fixture_path=tmp_path / "nonexistent.dat")
        assert missing_adapter.health_check().ok is False
        assert missing_adapter.fetch_sites().ok is False
