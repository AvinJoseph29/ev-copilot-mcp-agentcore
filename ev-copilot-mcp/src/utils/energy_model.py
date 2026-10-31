"""
Deterministic EV energy model.

Pure functions (no I/O) used by the vehicle server to simulate battery
state-of-charge (SoC) along a planned trip:

- ``leg_energy_kwh``   physics-inspired consumption estimate for one leg
                       (base efficiency x speed factor x temperature factor
                       + climbing energy - regenerated energy)
- ``curve_power``      linear interpolation of the vehicle DC charging curve
- ``charge_minutes``   charging time between two SoC values (1 % integration)
- ``simulate_trip``    SoC bookkeeping across legs and charging stops,
                       feasibility check, issues and SoC timeline

The same inputs always produce the same outputs, so the agent can iterate
on a plan (add / move stops) and compare results reliably.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRAVITY = 9.81                 # m/s^2
JOULES_PER_KWH = 3.6e6
DRIVETRAIN_EFFICIENCY = 0.90   # battery -> wheels when climbing
REGEN_EFFICIENCY = 0.60        # potential energy recovered when descending
CHARGING_EFFICIENCY = 0.92     # grid/charger -> battery
REFERENCE_SPEED_KMH = 90.0     # speed at which base efficiency applies
MIN_ENERGY_FRACTION = 0.30     # floor: a leg never uses less than 30 % of base
DEPARTURE_MARGIN_PERCENT = 3.0 # extra SoC on top of the buffer when leaving a stop
TIMELINE_STEP_KM = 5.0         # SoC timeline resolution


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

LatLngTuple = tuple[float, float]


@dataclass(frozen=True, slots=True)
class LegInput:
    """One driving leg between two consecutive points of the trip."""

    start: LatLngTuple
    end: LatLngTuple
    distance_km: float
    duration_min: float
    ascent_m: float = 0.0
    descent_m: float = 0.0


@dataclass(frozen=True, slots=True)
class StopInput:
    """A charging stop at the end of a leg (between leg i and leg i+1)."""

    location: LatLngTuple
    charger_power_kw: float = 50.0
    name: str = ""


@dataclass(slots=True)
class LegResult:
    index: int
    start: LatLngTuple
    end: LatLngTuple
    distance_km: float
    duration_min: float
    avg_speed_kmh: float
    ascent_m: float
    descent_m: float
    energy_kwh: float
    start_soc_percent: float
    arrival_soc_percent: float
    below_buffer: bool


@dataclass(slots=True)
class StopResult:
    index: int
    name: str
    location: LatLngTuple
    arrival_soc_percent: float
    departure_soc_percent: float
    energy_added_kwh: float
    charge_min: float
    charger_power_kw: float


@dataclass(slots=True)
class SimulationResult:
    feasible: bool
    issues: list[str] = field(default_factory=list)
    total_distance_km: float = 0.0
    total_drive_min: float = 0.0
    total_charge_min: float = 0.0
    total_trip_min: float = 0.0
    energy_used_kwh: float = 0.0
    arrival_soc_percent: float = 0.0
    legs: list[LegResult] = field(default_factory=list)
    stops: list[StopResult] = field(default_factory=list)
    soc_timeline: list[tuple[float, float]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Consumption
# ---------------------------------------------------------------------------


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` to the closed interval [low, high]."""
    return max(low, min(value, high))


def speed_factor(avg_speed_kmh: float) -> float:
    """Aerodynamic speed correction relative to the reference speed (90 km/h)."""
    return clamp(0.6 + 0.4 * (avg_speed_kmh / REFERENCE_SPEED_KMH) ** 2, 0.8, 1.6)


def temperature_factor(temperature_c: float | None) -> float:
    """Cabin heating / battery conditioning correction (1.0 when unknown)."""
    if temperature_c is None:
        return 1.0
    cold = min(1.0 + 0.015 * max(0.0, 15.0 - temperature_c), 1.35)
    heat = 0.01 * max(0.0, temperature_c - 30.0)
    return cold + heat


