"""Unit tests for the Longley-Rice ITM preprocessor (qlrpfl) and Bullington Diffraction engine."""

from __future__ import annotations

import math
import pytest

from meshscout.core.contracts import (
    Coordinate,
    ElevationPoint,
    ElevationProfile,
    RadioConfig,
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
