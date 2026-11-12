"""Unit tests for Multi-Origin Composite Viewshed and Backhaul Link Matrix Engine."""

import pytest
from meshscout.core.contracts import (
    Coordinate,
    RadioConfig,
    ReachabilityState,
    SiteCandidate,
    SiteRadioProfile,
    SiteType,
)
from meshscout.core.presets import (
    CLIENT_ENVIRONMENT_PROFILES,
    HARDWARE_PRESETS,
    build_radio_config,
    resolve_site_radio_profile,
)
from meshscout.core.composite_viewshed import (
    BackhaulLinkStatus,
    CompositeViewshedResult,
    compute_composite_viewshed,
    _synthetic_vermont_elevation_fn,
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
def valley_site_west() -> SiteCandidate:
    """Low valley site on west side of the Green Mountain ridge (Burlington waterfront)."""
    return SiteCandidate(
        site_id="VT-VALLEY-WEST",
        name="Burlington Waterfront Low",
        location=Coordinate(lat=44.4759, lon=-73.2200, elevation_m=35.0),
        mast_height_m=2.0,
    )


@pytest.fixture
def valley_site_east() -> SiteCandidate:
    """Low valley site on east side of the Green Mountain ridge (Stowe village basin)."""
    return SiteCandidate(
        site_id="VT-VALLEY-EAST",
        name="Stowe Village Basin Low",
        location=Coordinate(lat=44.4654, lon=-72.6874, elevation_m=220.0),
        mast_height_m=2.0,
    )


def test_empty_origins_returns_empty_result():
    """Verify empty origins sequence returns a valid success Result with empty composite models."""
    res = compute_composite_viewshed(origins=[])
    assert res.ok is True
    assert res.value is not None

    cv = res.value
    assert isinstance(cv, CompositeViewshedResult)
    assert cv.origin_site_ids == []
    assert cv.individual_polygons == {}
    assert cv.composite_polygons == []
    assert cv.total_illuminated_area_sq_km == 0.0
    assert cv.illuminated_towns == []
    assert cv.intersite_backhaul_links == []


def test_single_origin_returns_single_viewshed_polygon(mansfield_site):
    """Verify single origin produces exactly 1 individual polygon, 1 composite ring, and no backhaul links."""
    res = compute_composite_viewshed(origins=[mansfield_site], max_range_km=40.0, num_radials=36)
    assert res.ok is True
    assert res.value is not None

    cv = res.value
    assert cv.origin_site_ids == ["VT-CHIT-MANS-01"]
    assert len(cv.individual_polygons) == 1
    assert "VT-CHIT-MANS-01" in cv.individual_polygons

    # Closed polygon linear ring has 37 vertices [lon, lat] (36 radials + closed ring)
    mansfield_poly = cv.individual_polygons["VT-CHIT-MANS-01"]
    assert len(mansfield_poly) == 37
    assert mansfield_poly[0] == mansfield_poly[-1]
    # Coordinates in individual_polygons must be [lon, lat]
    for pt in mansfield_poly:
        assert len(pt) == 2
        lon, lat = pt
        assert -75.0 <= lon <= -70.0
        assert 43.0 <= lat <= 46.0

    assert len(cv.composite_polygons) == 1
    assert cv.composite_polygons[0] == mansfield_poly
    assert cv.total_illuminated_area_sq_km > 0.0
    # No pairwise backhaul links for a single site
    assert cv.intersite_backhaul_links == []
    # Municipal towns within Mansfield reach
    assert len(cv.illuminated_towns) > 0
    assert "Burlington" in cv.illuminated_towns


def test_multi_origin_composite_viewshed(mansfield_site, bolton_site):
    """Verify multi-origin viewshed aggregates individual polygons and evaluates backhaul."""
    origins = [mansfield_site, bolton_site]
    res = compute_composite_viewshed(origins=origins, max_range_km=50.0, num_radials=36)
    assert res.ok is True
    assert res.value is not None

    cv = res.value
    assert cv.origin_site_ids == ["VT-CHIT-MANS-01", "VT-CHIT-BOLT-01"]

    # Both sites have individual polygons
    assert "VT-CHIT-MANS-01" in cv.individual_polygons
    assert "VT-CHIT-BOLT-01" in cv.individual_polygons
    assert len(cv.individual_polygons) == 2

    # Composite polygons list contains both rings
    assert len(cv.composite_polygons) == 2

    # Total illuminated area > 0
    assert cv.total_illuminated_area_sq_km > 0.0

    # Intersite backhaul link analysis
    assert len(cv.intersite_backhaul_links) == 1
    link = cv.intersite_backhaul_links[0]
    assert isinstance(link, BackhaulLinkStatus)
    assert link.site_a_id == "VT-CHIT-MANS-01"
    assert link.site_b_id == "VT-CHIT-BOLT-01"
    assert link.distance_km > 0.0
    assert 10.0 <= link.distance_km <= 20.0

    # Key regional towns illuminated by composite network
    assert "Burlington" in cv.illuminated_towns
    assert "Stowe" in cv.illuminated_towns
    assert "Underhill" in cv.illuminated_towns


def test_pairwise_backhaul_clear_los_between_mountain_peaks(mansfield_site, bolton_site):
    """Verify mountain peak to mountain peak link has clear optical LOS and positive link margin."""
    res = compute_composite_viewshed(
        origins=[mansfield_site, bolton_site],
        max_range_km=40.0,
        num_radials=16,
    )
    assert res.ok is True
    assert res.value is not None
    assert len(res.value.intersite_backhaul_links) == 1

    link = res.value.intersite_backhaul_links[0]
    assert link.has_line_of_sight is True
    assert link.link_margin_db > 20.0
    assert link.fresnel_clearance_ratio >= 1.0


def test_pairwise_backhaul_obstructed_los_across_mountain_ridge(valley_site_west, valley_site_east):
    """Verify low valley sites on opposite sides of the Green Mountain spine report obstructed LOS."""
    res = compute_composite_viewshed(
        origins=[valley_site_west, valley_site_east],
        max_range_km=40.0,
        num_radials=16,
    )
    assert res.ok is True
    assert res.value is not None
    assert len(res.value.intersite_backhaul_links) == 1

    link = res.value.intersite_backhaul_links[0]
    assert link.has_line_of_sight is False
    assert link.fresnel_clearance_ratio < 1.0


def test_custom_reference_towns_dictionary(mansfield_site):
    """Verify custom reference_towns dictionary is respected and filtered accurately."""
    custom_towns = {
        "CustomUnderhill": {
            "name": "CustomUnderhill",
            "lat": 44.5275,
            "lon": -72.8950,
            "elevation_m": 215.0,
        },
        "FarAwayTown": {
            "name": "FarAwayTown",
            "lat": 41.0000,
            "lon": -71.0000,
            "elevation_m": 10.0,
        },
    }
    res = compute_composite_viewshed(
        origins=[mansfield_site],
        reference_towns=custom_towns,
        max_range_km=30.0,
        num_radials=16,
    )
    assert res.ok is True
    assert res.value is not None
    assert "CustomUnderhill" in res.value.illuminated_towns
    assert "FarAwayTown" not in res.value.illuminated_towns


def test_custom_radio_config_affects_viewshed(mansfield_site):
    """Verify customized RadioConfig (higher tx power and gain) produces valid viewshed output."""
    high_power_radio = RadioConfig(
        frequency_mhz=915.0,
        tx_power_dbm=30.0,
        antenna_gain_dbi=8.0,
        cable_loss_db=0.5,
        rx_sensitivity_dbm=-137.0,
    )
    res = compute_composite_viewshed(
        origins=[mansfield_site],
        radio_config=high_power_radio,
        max_range_km=60.0,
        num_radials=24,
    )
    assert res.ok is True
    assert res.value is not None
    assert res.value.total_illuminated_area_sq_km > 0.0


def test_legacy_symmetric_defaults_preserve_none_directional_fields(
    mansfield_site: SiteCandidate,
    bolton_site: SiteCandidate,
) -> None:
    """Verify legacy symmetric mode preserves exact behavior and leaves directional fields None."""
    res = compute_composite_viewshed(
        origins=[mansfield_site, bolton_site],
        max_range_km=50.0,
        num_radials=36,
    )
    assert res.ok is True
    assert res.value is not None

    cv = res.value
    assert cv.direction == "downlink"
    assert len(cv.intersite_backhaul_links) == 1

    link = cv.intersite_backhaul_links[0]
    assert link.forward_margin_db is None
    assert link.reverse_margin_db is None
    assert link.reachability_state is None
    assert callable(_synthetic_vermont_elevation_fn)
    assert _synthetic_vermont_elevation_fn(44.5437, -72.8143) > 1000.0


def test_invalid_direction_returns_error(mansfield_site: SiteCandidate) -> None:
    """Verify invalid direction strings return Result.fail('INVALID_DIRECTION', ...)."""
    bad_res = compute_composite_viewshed(
        origins=[mansfield_site],
        direction="sideways_invalid",
    )
    assert bad_res.ok is False
    assert bad_res.error is not None
    assert bad_res.error.code == "INVALID_DIRECTION"

    bad_empty_res = compute_composite_viewshed(
        origins=[],
        direction="not_a_direction",
    )
    assert bad_empty_res.ok is False
    assert bad_empty_res.error is not None
    assert bad_empty_res.error.code == "INVALID_DIRECTION"


def test_directional_composite_footprint_and_town_illumination_shrinkage(
    mansfield_site: SiteCandidate,
    bolton_site: SiteCandidate,
) -> None:
    """Verify directional composite footprint and town illumination shrinkage:
    two_way <= min(uplink, downlink) and strict uplink < downlink when pairing
    STATION_G2_BACKBONE summits with a SENSECAP_T1000E + VEHICLE_CABIN handheld.
    """
    g2_hw = HARDWARE_PRESETS["STATION_G2_BACKBONE"]
    t1000e_hw = HARDWARE_PRESETS["SENSECAP_T1000E"]
    vehicle_env = CLIENT_ENVIRONMENT_PROFILES["VEHICLE_CABIN"]

    # Model -124 dBm high-speed modulation with 16 dB mobile fade reserve (-108 dBm effective)
    # and summer foliage (8.5 dB) so RF cutoff occurs inside the 60 km Vermont basin window.
    summit_radio = RadioConfig(
        frequency_mhz=915.0,
        tx_power_dbm=g2_hw.tx_power_dbm,
        rx_sensitivity_dbm=-108.0,
        antenna_gain_dbi=g2_hw.antenna_gain_dbi,
        cable_loss_db=g2_hw.cable_loss_db,
        environmental_clutter_db=8.5,
    )
    handheld_radio = RadioConfig(
        frequency_mhz=915.0,
        tx_power_dbm=t1000e_hw.tx_power_dbm,
        rx_sensitivity_dbm=-108.0,
        antenna_gain_dbi=t1000e_hw.antenna_gain_dbi,
        cable_loss_db=t1000e_hw.cable_loss_db,
        environmental_clutter_db=8.5,
    )

    mansfield_comm = mansfield_site.model_copy(update={"site_type": SiteType.COMMUNICATIONS_TOWER})
    bolton_peak = bolton_site.model_copy(update={"site_type": SiteType.MOUNTAIN_PEAK})
    origins = [mansfield_comm, bolton_peak]

    site_profiles = {
        mansfield_comm.site_id: SiteRadioProfile(
            radio=summit_radio,
            noise_penalty_db=6.0,
            hardware_preset="STATION_G2_BACKBONE",
        ),
        bolton_peak.site_id: SiteRadioProfile(
            radio=summit_radio,
            noise_penalty_db=3.0,
            hardware_preset="STATION_G2_BACKBONE",
        ),
    }

    reference_towns = {
        "Underhill": {
            "name": "Underhill",
            "lat": 44.5275,
            "lon": -72.8950,
            "elevation_m": 215.0,
        },
        "Burlington": {
            "name": "Burlington",
            "lat": 44.4759,
            "lon": -73.2121,
            "elevation_m": 65.0,
        },
    }

    common_kwargs = dict(
        origins=origins,
        max_range_km=60.0,
        num_radials=36,
        reference_towns=reference_towns,
        radio_config=summit_radio,
        client_radio=handheld_radio,
        client_rx_height_m=vehicle_env.default_agl_m,
        client_env_loss_db=vehicle_env.clutter_loss_db,
        site_profiles=site_profiles,
    )

    down_res = compute_composite_viewshed(**common_kwargs, direction="downlink")
    up_res = compute_composite_viewshed(**common_kwargs, direction="uplink")
    twoway_res = compute_composite_viewshed(**common_kwargs, direction="two_way")

    assert down_res.ok and down_res.value is not None
    assert up_res.ok and up_res.value is not None
    assert twoway_res.ok and twoway_res.value is not None

    down_cv = down_res.value
    up_cv = up_res.value
    twoway_cv = twoway_res.value

    assert down_cv.direction == "downlink"
    assert up_cv.direction == "uplink"
    assert twoway_cv.direction == "two_way"

    # Composite footprint area: strict uplink < downlink and two_way <= min(uplink, downlink)
    assert up_cv.total_illuminated_area_sq_km < down_cv.total_illuminated_area_sq_km
    assert twoway_cv.total_illuminated_area_sq_km <= min(
        up_cv.total_illuminated_area_sq_km,
        down_cv.total_illuminated_area_sq_km,
    )

    # Town illumination respects RF link-budget polygon cutoff (no pure-optical override!):
    # Burlington (~32.5 km) hears the 28 dBm summit on downlink ("alligator"), but its
    # 20 dBm vehicle-attenuated handheld uplink fails to close back to the noisy summits.
    assert "Underhill" in down_cv.illuminated_towns
    assert "Burlington" in down_cv.illuminated_towns
    assert "Underhill" in up_cv.illuminated_towns
    assert "Burlington" not in up_cv.illuminated_towns
    assert "Burlington" not in twoway_cv.illuminated_towns
    assert len(up_cv.illuminated_towns) < len(down_cv.illuminated_towns)
    assert len(twoway_cv.illuminated_towns) <= min(
        len(up_cv.illuminated_towns),
        len(down_cv.illuminated_towns),
    )

    # Also verify unmodified preset sensitivity (RETICULUM_RNODE_FAST + SUMMER_LEAF_ON) over 130 km horizon
    g2_preset = resolve_site_radio_profile(
        site_type=SiteType.COMMUNICATIONS_TOWER,
        hardware_id="STATION_G2_BACKBONE",
        protocol_id="RETICULUM_RNODE_FAST",
        season_id="SUMMER_LEAF_ON",
    ).value
    t1000e_preset = build_radio_config(
        hardware_id="SENSECAP_T1000E",
        protocol_id="RETICULUM_RNODE_FAST",
        season_id="SUMMER_LEAF_ON",
    ).value
    assert g2_preset is not None and t1000e_preset is not None

    preset_down = compute_composite_viewshed(
        origins=[mansfield_comm],
        max_range_km=130.0,
        num_radials=36,
        client_radio=t1000e_preset,
        client_rx_height_m=vehicle_env.default_agl_m,
        client_env_loss_db=vehicle_env.clutter_loss_db,
        site_profiles={mansfield_comm.site_id: g2_preset},
        direction="downlink",
    ).value
    preset_up = compute_composite_viewshed(
        origins=[mansfield_comm],
        max_range_km=130.0,
        num_radials=36,
        client_radio=t1000e_preset,
        client_rx_height_m=vehicle_env.default_agl_m,
        client_env_loss_db=vehicle_env.clutter_loss_db,
        site_profiles={mansfield_comm.site_id: g2_preset},
        direction="uplink",
    ).value
    preset_twoway = compute_composite_viewshed(
        origins=[mansfield_comm],
        max_range_km=130.0,
        num_radials=36,
        client_radio=t1000e_preset,
        client_rx_height_m=vehicle_env.default_agl_m,
        client_env_loss_db=vehicle_env.clutter_loss_db,
        site_profiles={mansfield_comm.site_id: g2_preset},
        direction="two_way",
    ).value
    assert preset_down is not None and preset_up is not None and preset_twoway is not None
    assert preset_up.total_illuminated_area_sq_km < preset_down.total_illuminated_area_sq_km
    assert preset_twoway.total_illuminated_area_sq_km <= min(
        preset_up.total_illuminated_area_sq_km,
        preset_down.total_illuminated_area_sq_km,
    )


def test_heterogeneous_summit_to_relay_intersite_backhaul_links() -> None:
    """Verify heterogeneous summit-to-relay intersite_backhaul_links
    (28 dBm noisy commercial tower <-> 22 dBm quiet solar water tank) populate
    forward_margin_db, reverse_margin_db, reachability_state, and set
    link_margin_db == min(forward_margin_db, reverse_margin_db).
    """
    summit_tower = SiteCandidate(
        site_id="VT-SUMMIT-COMM-01",
        name="Mount Mansfield Commercial Tower",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=20.0,
        has_grid_power=True,
    )
    solar_water_tank = SiteCandidate(
        site_id="VT-RELAY-TANK-01",
        name="Essex Foothill Solar Water Tank",
        location=Coordinate(lat=44.4950, lon=-73.0850, elevation_m=195.0),
        site_type=SiteType.WATER_TOWER,
        mast_height_m=18.0,
        has_grid_power=False,
    )

    tower_profile = resolve_site_radio_profile(
        site_type=SiteType.COMMUNICATIONS_TOWER,
        hardware_id="STATION_G2_BACKBONE",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="SUMMER_LEAF_ON",
    ).value
    tank_profile = resolve_site_radio_profile(
        site_type=SiteType.WATER_TOWER,
        hardware_id="RAK4631_SOLAR",
        protocol_id="MESHTASTIC_LONGFAST",
        season_id="SUMMER_LEAF_ON",
    ).value
    assert tower_profile is not None and tank_profile is not None
    assert tower_profile.radio.tx_power_dbm == 28.0
    assert tower_profile.noise_penalty_db == 6.0
    assert tank_profile.radio.tx_power_dbm == 22.0
    assert tank_profile.noise_penalty_db == 1.0

    res = compute_composite_viewshed(
        origins=[summit_tower, solar_water_tank],
        max_range_km=50.0,
        num_radials=24,
        site_profiles={
            summit_tower.site_id: tower_profile,
            solar_water_tank.site_id: tank_profile,
        },
        direction="two_way",
    )
    assert res.ok is True
    assert res.value is not None
    assert len(res.value.intersite_backhaul_links) == 1

    link = res.value.intersite_backhaul_links[0]
    assert link.site_a_id == "VT-SUMMIT-COMM-01"
    assert link.site_b_id == "VT-RELAY-TANK-01"
    assert link.forward_margin_db is not None
    assert link.reverse_margin_db is not None
    assert link.reachability_state == ReachabilityState.TWO_WAY

    # 28 dBm TX into 1 dB noise tank vs 22 dBm TX into 6 dB noise tower -> +11.0 dB forward advantage
    assert link.forward_margin_db > link.reverse_margin_db
    assert link.forward_margin_db - link.reverse_margin_db == pytest.approx(11.0, abs=0.05)
    assert link.link_margin_db == min(link.forward_margin_db, link.reverse_margin_db)
    assert link.link_margin_db == link.reverse_margin_db

    # Verify fallback to SiteRadioProfile(radio=active_radio, noise_penalty_db=get_site_noise_penalty_db(...))
    # when a site is omitted from site_profiles, plus HEAR_ONLY_ALLIGATOR on obstructed cross-ridge path
    west_comm = SiteCandidate(
        site_id="VT-WEST-COMM",
        name="Western Valley Commercial Tower",
        location=Coordinate(lat=44.4759, lon=-73.2200, elevation_m=35.0),
        site_type=SiteType.COMMUNICATIONS_TOWER,
        mast_height_m=10.0,
    )
    east_tank = SiteCandidate(
        site_id="VT-EAST-TANK",
        name="Eastern Valley Solar Water Tank",
        location=Coordinate(lat=44.4654, lon=-72.6874, elevation_m=220.0),
        site_type=SiteType.WATER_TOWER,
        mast_height_m=10.0,
    )
    tight_tower_radio = tower_profile.radio.model_copy(update={"rx_sensitivity_dbm": -125.0})
    tight_tank_radio = tank_profile.radio.model_copy(update={"rx_sensitivity_dbm": -125.0})

    partial_res = compute_composite_viewshed(
        origins=[west_comm, east_tank],
        max_range_km=40.0,
        num_radials=16,
        radio_config=tight_tank_radio,
        site_profiles={
            west_comm.site_id: SiteRadioProfile(
                radio=tight_tower_radio,
                noise_penalty_db=6.0,
                hardware_preset="STATION_G2_BACKBONE",
            ),
            # east_tank intentionally omitted to verify fallback using radio_config + WATER_TOWER (1.0 dB)
        },
    )
    assert partial_res.ok is True
    assert partial_res.value is not None
    obstructed_link = partial_res.value.intersite_backhaul_links[0]
    assert obstructed_link.forward_margin_db is not None
    assert obstructed_link.reverse_margin_db is not None
    assert obstructed_link.forward_margin_db - obstructed_link.reverse_margin_db == pytest.approx(
        11.0, abs=0.05
    )
    assert obstructed_link.link_margin_db == min(
        obstructed_link.forward_margin_db, obstructed_link.reverse_margin_db
    )
    assert obstructed_link.reachability_state in (
        ReachabilityState.HEAR_ONLY_ALLIGATOR,
        ReachabilityState.TWO_WAY,
        ReachabilityState.UNREACHABLE,
    )