def leg_energy_kwh(
    distance_km: float,
    avg_speed_kmh: float,
    ascent_m: float,
    descent_m: float,
    efficiency_wh_per_km: float,
    mass_kg: float,
    temperature_c: float | None,
) -> float:
    """Estimate the battery energy (kWh) used to drive one leg.

    Args:
        distance_km: Leg distance in kilometres.
        avg_speed_kmh: Average speed over the leg.
        ascent_m: Total climb in metres.
        descent_m: Total descent in metres.
        efficiency_wh_per_km: Vehicle base consumption at ~90 km/h, mild weather.
        mass_kg: Vehicle mass including payload.
        temperature_c: Outside temperature, or None if unknown.
    """
    base = distance_km * efficiency_wh_per_km / 1000.0
    climb = mass_kg * GRAVITY * ascent_m / JOULES_PER_KWH / DRIVETRAIN_EFFICIENCY
    regen = REGEN_EFFICIENCY * mass_kg * GRAVITY * descent_m / JOULES_PER_KWH
    energy = base * speed_factor(avg_speed_kmh) * temperature_factor(temperature_c) + climb - regen
    return max(energy, MIN_ENERGY_FRACTION * base)


# ---------------------------------------------------------------------------
# Charging
# ---------------------------------------------------------------------------


def curve_power(charging_curve: list[dict], soc_percent: float) -> float:
    """Linearly interpolate the DC charging curve at ``soc_percent``.

    ``charging_curve`` is a list of ``{"soc_percent", "power_kw"}`` points;
    values outside the curve are clamped to the first / last point.
    """
    points = sorted(
        ((float(p["soc_percent"]), float(p["power_kw"])) for p in charging_curve),
        key=lambda p: p[0],
    )
    if not points:
        return 0.0
    if soc_percent <= points[0][0]:
        return points[0][1]
    if soc_percent >= points[-1][0]:
        return points[-1][1]
    for (s0, p0), (s1, p1) in itertools.pairwise(points):
        if s0 <= soc_percent <= s1:
            if s1 == s0:
                return p1
            return p0 + (p1 - p0) * (soc_percent - s0) / (s1 - s0)
    return points[-1][1]


def charge_minutes(
    vehicle: dict,
    from_soc: float,
    to_soc: float,
    charger_kw: float,
) -> float:
    """Charging time (minutes) from ``from_soc`` to ``to_soc`` percent.

    Integrates in 1 % steps using
    ``min(curve_power(soc), charger_kw, max_dc_charge_kw) * 0.92``.

    Args:
        vehicle: Catalog entry with ``usable_battery_kwh``, ``charging_curve``
            and ``max_dc_charge_kw``.
        from_soc: Arrival state of charge (%).
        to_soc: Target state of charge (%).
        charger_kw: Charger max power (kW).
    """
    from_soc = clamp(from_soc, 0.0, 100.0)
    to_soc = clamp(to_soc, 0.0, 100.0)
    if to_soc <= from_soc or charger_kw <= 0:
        return 0.0

    usable_kwh = float(vehicle["usable_battery_kwh"])
    max_dc_kw = float(vehicle["max_dc_charge_kw"])
    curve = vehicle.get("charging_curve", [])

    hours = 0.0
    soc = from_soc
    while soc < to_soc - 1e-9:
        step = min(1.0, to_soc - soc)
        mid = soc + step / 2
        power_kw = min(curve_power(curve, mid) if curve else max_dc_kw, charger_kw, max_dc_kw)
        power_kw *= CHARGING_EFFICIENCY
        if power_kw <= 0:
            return math.inf
        hours += (usable_kwh * step / 100.0) / power_kw
        soc += step
    return hours * 60.0


# ---------------------------------------------------------------------------
# Trip simulation
# ---------------------------------------------------------------------------


