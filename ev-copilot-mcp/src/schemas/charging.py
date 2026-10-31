"""Pydantic response models for EV charging tools (Google Places evChargeOptions / Open Charge Map)."""

from typing import Literal

from pydantic import BaseModel, Field

from src.schemas.routing import LatLng


class ConnectorAggregation(BaseModel):
    type: str = Field(
        description=(
            "Normalized connector type: CCS2, CCS1, CHADEMO, TYPE_2, J1772, "
            "TESLA, NACS, GB_T or OTHER."
        )
    )
    max_charge_rate_kw: float | None = Field(None, description="Max charging power of each connector in kW.")
    count: int = Field(description="Number of connectors of this type and power.")
    available_count: int | None = Field(
        None, description="Connectors currently available (live data; None if unknown)."
    )
    out_of_service_count: int | None = Field(
        None, description="Connectors currently out of service (live data; None if unknown)."
    )
    availability_updated_at: str | None = Field(
        None, description="Timestamp of the last live availability update (RFC 3339)."
    )


class Charger(BaseModel):
    place_id: str | None = Field(None, description="Google Place ID (or 'ocm:<ID>' for Open Charge Map).")
    name: str = Field(description="Charging station name.")
    address: str | None = Field(None, description="Full formatted address.")
    location: LatLng | None = Field(None, description="Geographic coordinates.")
    rating: float | None = Field(None, description="Average user rating (1-5).")
    review_count: int | None = Field(None, description="Total number of user reviews.")
    max_charge_rate_kw: float | None = Field(None, description="Highest connector power at the station in kW.")
    connector_count: int | None = Field(None, description="Total number of connectors.")
    connectors: list[ConnectorAggregation] = Field(
        default_factory=list, description="Connectors grouped by type and power."
    )
    has_live_availability: bool = Field(
        False, description="True when live connector availability data is present."
    )
    available_connectors: int | None = Field(
        None, description="Total connectors currently available (None when no live data)."
    )
    detour_duration_min: float | None = Field(
        None, description="Extra driving minutes to visit this charger vs. the direct route."
    )
    detour_distance_km: float | None = Field(
        None, description="Extra driving kilometres to visit this charger vs. the direct route."
    )
    amenity_summary: str | None = Field(
        None, description="Summary of amenities (coffee, food, stores) at or near the charger."
    )
    opening_hours: list[str] = Field(default_factory=list, description="Opening hours per weekday.")
    google_maps_uri: str | None = Field(None, description="Link to the charger in Google Maps.")
    source: Literal["google", "open_charge_map"] = Field(
        "google", description="Data source of this charger."
    )


class ChargerSearchResponse(BaseModel):
    count: int = Field(description="Number of chargers returned.")
    chargers: list[Charger] = Field(description="List of matching chargers.")
