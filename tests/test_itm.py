"""Unit tests for the Longley-Rice ITM preprocessor (qlrpfl) and Bullington Diffraction engine."""

from __future__ import annotations

import math
import pytest

from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RadioConfig,
    ReachabilityState,
    SiteCandidate,
    SiteType,
)
from meshscout.core.itm import (
    bullington_diffraction_loss_db,
    evaluate_point_to_point_link,
    extract_qlrpfl_parameters,
    free_space_path_loss_db,
    knife_edge_diffraction_loss_db,
)
from meshscout.core.presets import (
    CLIENT_ENVIRONMENT_PROFILES,
    build_radio_config,
    get_site_noise_penalty_db,
    resolve_site_radio_profile,
)


def _make_site(
    site_id: str,
    name: str,
    lat: float,
    lon: float,
    elevation_m: float,
    mast_height_m: float = 10.0,
) -> SiteCandidate:
    return SiteCandidate(
        site_id=site_id,
        name=name,
        location=Coordinate(lat=lat, lon=lon, elevation_m=elevation_m),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=mast_height_m,
    )


def _build_synthetic_profile(
    distance_km: float,
    num_points: int,
    elev_fn,
    tx_mast_m: float = 10.0,
    rx_mast_m: float = 10.0,
) -> ElevationProfile:
    total_m = distance_km * 1000.0
    step_m = total_m / (num_points - 1)
    points = []
    for i in range(num_points):
        d_m = i * step_m
        z_m = float(elev_fn(d_m, total_m))
        frac = d_m / total_m
        lat = 44.5 + 0.1 * frac
        lon = -72.8 - 0.2 * frac
        points.append(
            ElevationPoint(
                distance_m=d_m,
                elevation_m=z_m,
                coordinate=Coordinate(lat=lat, lon=lon, elevation_m=z_m),
            )
        )
    source = _make_site("VT-TX", "Source Site", 44.5, -72.8, points[0].elevation_m, tx_mast_m)
    target = _make_site("VT-RX", "Target Site", 44.6, -73.0, points[-1].elevation_m, rx_mast_m)
    return ElevationProfile(
        source_site=source,
        target_site=target,
        distance_km=distance_km,
        points=points,
    )


class TestFreeSpacePathLoss:
    """Analytical benchmark tests for 915 MHz US915 Meshtastic Free-Space Path Loss."""

    @pytest.mark.parametrize(
        "distance_km,expected_fspl_db",
        [
            (1.0, 91.6683),
            (10.0, 111.6683),
            (50.0, 125.6477),
        ],
    )
    def test_fspl_915mhz_benchmarks(self, distance_km: float, expected_fspl_db: float) -> None:
        fspl = free_space_path_loss_db(distance_km=distance_km, frequency_mhz=915.0)
        assert fspl == pytest.approx(expected_fspl_db, abs=0.05)

    def test_fspl_rejects_non_positive_inputs(self) -> None:
        with pytest.raises(ValueError, match="distance_km"):
            free_space_path_loss_db(0.0, 915.0)
        with pytest.raises(ValueError, match="frequency_mhz"):
            free_space_path_loss_db(5.0, -915.0)


class TestKnifeEdgeDiffraction:
    """ITU-R P.526 Lee approximation tests across Fresnel-Kirchhoff regimes."""

    def test_clear_fresnel_zone_returns_zero_loss(self) -> None:
        assert knife_edge_diffraction_loss_db(-0.78) == 0.0
        assert knife_edge_diffraction_loss_db(-1.5) == 0.0
        assert knife_edge_diffraction_loss_db(-5.0) == 0.0

    def test_grazing_incidence_returns_6db(self) -> None:
        # At nu = 0 (direct ray grazing knife edge), diffraction loss is ~6.02 dB
        loss_0 = knife_edge_diffraction_loss_db(0.0)
        assert loss_0 == pytest.approx(6.02, abs=0.05)

    def test_deep_shadow_diffraction_loss(self) -> None:
        # At nu = 2.0, J(2.0) = 6.9 + 20*log10(sqrt(1.9^2 + 1) + 1.9) = 19.04 dB
        loss_2 = knife_edge_diffraction_loss_db(2.0)
        assert loss_2 == pytest.approx(19.04, abs=0.1)


