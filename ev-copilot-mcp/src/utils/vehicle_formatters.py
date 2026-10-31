"""Formatting helpers for the vehicle catalog and trip energy simulation."""

from src.schemas.routing import LatLng
from src.schemas.vehicle import (
    ChargeStopResult,
    CurvePoint,
    EnergyLeg,
    SocPoint,
    TripEnergyPlan,
    VehicleSearchResponse,
    VehicleSpec,
    VehicleSummary,
)
from src.utils.energy_model import SimulationResult


def vehicle_display_name(vehicle: dict) -> str:
    """Human-readable vehicle name (e.g. "Tata Nexon EV 45 kWh (Long Range)")."""
    return f"{vehicle['make']} {vehicle['model']} {vehicle['variant']}".strip()


def _latlng(point: tuple[float, float]) -> LatLng:
    return LatLng(latitude=point[0], longitude=point[1])


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def format_vehicle_summary(vehicle: dict) -> VehicleSummary:
    """Format a catalog entry into a VehicleSummary model."""
    return VehicleSummary(
        vehicle_id=vehicle["vehicle_id"],
        make=vehicle["make"],
        model=vehicle["model"],
        variant=vehicle["variant"],
        usable_battery_kwh=vehicle["usable_battery_kwh"],
        est_range_km=vehicle["est_range_km"],
    )


def format_vehicle_search(vehicles: list[dict]) -> VehicleSearchResponse:
    """Format matching catalog entries into a VehicleSearchResponse model."""
    return VehicleSearchResponse(
        count=len(vehicles),
        vehicles=[format_vehicle_summary(v) for v in vehicles],
    )


def format_vehicle_spec(vehicle: dict) -> VehicleSpec:
    """Format a catalog entry into a full VehicleSpec model."""
    return VehicleSpec(
        vehicle_id=vehicle["vehicle_id"],
        make=vehicle["make"],
        model=vehicle["model"],
        variant=vehicle["variant"],
        usable_battery_kwh=vehicle["usable_battery_kwh"],
        efficiency_wh_per_km=vehicle["efficiency_wh_per_km"],
        mass_kg=vehicle["mass_kg"],
        max_ac_charge_kw=vehicle["max_ac_charge_kw"],
        max_dc_charge_kw=vehicle["max_dc_charge_kw"],
        ac_connectors=vehicle.get("ac_connectors", []),
        dc_connectors=vehicle.get("dc_connectors", []),
        charging_curve=[
            CurvePoint(soc_percent=p["soc_percent"], power_kw=p["power_kw"])
            for p in vehicle.get("charging_curve", [])
        ],
        est_range_km=vehicle["est_range_km"],
        markets=vehicle.get("markets", []),
    )


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def format_trip_energy_plan(
    vehicle: dict,
    simulation: SimulationResult,
    encoded_polyline: str | None = None,
) -> TripEnergyPlan:
    """Format an energy-model SimulationResult into a TripEnergyPlan model."""
    return TripEnergyPlan(
        vehicle_id=vehicle["vehicle_id"],
        vehicle_name=vehicle_display_name(vehicle),
        feasible=simulation.feasible,
        issues=simulation.issues,
        total_distance_km=simulation.total_distance_km,
        total_drive_min=simulation.total_drive_min,
        total_charge_min=simulation.total_charge_min,
        total_trip_min=simulation.total_trip_min,
        energy_used_kwh=simulation.energy_used_kwh,
        arrival_soc_percent=simulation.arrival_soc_percent,
        legs=[
            EnergyLeg(
                index=leg.index,
                start=_latlng(leg.start),
                end=_latlng(leg.end),
                distance_km=leg.distance_km,
                duration_min=leg.duration_min,
                avg_speed_kmh=leg.avg_speed_kmh,
                ascent_m=leg.ascent_m,
                descent_m=leg.descent_m,
                energy_kwh=leg.energy_kwh,
                start_soc_percent=leg.start_soc_percent,
                arrival_soc_percent=leg.arrival_soc_percent,
                below_buffer=leg.below_buffer,
            )
            for leg in simulation.legs
        ],
        stops=[
            ChargeStopResult(
                index=stop.index,
                name=stop.name,
                location=_latlng(stop.location),
                arrival_soc_percent=stop.arrival_soc_percent,
                departure_soc_percent=stop.departure_soc_percent,
                energy_added_kwh=stop.energy_added_kwh,
                charge_min=stop.charge_min,
                charger_power_kw=stop.charger_power_kw,
            )
            for stop in simulation.stops
        ],
        soc_timeline=[
            SocPoint(distance_km=distance, soc_percent=soc)
            for distance, soc in simulation.soc_timeline
        ],
        encoded_polyline=encoded_polyline,
        assumptions=simulation.assumptions,
    )
