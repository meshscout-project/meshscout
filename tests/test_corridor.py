"""Unit tests for Multi-Hop Corridor Evaluation Engine."""

import pytest
from meshscout.core.contracts import (
    Coordinate,
    RadioConfig,
    ReachabilityState,
    SiteCandidate,
    SiteRadioProfile,
    SiteType,
)
from meshscout.core.corridor import (
    CorridorHopResult,
    MultiHopCorridorResult,
    evaluate_multihop_corridor,
)
from meshscout.core.presets import build_radio_config, resolve_site_radio_profile


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


def test_corridor_legacy_symmetric_defaults_keep_directional_fields_none(
    mansfield_site: SiteCandidate,
    bolton_site: SiteCandidate,
):
    """Verify legacy symmetric evaluation leaves directional and reachability fields as None."""
    res = evaluate_multihop_corridor(nodes=[mansfield_site, bolton_site])
    assert res.ok is True
    assert res.value is not None

    hop = res.value.hops[0]
    assert hop.forward_margin_db is None
    assert hop.reverse_margin_db is None
    assert hop.reachability_state is None


def test_heterogeneous_site_profiles_corridor_bottleneck():
    """Verify heterogeneous 28 dBm commercial tower -> 22 dBm solar relay -> 28 dBm summit corridor."""
    comm_tower = SiteCandidate(
        site_id="VT-COMM-01",
        name="Commercial Broadcast Tower",
        location=Coordinate(lat=44.4800, lon=-73.2200, elevation_m=320.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=25.0,
    )
    solar_relay = SiteCandidate(
        site_id="VT-SOLAR-01",
        name="Foothill Solar Lookout Relay",
        location=Coordinate(lat=44.4900, lon=-73.0200, elevation_m=520.0),
        site_type=SiteType.FIRE_LOOKOUT,
        mast_height_m=8.0,
    )
    summit_node = SiteCandidate(
        site_id="VT-SUMM-01",
        name="Green Mountain Summit Backbone",
        location=Coordinate(lat=44.5400, lon=-72.8100, elevation_m=1180.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=15.0,
    )

    comm_prof = resolve_site_radio_profile(
        site_type=comm_tower.site_type,
        hardware_id="STATION_G2_BACKBONE",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="SUMMER_FOLIAGE",
    ).value
    solar_prof = resolve_site_radio_profile(
        site_type=solar_relay.site_type,
        hardware_id="RAK4631_SOLAR",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="SUMMER_FOLIAGE",
    ).value
    summit_prof = resolve_site_radio_profile(
        site_type=summit_node.site_type,
        hardware_id="STATION_G2_BACKBONE",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="SUMMER_FOLIAGE",
    ).value
    assert comm_prof is not None and solar_prof is not None and summit_prof is not None

    res = evaluate_multihop_corridor(
        nodes=[comm_tower, solar_relay, summit_node],
        elevation_fn=lambda lat, lon: 150.0,
        site_profiles={
            comm_tower.site_id: comm_prof,
            solar_relay.site_id: solar_prof,
            summit_node.site_id: summit_prof,
        },
        min_margin_db=3.0,
    )
    assert res.ok is True
    assert res.value is not None
    corridor = res.value
    assert corridor.total_hops == 2

    hop0, hop1 = corridor.hops[0], corridor.hops[1]
    assert hop0.forward_margin_db is not None and hop0.reverse_margin_db is not None
    assert hop1.forward_margin_db is not None and hop1.reverse_margin_db is not None
    assert hop0.reachability_state == ReachabilityState.TWO_WAY
    assert hop1.reachability_state == ReachabilityState.TWO_WAY

    # Hop 0: 28 dBm noisy (6 dB) comm tower -> 22 dBm quiet (1 dB) solar relay:
    # forward exceeds reverse by (28 - 22) + (6 - 1) = +11.0 dB
    assert hop0.forward_margin_db - hop0.reverse_margin_db == pytest.approx(11.0, abs=0.05)
    assert hop0.link_margin_db == hop0.reverse_margin_db

    # Hop 1: 22 dBm quiet (1 dB) solar relay -> 28 dBm mountain peak (3 dB):
    # reverse exceeds forward by (28 - 22) + (3 - 1) = +8.0 dB
    assert hop1.reverse_margin_db - hop1.forward_margin_db == pytest.approx(8.0, abs=0.05)
    assert hop1.link_margin_db == hop1.forward_margin_db

    expected_worst = min(hop0.link_margin_db, hop1.link_margin_db)
    assert corridor.worst_link_margin_db == expected_worst
    assert corridor.bottleneck_hop_index is not None
    assert corridor.hops[corridor.bottleneck_hop_index].link_margin_db == expected_worst


def test_corridor_reverse_direction_bottleneck_identification():
    """Verify reverse-direction uplink degradation overrides higher forward margin in bottleneck index."""
    node_a = SiteCandidate(
        site_id="VT-NOISY-TOWER",
        name="High-Desense Commercial Tower",
        location=Coordinate(lat=44.4000, lon=-73.2000, elevation_m=300.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=15.0,
    )
    node_b = SiteCandidate(
        site_id="VT-MID-SOLAR",
        name="Mid-Corridor Solar Relay",
        location=Coordinate(lat=44.4000, lon=-73.0500, elevation_m=300.0),
        site_type=SiteType.FIRE_LOOKOUT,
        mast_height_m=15.0,
    )
    node_c = SiteCandidate(
        site_id="VT-EAST-SOLAR",
        name="East Ridge Solar Relay",
        location=Coordinate(lat=44.4000, lon=-72.8300, elevation_m=300.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=15.0,
    )

    noisy_g2_prof = resolve_site_radio_profile(
        site_type=node_a.site_type,
        hardware_id="STATION_G2_BACKBONE",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="SUMMER_FOLIAGE",
        noise_override_db=22.0,
    ).value
    solar_radio = build_radio_config(
        hardware_id="RAK4631_SOLAR",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="SUMMER_FOLIAGE",
    ).value
    assert noisy_g2_prof is not None and solar_radio is not None

    # Supply node_a in site_profiles; let node_b and node_c resolve via fallback (solar_radio + site noise)
    res = evaluate_multihop_corridor(
        nodes=[node_a, node_b, node_c],
        elevation_fn=lambda lat, lon: 100.0,
        radio_config=solar_radio,
        site_profiles={node_a.site_id: noisy_g2_prof},
        min_margin_db=35.0,
    )
    assert res.ok is True
    assert res.value is not None
    corridor = res.value

    hop0, hop1 = corridor.hops[0], corridor.hops[1]
    assert hop0.forward_margin_db is not None and hop0.reverse_margin_db is not None
    assert hop1.forward_margin_db is not None and hop1.reverse_margin_db is not None

    # Forward-only check would consider Hop 0 stronger than longer Hop 1:
    assert hop0.forward_margin_db > hop1.forward_margin_db
    # However, Hop 0 reverse direction (22 dBm into 22 dB desensed tower) is severely degraded:
    assert hop0.reverse_margin_db < 35.0
    assert hop0.reachability_state == ReachabilityState.HEAR_ONLY_ALLIGATOR
    assert hop1.reachability_state == ReachabilityState.TWO_WAY

    # Bidirectional bottleneck correctly flags Hop 0 via its reverse margin!
    assert hop0.link_margin_db == hop0.reverse_margin_db
    assert corridor.bottleneck_hop_index == 0
    assert corridor.worst_link_margin_db == hop0.reverse_margin_db