class TestQlrpflPreprocessor:
    """Tests for Longley-Rice ITM qlrpfl (zlsq1 + hzns) parameter extraction."""

    def test_flat_plain_zero_irregularity_and_clear_los(self) -> None:
        profile = _build_synthetic_profile(
            distance_km=10.0,
            num_points=101,
            elev_fn=lambda d_m, total_m: 100.0,
            tx_mast_m=15.0,
            rx_mast_m=15.0,
        )
        metrics = extract_qlrpfl_parameters(profile)
        assert metrics.delta_h_m == pytest.approx(0.0, abs=1e-6)
        assert metrics.he1_m == pytest.approx(15.0, abs=0.1)
        assert metrics.he2_m == pytest.approx(15.0, abs=0.1)
        assert metrics.is_line_of_sight is True

    def test_rough_mountain_profile_extracts_delta_h_and_horizons(self) -> None:
        # Rough terrain with oscillations in the central basin and a dominant central peak at d = 10 km
        def rough_ridge(d_m: float, total_m: float) -> float:
            # Envelope keeps near-field slopes below the central mountain peak horizon angle
            envelope = math.sin(math.pi * d_m / total_m) ** 2
            roughness = 95.0 * envelope * math.sin(2.0 * math.pi * d_m / 2500.0)
            # Dominant central ridge at 10 km (midpoint of 20 km path)
            ridge = 450.0 * math.exp(-((d_m - 10_000.0) / 800.0) ** 2)
            return 200.0 + roughness + ridge

        profile = _build_synthetic_profile(
            distance_km=20.0,
            num_points=201,
            elev_fn=rough_ridge,
            tx_mast_m=10.0,
            rx_mast_m=10.0,
        )
        metrics = extract_qlrpfl_parameters(profile)
        assert metrics.delta_h_m > 120.0
        assert metrics.is_line_of_sight is False
        assert metrics.dl1_m == pytest.approx(10_000.0, abs=300.0)
        assert metrics.dl2_m == pytest.approx(10_000.0, abs=300.0)
        assert metrics.the1_rad > 0.0
        assert metrics.the2_rad > 0.0


