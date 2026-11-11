"""Unit tests for Multi-Hop Corridor Evaluation Engine."""

import pytest
from meshscout.core.contracts import Coordinate, RadioConfig, SiteCandidate
from meshscout.core.corridor import (
    CorridorHopResult,
    MultiHopCorridorResult,
    evaluate_multihop_corridor,
)


@pytest.fixture
def mansfield_site() -> SiteCandidate:
    """Mount Mansfield summit high-site candidate."""
    return SiteCandidate(
        site_id="VT-CHIT-MANS-01",
        name="Mount Mansfield Summit",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        mast_height_m=15.0,
    )


@pytest.fixture
def bolton_site() -> SiteCandidate:
    """Bolton Mountain peak candidate."""
    return SiteCandidate(
        site_id="VT-CHIT-BOLT-01",
        name="Bolton Mountain Peak",
        location=Coordinate(lat=44.4285, lon=-72.8550, elevation_m=1123.0),
        mast_height_m=15.0,
    )


@pytest.fixture
def philo_site() -> SiteCandidate:
    """Mount Philo state park summit candidate."""
    return SiteCandidate(
        site_id="VT-CHIT-PHIL-01",
        name="Mount Philo",
        location=Coordinate(lat=44.2789, lon=-73.2167, elevation_m=295.0),
        mast_height_m=15.0,
    )


@pytest.fixture
def burlington_site() -> SiteCandidate:
    """Burlington municipal water tank candidate."""
    return SiteCandidate(
        site_id="VT-CHIT-BURL-01",
        name="Burlington Water Tank",
        location=Coordinate(lat=44.4759, lon=-73.2000, elevation_m=110.0),
        mast_height_m=20.0,
    )


def test_empty_corridor():
    """Verify empty nodes sequence returns success with 0 hops."""
    res = evaluate_multihop_corridor([])
    assert res.ok is True
    assert res.value is not None

    r = res.value
    assert r.node_ids == []
    assert r.total_hops == 0
    assert r.total_distance_km == 0.0
    assert r.all_clear_los is True
    assert r.worst_link_margin_db == 999.0
    assert r.bottleneck_hop_index is None
    assert r.hops == []


def test_single_node_corridor(mansfield_site: SiteCandidate):
    """Verify single-node sequence returns success with 0 hops."""
    res = evaluate_multihop_corridor([mansfield_site])
    assert res.ok is True
    assert res.value is not None

    r = res.value
    assert r.node_ids == ["VT-CHIT-MANS-01"]
    assert r.total_hops == 0
    assert r.total_distance_km == 0.0
    assert r.all_clear_los is True
    assert r.worst_link_margin_db == 999.0
    assert r.bottleneck_hop_index is None
    assert r.hops == []


def test_two_node_sequence_mansfield_to_bolton(
    mansfield_site: SiteCandidate,
    bolton_site: SiteCandidate,
):
    """Verify two-node sequence (Mount Mansfield to Bolton Mountain)."""
    res = evaluate_multihop_corridor([mansfield_site, bolton_site])
    assert res.ok is True
    assert res.value is not None

    r = res.value
    assert r.node_ids == ["VT-CHIT-MANS-01", "VT-CHIT-BOLT-01"]
    assert r.total_hops == 1
    assert len(r.hops) == 1

    hop = r.hops[0]
    assert hop.hop_index == 0
    assert hop.origin_site_id == "VT-CHIT-MANS-01"
    assert hop.origin_name == "Mount Mansfield Summit"
    assert hop.target_site_id == "VT-CHIT-BOLT-01"
    assert hop.target_name == "Bolton Mountain Peak"
    assert hop.distance_km > 12.0
    assert hop.has_line_of_sight is True
    assert hop.link_margin_db > 20.0
    assert hop.fresnel_clearance_ratio > 1.0
    assert hop.elevation_delta_m == round(1123.0 - 1339.0, 1)

    assert r.all_clear_los is True
    assert r.bottleneck_hop_index == 0
    assert r.worst_link_margin_db == hop.link_margin_db
    assert r.total_distance_km == hop.distance_km


