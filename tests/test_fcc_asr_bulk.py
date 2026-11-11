"""Unit tests for FCC ASR Bulk Adapter and Canadian ISED SMS Parser."""

from __future__ import annotations

from pathlib import Path
import pytest

from meshscout.adapters.fcc_asr_bulk import (
    OwnerCategory,
    classify_fcc_structure_type,
    classify_tower_ownership,
    parse_fcc_asr_bulk,
    parse_fcc_asr_directory,
)
from meshscout.adapters.ised_sms import (
    classify_ised_structure_type,
    parse_ised_sms_records,
)
from meshscout.core.contracts import (
    AccessDifficulty,
    RegionalBounds,
    SiteType,
)


class TestClassifyTowerOwnership:
    """Validate keyword-based ownership categorization."""

    def test_municipal_and_civic_inputs(self) -> None:
        assert classify_tower_ownership("Town of Stowe Police Dept") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("City of Burlington") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("Village of Waterbury") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("County of Chittenden Sheriff") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("State of Vermont - Public Safety") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("University of Vermont") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("Middlebury College") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("Colchester Water District") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("Rutland High School") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value

    def test_fire_department_inputs(self) -> None:
        assert classify_tower_ownership("Underhill Fire Dept") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("Stowe Volunteer Fire Department") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("Richmond Volunteer Fire Company") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value
        assert classify_tower_ownership("Montpelier Fire & EMS") == OwnerCategory.CIVIC_PUBLIC_SAFETY.value

    def test_electric_coop_utility_and_farm_inputs(self) -> None:
        assert classify_tower_ownership("Vermont Electric Coop") == OwnerCategory.COOP_UTILITY_AG.value
        assert classify_tower_ownership("Washington Electric Cooperative Inc") == OwnerCategory.COOP_UTILITY_AG.value
        assert classify_tower_ownership("Green Mountain Power") == OwnerCategory.COOP_UTILITY_AG.value
        assert classify_tower_ownership("Champlain Water Authority") == OwnerCategory.COOP_UTILITY_AG.value
        assert classify_tower_ownership("Miller Family Farm") == OwnerCategory.COOP_UTILITY_AG.value
        assert classify_tower_ownership("Highland Dairy Farm Silo") == OwnerCategory.COOP_UTILITY_AG.value
        assert classify_tower_ownership("Valley Grain Elevators Co.") == OwnerCategory.COOP_UTILITY_AG.value
        assert classify_tower_ownership("Hydro-Quebec TransEnergie") == OwnerCategory.COOP_UTILITY_AG.value

    def test_commercial_carrier_inputs(self) -> None:
        assert classify_tower_ownership("American Tower Management LLC") == OwnerCategory.COMMERCIAL_CARRIER.value
        assert classify_tower_ownership("Crown Castle Towers 09 LLC") == OwnerCategory.COMMERCIAL_CARRIER.value
        assert classify_tower_ownership("SBA Towers IX LLC") == OwnerCategory.COMMERCIAL_CARRIER.value
        assert classify_tower_ownership("Cellco Partnership", "Verizon Wireless") == OwnerCategory.COMMERCIAL_CARRIER.value
        assert classify_tower_ownership("New Cingular Wireless PCS LLC", "AT&T Mobility") == OwnerCategory.COMMERCIAL_CARRIER.value
        assert classify_tower_ownership("T-Mobile Northeast LLC") == OwnerCategory.COMMERCIAL_CARRIER.value
        assert classify_tower_ownership("Sprint Spectrum L.P.") == OwnerCategory.COMMERCIAL_CARRIER.value
        assert classify_tower_ownership("Vertical Bridge LLC") == OwnerCategory.COMMERCIAL_CARRIER.value

    def test_commercial_fallback_and_unknown(self) -> None:
        # Commercial fallback when structure or corporate suffix looks commercial
        assert classify_tower_ownership("Apex Tower LLC") == OwnerCategory.COMMERCIAL_CARRIER.value
        assert classify_tower_ownership("Broadcasting Properties Inc") == OwnerCategory.COMMERCIAL_CARRIER.value
        # Unknown personal or unspecified landowner
        assert classify_tower_ownership("John Doe", "Private residential lot") == OwnerCategory.UNKNOWN.value


