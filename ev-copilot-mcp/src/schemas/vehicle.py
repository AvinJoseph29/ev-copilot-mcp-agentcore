"""Pydantic models for the vehicle catalog and trip energy simulation tools."""

from pydantic import BaseModel, Field

from src.schemas.routing import LatLng

# --- Vehicle catalog ---


class CurvePoint(BaseModel):
    soc_percent: float = Field(description="State of charge in percent (0-100).")
    power_kw: float = Field(description="Max DC charging power the car accepts at this SoC in kW.")


class VehicleSummary(BaseModel):
    vehicle_id: str = Field(description="Catalog vehicle ID (e.g. 'tata-nexon-ev-45').")
    make: str = Field(description="Manufacturer (e.g. Tata).")
    model: str = Field(description="Model name (e.g. Nexon EV).")
    variant: str = Field(description="Variant / battery option (e.g. 45 kWh).")
    usable_battery_kwh: float = Field(description="Usable battery capacity in kWh.")
    est_range_km: float = Field(description="Estimated real-world range in kilometres.")


class VehicleSearchResponse(BaseModel):
    count: int = Field(description="Number of vehicles returned.")
    vehicles: list[VehicleSummary] = Field(description="Best matching vehicles, most relevant first.")


class VehicleSpec(BaseModel):
    vehicle_id: str = Field(description="Catalog vehicle ID.")
    make: str = Field(description="Manufacturer.")
    model: str = Field(description="Model name.")
    variant: str = Field(description="Variant / battery option.")
    usable_battery_kwh: float = Field(description="Usable battery capacity in kWh.")
    efficiency_wh_per_km: float = Field(description="Typical mixed-driving consumption in Wh/km.")
    mass_kg: float = Field(description="Kerb mass in kilograms.")
    max_ac_charge_kw: float = Field(description="Max AC charging power in kW.")
    max_dc_charge_kw: float = Field(description="Max DC fast-charging power in kW.")
    ac_connectors: list[str] = Field(default_factory=list, description="Supported AC connector types.")
    dc_connectors: list[str] = Field(default_factory=list, description="Supported DC connector types.")
    charging_curve: list[CurvePoint] = Field(
        default_factory=list, description="DC charging curve (power vs. state of charge)."
    )
    est_range_km: float = Field(description="Estimated real-world range in kilometres.")
    markets: list[str] = Field(default_factory=list, description="Markets where this variant is sold (ISO codes).")


# --- Trip energy simulation ---


class ChargingStopInput(BaseModel):
    """Planned charging stop passed as a tool argument."""

    latitude: float = Field(description="Charging stop latitude.")
    longitude: float = Field(description="Charging stop longitude.")
    charger_power_kw: float = Field(50, description="Charger max power in kW (default 50).")
    name: str = Field("", description="Charger name for the plan (optional).")


class EnergyLeg(BaseModel):
    index: int = Field(description="Zero-based leg index.")
    start: LatLng = Field(description="Leg start coordinates.")
    end: LatLng = Field(description="Leg end coordinates.")
    distance_km: float = Field(description="Leg distance in kilometres.")
    duration_min: float = Field(description="Leg driving duration in minutes.")
    avg_speed_kmh: float = Field(description="Average speed over the leg in km/h.")
    ascent_m: float = Field(description="Total climb over the leg in metres.")
    descent_m: float = Field(description="Total descent over the leg in metres.")
    energy_kwh: float = Field(description="Estimated energy consumed over the leg in kWh.")
    start_soc_percent: float = Field(description="Battery % at the start of the leg.")
    arrival_soc_percent: float = Field(description="Battery % on arrival at the end of the leg.")
    below_buffer: bool = Field(description="True if the leg arrives below the safety buffer.")


class ChargeStopResult(BaseModel):
    index: int = Field(description="One-based charging stop number.")
    name: str = Field(description="Charger name.")
    location: LatLng = Field(description="Charger coordinates.")
    arrival_soc_percent: float = Field(description="Battery % on arrival at the charger.")
    departure_soc_percent: float = Field(description="Battery % when leaving the charger.")
    energy_added_kwh: float = Field(description="Energy added at this stop in kWh.")
    charge_min: float = Field(description="Estimated charging time in minutes.")
    charger_power_kw: float = Field(description="Charger max power in kW.")


class SocPoint(BaseModel):
    distance_km: float = Field(description="Distance from the origin in kilometres.")
    soc_percent: float = Field(description="Battery % at this point.")


class TripEnergyPlan(BaseModel):
    vehicle_id: str = Field(description="Catalog vehicle ID.")
    vehicle_name: str = Field(description="Human-readable vehicle name.")
    feasible: bool = Field(description="True if every leg arrives at or above the buffer.")
    issues: list[str] = Field(default_factory=list, description="Human-readable problems with the plan.")
    total_distance_km: float = Field(description="Total driving distance in kilometres.")
    total_drive_min: float = Field(description="Total driving time in minutes.")
    total_charge_min: float = Field(description="Total charging time in minutes.")
    total_trip_min: float = Field(description="Total trip time (driving + charging) in minutes.")
    energy_used_kwh: float = Field(description="Total energy consumed in kWh.")
    arrival_soc_percent: float = Field(description="Battery % on arrival at the destination.")
    legs: list[EnergyLeg] = Field(default_factory=list, description="Per-leg energy breakdown.")
    stops: list[ChargeStopResult] = Field(default_factory=list, description="Charging stop results.")
    soc_timeline: list[SocPoint] = Field(
        default_factory=list, description="Battery % along the route (for charting)."
    )
    encoded_polyline: str | None = Field(None, description="Google encoded polyline of the whole route.")
    assumptions: list[str] = Field(default_factory=list, description="Model assumptions used for the estimate.")
