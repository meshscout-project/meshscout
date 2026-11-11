"""Unit test suite for MeshScout winter solar and battery survival simulator.

Verifies:
1. Solar irradiance calculation symmetry across seasonal days and tilt angles.
2. LTO battery surviving a 5-day Vermont sub-zero cloudy storm where standard LiFePO4
   browns out due to freezing temperature charge lockout.
3. Sizing recommendations giving higher panel/battery requirements for power-hungry nodes
   (ESP32 / Station G2) vs low-power nRF52 nodes.
4. Daily timeline generation, energy accounting, and brownout hour accumulation.
5. Battery chemistry properties and parameter validation error handling.
"""

import math
import pytest
from meshscout.core.contracts import Coordinate
from meshscout.core.solar import (
    BatteryChemistry,
    DailySolarStep,
    SolarSetup,
    WinterSurvivalReport,
    estimate_vermont_winter_irradiance,
    simulate_winter_battery_survival,
)


@pytest.fixture
def burlington_coord() -> Coordinate:
    """Burlington, Vermont benchmark coordinate (44.4759 N, -73.2121 W)."""
    return Coordinate(lat=44.4759, lon=-73.2121, elevation_m=100.0)


@pytest.fixture
def mansfield_coord() -> Coordinate:
    """Mount Mansfield summit benchmark coordinate (44.5437 N, -72.8143 W)."""
    return Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0)


# =========================================================================
# 1. Solar Irradiance Geometry and Seasonal Symmetry
# =========================================================================

def test_vermont_winter_irradiance_range(burlington_coord: Coordinate):
    """Verify winter clear-sky PSH on 60 deg tilted panel is ~1.5 to 2.2 PSH."""
    # Day 355 is ~Winter Solstice (Dec 21)
    psh_solstice = estimate_vermont_winter_irradiance(burlington_coord.lat, 355, tilt_deg=60.0)
    assert 1.5 <= psh_solstice <= 2.2, f"Expected 1.5-2.2 PSH on winter solstice, got {psh_solstice}"

    # Day 15 is mid-January deep freeze
    psh_jan15 = estimate_vermont_winter_irradiance(burlington_coord.lat, 15, tilt_deg=60.0)
    assert 1.5 <= psh_jan15 <= 2.3, f"Expected 1.5-2.3 PSH in mid-January, got {psh_jan15}"


def test_irradiance_tilt_angle_advantage(burlington_coord: Coordinate):
    """Verify 60 deg steep tilt captures substantially more winter sun than flat panel."""
    # Mid-winter day 15 (Jan 15)
    psh_flat = estimate_vermont_winter_irradiance(burlington_coord.lat, 15, tilt_deg=0.0)
    psh_steep = estimate_vermont_winter_irradiance(burlington_coord.lat, 15, tilt_deg=60.0)

    # Steep 60 tilt should capture at least 2x the energy of a flat panel in midwinter
    assert psh_steep > 2.0 * psh_flat, f"Steep tilt ({psh_steep}) should exceed 2x flat ({psh_flat})"


def test_irradiance_seasonal_symmetry(burlington_coord: Coordinate):
    """Verify mathematical symmetry across solstices and equinoxes."""
    # Days symmetric around summer solstice (approx day 172)
    # Day 142 (30 days before) vs Day 202 (30 days after)
    psh_before_summer = estimate_vermont_winter_irradiance(burlington_coord.lat, 142, tilt_deg=45.0)
    psh_after_summer = estimate_vermont_winter_irradiance(burlington_coord.lat, 202, tilt_deg=45.0)
    assert math.isclose(psh_before_summer, psh_after_summer, rel_tol=0.05)

    # Spring equinox (approx day 80) and Autumn equinox (approx day 264)
    psh_spring = estimate_vermont_winter_irradiance(burlington_coord.lat, 80, tilt_deg=45.0)
    psh_autumn = estimate_vermont_winter_irradiance(burlington_coord.lat, 264, tilt_deg=45.0)
    assert math.isclose(psh_spring, psh_autumn, rel_tol=0.05)


# =========================================================================
# 2. LTO vs LiFePO4 Cold Charging Lockout Survival
# =========================================================================