class TestClassifyFccStructureType:
    """Validate structure code classification into SiteType enum values."""

    def test_tank_classifications(self) -> None:
        assert classify_fcc_structure_type("TANK") == SiteType.WATER_TOWER
        assert classify_fcc_structure_type("WT") == SiteType.WATER_TOWER
        assert classify_fcc_structure_type("TK") == SiteType.WATER_TOWER
        assert classify_fcc_structure_type("WATER TANK") == SiteType.WATER_TOWER
        assert classify_fcc_structure_type("WATER TOWER") == SiteType.WATER_TOWER

    def test_silo_classifications(self) -> None:
        assert classify_fcc_structure_type("SILO") == SiteType.SILO
        assert classify_fcc_structure_type("GRAIN SILO") == SiteType.SILO

    def test_lookout_classifications(self) -> None:
        assert classify_fcc_structure_type("LOOKOUT") == SiteType.FIRE_LOOKOUT
        assert classify_fcc_structure_type("FIRE") == SiteType.FIRE_LOOKOUT
        assert classify_fcc_structure_type("FIRE TOWER") == SiteType.FIRE_LOOKOUT
        assert classify_fcc_structure_type("FIRE WATCH") == SiteType.FIRE_LOOKOUT

    def test_building_classifications(self) -> None:
        assert classify_fcc_structure_type("BLDG") == SiteType.BUILDING_ROOFTOP
        assert classify_fcc_structure_type("ROOF") == SiteType.BUILDING_ROOFTOP
        assert classify_fcc_structure_type("BUILDING") == SiteType.BUILDING_ROOFTOP
        assert classify_fcc_structure_type("ROOFTOP") == SiteType.BUILDING_ROOFTOP

    def test_research_classifications(self) -> None:
        assert classify_fcc_structure_type("RESEARCH") == SiteType.RESEARCH_TOWER
        assert classify_fcc_structure_type("OBS") == SiteType.RESEARCH_TOWER
        assert classify_fcc_structure_type("OBSERVATORY") == SiteType.RESEARCH_TOWER
        assert classify_fcc_structure_type("FLUX") == SiteType.RESEARCH_TOWER

    def test_tower_and_default_classifications(self) -> None:
        assert classify_fcc_structure_type("TOWER") == SiteType.COMMUNICATIONS_TOWER
        assert classify_fcc_structure_type("MAST") == SiteType.COMMUNICATIONS_TOWER
        assert classify_fcc_structure_type("POLE") == SiteType.COMMUNICATIONS_TOWER
        assert classify_fcc_structure_type("STACK") == SiteType.COMMUNICATIONS_TOWER
        assert classify_fcc_structure_type("UTOWER") == SiteType.COMMUNICATIONS_TOWER
        assert classify_fcc_structure_type("GTOWER") == SiteType.COMMUNICATIONS_TOWER
        assert classify_fcc_structure_type("CUSTOM_ANTENNA") == SiteType.COMMUNICATIONS_TOWER
        assert classify_fcc_structure_type("") == SiteType.COMMUNICATIONS_TOWER


