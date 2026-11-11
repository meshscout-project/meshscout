"""Hermetic unit tests for Canadian ISED SMS Adapter."""

from __future__ import annotations

import io
from pathlib import Path
import pytest

from meshscout.adapters.ised_sms import (
    classify_ised_structure_type,
    parse_ised_sms_records,
)
from meshscout.core.contracts import (
    AccessDifficulty,
    RegionalBounds,
    SiteCandidate,
    SiteType,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
ISED_SAMPLE_PATH = FIXTURES_DIR / "ised_sms_sample.csv"

SYNTHETIC_ISED_CSV = """BAN,Site Name,Latitude,Longitude,Structure Height,Structure Type
1001,Mont-Royal Tower,45.5048,-73.5872,35.0,Tower
1002,Reservoir McTavish,45.5033,-73.5783,15.0,Water Tank
1003,Mont Sutton Sommet,45.1053,-72.5628,18.0,Tour de télécom
1004,Observatoire Mont-Mégantic,45.4558,-71.1528,20.0,Observatory
1005,Poste Lévis,46.8033,-71.1822,30.0,Pylône
"""


def _make_tafl_row(
    tx_type: str = "TX",
    callsign_id: str = "01002345",
    site_name: str = "CAMP FORTUNE",
    prov: str = "QC",
    lat: float = 45.5133,
    lon: float = -75.8522,
    elevation_m: float = 380.0,
    height_m: float = 65.0,
    licensee: str = "Rogers Communications Canada Inc.",
) -> str:
    """Generate an authentic 61-column headerless TAFL_LTAF.csv row."""
    cols = [""] * 61
    cols[0] = tx_type
    cols[2] = callsign_id
    cols[31] = site_name
    cols[39] = prov
    cols[40] = str(lat)
    cols[41] = str(lon)
    cols[42] = str(elevation_m)
    cols[43] = str(height_m)
    cols[54] = licensee
    return ",".join(f'"{c}"' for c in cols)


class TestClassifyIsedStructureType:
    """Test Canadian ISED structure description and classification heuristics."""

    def test_water_tank_classification(self) -> None:
        assert classify_ised_structure_type("Water Tank") == SiteType.WATER_TOWER
        assert classify_ised_structure_type("Réservoir") == SiteType.WATER_TOWER
        assert classify_ised_structure_type("Château d'eau") == SiteType.WATER_TOWER
        assert classify_ised_structure_type("WT") == SiteType.WATER_TOWER

    def test_fire_lookout_classification(self) -> None:
        assert classify_ised_structure_type("Fire Lookout") == SiteType.FIRE_LOOKOUT
        assert classify_ised_structure_type("Tour de guet") == SiteType.FIRE_LOOKOUT
        assert classify_ised_structure_type("Garde-feu") == SiteType.FIRE_LOOKOUT

    def test_research_observatory_classification(self) -> None:
        assert classify_ised_structure_type("Observatory") == SiteType.RESEARCH_TOWER
        assert classify_ised_structure_type("Station de recherche") == SiteType.RESEARCH_TOWER
        assert classify_ised_structure_type("Station météorologique") == SiteType.RESEARCH_TOWER

    def test_building_rooftop_classification(self) -> None:
        assert classify_ised_structure_type("Building Rooftop") == SiteType.BUILDING_ROOFTOP
        assert classify_ised_structure_type("Toit d'immeuble") == SiteType.BUILDING_ROOFTOP
        assert classify_ised_structure_type("Bâtiment") == SiteType.BUILDING_ROOFTOP

    def test_silo_classification(self) -> None:
        assert classify_ised_structure_type("Grain Silo") == SiteType.SILO
        assert classify_ised_structure_type("Silo agricole") == SiteType.SILO

    def test_telecom_tower_default(self) -> None:
        assert classify_ised_structure_type("Tower") == SiteType.COMMUNICATIONS_TOWER
        assert classify_ised_structure_type("Tour de télécom") == SiteType.COMMUNICATIONS_TOWER
        assert classify_ised_structure_type("Pylône haubané") == SiteType.COMMUNICATIONS_TOWER
        assert classify_ised_structure_type("") == SiteType.COMMUNICATIONS_TOWER


class TestParseIsedSmsRecords:
    """Validate Canadian ISED SMS spectrum management records parser."""

    def test_ised_csv_parsing_and_types(self) -> None:
        candidates = parse_ised_sms_records(SYNTHETIC_ISED_CSV)
        assert len(candidates) == 5

        site_map = {c.site_id: c for c in candidates}
        assert "ISED_1001" in site_map
        c1 = site_map["ISED_1001"]
        assert c1.site_type == SiteType.COMMUNICATIONS_TOWER
        assert pytest.approx(c1.location.lat, abs=1e-4) == 45.5048
        assert pytest.approx(c1.location.lon, abs=1e-4) == -73.5872
        assert c1.mast_height_m == 35.0
        assert "ISED SMS: 1001" in c1.notes

        c2 = site_map["ISED_1002"]
        assert c2.site_type == SiteType.WATER_TOWER
        assert c2.mast_height_m == 15.0

    def test_ised_return_metadata_contract(self) -> None:
        records = parse_ised_sms_records(SYNTHETIC_ISED_CSV, return_metadata=True)
        assert len(records) == 5
        cand, meta = records[0]
        assert isinstance(cand, SiteCandidate)
        assert isinstance(meta, dict)
        assert "jurisdiction" in meta
        assert "owner" in meta
        assert "owner_category" in meta
        assert "source_record_id" in meta
        assert meta["source_record_id"] == "1001"

    def test_ised_sample_fixture_file(self) -> None:
        assert ISED_SAMPLE_PATH.exists()
        candidates = parse_ised_sms_records(ISED_SAMPLE_PATH)
        assert len(candidates) == 6

        records_with_meta = parse_ised_sms_records(ISED_SAMPLE_PATH, return_metadata=True)
        assert len(records_with_meta) == 6
        jurisdictions = {m["jurisdiction"] for _, m in records_with_meta}
        assert "QC" in jurisdictions
        assert "ON" in jurisdictions

    def test_ised_tafl_61_column_format(self) -> None:
        """Validate genuine 61-column headerless TAFL_LTAF.csv extraction."""
        row_str = _make_tafl_row(
            tx_type="TX",
            callsign_id="01002345",
            site_name="CAMP FORTUNE",
            prov="QC",
            lat=45.5133,
            lon=-75.8522,
            elevation_m=380.0,
            height_m=65.0,
            licensee="Rogers Communications Canada Inc.",
        )
        records = parse_ised_sms_records(row_str, return_metadata=True)
        assert len(records) == 1
        cand, meta = records[0]

        assert cand.site_id == "ISED_01002345"
        assert pytest.approx(cand.location.lat, abs=1e-4) == 45.5133
        assert pytest.approx(cand.location.lon, abs=1e-4) == -75.8522
        assert cand.location.elevation_m == 380.0
        assert cand.mast_height_m == 65.0
        assert "CAMP FORTUNE" in cand.name
        assert "Rogers Communications Canada Inc." in cand.name
        assert "ISED SMS: 01002345" in cand.notes
        assert "Licensee: Rogers Communications Canada Inc." in cand.notes
        assert "Elevation: 380.0 m" in cand.notes

        assert meta["jurisdiction"] == "QC"
        assert meta["owner"] == "Rogers Communications Canada Inc."
        assert meta["source_record_id"] == "01002345"
        assert meta["owner_category"] == "commercial_carrier"

    def test_ised_tafl_positive_west_longitude(self) -> None:
        """Ensure Canadian TAFL positive longitude values are converted to negative."""
        row_str = _make_tafl_row(
            tx_type="TXRX",
            callsign_id="02009999",
            lat=45.5133,
            lon=75.8522,  # Positive West longitude
        )
        candidates = parse_ised_sms_records(row_str)
        assert len(candidates) == 1
        assert candidates[0].location.lon < 0
        assert pytest.approx(candidates[0].location.lon, abs=1e-4) == -75.8522

    def test_ised_station_collapse_5_colocated_transmitters(self) -> None:
        """Verify that 5 co-located transmitters within 1 arcsecond collapse to 1 SiteCandidate.

        Must retain maximum antenna mast height, ground elevation AMSL, and aggregate unique licensees.
        """
        rows = [
            _make_tafl_row(
                tx_type="TX",
                callsign_id="01001",
                site_name="MONT-ROYAL SUMMIT",
                prov="QC",
                lat=45.50480,
                lon=-73.58720,
                elevation_m=233.0,
                height_m=30.0,
                licensee="Bell Mobility Inc.",
            ),
            _make_tafl_row(
                tx_type="TX",
                callsign_id="01002",
                site_name="MONT-ROYAL SUMMIT",
                prov="QC",
                lat=45.50481,  # within 1 arcsecond
                lon=-73.58719,
                elevation_m=233.0,
                height_m=45.0,
                licensee="Rogers Communications Canada Inc.",
            ),
            _make_tafl_row(
                tx_type="TXRX",
                callsign_id="01003",
                site_name="MONT-ROYAL SUMMIT",
                prov="QC",
                lat=45.50482,  # within 1 arcsecond
                lon=-73.58721,
                elevation_m=233.0,
                height_m=85.0,  # MAX HEIGHT
                licensee="Telus Mobility",
            ),
            _make_tafl_row(
                tx_type="TX",
                callsign_id="01004",
                site_name="MONT-ROYAL SUMMIT",
                prov="QC",
                lat=45.50479,  # within 1 arcsecond
                lon=-73.58720,
                elevation_m=233.0,
                height_m=20.0,
                licensee="CBC/Radio-Canada",
            ),
            _make_tafl_row(
                tx_type="RX",
                callsign_id="01005",
                site_name="MONT-ROYAL SUMMIT",
                prov="QC",
                lat=45.50483,  # within 1 arcsecond
                lon=-73.58722,
                elevation_m=233.0,
                height_m=60.0,
                licensee="Hydro-Quebec",
            ),
        ]
        tafl_data = "\n".join(rows)
        records = parse_ised_sms_records(tafl_data, return_metadata=True)

        assert len(records) == 1
        cand, meta = records[0]

        # Retains maximum mast height among all 5 transmitters
        assert cand.mast_height_m == 85.0
        # Retains ground elevation AMSL
        assert cand.location.elevation_m == 233.0
        # Aggregates unique licensees into notes
        for lic in (
            "Bell Mobility Inc.",
            "Rogers Communications Canada Inc.",
            "Telus Mobility",
            "CBC/Radio-Canada",
            "Hydro-Quebec",
        ):
            assert lic in cand.notes
            assert lic in meta["owner"]

        assert "Licensees:" in cand.notes
        assert meta["jurisdiction"] == "QC"

    def test_ised_station_collapse_licensee_cap_at_five(self) -> None:
        """Verify unique licensees aggregation is capped at 5 in notes."""
        rows = [
            _make_tafl_row(callsign_id=f"T{i}", height_m=float(20 + i), licensee=f"Carrier {i}")
            for i in range(1, 8)  # 7 distinct licensees
        ]
        tafl_data = "\n".join(rows)
        candidates = parse_ised_sms_records(tafl_data)

        assert len(candidates) == 1
        cand = candidates[0]
        # Max height of 20+7 = 27.0
        assert cand.mast_height_m == 27.0

        # Carriers 1..5 present, 6 and 7 excluded due to 5-licensee cap
        assert "Carrier 1" in cand.notes
        assert "Carrier 5" in cand.notes
        assert "Carrier 6" not in cand.notes
        assert "Carrier 7" not in cand.notes

    def test_ised_header_structure_type_disambiguation(self) -> None:
        """Validate header disambiguation: matches Structure Type rather than Station Type or Site Type."""
        header_csv = (
            "Site Id,Site Name,Station Type,Site Type,Structure Type,Latitude,Longitude,Structure Height,Province,Licensee\n"
            "FX101,Mont St-Hilaire,Fixed Base,Hilltop,Water Tank,45.5550,-73.1500,22.0,QC,Ville de St-Hilaire\n"
        )
        candidates = parse_ised_sms_records(header_csv)
        assert len(candidates) == 1
        cand = candidates[0]
        # If 'Structure Type' was matched, it becomes WATER_TOWER (not COMMUNICATIONS_TOWER)
        assert cand.site_type == SiteType.WATER_TOWER
        assert cand.mast_height_m == 22.0
        assert cand.site_id == "ISED_FX101"

    def test_ised_streaming_from_file_path_and_stringio(self, tmp_path: Path) -> None:
        """Verify parse_ised_sms_records streams from file paths and io.StringIO without loading into memory."""
        tafl_file = tmp_path / "sample_tafl.csv"
        tafl_row = _make_tafl_row(
            tx_type="TX",
            callsign_id="099901",
            site_name="STREAM TEST",
            prov="ON",
            lat=45.4215,
            lon=-75.6972,
            elevation_m=70.0,
            height_m=50.0,
            licensee="Stream Telco",
        )
        tafl_file.write_text(tafl_row, encoding="utf-8")

        # Test Path object input
        from_path = parse_ised_sms_records(tafl_file)
        assert len(from_path) == 1
        assert from_path[0].site_id == "ISED_099901"
        assert from_path[0].mast_height_m == 50.0

        # Test string path input
        from_str_path = parse_ised_sms_records(str(tafl_file))
        assert len(from_str_path) == 1
        assert from_str_path[0].site_id == "ISED_099901"

        # Test io.StringIO input
        from_stringio = parse_ised_sms_records(io.StringIO(tafl_row))
        assert len(from_stringio) == 1
        assert from_stringio[0].site_id == "ISED_099901"
