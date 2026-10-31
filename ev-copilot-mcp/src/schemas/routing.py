"""Pydantic models for Google Routes / Geocoding / Elevation tools."""

from pydantic import BaseModel, Field

# --- Shared ---


class LatLng(BaseModel):
    latitude: float = Field(description="Latitude coordinate.")
    longitude: float = Field(description="Longitude coordinate.")


class Waypoint(BaseModel):
    """Intermediate stop passed as a tool argument (never an encoded polyline)."""

    latitude: float = Field(description="Waypoint latitude (e.g. 16.7050 for Kolhapur).")
    longitude: float = Field(description="Waypoint longitude (e.g. 74.2433 for Kolhapur).")


# --- Geocoding ---


class GeocodedLocation(BaseModel):
    formatted_address: str | None = Field(None, description="Full human-readable address.")
    latitude: float | None = Field(None, description="Latitude coordinate.")
    longitude: float | None = Field(None, description="Longitude coordinate.")
    place_id: str | None = Field(None, description="Google Place ID of the result.")
    types: list[str] = Field(default_factory=list, description="Result type categories (e.g. locality).")
    locality: str | None = Field(None, description="City or locality name.")
    region: str | None = Field(None, description="State or region (administrative area level 1).")
    country: str | None = Field(None, description="Country name.")


class GeocodeResponse(BaseModel):
    count: int = Field(description="Number of results returned.")
    results: list[GeocodedLocation] = Field(description="List of geocoded locations.")


# --- Routes ---


class RouteLeg(BaseModel):
    index: int = Field(description="Zero-based leg index (origin -> first waypoint is leg 0).")
    start: LatLng = Field(description="Leg start coordinates.")
    end: LatLng = Field(description="Leg end coordinates.")
    distance_km: float = Field(description="Leg distance in kilometres.")
    duration_min: float = Field(description="Leg driving duration in minutes (traffic-aware).")
    encoded_polyline: str | None = Field(None, description="Google encoded polyline of the leg.")


class RouteResponse(BaseModel):
    distance_km: float = Field(description="Total route distance in kilometres.")
    duration_min: float = Field(description="Total driving duration in minutes (traffic-aware).")
    static_duration_min: float | None = Field(
        None, description="Total driving duration in minutes without traffic."
    )
    encoded_polyline: str | None = Field(None, description="Google encoded polyline of the whole route.")
    legs: list[RouteLeg] = Field(default_factory=list, description="Route legs between waypoints.")
    toll_info: str | None = Field(None, description="Estimated toll cost (e.g. 'INR 785.00'), if any.")
    warnings: list[str] = Field(default_factory=list, description="Route warnings returned by Google.")


# --- Elevation ---


class ElevationPoint(BaseModel):
    latitude: float = Field(description="Sample latitude.")
    longitude: float = Field(description="Sample longitude.")
    elevation_m: float = Field(description="Elevation above sea level in metres.")
    distance_km: float = Field(description="Distance along the route from the origin in kilometres.")


class ElevationProfileResponse(BaseModel):
    total_ascent_m: float = Field(description="Total climb along the route in metres.")
    total_descent_m: float = Field(description="Total descent along the route in metres.")
    min_elevation_m: float | None = Field(None, description="Lowest sampled elevation in metres.")
    max_elevation_m: float | None = Field(None, description="Highest sampled elevation in metres.")
    points: list[ElevationPoint] = Field(default_factory=list, description="Elevation samples along the route.")