class TestParseFccAsrBulk:
    """Validate parse_fcc_asr_bulk with synthetic buffer and files."""

    SYNTHETIC_ASR_CONTENT = """# Synthetic FCC ASR Bulk Data
ANT|1010001|A0101001|44-28-33.0 N|073-12-45.0 W|TOWER|195.0|320.0|515.0|Burlington|VT|Chittenden|CONSTRUCTED
OWN|1010001|American Tower Management LLC|116 Huntington Ave|Boston|MA|02116
ANT|1010002|A0101002|44-30-22.0 N|073-05-15.0 W|TANK|120.0|400.0|520.0|Essex Junction|VT|Chittenden|CONSTRUCTED
OWN|1010002|Town of Essex Water Dept|81 Main St|Essex Junction|VT|05452
ANT|1010003|A0101003|44-35-10.0 N|073-00-50.0 W|SILO|80.0|350.0|430.0|Westford|VT|Chittenden|CONSTRUCTED
OWN|1010003|Westford Dairy Farm|120 Farm Rd|Westford|VT|05494
ANT|1010004|A0101004|44-20-15.0 N|072-55-30.0 W|LOOKOUT|60.0|2200.0|2260.0|Bolton|VT|Chittenden|CONSTRUCTED
OWN|1010004|State of Vermont - Public Safety|45 State Dr|Waterbury|VT|05671
ANT|1010005|A0101005|44-10-00.0 N|073-10-00.0 W|TOWER|150.0|200.0|350.0|Charlotte|VT|Chittenden|DISMANTLED
OWN|1010005|Old Telecom LLC|100 St|Charlotte|VT|05445
"""

    def test_parse_synthetic_buffer_types_and_notes(self) -> None:
        candidates = parse_fcc_asr_bulk(self.SYNTHETIC_ASR_CONTENT)
        # 5 records in buffer, 1 dismantled -> 4 valid candidates
        assert len(candidates) == 4

        site_map = {c.site_id: c for c in candidates}

        # 1. Commercial tower
        tower = site_map["ASR_1010001"]
        assert tower.site_type == SiteType.COMMUNICATIONS_TOWER
        assert pytest.approx(tower.location.lat, abs=1e-4) == 44.4758
        assert pytest.approx(tower.location.lon, abs=1e-4) == -73.2125
        assert pytest.approx(tower.mast_height_m, abs=0.1) == 59.44  # 195 ft * 0.3048
        assert "American Tower" in tower.name
        assert "Owner Category: commercial_carrier" in tower.notes
        assert "Structure: TOWER" in tower.notes
        assert "FCC ASR: 1010001" in tower.notes

        # 2. Water Tank (TANK)
        tank = site_map["ASR_1010002"]
        assert tank.site_type == SiteType.WATER_TOWER
        assert pytest.approx(tank.mast_height_m, abs=0.1) == 36.58  # 120 ft * 0.3048
        assert "Town of Essex" in tank.name
        assert "Owner Category: civic_public_safety" in tank.notes
        assert "Structure: TANK" in tank.notes

        # 3. Agricultural Silo (SILO)
        silo = site_map["ASR_1010003"]
        assert silo.site_type == SiteType.SILO
        assert pytest.approx(silo.mast_height_m, abs=0.1) == 24.38  # 80 ft * 0.3048
        assert "Westford Dairy Farm" in silo.name
        assert "Owner Category: coop_utility_ag" in silo.notes
        assert "Structure: SILO" in silo.notes

        # 4. Fire Lookout (LOOKOUT)
        lookout = site_map["ASR_1010004"]
        assert lookout.site_type == SiteType.FIRE_LOOKOUT
        assert "State of Vermont" in lookout.name
        assert "Owner Category: civic_public_safety" in lookout.notes

    def test_bounds_filtering(self) -> None:
        # Narrow bounds around Burlington/Essex Junction only
        bounds = RegionalBounds(
            name="Burlington_Area",
            min_lat=44.25,
            max_lat=44.32,
            min_lon=-73.25,
            max_lon=-73.04,
        )
        candidates = parse_fcc_asr_bulk(self.SYNTHETIC_ASR_CONTENT, bounds=bounds)
        # Should include Burlington (44.47 is actually outside? Wait, 44-28-33 is 44.4758)
        # Let's check: 44-28-33 is 44.4758. Min lat 44.25 to max lat 44.50.
        bounds = RegionalBounds(
            name="Chittenden_Narrow",
            min_lat=44.40,
            max_lat=44.55,
            min_lon=-73.25,
            max_lon=-73.04,
        )
        filtered = parse_fcc_asr_bulk(self.SYNTHETIC_ASR_CONTENT, bounds=bounds)
        # 1010001 (Burlington 44.4758, -73.2125) and 1010002 (Essex 44.5061, -73.0875) are inside
        # 1010003 (Westford -73.0139) is outside max_lon (-73.04)
        # 1010004 (Bolton 44.3375, -72.9250) is outside
        site_ids = {c.site_id for c in filtered}
        assert "ASR_1010001" in site_ids
        assert "ASR_1010002" in site_ids
        assert "ASR_1010003" not in site_ids
        assert "ASR_1010004" not in site_ids

    def test_paired_ant_and_own_content(self) -> None:
        ant_content = "ANT|2000001|A0200001|44-30-00.0 N|073-10-00.0 W|ROOF|100.0|250.0|350.0|Burlington|VT|Chittenden|CONSTRUCTED\n"
        own_content = "OWN|2000001|Crown Castle Towers 09 LLC|2000 Corporate Dr|Canonsburg|PA|15317\n"

        candidates = parse_fcc_asr_bulk(ant_content, own_path_or_content=own_content)
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.site_id == "ASR_2000001"
        assert cand.site_type == SiteType.BUILDING_ROOFTOP
        assert "Crown Castle" in cand.name
        assert "Owner Category: commercial_carrier" in cand.notes

    def test_parse_vt_fixture_file(self) -> None:
        from meshscout.adapters.fcc_asr import DEFAULT_FCC_ASR_FIXTURE_PATH
        candidates = parse_fcc_asr_bulk(DEFAULT_FCC_ASR_FIXTURE_PATH)
        assert len(candidates) > 0
        for c in candidates:
            assert c.site_id.startswith("ASR_")
            assert c.site_type in SiteType
            assert "FCC ASR:" in c.notes
            assert "Owner Category:" in c.notes