def test_lto_survives_subzero_storm_where_lifepo4_browns_out(mansfield_coord: Coordinate):
    """LTO survives 5-day sub-zero storm streak; LiFePO4 browns out due to 0 C lockout."""
    # Sized with a compact 6.0 Wh battery pack (e.g. 2S 18650 size) drawing 45 mW (1.08 Wh/day)
    setup_lto = SolarSetup(
        panel_watts=10.0,
        battery_chemistry=BatteryChemistry.LTO,
        battery_capacity_wh=6.0,
        radio_power_mw=45.0,
        panel_tilt_deg=60.0,
    )
    setup_lifepo4 = SolarSetup(
        panel_watts=10.0,
        battery_chemistry=BatteryChemistry.LIFEPO4,
        battery_capacity_wh=6.0,
        radio_power_mw=45.0,
        panel_tilt_deg=60.0,
    )

    res_lto = simulate_winter_battery_survival(mansfield_coord, setup_lto, consecutive_cloudy_days=5)
    res_lifepo4 = simulate_winter_battery_survival(mansfield_coord, setup_lifepo4, consecutive_cloudy_days=5)

    assert res_lto.ok is True
    assert res_lifepo4.ok is True

    rep_lto = res_lto.value
    rep_lifepo4 = res_lifepo4.value

    # LTO charges down to -30 C, harvesting diffuse light during storm and clear sub-zero post-storm
    assert rep_lto.survived_winter_streak is True
    assert rep_lto.brownout_hours == 0.0
    assert rep_lto.min_state_of_charge_pct > 60.0

    # LiFePO4 BMS locks out charging <= 0 C, causing brownout during sub-zero stretch
    assert rep_lifepo4.survived_winter_streak is False
    assert rep_lifepo4.brownout_hours > 0.0
    assert rep_lifepo4.min_state_of_charge_pct <= 20.0  # Cutoff hit


def test_sodium_ion_cold_charging_resilience(burlington_coord: Coordinate):
    """Sodium-ion operates down to -20 C, surviving the -12 C storm."""
    setup_sodium = SolarSetup(
        panel_watts=10.0,
        battery_chemistry=BatteryChemistry.SODIUM_ION,
        battery_capacity_wh=6.0,
        radio_power_mw=45.0,
        panel_tilt_deg=60.0,
    )
    res = simulate_winter_battery_survival(burlington_coord, setup_sodium, consecutive_cloudy_days=5)
    assert res.ok is True
    # At -12 C storm temp, Sodium-ion can charge (threshold is -20 C)
    assert res.value.survived_winter_streak is True
    assert res.value.brownout_hours == 0.0


# =========================================================================
# 3. Hardware Sizing Recommendations Scaling
# =========================================================================

def test_hardware_sizing_recommendations_scaling(burlington_coord: Coordinate):
    """Station G2 (1800mW) and ESP32 (450mW) require much larger panel/battery than nRF52 (45mW)."""
    nrf52_setup = SolarSetup(radio_power_mw=45.0, battery_chemistry=BatteryChemistry.LTO)
    esp32_setup = SolarSetup(radio_power_mw=450.0, battery_chemistry=BatteryChemistry.LTO)
    station_g2_setup = SolarSetup(radio_power_mw=1800.0, battery_chemistry=BatteryChemistry.LTO)

    rep_nrf = simulate_winter_battery_survival(burlington_coord, nrf52_setup).value
    rep_esp = simulate_winter_battery_survival(burlington_coord, esp32_setup).value
    rep_g2 = simulate_winter_battery_survival(burlington_coord, station_g2_setup).value

    # Battery recommendations must scale monotonically with continuous power draw
    assert rep_g2.recommended_battery_wh > rep_esp.recommended_battery_wh > rep_nrf.recommended_battery_wh
    # Panel recommendations must scale monotonically
    assert rep_g2.recommended_panel_watts > rep_esp.recommended_panel_watts > rep_nrf.recommended_panel_watts

    # Station G2 draws 40x power of nRF52; recommended battery should be ~40x
    ratio_batt = rep_g2.recommended_battery_wh / rep_nrf.recommended_battery_wh
    assert ratio_batt >= 30.0, f"Expected Station G2 battery ratio >= 30, got {ratio_batt}"

    ratio_panel = rep_g2.recommended_panel_watts / rep_nrf.recommended_panel_watts
    assert ratio_panel >= 20.0, f"Expected Station G2 panel ratio >= 20, got {ratio_panel}"


# =========================================================================
# 4. Daily Timeline Generation and Brownout Accounting
# =========================================================================