def _point_label(index: int, stops: list[StopInput], total_points: int) -> str:
    """Human-readable label for trip point ``index`` (0 = start, last = destination)."""
    if index == 0:
        return "Start"
    if index == total_points - 1:
        return "Destination"
    stop = stops[index - 1]
    return stop.name or f"Stop {index}"


def simulate_trip(
    vehicle: dict,
    legs: list[LegInput],
    stops: list[StopInput],
    start_soc_percent: float = 90.0,
    buffer_percent: float = 15.0,
    charge_to_percent: float = 80.0,
    temperature_c: float | None = None,
    payload_kg: float = 150.0,
) -> SimulationResult:
    """Simulate battery SoC across all legs and charging stops.

    ``legs[i]`` ends at ``stops[i]`` (for i < len(stops)); the last leg ends
    at the destination, so ``len(legs) == len(stops) + 1``.

    SoC bookkeeping: the car departs each stop at
    ``max(charge_to_percent, SoC needed for the next leg + buffer + 3 %)``,
    capped at 100 % (flagged as an issue when more than 100 % is needed).
    The plan is ``feasible`` when no leg arrives below the buffer and no stop
    requires more than a full battery.
    """
    if len(legs) != len(stops) + 1:
        raise ValueError(
            f"Expected {len(stops) + 1} legs for {len(stops)} charging stop(s), got {len(legs)}."
        )

    usable_kwh = float(vehicle["usable_battery_kwh"])
    efficiency = float(vehicle["efficiency_wh_per_km"])
    total_mass = float(vehicle["mass_kg"]) + max(0.0, payload_kg)
    total_points = len(legs) + 1

    result = SimulationResult(feasible=True)

    # --- Per-leg energy ---
    leg_energy: list[float] = []
    leg_speed: list[float] = []
    for leg in legs:
        hours = leg.duration_min / 60.0
        speed = leg.distance_km / hours if hours > 0 else REFERENCE_SPEED_KMH
        leg_speed.append(speed)
        leg_energy.append(
            leg_energy_kwh(
                distance_km=leg.distance_km,
                avg_speed_kmh=speed,
                ascent_m=leg.ascent_m,
                descent_m=leg.descent_m,
                efficiency_wh_per_km=efficiency,
                mass_kg=total_mass,
                temperature_c=temperature_c,
            )
        )

    # --- SoC bookkeeping ---
    soc = start_soc_percent
    distance_so_far = 0.0
    timeline: list[tuple[float, float]] = [(0.0, round(soc, 1))]

    if start_soc_percent < buffer_percent:
        result.issues.append(
            f"Starting battery {start_soc_percent:.0f}% is already below the "
            f"{buffer_percent:.0f}% buffer — charge before departing."
        )

    for i, leg in enumerate(legs):
        leg_pct = leg_energy[i] / usable_kwh * 100.0

        # Charging stop before this leg (stop i-1 sits at the start of leg i)
        if i > 0:
            stop = stops[i - 1]
            arrival = soc
            needed = leg_pct + buffer_percent + DEPARTURE_MARGIN_PERCENT
            target = max(charge_to_percent, needed)
            if target > 100.0:
                result.feasible = False
                result.issues.append(
                    f"Leaving {_point_label(i, stops, total_points)} the next leg "
                    f"({leg.distance_km:.0f} km) needs {needed:.0f}% — more than a full "
                    f"battery. Add a charging stop between "
                    f"{_point_label(i, stops, total_points)} and "
                    f"{_point_label(i + 1, stops, total_points)}."
                )
                target = 100.0
            target = max(target, arrival)
            minutes = charge_minutes(vehicle, arrival, target, stop.charger_power_kw)
            energy_added = (target - max(arrival, 0.0)) / 100.0 * usable_kwh
            result.stops.append(
                StopResult(
                    index=i,
                    name=stop.name or f"Stop {i}",
                    location=stop.location,
                    arrival_soc_percent=round(max(arrival, 0.0), 1),
                    departure_soc_percent=round(target, 1),
                    energy_added_kwh=round(max(energy_added, 0.0), 2),
                    charge_min=round(minutes, 1),
                    charger_power_kw=stop.charger_power_kw,
                )
            )
            result.total_charge_min += minutes
            soc = target
            timeline.append((round(distance_so_far, 1), round(soc, 1)))

        start_soc = soc
        arrival = soc - leg_pct
        below = arrival < buffer_percent

        # Timeline points every ~5 km within the leg (linear in distance)
        steps = max(1, int(leg.distance_km // TIMELINE_STEP_KM))
        for k in range(1, steps + 1):
            d = leg.distance_km * k / steps
            point_soc = start_soc - leg_pct * (d / leg.distance_km if leg.distance_km else 1.0)
            timeline.append((round(distance_so_far + d, 1), round(max(point_soc, 0.0), 1)))

        if below:
            result.feasible = False
            km_to_buffer = (
                max(start_soc - buffer_percent, 0.0) / leg_pct * leg.distance_km
                if leg_pct > 0
                else leg.distance_km
            )
            result.issues.append(
                f"Leg {i + 1} ({_point_label(i, stops, total_points)} → "
                f"{_point_label(i + 1, stops, total_points)}) arrives at "
                f"{max(arrival, 0.0):.0f}% (< {buffer_percent:.0f}% buffer) — add a "
                f"charging stop before km {distance_so_far + km_to_buffer:.0f}."
            )

        result.legs.append(
            LegResult(
                index=i,
                start=leg.start,
                end=leg.end,
                distance_km=round(leg.distance_km, 2),
                duration_min=round(leg.duration_min, 1),
                avg_speed_kmh=round(leg_speed[i], 1),
                ascent_m=round(leg.ascent_m, 1),
                descent_m=round(leg.descent_m, 1),
                energy_kwh=round(leg_energy[i], 2),
                start_soc_percent=round(start_soc, 1),
                arrival_soc_percent=round(max(arrival, 0.0), 1),
                below_buffer=below,
            )
        )

        soc = arrival
        distance_so_far += leg.distance_km
        result.total_drive_min += leg.duration_min

    # --- Totals ---
    result.total_distance_km = round(distance_so_far, 2)
    result.total_drive_min = round(result.total_drive_min, 1)
    result.total_charge_min = round(result.total_charge_min, 1)
    result.total_trip_min = round(result.total_drive_min + result.total_charge_min, 1)
    result.energy_used_kwh = round(sum(leg_energy), 2)
    result.arrival_soc_percent = round(max(soc, 0.0), 1)
    result.soc_timeline = timeline

    # --- Transparency ---
    result.assumptions = [
        (
            f"Base consumption {efficiency:.0f} Wh/km and {usable_kwh:.1f} kWh usable battery "
            f"(approximate public specifications)."
        ),
        f"Vehicle mass {float(vehicle['mass_kg']):.0f} kg + {max(0.0, payload_kg):.0f} kg payload.",
        (
            f"Outside temperature {temperature_c:.0f}°C "
            f"(consumption x{temperature_factor(temperature_c):.2f})."
            if temperature_c is not None
            else "Outside temperature unknown — no temperature correction applied."
        ),
        (
            "Average speeds from traffic-aware Google route durations "
            "(aerodynamic correction relative to 90 km/h)."
        ),
        (
            "Elevation from the Google Elevation API "
            f"({DRIVETRAIN_EFFICIENCY:.0%} drivetrain efficiency climbing, "
            f"{REGEN_EFFICIENCY:.0%} regeneration descending)."
        ),
        (
            f"Charging power = min(vehicle curve, charger, vehicle max DC) x "
            f"{CHARGING_EFFICIENCY:.0%} efficiency."
        ),
        (
            f"Arrive with ≥{buffer_percent:.0f}% buffer; depart stops at ≥{charge_to_percent:.0f}% "
            f"or enough for the next leg + buffer + {DEPARTURE_MARGIN_PERCENT:.0f}%."
        ),
    ]
    return result