class TestParseFccAsrDirectory:
    """Validate streaming join across FCC r_tower extracted tables (CO.dat, EN.dat, RA.dat)."""

    SAMPLE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "fcc_r_tower_sample"

    def test_fixture_join_correctness(self) -> None:
        candidates = list(parse_fcc_asr_directory(self.SAMPLE_DIR))
        # 7 rows in RA.dat:
        # - 1010001: Constructed tower (included)
        # - 1010002: Granted water tank (included)
        # - 1010003: Constructed silo (included)
        # - 1010004: Constructed lookout (included)
        # - 1010005: Status 'D' (dismantled) -> filtered out
        # - 1010006: Height 10.0m (< 15.0m) -> filtered out
        # - 1010007: Albany NY tower (included)
        assert len(candidates) == 5

        site_map = {c.site_id: c for c in candidates}

        # 1. Commercial tower join
        c1 = site_map["ASR_1010001"]
        assert c1.site_type == SiteType.COMMUNICATIONS_TOWER
        assert pytest.approx(c1.location.lat, abs=1e-4) == 44.4758
        assert pytest.approx(c1.location.lon, abs=1e-4) == -73.2125
        assert c1.mast_height_m == 59.4
        assert c1.location.elevation_m == 97.5
        assert "American Tower" in c1.name
        assert "Owner Category: commercial_carrier" in c1.notes
        assert "Height AGL: 59.4 m" in c1.notes

        # 2. Water tank (TANK) join
        c2 = site_map["ASR_1010002"]
        assert c2.site_type == SiteType.WATER_TOWER
        assert c2.mast_height_m == 36.6
        assert c2.location.elevation_m == 121.9
        assert "Town of Essex" in c2.name
        assert "Owner Category: civic_public_safety" in c2.notes

        # 3. Silo with owner 'O' preferred over representative 'R'
        c3 = site_map["ASR_1010003"]
        assert c3.site_type == SiteType.SILO
        assert c3.mast_height_m == 24.4
        assert "Westford Dairy Farm" in c3.name
        assert "Consulting Engineers" not in c3.name
        assert "Owner Category: coop_utility_ag" in c3.notes

        # 4. Fire lookout (LOOKOUT)
        c4 = site_map["ASR_1010004"]
        assert c4.site_type == SiteType.FIRE_LOOKOUT
        assert c4.mast_height_m == 18.3
        assert c4.location.elevation_m == 670.6
        assert "State of Vermont" in c4.name

        # 5. Dismantled and short structures are excluded
        assert "ASR_1010005" not in site_map
        assert "ASR_1010006" not in site_map

        # 6. Out-of-state tower
        assert "ASR_1010007" in site_map

    def test_native_meter_preservation_no_feet_shrinkage(self) -> None:
        """CRITICAL UNIT INVARIANT: RA.dat heights and elevations must NOT be multiplied by 0.3048."""
        candidates = list(parse_fcc_asr_directory(self.SAMPLE_DIR))
        site_map = {c.site_id: c for c in candidates}
        c1 = site_map["ASR_1010001"]

        # If incorrectly multiplied by 0.3048, 59.4 would become ~18.10 m and 97.5 would become ~29.7 m
        assert c1.mast_height_m == 59.4
        assert c1.location.elevation_m == 97.5
        assert c1.mast_height_m != pytest.approx(59.4 * 0.3048, abs=0.5)

    def test_regional_bounds_filtering(self) -> None:
        vt_bounds = RegionalBounds(
            name="Vermont",
            min_lat=42.7,
            max_lat=45.1,
            min_lon=-73.5,
            max_lon=-71.5,
        )
        candidates = list(parse_fcc_asr_directory(self.SAMPLE_DIR, bounds=vt_bounds))
        site_ids = {c.site_id for c in candidates}

        # Vermont sites should be included
        assert "ASR_1010001" in site_ids
        assert "ASR_1010002" in site_ids
        assert "ASR_1010003" in site_ids
        assert "ASR_1010004" in site_ids

        # Albany NY (lat 42.65, lon -73.75) is outside VT bounds and must be filtered out
        assert "ASR_1010007" not in site_ids

    def test_return_metadata_mode(self) -> None:
        results = list(parse_fcc_asr_directory(self.SAMPLE_DIR, return_metadata=True))
        assert len(results) == 5
        cand, meta = results[0]
        assert isinstance(meta, dict)
        assert meta["jurisdiction"] in ("VT", "NY")
        assert "owner" in meta
        assert "owner_category" in meta
        assert meta["source_record_id"] == "1010001"

    def test_missing_table_raises_file_not_found(self, tmp_path: Path) -> None:
        # Directory without tables
        with pytest.raises(FileNotFoundError):
            list(parse_fcc_asr_directory(tmp_path))

        # Directory with only CO.dat (missing RA.dat)
        (tmp_path / "CO.dat").write_text("CO|1|...|\n", encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="RA.dat"):
            list(parse_fcc_asr_directory(tmp_path))

    def test_synthetic_streaming_performance_and_memory(self, tmp_path: Path) -> None:
        """Synthetic streaming test verifying memory stays bounded and completes in < 2s for 15,000+ rows."""
        import time
        import tracemalloc

        co_lines = []
        en_lines = []
        ra_lines = []

        total_rows = 15000
        for i in range(total_rows):
            reg = f"{2000000 + i}"
            sys_id = f"{3000000 + i}"
            # 18 cols for CO.dat
            co_row = [""] * 18
            co_row[0] = "CO"
            co_row[1] = "1"
            co_row[2] = f"A{reg}"
            co_row[3] = reg
            co_row[4] = sys_id
            co_row[6] = "44"
            co_row[7] = "25"
            co_row[8] = "10.0"
            co_row[9] = "N"
            co_row[11] = "73"
            co_row[12] = "10"
            co_row[13] = "20.0"
            co_row[14] = "W"
            co_lines.append("|".join(co_row))

            # 25 cols for EN.dat
            en_row = [""] * 25
            en_row[0] = "EN"
            en_row[1] = "1"
            en_row[2] = f"A{reg}"
            en_row[3] = reg
            en_row[4] = sys_id
            en_row[5] = "O"
            en_row[9] = f"Stream Carrier {i % 100} LLC"
            en_row[20] = "Burlington"
            en_row[21] = "VT"
            en_lines.append("|".join(en_row))

            # 49 cols for RA.dat
            ra_row = [""] * 49
            ra_row[0] = "RA"
            ra_row[1] = "1"
            ra_row[2] = f"A{reg}"
            ra_row[3] = reg
            ra_row[4] = sys_id
            ra_row[8] = "C" if i % 10 != 0 else "D"  # 10% dismantled
            ra_row[24] = "Burlington"
            ra_row[25] = "VT"
            ra_row[28] = "50.0" if i % 7 != 0 else "10.0"  # ~14% below 15m
            ra_row[29] = "100.0"
            ra_row[30] = "50.0" if i % 7 != 0 else "10.0"
            ra_row[32] = "TOWER"
            ra_lines.append("|".join(ra_row))

        (tmp_path / "CO.dat").write_text("\n".join(co_lines) + "\n", encoding="utf-8")
        (tmp_path / "EN.dat").write_text("\n".join(en_lines) + "\n", encoding="utf-8")
        (tmp_path / "RA.dat").write_text("\n".join(ra_lines) + "\n", encoding="utf-8")

        # 1. Performance timing (clean wall-clock measurement without profiler overhead)
        t0 = time.perf_counter()
        count = 0
        for candidate in parse_fcc_asr_directory(tmp_path):
            count += 1
            assert candidate.mast_height_m >= 15.0
        elapsed = time.perf_counter() - t0

        # 2. Memory bound check with tracemalloc
        tracemalloc.start()
        batch_count = sum(1 for _ in parse_fcc_asr_directory(tmp_path))
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / (1024 * 1024)

        # Performance assertions
        assert count > 10000
        assert elapsed < 2.0, f"Streaming execution took {elapsed:.2f}s, expected < 2.0s"
        assert peak_mb < 50.0, f"Peak memory {peak_mb:.1f} MB exceeded 50 MB threshold (bound is 150 MB)"

    def test_tower_ingest_with_fcc_directory_and_file_parent(self) -> None:
        """Verify ingest_tower_source accepts directory and file whose parent contains tables."""
        from meshscout.adapters.tower_ingest import ingest_tower_source
        from meshscout.core.tower_registry import UnifiedTowerRegistry

        # 1. Directory input
        reg1 = UnifiedTowerRegistry(":memory:")
        res1 = ingest_tower_source(reg1, "fcc_asr", self.SAMPLE_DIR)
        assert res1["ok"] is True
        assert res1["ingested_count"] == 5

        # 2. File input where parent contains RA.dat and CO.dat
        reg2 = UnifiedTowerRegistry(":memory:")
        res2 = ingest_tower_source(reg2, "fcc_asr", self.SAMPLE_DIR / "RA.dat")
        assert res2["ok"] is True
        assert res2["ingested_count"] == 5