def test_daily_timeline_generation_and_energy_balance(burlington_coord: Coordinate):
    """Verify daily timeline length, fields, and net energy balance."""
    setup = SolarSetup(panel_watts=10.0, battery_capacity_wh=24.0, radio_power_mw=45.0)
    res = simulate_winter_battery_survival(burlington_coord, setup, simulation_days=30, consecutive_cloudy_days=5)
    assert res.ok is True
    report = res.value

    assert len(report.daily_timeline) == 30
    assert report.simulation_days == 30

    storm_steps = [s for s in report.daily_timeline if s.cloud_cover_pct >= 85.0]
    assert len(storm_steps) == 5, f"Expected 5 storm steps, got {len(storm_steps)}"

    for step in report.daily_timeline:
        assert isinstance(step.day_index, int)
        assert isinstance(step.date_label, str)
        assert step.net_wh == round(step.generation_wh - step.consumption_wh, 3)
        assert 0.0 <= step.state_of_charge_pct <= 100.0


def test_brownout_accounting_under_heavy_drain(burlington_coord: Coordinate):
    """Under extreme load deficit, brownout hours accumulate accurately."""
    # Under-sized 2 Wh battery with power-hungry 500 mW load and zero panel
    starved_setup = SolarSetup(
        panel_watts=0.01,  # Virtually no generation
        battery_chemistry=BatteryChemistry.LEAD_ACID_AGM,  # 50% usable DoD
        battery_capacity_wh=2.0,
        radio_power_mw=500.0,  # 12 Wh/day load
    )
    res = simulate_winter_battery_survival(burlington_coord, starved_setup, simulation_days=5)
    assert res.ok is True
    report = res.value

    assert report.survived_winter_streak is False
    assert report.brownout_hours > 0.0
    assert any(step.brownout_occurred for step in report.daily_timeline)


# =========================================================================
# 5. Chemistry Properties and Validation Error Handling
# =========================================================================

def test_battery_chemistry_properties():
    """Verify nominal voltages, cold thresholds, and usable capacities."""
    assert BatteryChemistry.LIFEPO4.nominal_voltage_v == 3.2
    assert BatteryChemistry.LIFEPO4.min_charge_temp_c == 0.0
    assert BatteryChemistry.LIFEPO4.usable_capacity_ratio == 0.80

    assert BatteryChemistry.LTO.nominal_voltage_v == 2.4
    assert BatteryChemistry.LTO.min_charge_temp_c == -30.0
    assert BatteryChemistry.LTO.usable_capacity_ratio == 0.90

    assert BatteryChemistry.SODIUM_ION.nominal_voltage_v == 3.1
    assert BatteryChemistry.SODIUM_ION.min_charge_temp_c == -20.0
    assert BatteryChemistry.SODIUM_ION.usable_capacity_ratio == 0.85

    assert BatteryChemistry.LEAD_ACID_AGM.nominal_voltage_v == 12.0
    assert BatteryChemistry.LEAD_ACID_AGM.min_charge_temp_c == -20.0
    assert BatteryChemistry.LEAD_ACID_AGM.usable_capacity_ratio == 0.50


def test_validation_errors(burlington_coord: Coordinate):
    """Verify Result.fail responses for physically invalid parameters."""
    setup = SolarSetup()

    # Invalid latitude (constructed via model_construct to bypass model-level check)
    bad_coord = Coordinate.model_construct(lat=95.0, lon=-73.0, elevation_m=0.0)
    res = simulate_winter_battery_survival(bad_coord, setup)
    assert res.ok is False
    assert res.error.code == "INVALID_COORDINATE"

    # Negative panel wattage (constructed via model_construct)
    bad_panel = SolarSetup.model_construct(panel_watts=-5.0, battery_chemistry=BatteryChemistry.LTO, battery_capacity_wh=24.0, radio_power_mw=45.0, panel_tilt_deg=60.0, snow_shading_factor=0.2)
    res = simulate_winter_battery_survival(burlington_coord, bad_panel)
    assert res.ok is False
    assert res.error.code == "INVALID_PANEL_WATTS"

    # Zero simulation days
    res = simulate_winter_battery_survival(burlington_coord, setup, simulation_days=0)
    assert res.ok is False
    assert res.error.code == "INVALID_SIMULATION_DAYS"

    # Consecutive cloudy days > simulation days
    res = simulate_winter_battery_survival(burlington_coord, setup, consecutive_cloudy_days=40, simulation_days=30)
    assert res.ok is False
    assert res.error.code == "INVALID_CLOUDY_STREAK"

    # Invalid winter month
    res = simulate_winter_battery_survival(burlington_coord, setup, winter_month=13)
    assert res.ok is False
    assert res.error.code == "INVALID_WINTER_MONTH"
