"""Unit tests for the Co-Location RF Desense and Site Viability Scorer."""

from __future__ import annotations

import pytest

from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    SiteCandidate,
    SiteType,
)
from meshscout.core.scorer import (
    DesenseRiskLevel,
    EmitterSpec,
    evaluate_rf_desense_risk,
    rank_candidate_sites,
    score_site_viability,
)


def _sample_municipal_water_tower() -> SiteCandidate:
    return SiteCandidate(
        site_id="VT-ESSX-WT1",
        name="Essex Municipal Water Tower",
        location=Coordinate(lat=44.4906, lon=-73.1112, elevation_m=150.0),
        site_type=SiteType.WATER_TOWER,
        mast_height_m=22.0,
        has_grid_power=True,
        solar_exposure_pct=95.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        notes="Town municipal water tank with cooperative emergency management access",
    )


def _sample_public_silo() -> SiteCandidate:
    return SiteCandidate(
        site_id="VT-CHAR-SL1",
        name="Charlotte Cooperative Farm Silo",
        location=Coordinate(lat=44.3168, lon=-73.2425, elevation_m=115.0),
        site_type=SiteType.SILO,
        mast_height_m=18.0,
        has_grid_power=True,
        solar_exposure_pct=100.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        notes="Local agricultural cooperative grain silo",
    )


def _sample_commercial_carrier_tower() -> SiteCandidate:
    return SiteCandidate(
        site_id="VT-BURL-ATC1",
        name="American Tower Leased Cellular Monopole",
        location=Coordinate(lat=44.4759, lon=-73.2121, elevation_m=140.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=30.0,
        has_grid_power=True,
        solar_exposure_pct=90.0,
        access_difficulty=AccessDifficulty.DRIVE_UP,
        notes="Crown Castle / American Tower leased multi-carrier cellular site",
    )


class TestCivicVsCommercialRanking:
    """Verify civic/cooperative assets rank strictly above leased commercial telecom towers."""

    def test_municipal_water_tower_and_silo_rank_above_commercial_tower(self) -> None:
        water_tower = _sample_municipal_water_tower()
        farm_silo = _sample_public_silo()
        commercial_tower = _sample_commercial_carrier_tower()

        res = rank_candidate_sites(
            sites=[commercial_tower, farm_silo, water_tower],
            coverage_by_site={
                "VT-ESSX-WT1": 0.65,
                "VT-CHAR-SL1": 0.65,
                "VT-BURL-ATC1": 0.68,
            },
        )
        assert res.ok is True and res.value is not None
        ranked = res.value
        assert len(ranked) == 3

        # Municipal water tower and farm silo must both outrank the commercial tower
        ranked_ids = [item.site.site_id for item in ranked]
        assert ranked_ids[0] in ("VT-ESSX-WT1", "VT-CHAR-SL1")
        assert ranked_ids[1] in ("VT-ESSX-WT1", "VT-CHAR-SL1")
        assert ranked_ids[2] == "VT-BURL-ATC1"

        comm_score = ranked[2]
        assert comm_score.requires_cavity_filter is True
        assert comm_score.access_and_ownership_score < 50.0


class TestRfDesenseRiskEvaluation:
    """Verify front-end LNA overload and cavity filter detection near 850/900 MHz emitters."""

    def test_quiet_rural_site_has_low_desense_risk(self) -> None:
        silo = _sample_public_silo()
        cleanliness, risk, needs_cavity, notes = evaluate_rf_desense_risk(silo, nearby_emitters=[])
        assert cleanliness == pytest.approx(100.0)
        assert risk == DesenseRiskLevel.LOW
        assert needs_cavity is False
        assert not any("cavity filter" in n.lower() for n in notes)

    def test_co_located_high_power_900mhz_emitter_triggers_cavity_filter(self) -> None:
        water_tower = _sample_municipal_water_tower()
        # High-ERP 896 MHz SMR / 930 MHz paging transmitter co-located within 30 meters
        high_power_paging = EmitterSpec(
            emitter_id="WPVT-930-PAGE",
            location=Coordinate(lat=44.4907, lon=-73.1112, elevation_m=150.0),
            frequency_mhz=929.5,
            erp_watts=500.0,
            service_type="paging",
        )
        cellular_850 = EmitterSpec(
            emitter_id="KNKA-850-CELL",
            location=Coordinate(lat=44.4906, lon=-73.1110, elevation_m=150.0),
            frequency_mhz=880.0,
            erp_watts=250.0,
            service_type="cellular",
        )

        res = score_site_viability(
            site=water_tower,
            nearby_emitters=[high_power_paging, cellular_850],
        )
        assert res.ok is True and res.value is not None
        score = res.value
        assert score.requires_cavity_filter is True
        assert score.desense_risk in (DesenseRiskLevel.HIGH, DesenseRiskLevel.CRITICAL)
        assert score.rf_cleanliness_score < 50.0
        assert any("902-928 mhz bandpass cavity filter" in n.lower() for n in score.recommended_hardware_notes)


class TestPowerAndAccessScoring:
    """Verify scoring differences between drive-up grid sites and remote off-grid peaks."""

    def test_drive_up_grid_site_beats_remote_helicopter_peak_on_structural_score(self) -> None:
        drive_up_site = _sample_municipal_water_tower()
        helicopter_peak = SiteCandidate(
            site_id="VT-CAMEL-PK",
            name="Camel's Hump Alpine Summit",
            location=Coordinate(lat=44.3195, lon=-72.8863, elevation_m=1244.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=4.0,
            has_grid_power=False,
            solar_exposure_pct=55.0,
            access_difficulty=AccessDifficulty.HELICOPTER,
        )

        res_drive = score_site_viability(drive_up_site)
        res_heli = score_site_viability(helicopter_peak)
        assert res_drive.ok and res_drive.value is not None
        assert res_heli.ok and res_heli.value is not None

        assert res_drive.value.structural_and_power_score > res_heli.value.structural_and_power_score + 35.0
        assert any("lifepo4" in n.lower() for n in res_heli.value.recommended_hardware_notes)

    def test_empty_candidates_returns_result_fail(self) -> None:
        res = rank_candidate_sites([])
        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "EMPTY_CANDIDATES"

    def test_invalid_coverage_fraction_returns_result_fail(self) -> None:
        res = score_site_viability(_sample_public_silo(), coverage_fraction=1.5)
        assert res.ok is False
        assert res.error is not None
        assert res.error.code == "INVALID_COVERAGE_FRACTION"