class TestParseIsedSmsRecords:
    """Validate Canadian ISED SMS spectrum management records parser."""

    SYNTHETIC_ISED_CSV = """BAN,Site Name,Latitude,Longitude,Structure Height,Structure Type
1001,Mont-Royal Tower,45.5048,-73.5872,35.0,Tower
1002,Reservoir McTavish,45.5033,-73.5783,15.0,Water Tank
1003,Mont Sutton Sommet,45.1053,-72.5628,18.0,Tour de télécom
1004,Observatoire Mont-Mégantic,45.4558,-71.1528,20.0,Observatory
1005,Poste Lévis,46.8033,-71.1822,30.0,Pylône
"""

    def test_ised_csv_parsing_and_types(self) -> None:
        candidates = parse_ised_sms_records(self.SYNTHETIC_ISED_CSV)
        assert len(candidates) == 5

        site_map = {c.site_id: c for c in candidates}

        # 1. Mont-Royal Tower
        c1 = site_map["ISED_1001"]
        assert c1.site_type == SiteType.COMMUNICATIONS_TOWER
        assert pytest.approx(c1.location.lat, abs=1e-4) == 45.5048
        assert pytest.approx(c1.location.lon, abs=1e-4) == -73.5872
        assert c1.mast_height_m == 35.0
        assert "ISED SMS: 1001" in c1.notes

        # 2. Water Tank
        c2 = site_map["ISED_1002"]
        assert c2.site_type == SiteType.WATER_TOWER
        assert c2.mast_height_m == 15.0

        # 3. Mont Sutton
        c3 = site_map["ISED_1003"]
        assert c3.site_type == SiteType.COMMUNICATIONS_TOWER
        assert pytest.approx(c3.location.lat, abs=1e-4) == 45.1053
        assert pytest.approx(c3.location.lon, abs=1e-4) == -72.5628

        # 4. Observatoire Mont Mégantic (Research Tower)
        c4 = site_map["ISED_1004"]
        assert c4.site_type == SiteType.RESEARCH_TOWER
        assert pytest.approx(c4.location.lat, abs=1e-4) == 45.4558
        assert pytest.approx(c4.location.lon, abs=1e-4) == -71.1528

    def test_ised_regional_bounds_filtering(self) -> None:
        # Bounding box for Southern Quebec / Montreal / Eastern Townships
        # Excluding Quebec City / Lévis (lat ~46.8)
        bounds = RegionalBounds(
            name="Montreal_Eastern_Townships",
            min_lat=45.0,
            max_lat=45.6,
            min_lon=-74.0,
            max_lon=-71.0,
        )
        filtered = parse_ised_sms_records(self.SYNTHETIC_ISED_CSV, bounds=bounds)
        ids = {c.site_id for c in filtered}

        assert "ISED_1001" in ids  # Mont-Royal (45.5048)
        assert "ISED_1002" in ids  # McTavish (45.5033)
        assert "ISED_1003" in ids  # Mont Sutton (45.1053)
        assert "ISED_1004" in ids  # Mont Megantic (45.4558)
        assert "ISED_1005" not in ids  # Levis (46.8033 is out of bounds)

    def test_ised_pipe_and_tsv_delimiters(self) -> None:
        pipe_content = """BAN|Site Name|Latitude|Longitude|Structure Height|Structure Type
QC-991|Tremblant Sommet|46.2125|-74.5561|25.0|Fire Lookout
"""
        cands = parse_ised_sms_records(pipe_content)
        assert len(cands) == 1
        assert cands[0].site_id == "ISED_QC-991"
        assert cands[0].site_type == SiteType.FIRE_LOOKOUT
        assert cands[0].mast_height_m == 25.0
        assert pytest.approx(cands[0].location.lat, abs=1e-4) == 46.2125

    def test_ised_positive_west_longitude_conversion(self) -> None:
        # Canadian data with positive West longitude (73.5872 instead of -73.5872)
        content = """BAN,Site Name,Latitude,Longitude,Structure Height,Structure Type
2001,Montreal Downtown,45.5000,73.5700,20.0,Building
"""
        cands = parse_ised_sms_records(content)
        assert len(cands) == 1
        assert cands[0].location.lon < 0
        assert pytest.approx(cands[0].location.lon, abs=1e-4) == -73.5700
        assert cands[0].site_type == SiteType.BUILDING_ROOFTOP