class TestReferencePathLossCurves:
    """Reference path loss curve parity within 2.5 dB across canonical propagation regimes."""

    def test_unobstructed_high_altitude_los_parity(self) -> None:
        # 15 km link from a 1200m peak to a 200m hilltop over a concave valley (100m floor)
        def concave_valley(d_m: float, total_m: float) -> float:
            frac = d_m / total_m
            linear = 1200.0 * (1.0 - frac) + 200.0 * frac
            sag = 250.0 * math.sin(math.pi * frac)
            return linear - sag

        profile = _build_synthetic_profile(
            distance_km=15.0,
            num_points=151,
            elev_fn=concave_valley,
            tx_mast_m=10.0,
            rx_mast_m=10.0,
        )
        res = evaluate_point_to_point_link(profile)
        assert res.ok is True and res.value is not None
        # Expected reference total path loss = FSPL(15 km, 915 MHz) = 115.19 dB (0 dB diffraction)
        expected_reference_loss_db = 115.19
        assert res.value.has_line_of_sight is True
        assert res.value.diffraction_loss_db == pytest.approx(0.0, abs=0.1)
        assert abs(res.value.total_path_loss_db - expected_reference_loss_db) <= 2.5

    def test_single_horizon_knife_edge_ridge_parity(self) -> None:
        # 10 km link between two 100m stations with a single knife-edge ridge at 5 km.
        # Earth bulge at midpoint (d1=d2=5000m, k=4/3) is 5000*5000 / (2 * 8494667) = 1.4715 m.
        # Antenna heights are 100 + 10 = 110 m.
        # A ridge at 118.53 m gives effective height 120.0 m -> h_obs = 10.0 m above direct ray.
        # First Fresnel radius F1 = sqrt(0.32764 * 5000 * 5000 / 10000) = 28.62 m.
        # Diffraction parameter nu = 10.0 * sqrt(2) / 28.62 = 0.4941.
        # Reference ITU-R P.526 J(0.4941) = 10.24 dB; FSPL(10km) = 111.67 dB -> Total = 121.91 dB.
        def single_ridge(d_m: float, total_m: float) -> float:
            if abs(d_m - 5000.0) < 1e-3:
                return 118.53
            return 100.0

        profile = _build_synthetic_profile(
            distance_km=10.0,
            num_points=101,
            elev_fn=single_ridge,
            tx_mast_m=10.0,
            rx_mast_m=10.0,
        )
        res = evaluate_point_to_point_link(profile)
        assert res.ok is True and res.value is not None
        expected_reference_loss_db = 121.91
        assert res.value.has_line_of_sight is False
        assert abs(res.value.total_path_loss_db - expected_reference_loss_db) <= 2.5

    def test_double_horizon_mountain_shadow_parity(self) -> None:
        # 20 km link across two separated ridges at 5 km and 15 km (each 140m vs 110m endpoints).
        # Bullington intersection occurs at midpoint d1_b = 10 km with virtual height ~178.8 m
        # (h_obs = 68.83 m, F1 = 40.475 m, nu = 2.405 -> J(nu) = 20.56 dB).
        # FSPL(20 km, 915 MHz) = 117.69 dB -> Reference Bullington total path loss = 138.25 dB.
        def double_ridge(d_m: float, total_m: float) -> float:
            if abs(d_m - 5000.0) < 1e-3 or abs(d_m - 15000.0) < 1e-3:
                return 140.0
            return 100.0

        profile = _build_synthetic_profile(
            distance_km=20.0,
            num_points=201,
            elev_fn=double_ridge,
            tx_mast_m=10.0,
            rx_mast_m=10.0,
        )
        res = evaluate_point_to_point_link(profile)
        assert res.ok is True and res.value is not None
        expected_reference_loss_db = 138.25
        assert res.value.has_line_of_sight is False
        assert abs(res.value.total_path_loss_db - expected_reference_loss_db) <= 2.5


