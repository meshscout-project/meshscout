"""Winter Solar & Battery Survival Simulator for Vermont Off-Grid Mesh Nodes.

Models seasonal solar irradiance, steep winter panel tilts, sub-zero battery chemistries
(LiFePO4 cold charge lockout vs LTO ultra-rugged cold charging), multi-day storm streaks,
and sizing recommendations for high-reliability mountaintop repeaters.
"""

from __future__ import annotations

import datetime
import math
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from meshscout.core.contracts import Coordinate, Result


class BatteryChemistry(str, Enum):
    """Battery chemistry profiles and cold-weather charging constraints."""

    LIFEPO4 = "lifepo4"
    LTO = "lto"
    SODIUM_ION = "sodium_ion"
    LEAD_ACID_AGM = "agm"

    @property
    def nominal_voltage_v(self) -> float:
        """Nominal cell/pack operating voltage."""
        mapping = {
            BatteryChemistry.LIFEPO4: 3.2,
            BatteryChemistry.LTO: 2.4,
            BatteryChemistry.SODIUM_ION: 3.1,
            BatteryChemistry.LEAD_ACID_AGM: 12.0,
        }
        return mapping[self]

    @property
    def min_charge_temp_c(self) -> float:
        """Minimum allowable battery charging temperature in degrees Celsius.

        Below this temperature, BMS or chemical limits cut charging current to 0A
        to prevent lithium plating, internal short circuits, or irreversible cell damage.
        """
        mapping = {
            BatteryChemistry.LIFEPO4: 0.0,
            BatteryChemistry.LTO: -30.0,
            BatteryChemistry.SODIUM_ION: -20.0,
            BatteryChemistry.LEAD_ACID_AGM: -20.0,
        }
        return mapping[self]

    @property
    def usable_capacity_ratio(self) -> float:
        """Fraction of total nominal capacity that is safely usable without damage."""
        mapping = {
            BatteryChemistry.LIFEPO4: 0.80,
            BatteryChemistry.LTO: 0.90,
            BatteryChemistry.SODIUM_ION: 0.85,
            BatteryChemistry.LEAD_ACID_AGM: 0.50,
        }
        return mapping[self]


class SolarSetup(BaseModel):
    """Solar harvesting and energy storage configuration for an off-grid node."""

    panel_watts: float = Field(default=10.0, gt=0.0, description="Rated peak DC power of photovoltaic panel in Watts")
    battery_chemistry: BatteryChemistry = Field(
        default=BatteryChemistry.LTO,
        description="Battery cell chemistry with associated thermal and DoD envelope",
    )
    battery_capacity_wh: float = Field(
        default=24.0, gt=0.0, description="Total nominal battery pack capacity in Watt-hours (e.g. 10Ah @ 2.4V = 24Wh)"
    )
    radio_power_mw: float = Field(
        default=45.0, gt=0.0, description="Continuous average power consumption of mesh radio hardware in milliwatts"
    )
    panel_tilt_deg: float = Field(
        default=60.0, ge=0.0, le=90.0, description="Panel tilt angle above horizontal in degrees (60 deg optimal for Vermont winter)"
    )
    snow_shading_factor: float = Field(
        default=0.20, ge=0.0, le=1.0, description="Fractional reduction in insolation due to snow accumulation, frost, or local obstruction"
    )


class DailySolarStep(BaseModel):
    """Single day simulation step recording insolation, temperature, energy flows, and state of charge."""

    day_index: int = Field(..., ge=1, description="1-based sequence index of simulation day")
    date_label: str = Field(..., description="Descriptive date or day label (e.g. 'Jan 15', 'Day 10')")
    irradiance_peak_sun_hours: float = Field(..., ge=0.0, description="Clear-sky equivalent peak sun hours (PSH) on tilted surface")
    cloud_cover_pct: float = Field(..., ge=0.0, le=100.0, description="Atmospheric cloud cover percentage (0-100%)")
    temp_c: float = Field(..., description="Average ambient daytime temperature in degrees Celsius")
    generation_wh: float = Field(..., ge=0.0, description="Net solar energy harvested and accepted by battery in Watt-hours")
    consumption_wh: float = Field(..., ge=0.0, description="Node energy consumption in Watt-hours")
    net_wh: float = Field(..., description="Net daily energy balance (generation - consumption) in Watt-hours")
    ending_battery_wh: float = Field(..., ge=0.0, description="Battery energy remaining at conclusion of day in Watt-hours")
    state_of_charge_pct: float = Field(..., ge=0.0, le=100.0, description="Ending state of charge percentage of total capacity (0-100%)")
    brownout_occurred: bool = Field(..., description="Whether battery was depleted below minimum cutoff threshold")


