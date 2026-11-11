"""Hermetic unit tests for cross-border high sites (New Hampshire, New York Adirondack/Champlain, Quebec, Maine).

Validates schema adherence, Pydantic contracts, and point-to-point RF link budgets
between Vermont/New Hampshire backbone nodes and neighboring high-elevation repeaters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
import pytest

from meshscout.adapters.vt_counties import _normalize_site_dict
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    ElevationProfile,
    RadioConfig,
    SiteCandidate,
    SiteType,
)
from meshscout.core.fresnel import haversine_distance_km
from meshscout.core.itm import evaluate_point_to_point_link
from meshscout.core.viewshed import sample_transect_points

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
NH_FIXTURE_PATH = FIXTURES_DIR / "nh_high_sites_sample.json"
NY_FIXTURE_PATH = FIXTURES_DIR / "ny_adirondack_champlain_sample.json"
QC_FIXTURE_PATH = FIXTURES_DIR / "qc_high_sites_sample.json"
ME_FIXTURE_PATH = FIXTURES_DIR / "me_high_sites_sample.json"


def _load_and_validate_fixture(path: Path) -> List[SiteCandidate]:
    """Load JSON array fixture and validate each entry as a SiteCandidate."""
    assert path.exists(), f"Fixture file not found: {path}"
    raw_content = path.read_text(encoding="utf-8")
    raw_sites = json.loads(raw_content)
    assert isinstance(raw_sites, list), f"Expected list in {path}, got {type(raw_sites)}"

    candidates: List[SiteCandidate] = []
    for item in raw_sites:
        assert isinstance(item, dict), f"Expected dict site item, got {type(item)}"
        normalized = _normalize_site_dict(item)
        candidate = SiteCandidate.model_validate(normalized)
        candidates.append(candidate)
    return candidates


class TestCrossBorderFixtures:
    """Validate JSON structure, completeness, and Pydantic validation of cross-border fixtures."""

    @pytest.mark.parametrize("fixture_path", [NH_FIXTURE_PATH, NY_FIXTURE_PATH, QC_FIXTURE_PATH, ME_FIXTURE_PATH])
    def test_fixture_files_exist_and_parse(self, fixture_path: Path) -> None:
        """Verify fixture JSON files exist and contain valid non-empty arrays."""
        assert fixture_path.exists()
        candidates = _load_and_validate_fixture(fixture_path)
        assert len(candidates) >= 2, f"Fixture {fixture_path.name} should contain at least 2 sites."

    def test_nh_high_sites_contract_conformance(self) -> None:
        """Verify New Hampshire high sites adhere to SiteCandidate contract requirements."""
        candidates = _load_and_validate_fixture(NH_FIXTURE_PATH)
        assert len(candidates) == 6

        expected_site_ids = {
            "NH-COOS-WASH-01",
            "NH-GRAF-CANN-01",
            "NH-MERR-KEAR-01",
            "NH-CHES-MONA-01",
            "NH-BELK-GUNS-01",
            "NH-GRAF-MOOS-01",
        }
        loaded_ids = {s.site_id for s in candidates}
        assert loaded_ids == expected_site_ids

        for site in candidates:
            assert len(site.name.strip()) > 0, f"Site {site.site_id} must have a non-empty name"
            assert site.location.elevation_m > 0.0, f"Site {site.site_id} must have positive elevation"
            assert site.source_url is not None and (
                site.source_url.startswith("https://") or site.source_url.startswith("http://")
            )
            assert site.site_type in set(SiteType)
            assert site.access_difficulty in set(AccessDifficulty)
            assert site.mast_height_m > 0.0
            assert 0.0 <= site.solar_exposure_pct <= 100.0

            # Bounding check for New Hampshire: latitude 42.6 to 45.4, longitude -72.6 to -70.6
            assert 42.6 <= site.location.lat <= 45.4
            assert -72.6 <= site.location.lon <= -70.6

    def test_ny_adirondack_champlain_contract_conformance(self) -> None:
        """Verify New York Adirondack / Champlain sites adhere to SiteCandidate contract requirements."""
        candidates = _load_and_validate_fixture(NY_FIXTURE_PATH)
        assert len(candidates) == 4

        expected_site_ids = {
            "NY-ESSE-WHIT-01",
            "NY-CLIN-LYON-01",
            "NY-ESSE-POKE-01",
            "NY-WARR-PROS-01",
        }
        loaded_ids = {s.site_id for s in candidates}
        assert loaded_ids == expected_site_ids

        for site in candidates:
            assert len(site.name.strip()) > 0, f"Site {site.site_id} must have a non-empty name"
            assert site.location.elevation_m > 0.0, f"Site {site.site_id} must have positive elevation"
            assert site.source_url is not None and (
                site.source_url.startswith("https://") or site.source_url.startswith("http://")
            )
            assert site.site_type in set(SiteType)
            assert site.access_difficulty in set(AccessDifficulty)
            assert site.mast_height_m > 0.0
            assert 0.0 <= site.solar_exposure_pct <= 100.0

            # Bounding check for Eastern NY / Adirondacks: latitude 43.0 to 45.1, longitude -74.5 to -73.3
            assert 43.0 <= site.location.lat <= 45.1
            assert -74.5 <= site.location.lon <= -73.3

    def test_qc_high_sites_contract_conformance(self) -> None:
        """Verify Quebec high sites adhere to SiteCandidate contract requirements."""
        candidates = _load_and_validate_fixture(QC_FIXTURE_PATH)
        assert len(candidates) == 5

        expected_site_ids = {
            "QC-ESTR-SUTT-01",
            "QC-ESTR-MEGA-01",
            "QC-ESTR-ORFO-01",
            "QC-MONT-HILA-01",
            "QC-MTL-ROYA-01",
        }
        loaded_ids = {s.site_id for s in candidates}
        assert loaded_ids == expected_site_ids

        for site in candidates:
            assert len(site.name.strip()) > 0, f"Site {site.site_id} must have a non-empty name"
            assert site.location.elevation_m > 0.0, f"Site {site.site_id} must have positive elevation"
            assert site.source_url is not None and (
                site.source_url.startswith("https://") or site.source_url.startswith("http://")
            )
            assert site.site_type in set(SiteType)
            assert site.access_difficulty in set(AccessDifficulty)
            assert site.mast_height_m > 0.0
            assert 0.0 <= site.solar_exposure_pct <= 100.0

            # Bounding check for Southern Quebec / Monteregie / Estrie / Montreal: lat 45.0 to 46.0, lon -74.0 to -71.0
            assert 45.0 <= site.location.lat <= 46.0
            assert -74.0 <= site.location.lon <= -71.0

    def test_me_high_sites_contract_conformance(self) -> None:
        """Verify Maine high sites adhere to SiteCandidate contract requirements."""
        candidates = _load_and_validate_fixture(ME_FIXTURE_PATH)
        assert len(candidates) == 2

        expected_site_ids = {
            "ME-FRAN-SUGA-01",
            "ME-OXFO-PLEA-01",
        }
        loaded_ids = {s.site_id for s in candidates}
        assert loaded_ids == expected_site_ids

        for site in candidates:
            assert len(site.name.strip()) > 0, f"Site {site.site_id} must have a non-empty name"
            assert site.location.elevation_m > 0.0, f"Site {site.site_id} must have positive elevation"
            assert site.source_url is not None and (
                site.source_url.startswith("https://") or site.source_url.startswith("http://")
            )
            assert site.site_type in set(SiteType)
            assert site.access_difficulty in set(AccessDifficulty)
            assert site.mast_height_m > 0.0
            assert 0.0 <= site.solar_exposure_pct <= 100.0

            # Bounding check for Western/Southern Maine: lat 43.8 to 45.5, lon -71.2 to -70.0
            assert 43.8 <= site.location.lat <= 45.5
            assert -71.2 <= site.location.lon <= -70.0


class TestCrossBorderLinks:
    """Evaluate interstate and international RF point-to-point links across VT-NH, VT-NY, VT-QC, and NH-QC corridors."""

    @pytest.fixture
    def mount_mansfield(self) -> SiteCandidate:
        """Reference Vermont high-site backbone node on Mount Mansfield."""
        return SiteCandidate(
            site_id="VT-MANS-01",
            name="Mount Mansfield Summit",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=15.0,
            has_grid_power=True,
            solar_exposure_pct=95.0,
            access_difficulty=AccessDifficulty.MODERATE,
            source_url="https://fpr.vermont.gov/mount-mansfield-state-forest",
            notes="Primary Green Mountain backbone repeater site",
        )

    @pytest.fixture
    def jay_peak(self) -> SiteCandidate:
        """Reference Northern Vermont high-site backbone node on Jay Peak."""
        return SiteCandidate(
            site_id="VT-FRA-01",
            name="Jay Peak Summit",
            location=Coordinate(lat=44.9242, lon=-72.5256, elevation_m=1176.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=15.0,
            has_grid_power=True,
            solar_exposure_pct=100.0,
            access_difficulty=AccessDifficulty.MODERATE,
            source_url="https://jaypeakresort.com",
            notes="Northern Vermont high-elevation sentinel overlooking Quebec border",
        )

    def test_link_mansfield_to_mount_washington(self, mount_mansfield: SiteCandidate) -> None:
        """Evaluate cross-border backbone link between Mount Mansfield (VT) and Mount Washington (NH)."""
        nh_sites = _load_and_validate_fixture(NH_FIXTURE_PATH)
        wash_candidates = [s for s in nh_sites if s.site_id == "NH-COOS-WASH-01"]
        assert len(wash_candidates) == 1
        mount_washington = wash_candidates[0]

        dist_km = haversine_distance_km(mount_mansfield.location, mount_washington.location)
        assert 120.0 <= dist_km <= 130.0, f"Unexpected distance: {dist_km} km (expected 120-130 km)"

        # Build transect profile and evaluate point-to-point link budget
        transect_pts = sample_transect_points(
            mount_mansfield.location,
            mount_washington.location,
            num_samples=25,
        )
        profile = ElevationProfile(
            source_site=mount_mansfield,
            target_site=mount_washington,
            distance_km=dist_km,
            points=transect_pts,
        )

        res = evaluate_point_to_point_link(profile, RadioConfig())
        assert res.ok is True, f"Link evaluation failed: {res.error}"
        assert res.value is not None

        link = res.value
        assert link.source_id == "VT-MANS-01"
        assert link.target_id == "NH-COOS-WASH-01"
        assert link.distance_km == pytest.approx(dist_km, abs=0.1)
        assert isinstance(link.link_margin_db, float)
        assert link.total_path_loss_db > 0.0

    def test_link_mansfield_to_whiteface_mountain(self, mount_mansfield: SiteCandidate) -> None:
        """Evaluate cross-border backbone link between Mount Mansfield (VT) and Whiteface Mountain (NY)."""
        ny_sites = _load_and_validate_fixture(NY_FIXTURE_PATH)
        whiteface_candidates = [s for s in ny_sites if s.site_id == "NY-ESSE-WHIT-01"]
        assert len(whiteface_candidates) == 1
        whiteface = whiteface_candidates[0]

        dist_km = haversine_distance_km(mount_mansfield.location, whiteface.location)
        assert 85.0 <= dist_km <= 95.0, f"Unexpected distance: {dist_km} km (expected 85-95 km)"

        # Build transect profile and evaluate point-to-point link budget
        transect_pts = sample_transect_points(
            mount_mansfield.location,
            whiteface.location,
            num_samples=25,
        )
        profile = ElevationProfile(
            source_site=mount_mansfield,
            target_site=whiteface,
            distance_km=dist_km,
            points=transect_pts,
        )

        res = evaluate_point_to_point_link(profile, RadioConfig())
        assert res.ok is True, f"Link evaluation failed: {res.error}"
        assert res.value is not None

        link = res.value
        assert link.source_id == "VT-MANS-01"
        assert link.target_id == "NY-ESSE-WHIT-01"
        assert link.distance_km == pytest.approx(dist_km, abs=0.1)
        assert isinstance(link.link_margin_db, float)
        assert link.total_path_loss_db > 0.0

    def test_link_jay_peak_to_mont_sutton(self, jay_peak: SiteCandidate) -> None:
        """Evaluate international cross-border backbone link between Jay Peak (VT) and Mont Sutton (QC)."""
        qc_sites = _load_and_validate_fixture(QC_FIXTURE_PATH)
        sutton_candidates = [s for s in qc_sites if s.site_id == "QC-ESTR-SUTT-01"]
        assert len(sutton_candidates) == 1
        mont_sutton = sutton_candidates[0]

        dist_km = haversine_distance_km(jay_peak.location, mont_sutton.location)
        assert 20.0 <= dist_km <= 22.0, f"Unexpected distance: {dist_km} km (expected ~21-22 km)"

        # Build transect profile and evaluate point-to-point link budget
        transect_pts = sample_transect_points(
            jay_peak.location,
            mont_sutton.location,
            num_samples=25,
        )
        profile = ElevationProfile(
            source_site=jay_peak,
            target_site=mont_sutton,
            distance_km=dist_km,
            points=transect_pts,
        )

        res = evaluate_point_to_point_link(profile, RadioConfig())
        assert res.ok is True, f"Link evaluation failed: {res.error}"
        assert res.value is not None

        link = res.value
        assert link.source_id == "VT-FRA-01"
        assert link.target_id == "QC-ESTR-SUTT-01"
        assert link.distance_km == pytest.approx(dist_km, abs=0.1)
        assert isinstance(link.link_margin_db, float)
        assert link.link_margin_db > 0.0
        assert link.total_path_loss_db > 0.0

    def test_link_mount_washington_to_mont_megantic(self) -> None:
        """Evaluate international cross-border backbone link between Mount Washington (NH) and Mont Mégantic (QC)."""
        nh_sites = _load_and_validate_fixture(NH_FIXTURE_PATH)
        wash_candidates = [s for s in nh_sites if s.site_id == "NH-COOS-WASH-01"]
        assert len(wash_candidates) == 1
        mount_washington = wash_candidates[0]

        qc_sites = _load_and_validate_fixture(QC_FIXTURE_PATH)
        mega_candidates = [s for s in qc_sites if s.site_id == "QC-ESTR-MEGA-01"]
        assert len(mega_candidates) == 1
        mont_megantic = mega_candidates[0]

        dist_km = haversine_distance_km(mount_washington.location, mont_megantic.location)
        assert 125.0 <= dist_km <= 135.0, f"Unexpected distance: {dist_km} km (expected ~130 km)"

        # Build transect profile and evaluate point-to-point link budget
        transect_pts = sample_transect_points(
            mount_washington.location,
            mont_megantic.location,
            num_samples=25,
        )
        profile = ElevationProfile(
            source_site=mount_washington,
            target_site=mont_megantic,
            distance_km=dist_km,
            points=transect_pts,
        )

        res = evaluate_point_to_point_link(profile, RadioConfig())
        assert res.ok is True, f"Link evaluation failed: {res.error}"
        assert res.value is not None

        link = res.value
        assert link.source_id == "NH-COOS-WASH-01"
        assert link.target_id == "QC-ESTR-MEGA-01"
        assert link.distance_km == pytest.approx(dist_km, abs=0.1)
        assert isinstance(link.link_margin_db, float)
        assert link.total_path_loss_db > 0.0
