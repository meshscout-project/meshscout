"""Unit tests for MeshScout ad-hoc tactical pins adapter."""

import pytest
from pydantic import ValidationError

from meshscout.adapters.pins import (
    AdHocPin,
    create_ad_hoc_pin,
    pin_to_site_candidate,
    sample_terrain_elevation,
)
from meshscout.core.contracts import (
    AccessDifficulty,
    Coordinate,
    SiteCandidate,
    SiteType,
)


def test_sample_terrain_elevation_mansfield() -> None:
    """Mount Mansfield summit (44.543, -72.814) should return >1000m ASL and be rounded to 1 decimal place."""
    elevation = sample_terrain_elevation(44.543, -72.814)
    assert isinstance(elevation, float)
    assert elevation > 1000.0
    # Check rounding precision (1 decimal place)
    assert elevation == round(elevation, 1)


def test_sample_terrain_elevation_custom_fn() -> None:
    """Custom elevation callable should be utilized and rounded to 1 decimal place."""
    custom_fn = lambda lat, lon: 123.4567
    elevation = sample_terrain_elevation(44.0, -73.0, elevation_fn=custom_fn)
    assert elevation == 123.5


def test_create_ad_hoc_pin_auto_elevation() -> None:
    """create_ad_hoc_pin auto-samples elevation when elevation_m is omitted."""
    pin = create_ad_hoc_pin(
        name="Mansfield Tactical Lookout",
        lat=44.543,
        lon=-72.814,
    )
    assert isinstance(pin, AdHocPin)
    assert pin.name == "Mansfield Tactical Lookout"
    assert pin.lat == 44.543
    assert pin.lon == -72.814
    assert pin.elevation_m > 1000.0
    assert pin.elevation_m == round(pin.elevation_m, 1)
    assert pin.mast_height_m == 10.0
    assert pin.site_type == SiteType.BUILDING_ROOFTOP
    assert pin.notes == ""
    assert pin.pin_id.startswith("pin_")
    assert pin.created_at_iso is not None


def test_create_ad_hoc_pin_explicit_parameters() -> None:
    """create_ad_hoc_pin retains explicit elevation, mast height, site type, and custom pin_id."""
    pin = create_ad_hoc_pin(
        name="Burlington Water Tower AdHoc",
        lat=44.4759,
        lon=-73.2121,
        mast_height_m=25.0,
        site_type=SiteType.WATER_TOWER,
        notes="High priority repeater node",
        elevation_m=95.0,
        pin_id="custom_burl_01",
        source_url="https://example.com/site",
    )
    assert pin.pin_id == "custom_burl_01"
    assert pin.elevation_m == 95.0
    assert pin.mast_height_m == 25.0
    assert pin.site_type == SiteType.WATER_TOWER
    assert pin.notes == "High priority repeater node"
    assert pin.source_url == "https://example.com/site"


def test_pin_to_site_candidate_conversion() -> None:
    """pin_to_site_candidate produces a fully valid SiteCandidate model with expected field mappings."""
    pin = create_ad_hoc_pin(
        name="Bolton Ridge Repeater",
        lat=44.42,
        lon=-72.88,
        mast_height_m=15.0,
        site_type=SiteType.COMMUNICATIONS_TOWER,
        notes="Backbone mesh relay",
        elevation_m=650.0,
        pin_id="bolton_relay_01",
    )

    candidate = pin_to_site_candidate(pin)

    assert isinstance(candidate, SiteCandidate)
    assert candidate.site_id == "adhoc_bolton_relay_01"
    assert candidate.name == "Bolton Ridge Repeater"
    assert candidate.location == Coordinate(lat=44.42, lon=-72.88, elevation_m=650.0)
    assert candidate.mast_height_m == 15.0
    assert candidate.site_type == SiteType.COMMUNICATIONS_TOWER
    assert candidate.access_difficulty == AccessDifficulty.DRIVE_UP
    assert candidate.has_grid_power is True
    assert candidate.solar_exposure_pct == 85.0
    assert candidate.notes == "Community Tactical Pin: Backbone mesh relay"
    assert candidate.source_url == "https://meshscout.local/ad-hoc"
    assert getattr(candidate, "county", None) == "Custom / Ad-Hoc"
    assert getattr(candidate, "is_public_land", None) is False


def test_pin_to_site_candidate_with_source_url() -> None:
    """pin_to_site_candidate preserves user-provided source_url."""
    pin = create_ad_hoc_pin(
        name="Stowe Peak",
        lat=44.53,
        lon=-72.79,
        elevation_m=800.0,
        source_url="https://communitymesh.org/nodes/42",
    )
    candidate = pin_to_site_candidate(pin)
    assert candidate.source_url == "https://communitymesh.org/nodes/42"


def test_validation_errors() -> None:
    """Invalid latitude, longitude, mast_height, and elevation raise ValidationError."""
    # Latitude out of bounds (> 90.0)
    with pytest.raises(ValidationError):
        AdHocPin(name="Invalid Lat", lat=91.0, lon=-72.0, elevation_m=100.0)

    # Latitude out of bounds (< -90.0)
    with pytest.raises(ValidationError):
        AdHocPin(name="Invalid Lat", lat=-90.1, lon=-72.0, elevation_m=100.0)

    # Longitude out of bounds (> 180.0)
    with pytest.raises(ValidationError):
        AdHocPin(name="Invalid Lon", lat=44.0, lon=180.1, elevation_m=100.0)

    # Longitude out of bounds (< -180.0)
    with pytest.raises(ValidationError):
        AdHocPin(name="Invalid Lon", lat=44.0, lon=-180.1, elevation_m=100.0)

    # Empty name
    with pytest.raises(ValidationError):
        AdHocPin(name="", lat=44.0, lon=-72.0, elevation_m=100.0)

    # Mast height < 1.0
    with pytest.raises(ValidationError):
        AdHocPin(name="Zero Mast", lat=44.0, lon=-72.0, elevation_m=100.0, mast_height_m=0.5)

    # Mast height > 300.0
    with pytest.raises(ValidationError):
        AdHocPin(name="Giant Mast", lat=44.0, lon=-72.0, elevation_m=100.0, mast_height_m=301.0)

    # Elevation < -100.0
    with pytest.raises(ValidationError):
        AdHocPin(name="Deep Trench", lat=44.0, lon=-72.0, elevation_m=-105.0)

    # Elevation > 9000.0
    with pytest.raises(ValidationError):
        AdHocPin(name="Stratosphere", lat=44.0, lon=-72.0, elevation_m=9005.0)


def test_round_trip_serialization() -> None:
    """AdHocPin and converted SiteCandidate support model_dump(mode='json') and validation."""
    pin = create_ad_hoc_pin(
        name="SerDe Test Pin",
        lat=44.4759,
        lon=-73.2121,
        elevation_m=112.5,
        notes="Testing JSON serialization",
    )
    raw_json = pin.model_dump(mode="json")
    assert isinstance(raw_json, dict)
    assert raw_json["name"] == "SerDe Test Pin"
    assert raw_json["elevation_m"] == 112.5

    restored_pin = AdHocPin.model_validate(raw_json)
    assert restored_pin.pin_id == pin.pin_id
    assert restored_pin.lat == pin.lat
    assert restored_pin.lon == pin.lon
    assert restored_pin.elevation_m == pin.elevation_m

    candidate = pin_to_site_candidate(pin)
    cand_json = candidate.model_dump(mode="json")
    assert isinstance(cand_json, dict)
    restored_cand = SiteCandidate.model_validate(cand_json)
    assert restored_cand.site_id == candidate.site_id
    assert restored_cand.location.lat == pin.lat