class TestLinkBudgetEvaluation:
    """End-to-end link budget evaluation for Vermont Chittenden County scenarios."""

    def test_mount_mansfield_to_essex_junction_positive_margin(self) -> None:
        # Mount Mansfield (1339 m) to Essex Junction (105 m) over 26.5 km unobstructed slope
        def mansfield_to_essex(d_m: float, total_m: float) -> float:
            frac = d_m / total_m
            # Exponential foothill drop-off giving wide Fresnel clearance
            return 105.0 + (1339.0 - 105.0) * ((1.0 - frac) ** 1.8)

        profile = _build_synthetic_profile(
            distance_km=26.5,
            num_points=101,
            elev_fn=mansfield_to_essex,
            tx_mast_m=12.0,
            rx_mast_m=8.0,
        )
        profile.source_site.site_id = "VT-MANS-01"
        profile.target_site.site_id = "VT-ESSX-01"

        radio = RadioConfig(
            frequency_mhz=915.0,
            tx_power_dbm=22.0,
            rx_sensitivity_dbm=-135.0,
            antenna_gain_dbi=5.0,
            cable_loss_db=1.0,
        )
        res = evaluate_point_to_point_link(profile, radio=radio)
        assert res.ok is True and res.value is not None
        budget = res.value
        assert budget.source_id == "VT-MANS-01"
        assert budget.target_id == "VT-ESSX-01"
        assert budget.has_line_of_sight is True
        assert budget.fresnel_clearance_ratio > 1.0
        assert budget.link_margin_db > 30.0

    def test_blocked_valley_to_valley_degraded_margin(self) -> None:
        # Two valley nodes at 120 m separated by a 900 m mountain massif over 18 km
        def blocked_massif(d_m: float, total_m: float) -> float:
            frac = d_m / total_m
            return 120.0 + 780.0 * math.sin(math.pi * frac) ** 2

        profile = _build_synthetic_profile(
            distance_km=18.0,
            num_points=181,
            elev_fn=blocked_massif,
            tx_mast_m=5.0,
            rx_mast_m=5.0,
        )
        res = evaluate_point_to_point_link(profile)
        assert res.ok is True and res.value is not None
        assert res.value.has_line_of_sight is False
        assert res.value.diffraction_loss_db > 30.0
        assert res.value.fresnel_clearance_ratio < 0.0

    def test_antenna_downtilt_and_vertical_beamwidth_overshoot(self) -> None:
        """Verify high mountain peak to valley drop-off calculates downtilt and warns on overshoot."""
        from meshscout.core.itm import calculate_antenna_downtilt
        from meshscout.core.contracts import SiteCandidate, Coordinate, SiteType

        peak = SiteCandidate(
            site_id="VT-PEAK-01",
            name="Mount Mansfield",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=15.0,
        )
        valley = SiteCandidate(
            site_id="VT-VAL-01",
            name="Underhill Valley Floor",
            location=Coordinate(lat=44.5275, lon=-72.8950, elevation_m=215.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
            mast_height_m=5.0,
        )
        # 8 km distance with 1134m drop = ~8° steep look-down angle
        dt_8dbi = calculate_antenna_downtilt(peak, valley, distance_km=8.0, antenna_gain_dbi=8.0)
        assert dt_8dbi.look_down_angle_deg > 6.0
        assert dt_8dbi.vertical_beamwidth_deg == 10.0
        # Half-beamwidth is 5.0°, so 8° look-down is an overshoot!
        assert dt_8dbi.is_overshooting is True
        assert dt_8dbi.recommended_downtilt_deg > 0.0
        assert "mechanical downtilt" in dt_8dbi.recommendation

        # Same link with 3dBi antenna has 55° beamwidth -> no overshoot!
        dt_3dbi = calculate_antenna_downtilt(peak, valley, distance_km=8.0, antenna_gain_dbi=3.0)
        assert dt_3dbi.vertical_beamwidth_deg == 55.0
        assert dt_3dbi.is_overshooting is False


class TestBidirectionalAsymmetricLinkBudget:
    """Tests for bidirectional asymmetric link budgets, reciprocity, clutter deduplication, and alligator detection."""

    def test_legacy_symmetric_parity_when_optional_args_omitted(self) -> None:
        """Verify omitting target_radio and noise/client losses preserves exact legacy None fields."""
        profile = _build_synthetic_profile(
            distance_km=10.0,
            num_points=51,
            elev_fn=lambda d_m, total_m: 150.0,
            tx_mast_m=10.0,
            rx_mast_m=10.0,
        )
        radio = build_radio_config("RAK4631_SOLAR", "MESHTASTIC_LONGFAST", "WINTER_LEAF_OFF").value
        assert radio is not None

        legacy_res = evaluate_point_to_point_link(profile, radio=radio)
        assert legacy_res.ok and legacy_res.value is not None
        leg = legacy_res.value
        assert leg.downlink_rx_dbm is None
        assert leg.downlink_margin_db is None
        assert leg.uplink_rx_dbm is None
        assert leg.uplink_margin_db is None
        assert leg.asymmetry_delta_db is None
        assert leg.reachability_state is None

        # Supplying identical target_radio with 0 penalties yields exact scalar parity + populated directional fields
        explicit_sym_res = evaluate_point_to_point_link(profile, radio=radio, target_radio=radio)
        assert explicit_sym_res.ok and explicit_sym_res.value is not None
        sym = explicit_sym_res.value
        assert sym.rx_power_dbm == pytest.approx(leg.rx_power_dbm)
        assert sym.link_margin_db == pytest.approx(leg.link_margin_db)
        assert sym.downlink_rx_dbm == pytest.approx(leg.rx_power_dbm)
        assert sym.uplink_rx_dbm == pytest.approx(leg.rx_power_dbm)
        assert sym.downlink_margin_db == pytest.approx(leg.link_margin_db)
        assert sym.uplink_margin_db == pytest.approx(leg.link_margin_db)
        assert sym.asymmetry_delta_db == pytest.approx(0.0)
        assert sym.reachability_state == ReachabilityState.TWO_WAY

    def test_reversed_endpoint_reciprocity_on_steep_valley_to_8dbi_summit(self) -> None:
        """Verify valley->8dBi summit and 8dBi summit->valley produce identical pattern loss and swapped directions."""
        summit = SiteCandidate(
            site_id="VT-SUMMIT-8DBI",
            name="Mount Mansfield 8dBi Backbone",
            location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
            site_type=SiteType.MOUNTAIN_PEAK,
            mast_height_m=15.0,
        )
        valley = SiteCandidate(
            site_id="VT-VALLEY-POCKET",
            name="Underhill Hiker Pocket Node",
            location=Coordinate(lat=44.5275, lon=-72.8950, elevation_m=215.0),
            site_type=SiteType.CUSTOM,
            mast_height_m=1.5,
        )
        dist_km = 8.0
        total_m = dist_km * 1000.0
        num_pts = 81

        fwd_points = []
        for i in range(num_pts):
            frac = i / (num_pts - 1)
            d_m = frac * total_m
            # Concave mountain slope from 1339m down to 215m
            elev = 215.0 + (1339.0 - 215.0) * ((1.0 - frac) ** 1.5)
            lat = summit.location.lat + frac * (valley.location.lat - summit.location.lat)
            lon = summit.location.lon + frac * (valley.location.lon - summit.location.lon)
            fwd_points.append(
                ElevationPoint(
                    distance_m=d_m,
                    elevation_m=elev,
                    coordinate=Coordinate(lat=lat, lon=lon, elevation_m=elev),
                )
            )

        rev_points = [
            ElevationPoint(
                distance_m=round(total_m - pt.distance_m, 6),
                elevation_m=pt.elevation_m,
                coordinate=pt.coordinate,
            )
            for pt in reversed(fwd_points)
        ]

        profile_summit_to_valley = ElevationProfile(
            source_site=summit,
            target_site=valley,
            distance_km=dist_km,
            points=fwd_points,
        )
        profile_valley_to_summit = ElevationProfile(
            source_site=valley,
            target_site=summit,
            distance_km=dist_km,
            points=rev_points,
        )

        summit_radio = build_radio_config("STATION_G2_BACKBONE", "MESHTASTIC_LONGFAST", "SUMMER_LEAF_ON").value
        valley_radio = build_radio_config("SENSECAP_T1000E", "MESHTASTIC_LONGFAST", "SUMMER_LEAF_ON").value
        assert summit_radio is not None and valley_radio is not None

        fwd_res = evaluate_point_to_point_link(
            profile_summit_to_valley,
            radio=summit_radio,
            target_radio=valley_radio,
            source_noise_penalty_db=3.0,
            target_noise_penalty_db=0.0,
            client_env_loss_db=4.0,
        )
        rev_res = evaluate_point_to_point_link(
            profile_valley_to_summit,
            radio=valley_radio,
            target_radio=summit_radio,
            source_noise_penalty_db=0.0,
            target_noise_penalty_db=3.0,
            client_env_loss_db=4.0,
        )
        assert fwd_res.ok and fwd_res.value is not None
        assert rev_res.ok and rev_res.value is not None
        fwd = fwd_res.value
        rev = rev_res.value

        # Both call orders detect the summit 8 dBi vertical beamwidth overshoot!
        assert fwd.downtilt_analysis is not None and rev.downtilt_analysis is not None
        assert fwd.downtilt_analysis.is_overshooting is True
        assert rev.downtilt_analysis.is_overshooting is True
        assert fwd.downtilt_analysis.pattern_attenuation_db > 0.0
        assert fwd.downtilt_analysis.pattern_attenuation_db == pytest.approx(
            rev.downtilt_analysis.pattern_attenuation_db
        )

        # Total path loss and conservative two-way scalars are 100% order-invariant
        assert fwd.total_path_loss_db == pytest.approx(rev.total_path_loss_db, abs=1e-4)
        assert fwd.rx_power_dbm == pytest.approx(rev.rx_power_dbm, abs=1e-4)
        assert fwd.link_margin_db == pytest.approx(rev.link_margin_db, abs=1e-4)

        # Directional budgets swap cleanly across call order
        assert fwd.downlink_rx_dbm == pytest.approx(rev.uplink_rx_dbm, abs=1e-4)
        assert fwd.uplink_rx_dbm == pytest.approx(rev.downlink_rx_dbm, abs=1e-4)
        assert fwd.downlink_margin_db == pytest.approx(rev.uplink_margin_db, abs=1e-4)
        assert fwd.uplink_margin_db == pytest.approx(rev.downlink_margin_db, abs=1e-4)
        assert fwd.asymmetry_delta_db == pytest.approx(-rev.asymmetry_delta_db, abs=1e-4)

    def test_single_path_clutter_non_double_counting(self) -> None:
        """Verify seasonal canopy loss and client_env_loss_db are each applied once per path."""
        profile = _build_synthetic_profile(
            distance_km=12.0,
            num_points=61,
            elev_fn=lambda d_m, total_m: 200.0,
            tx_mast_m=15.0,
            rx_mast_m=2.0,
        )
        tx_winter = build_radio_config("STATION_G2_BACKBONE", "MESHTASTIC_LONGFAST", "WINTER_LEAF_OFF").value
        rx_winter = build_radio_config("SENSECAP_T1000E", "MESHTASTIC_LONGFAST", "WINTER_LEAF_OFF").value
        tx_summer = build_radio_config("STATION_G2_BACKBONE", "MESHTASTIC_LONGFAST", "SUMMER_LEAF_ON").value
        rx_summer = build_radio_config("SENSECAP_T1000E", "MESHTASTIC_LONGFAST", "SUMMER_LEAF_ON").value
        assert tx_winter and rx_winter and tx_summer and rx_summer

        pocket_loss_db = CLIENT_ENVIRONMENT_PROFILES["BODY_WORN_POCKET"].clutter_loss_db  # 4.0 dB

        base_res = evaluate_point_to_point_link(
            profile,
            radio=tx_winter,
            target_radio=rx_winter,
            client_env_loss_db=0.0,
        )
        summer_pocket_res = evaluate_point_to_point_link(
            profile,
            radio=tx_summer,
            target_radio=rx_summer,
            client_env_loss_db=pocket_loss_db,
        )
        assert base_res.ok and base_res.value is not None
        assert summer_pocket_res.ok and summer_pocket_res.value is not None

        # Seasonal canopy (8.5 dB) + body-worn pocket (4.0 dB) = 12.5 dB total delta (not 17.0 + 4.0 = 21.0 dB)
        path_loss_delta = round(
            summer_pocket_res.value.total_path_loss_db - base_res.value.total_path_loss_db,
            4,
        )
        assert path_loss_delta == pytest.approx(8.5 + 4.0, abs=1e-4)

    def test_asymmetry_delta_exact_formula_independent_of_antenna_gain(self) -> None:
        """Verify asymmetry_delta_db == (28.0 - 20.0) + site_noise_penalty_db for G2 vs T1000-E across antenna gains."""
        profile = _build_synthetic_profile(
            distance_km=15.0,
            num_points=61,
            elev_fn=lambda d_m, total_m: 300.0,
            tx_mast_m=20.0,
            rx_mast_m=1.5,
        )
        t1000e = build_radio_config("SENSECAP_T1000E", "MESHTASTIC_LONGFAST", "SUMMER_LEAF_ON").value
        assert t1000e is not None

        for site_type in (
            SiteType.COMMUNICATIONS_TOWER,
            SiteType.MOUNTAIN_PEAK,
            SiteType.WATER_TOWER,
        ):
            site_prof = resolve_site_radio_profile(
                site_type=site_type,
                hardware_id="STATION_G2_BACKBONE",
                protocol_id="MESHTASTIC_LONGFAST",
                season_id="SUMMER_FOLIAGE",
            ).value
            assert site_prof is not None
            site_noise_penalty_db = get_site_noise_penalty_db(site_type)

            for test_gain_dbi in (1.5, 5.8, 8.0, 10.0):
                g2_variant = site_prof.radio.model_copy(update={"antenna_gain_dbi": test_gain_dbi})
                res = evaluate_point_to_point_link(
                    profile,
                    radio=g2_variant,
                    target_radio=t1000e,
                    source_noise_penalty_db=site_noise_penalty_db,
                    client_env_loss_db=4.0,
                )
                assert res.ok and res.value is not None
                assert res.value.asymmetry_delta_db == (28.0 - 20.0) + site_noise_penalty_db

    def test_hear_only_alligator_uplink_only_and_unreachable_states(self) -> None:
        """Verify ReachabilityState classification across hear_only_alligator, uplink_only, and unreachable regimes."""
        profile = _build_synthetic_profile(
            distance_km=35.0,
            num_points=71,
            elev_fn=lambda d_m, total_m: 250.0,
            tx_mast_m=30.0,
            rx_mast_m=1.5,
        )
        g2_radio = build_radio_config("STATION_G2_BACKBONE", "MESHTASTIC_LONGFAST", "SUMMER_LEAF_ON").value
        t1000e_radio = build_radio_config("SENSECAP_T1000E", "MESHTASTIC_LONGFAST", "SUMMER_LEAF_ON").value
        assert g2_radio is not None and t1000e_radio is not None

        # High-power noisy comm tower -> pocket client inside heavy clutter: downlink >= 0 > uplink
        alligator_res = evaluate_point_to_point_link(
            profile,
            radio=g2_radio,
            target_radio=t1000e_radio,
            source_noise_penalty_db=6.0,
            client_env_loss_db=30.0,
        )
        assert alligator_res.ok and alligator_res.value is not None
        alg = alligator_res.value
        assert alg.downlink_margin_db is not None and alg.uplink_margin_db is not None
        assert alg.downlink_margin_db >= 0.0
        assert alg.uplink_margin_db < 0.0
        assert alg.reachability_state == ReachabilityState.HEAR_ONLY_ALLIGATOR
        assert alg.link_margin_db == pytest.approx(alg.uplink_margin_db)
        assert alg.rx_power_dbm == pytest.approx(min(alg.downlink_rx_dbm, alg.uplink_rx_dbm))

        # Reversing source/target turns the same link into UPLINK_ONLY (target->source succeeds, source->target fails)
        uplink_only_res = evaluate_point_to_point_link(
            profile,
            radio=t1000e_radio,
            target_radio=g2_radio,
            target_noise_penalty_db=6.0,
            client_env_loss_db=30.0,
        )
        assert uplink_only_res.ok and uplink_only_res.value is not None
        assert uplink_only_res.value.reachability_state == ReachabilityState.UPLINK_ONLY

        # Extreme attenuation drives both directions negative -> UNREACHABLE
        unreach_res = evaluate_point_to_point_link(
            profile,
            radio=g2_radio,
            target_radio=t1000e_radio,
            source_noise_penalty_db=6.0,
            client_env_loss_db=60.0,
        )
        assert unreach_res.ok and unreach_res.value is not None
        assert unreach_res.value.reachability_state == ReachabilityState.UNREACHABLE