def test_three_node_sequence_philo_burlington_mansfield(
    philo_site: SiteCandidate,
    burlington_site: SiteCandidate,
    mansfield_site: SiteCandidate,
):
    """Verify three-node sequence (Mount Philo -> Burlington Water Tank -> Mount Mansfield)."""
    nodes = [philo_site, burlington_site, mansfield_site]
    res = evaluate_multihop_corridor(nodes)
    assert res.ok is True
    assert res.value is not None

    r = res.value
    assert r.node_ids == ["VT-CHIT-PHIL-01", "VT-CHIT-BURL-01", "VT-CHIT-MANS-01"]
    assert r.total_hops == 2
    assert len(r.hops) == 2

    hop0 = r.hops[0]
    hop1 = r.hops[1]

    # Verify hop indices and node names
    assert hop0.hop_index == 0
    assert hop0.origin_site_id == philo_site.site_id
    assert hop0.origin_name == philo_site.name
    assert hop0.target_site_id == burlington_site.site_id
    assert hop0.target_name == burlington_site.name
    assert hop0.elevation_delta_m == round(burlington_site.location.elevation_m - philo_site.location.elevation_m, 1)

    assert hop1.hop_index == 1
    assert hop1.origin_site_id == burlington_site.site_id
    assert hop1.origin_name == burlington_site.name
    assert hop1.target_site_id == mansfield_site.site_id
    assert hop1.target_name == mansfield_site.name
    assert hop1.elevation_delta_m == round(mansfield_site.location.elevation_m - burlington_site.location.elevation_m, 1)

    # Verify cumulative distance
    expected_distance = round(hop0.distance_km + hop1.distance_km, 2)
    assert r.total_distance_km == expected_distance

    # Verify bottleneck identification
    min_margin = min(hop0.link_margin_db, hop1.link_margin_db)
    assert r.worst_link_margin_db == min_margin
    assert r.bottleneck_hop_index is not None
    assert r.hops[r.bottleneck_hop_index].link_margin_db == min_margin


def test_corridor_with_custom_elevation_and_radio(
    mansfield_site: SiteCandidate,
    bolton_site: SiteCandidate,
):
    """Verify corridor evaluation respects custom elevation_fn and radio_config."""
    # Flat terrain elevation model at 100m
    flat_elevation_fn = lambda lat, lon: 100.0

    # Custom high-power radio
    custom_radio = RadioConfig(
        frequency_mhz=915.0,
        tx_power_dbm=30.0,
        rx_sensitivity_dbm=-140.0,
        antenna_gain_dbi=6.0,
    )

    res = evaluate_multihop_corridor(
        nodes=[mansfield_site, bolton_site],
        elevation_fn=flat_elevation_fn,
        radio_config=custom_radio,
    )
    assert res.ok is True
    assert res.value is not None
    assert res.value.all_clear_los is True
    # With 30dBm TX, 6dBi gain and -140dBm sensitivity, link margin should be very high (> 50dB)
    assert res.value.worst_link_margin_db > 50.0


def test_corridor_with_obstructed_hop(
    philo_site: SiteCandidate,
    burlington_site: SiteCandidate,
):
    """Verify an obstruction in elevation profile causes LOS failure and identifies bottleneck."""
    # Synthetic elevation function that places a 2000m wall between sites
    def wall_elevation_fn(lat: float, lon: float) -> float:
        mid_lat = (philo_site.location.lat + burlington_site.location.lat) / 2.0
        if abs(lat - mid_lat) < 0.02:
            return 2000.0
        return 100.0

    res = evaluate_multihop_corridor(
        nodes=[philo_site, burlington_site],
        elevation_fn=wall_elevation_fn,
    )
    assert res.ok is True
    assert res.value is not None
    assert res.value.all_clear_los is False
    assert res.value.hops[0].has_line_of_sight is False
    assert res.value.bottleneck_hop_index == 0