class TestFccAsrBulkEnhancements:
    """Validate multi-structure, native meters preservation, and Guam/CNMI East longitude."""

    def test_multi_structure_unique_system_identifier(self, tmp_path: Path) -> None:
        """Two antenna structures sharing the same registration number but distinct sys_id."""
        co_content = (
            "CO|1|A01|1099001|2000001||44|28|30.0|N||073|12|40.0|W\n"
            "CO|1|A01|1099001|2000002||44|28|35.0|N||073|12|45.0|W\n"
        )
        en_content = "EN|1|A01|1099001|2000001|O|||Town Police||||||||||||Burlington|VT\n"
        ra_content = (
            "RA|1|A01|1099001|2000001||||C||||||||||||||||Burlington|VT||35.0|150.0|35.0||TOWER\n"
            "RA|1|A01|1099001|2000002||||C||||||||||||||||Burlington|VT||40.0|155.0|40.0||TOWER\n"
        )

        (tmp_path / "CO.dat").write_text(co_content, encoding="utf-8")
        (tmp_path / "EN.dat").write_text(en_content, encoding="utf-8")
        (tmp_path / "RA.dat").write_text(ra_content, encoding="utf-8")

        candidates = list(parse_fcc_asr_directory(tmp_path))
        assert len(candidates) == 2
        site_ids = {c.site_id for c in candidates}
        assert "ASR_1099001" in site_ids
        assert "ASR_1099001_2000002" in site_ids

    def test_guam_cnmi_east_longitude_preserved(self, tmp_path: Path) -> None:
        """Guam and CNMI towers in Eastern Hemisphere must retain positive longitude."""
        co_content = "CO|1|A01|1099003|2000003||13|28|30.0|N||144|45|00.0|E\n"
        ra_content = "RA|1|A01|1099003|2000003||||C||||||||||||||||Agana|GU||50.0|100.0|50.0||TOWER\n"

        (tmp_path / "CO.dat").write_text(co_content, encoding="utf-8")
        (tmp_path / "RA.dat").write_text(ra_content, encoding="utf-8")

        candidates = list(parse_fcc_asr_directory(tmp_path))
        assert len(candidates) == 1
        guam_site = candidates[0]
        assert guam_site.location.lon > 0
        assert pytest.approx(guam_site.location.lon, abs=1e-3) == 144.750
        assert pytest.approx(guam_site.location.lat, abs=1e-3) == 13.475

    def test_native_meter_elevation_bulk_preservation(self) -> None:
        """When parsing full RA table records, elevations in meters must not be shrunk by FEET_TO_METERS."""
        ant_content = (
            "CO|1099004|44-30-00.0 N|073-10-00.0 W\n"
            "RA|1|A01|1099004|2000004||||C||||||||||||||||Burlington|VT|||45.0|220.0|45.0||TOWER\n"
        )
        candidates = parse_fcc_asr_bulk(ant_content)
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.mast_height_m == 45.0
        assert cand.location.elevation_m == 220.0