class WinterSurvivalReport(BaseModel):
    """Comprehensive winter autonomy simulation report and sizing recommendations."""

    location: Coordinate = Field(..., description="Target node deployment coordinate")
    setup: SolarSetup = Field(..., description="Evaluated solar panel and battery setup")
    simulation_days: int = Field(..., gt=0, description="Number of days simulated")
    total_generation_wh: float = Field(..., ge=0.0, description="Cumulative solar energy harvested over simulation in Wh")
    total_consumption_wh: float = Field(..., ge=0.0, description="Cumulative energy consumed by node over simulation in Wh")
    min_state_of_charge_pct: float = Field(..., ge=0.0, le=100.0, description="Lowest battery state of charge reached during simulation")
    brownout_hours: float = Field(..., ge=0.0, description="Total cumulative hours the node was unpowered due to battery depletion")
    survived_winter_streak: bool = Field(..., description="True if the node operated without any brownout throughout the simulation")
    max_cloudy_streak_days_tolerated: int = Field(..., ge=0, description="Maximum consecutive cloudy/freezing storm days the setup can withstand before brownout")
    recommended_panel_watts: float = Field(..., gt=0.0, description="Recommended minimum solar panel wattage for robust winter autonomy")
    recommended_battery_wh: float = Field(..., gt=0.0, description="Recommended minimum battery capacity in Wh for robust winter autonomy")
    daily_timeline: List[DailySolarStep] = Field(default_factory=list, description="Day-by-day simulation step timeline")


def estimate_vermont_winter_irradiance(lat: float, day_of_year: int, tilt_deg: float = 60.0) -> float:
    """Analytical clear-sky equivalent peak sun hours (PSH) for Northern New England.

    Calculates daily insolation on a south-facing tilted photovoltaic surface
    accounting for solar declination, air mass optical depth, sky diffuse component,
    and snow ground albedo.

    For Northern Vermont (lat ~44.5 deg N) in December/January with a steep 60 deg tilt,
    yields approximately 1.5 to 2.2 PSH, compared to <1.0 PSH on a flat horizontal panel.
    """
    phi = math.radians(lat)
    beta = math.radians(tilt_deg)

    # Solar declination angle via Cooper's equation
    delta = math.radians(23.45 * math.sin(math.radians(360.0 * (284 + day_of_year) / 365.0)))

    # Sunset hour angle for horizontal surface
    cos_ws = -math.tan(phi) * math.tan(delta)
    if cos_ws >= 1.0:
        return 0.0  # Polar night
    if cos_ws <= -1.0:
        ws = math.pi  # Midnight sun
    else:
        ws = math.acos(cos_ws)

    # Numerical integration across daylight hours
    n_steps = 100
    d_omega = (2.0 * ws) / n_steps
    dt_hours = d_omega / math.radians(15.0)

    total_psh = 0.0
    for i in range(n_steps):
        omega = -ws + (i + 0.5) * d_omega
        sin_alpha = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(omega)
        if sin_alpha <= 0.02:
            continue

        am = 1.0 / sin_alpha
        # Regional clear-sky DNI factor calibrated for Northern New England winter atmosphere
        # (aerosol optical depth, low sun elevation, water vapor)
        beam_dni = 0.65 * (0.70 ** (am ** 0.65))

        # Direct beam angle of incidence on south-facing tilted plane
        cos_theta = math.sin(delta) * math.sin(phi - beta) + math.cos(delta) * math.cos(phi - beta) * math.cos(omega)
        i_beam = beam_dni * max(0.0, cos_theta)

        # Sky diffuse radiation on tilted surface (isotropic sky approximation)
        diffuse_sky = 0.05 * sin_alpha * (1.0 + math.cos(beta)) / 2.0

        # Ground-reflected radiation (elevated albedo due to winter snow cover)
        albedo = 0.50 if (day_of_year <= 90 or day_of_year >= 330) else 0.20
        ground_refl = (beam_dni * sin_alpha + 0.05 * sin_alpha) * albedo * (1.0 - math.cos(beta)) / 2.0

        total_psh += (i_beam + diffuse_sky + ground_refl) * dt_hours

    return round(total_psh, 2)


