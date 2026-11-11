"""Hermetic unit tests for MeshScout core contracts and offline fixtures."""

import json
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    MeshScoutError,
    RegionalBounds,
    Result,
    SiteCandidate,
    SiteType,
)


def test_valid_coordinate():
    """Verify standard valid coordinate creation."""
    coord = Coordinate(lat=44.4759, lon=-73.2121, elevation_m=65.0)
    assert coord.lat == 44.4759
    assert coord.lon == -73.2121
    assert coord.elevation_m == 65.0


def test_coordinate_out_of_bounds():
    """Verify out-of-bounds coordinates raise ValidationError."""
    with pytest.raises(ValidationError):
        Coordinate(lat=95.0, lon=-73.0)

    with pytest.raises(ValidationError):
        Coordinate(lat=-95.0, lon=-73.0)

    with pytest.raises(ValidationError):
        Coordinate(lat=45.0, lon=190.0)

    with pytest.raises(ValidationError):
        Coordinate(lat=45.0, lon=-195.0)


def test_regional_bounds_containment():
    """Verify regional bounding box validation and containment checks."""
    bounds = RegionalBounds(
        name="Test_Region",
        min_lat=44.0,
        max_lat=45.0,
        min_lon=-74.0,
        max_lon=-72.0,
    )
    inside = Coordinate(lat=44.5, lon=-73.0)
    outside = Coordinate(lat=45.5, lon=-73.0)

    assert bounds.contains(inside) is True
    assert bounds.contains(outside) is False

    # Inverted latitude bounds should fail
    with pytest.raises(ValidationError):
        RegionalBounds(
            name="Inverted_Region",
            min_lat=45.0,
            max_lat=44.0,
            min_lon=-74.0,
            max_lon=-72.0,
        )


def test_site_candidate_contract():
    """Verify SiteCandidate validation and defaults."""
    site = SiteCandidate(
        site_id="SITE-01",
        name="Ridge Site",
        location=Coordinate(lat=44.5, lon=-72.8, elevation_m=800.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=12.0,
    )
    assert site.site_id == "SITE-01"
    assert site.site_type == SiteType.MOUNTAIN_PEAK
    assert site.access_difficulty == AccessDifficulty.MODERATE
    assert site.has_grid_power is False

    # Negative mast height should fail
    with pytest.raises(ValidationError):
        SiteCandidate(
            site_id="SITE-BAD",
            name="Bad Mast",
            location=Coordinate(lat=44.5, lon=-72.8),
            mast_height_m=-5.0,
        )


def test_result_union_pattern():
    """Verify Result monad pattern for success and failure."""
    res_success = Result[str].success("Computed link budget")
    assert res_success.ok is True
    assert res_success.value == "Computed link budget"
    assert res_success.error is None

    res_fail = Result[str].fail(code="TERRAIN_OCCLUSION", message="Direct line of sight blocked")
    assert res_fail.ok is False
    assert res_fail.value is None
    assert res_fail.error is not None
    assert res_fail.error.code == "TERRAIN_OCCLUSION"


def test_load_chittenden_fixture_speed():
    """Verify offline fixture parsing speed is strictly under 100ms."""
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "vt_chittenden_sample.json"
    assert fixture_path.exists(), "Offline fixture file missing"

    start = time.perf_counter()
    raw_data = json.loads(fixture_path.read_text(encoding="utf-8"))

    bounds = RegionalBounds.model_validate(raw_data["bounds"])
    sites = [SiteCandidate.model_validate(s) for s in raw_data["sites"]]
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert elapsed_ms < 100.0, f"Fixture load took {elapsed_ms:.2f}ms (expected <100ms)"
    assert bounds.name == "Vermont_Chittenden_County"
    assert len(sites) == 5

    # Verify all sites are geographically inside Chittenden County bounds
    for s in sites:
        assert bounds.contains(s.location), f"Site {s.site_id} outside bounds"