def simulate_winter_battery_survival(
    coord: Coordinate,
    setup: SolarSetup,
    consecutive_cloudy_days: int = 5,
    simulation_days: int = 30,
    winter_month: int = 1,
) -> Result[WinterSurvivalReport]:
    """Simulate winter off-grid node survival, cold charging lockouts, and sizing.

    Simulates a 30-day stretch centered on the winter solstice or January deep freeze.
    Injects a severe multi-day storm streak (`consecutive_cloudy_days` with cloud cover >= 85%
    and temp <= -10 deg C).
    Enforces chemistry-specific charging limits (e.g. LiFePO4 charging current is cut to zero
    when temp <= 0 deg C, causing brownouts during cold stretches even if sunlight is present;
    LTO charges down to -30 deg C).
    Tracks state of charge day by day and recommends optimal panel wattage and battery Wh.
    """
    if coord.lat < -90.0 or coord.lat > 90.0:
        return Result.fail("INVALID_COORDINATE", "Latitude must be between -90 and 90 degrees")
    if setup.panel_watts <= 0.0:
        return Result.fail("INVALID_PANEL_WATTS", "Panel wattage must be strictly positive")
    if setup.battery_capacity_wh <= 0.0:
        return Result.fail("INVALID_BATTERY_CAPACITY", "Battery capacity must be strictly positive")
    if setup.radio_power_mw <= 0.0:
        return Result.fail("INVALID_RADIO_POWER", "Radio power must be strictly positive")
    if simulation_days <= 0:
        return Result.fail("INVALID_SIMULATION_DAYS", "Simulation days must be greater than zero")
    if consecutive_cloudy_days < 0 or consecutive_cloudy_days > simulation_days:
        return Result.fail("INVALID_CLOUDY_STREAK", "Consecutive cloudy days must be between 0 and simulation_days")
    if winter_month < 1 or winter_month > 12:
        return Result.fail("INVALID_WINTER_MONTH", "Winter month must be between 1 and 12")

    # Calendar base date
    start_date = datetime.date(2026, winter_month, 1)

    # Battery chemistry and energy limits
    usable_ratio = setup.battery_chemistry.usable_capacity_ratio
    min_cutoff_wh = setup.battery_capacity_wh * (1.0 - usable_ratio)
    current_battery_wh = setup.battery_capacity_wh  # Starts at 100% full capacity

    # Daily radio consumption
    daily_consumption_wh = round((setup.radio_power_mw * 24.0) / 1000.0, 3)
    hourly_consumption_wh = daily_consumption_wh / 24.0

    # Multi-day storm placement
    storm_start = max(1, (simulation_days - consecutive_cloudy_days) // 2 + 1)
    storm_end = storm_start + consecutive_cloudy_days - 1

    daily_timeline: List[DailySolarStep] = []
    total_generation_wh = 0.0
    total_consumption_wh = 0.0
    total_brownout_hours = 0.0
    min_soc_pct = 100.0

    for d in range(1, simulation_days + 1):
        step_date = start_date + datetime.timedelta(days=d - 1)
        date_label = step_date.strftime("%b %d")
        day_of_year = step_date.timetuple().tm_yday

        # Meteorological conditions for this day
        if storm_start <= d <= storm_end:
            # Severe winter blizzard/storm streak
            cloud_cover_pct = 90.0
            temp_c = -12.0
        elif d < storm_start:
            # Pre-storm baseline winter conditions
            cloud_cover_pct = 25.0
            temp_c = 1.5
        else:
            # Post-storm: Arctic high pressure brings cold clear days followed by thaw
            days_after_storm = d - storm_end
            if days_after_storm <= 4:
                # Sub-zero bright clear sky
                cloud_cover_pct = 20.0
                temp_c = -6.0
            else:
                cloud_cover_pct = 30.0
                temp_c = 1.5

        # Solar irradiance on tilted panel
        psh_clear = estimate_vermont_winter_irradiance(coord.lat, day_of_year, setup.panel_tilt_deg)
        cloud_factor = max(0.10, 1.0 - 0.75 * (cloud_cover_pct / 100.0))
        snow_reduction = max(0.0, 1.0 - setup.snow_shading_factor)
        eff_psh = psh_clear * cloud_factor * snow_reduction

        # Potential DC solar generation with MPPT/wiring efficiency (85%)
        potential_gen_wh = setup.panel_watts * eff_psh * 0.85

        # Cold charging lockout verification
        if temp_c <= setup.battery_chemistry.min_charge_temp_c:
            generation_wh = 0.0
        else:
            generation_wh = round(potential_gen_wh * 0.95, 3)

        # Net energy and battery state transition:
        # Subtract concurrent daytime load before clamping potential charge against battery capacity
        daytime_load_wh = daily_consumption_wh * 0.5
        nighttime_load_wh = daily_consumption_wh - daytime_load_wh
        daytime_battery_wh = min(
            setup.battery_capacity_wh,
            max(0.0, current_battery_wh - daytime_load_wh) + generation_wh,
        )

        if daytime_battery_wh - nighttime_load_wh < min_cutoff_wh:
            brownout_occurred = True
            deficit_wh = min_cutoff_wh - (daytime_battery_wh - nighttime_load_wh)
            unpowered_hours = min(24.0, deficit_wh / hourly_consumption_wh)
            ending_battery_wh = min_cutoff_wh
        else:
            brownout_occurred = False
            unpowered_hours = 0.0
            ending_battery_wh = min(setup.battery_capacity_wh, daytime_battery_wh - nighttime_load_wh)

        net_wh = round(generation_wh - daily_consumption_wh, 3)
        soc_pct = round((ending_battery_wh / setup.battery_capacity_wh) * 100.0, 1)

        daily_timeline.append(
            DailySolarStep(
                day_index=d,
                date_label=date_label,
                irradiance_peak_sun_hours=psh_clear,
                cloud_cover_pct=cloud_cover_pct,
                temp_c=temp_c,
                generation_wh=generation_wh,
                consumption_wh=daily_consumption_wh,
                net_wh=net_wh,
                ending_battery_wh=round(ending_battery_wh, 3),
                state_of_charge_pct=soc_pct,
                brownout_occurred=brownout_occurred,
            )
        )

        total_generation_wh += generation_wh
        total_consumption_wh += daily_consumption_wh
        total_brownout_hours += unpowered_hours
        min_soc_pct = min(min_soc_pct, soc_pct)
        current_battery_wh = ending_battery_wh

    survived_winter = total_brownout_hours <= 1e-4

    # Calculate max cloudy storm days tolerated from 100% full capacity
    usable_wh = setup.battery_capacity_wh * usable_ratio
    # During severe storm at -12 deg C:
    if -12.0 <= setup.battery_chemistry.min_charge_temp_c:
        storm_day_gen = 0.0
    else:
        storm_eff_psh = 2.0 * max(0.10, 1.0 - 0.75 * 0.90) * snow_reduction
        storm_day_gen = setup.panel_watts * storm_eff_psh * 0.85 * 0.95

    if storm_day_gen >= daily_consumption_wh:
        max_tolerated_streak = min(99, simulation_days)
    else:
        net_storm_drain = daily_consumption_wh - storm_day_gen
        max_tolerated_streak = int(usable_wh / max(0.001, net_storm_drain))

    # Recommended sizing for winter autonomy
    reserve_days = max(7, consecutive_cloudy_days + 2)
    needed_usable_wh = reserve_days * daily_consumption_wh
    rec_battery_wh = round((needed_usable_wh * 1.25) / usable_ratio, 1)

    # Panel must supply daily load plus recharge battery within 4 sunny days (avg winter PSH ~1.2)
    daily_recharge_wh = (rec_battery_wh * usable_ratio) / 4.0
    total_target_daily_wh = daily_consumption_wh + daily_recharge_wh
    system_efficiency = snow_reduction * 0.85 * 0.95
    calc_panel_w = total_target_daily_wh / (1.2 * max(0.1, system_efficiency))
    rec_panel_w = round(max(5.0, calc_panel_w), 1)

    report = WinterSurvivalReport(
        location=coord,
        setup=setup,
        simulation_days=simulation_days,
        total_generation_wh=round(total_generation_wh, 2),
        total_consumption_wh=round(total_consumption_wh, 2),
        min_state_of_charge_pct=round(min_soc_pct, 1),
        brownout_hours=round(total_brownout_hours, 1),
        survived_winter_streak=survived_winter,
        max_cloudy_streak_days_tolerated=max_tolerated_streak,
        recommended_panel_watts=rec_panel_w,
        recommended_battery_wh=rec_battery_wh,
        daily_timeline=daily_timeline,
    )
    return Result.success(report)
