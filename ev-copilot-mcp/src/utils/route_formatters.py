"""Formatting helpers for Google Routes / Geocoding / Elevation API responses."""

import itertools

from src.schemas.routing import (
    ElevationPoint,
    ElevationProfileResponse,
    GeocodedLocation,
    GeocodeResponse,
    LatLng,
    RouteLeg,
    RouteResponse,
)
from src.utils.polyline import cumulative_distances_km


def parse_duration_seconds(value: str | None) -> float:
    """Parse a protobuf Duration string (e.g. "1234s" or "12.5s") into seconds."""
    if not value:
        return 0.0
    return float(str(value).rstrip("s") or 0)


def _extract_latlng(location: dict) -> LatLng:
    """Extract a LatLng from a Routes API Location ({"latLng": {...}})."""
    lat_lng = (location or {}).get("latLng", {})
    return LatLng(
        latitude=lat_lng.get("latitude", 0.0),
        longitude=lat_lng.get("longitude", 0.0),
    )


def _format_toll_info(travel_advisory: dict) -> str | None:
    """Format Routes API tollInfo into a short string (e.g. "INR 785.00")."""
    if "tollInfo" not in (travel_advisory or {}):
        return None
    prices = travel_advisory["tollInfo"].get("estimatedPrice", [])
    if not prices:
        return "Tolls on route (price unknown)"
    parts = []
    for price in prices:
        amount = float(price.get("units", 0)) + float(price.get("nanos", 0)) / 1e9
        parts.append(f"{price.get('currencyCode', '')} {amount:.2f}".strip())
    return " + ".join(parts)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def format_route(route: dict) -> RouteResponse:
    """Format a Routes API route into a RouteResponse model."""
    legs = []
    for index, leg in enumerate(route.get("legs", [])):
        legs.append(RouteLeg(
            index=index,
            start=_extract_latlng(leg.get("startLocation", {})),
            end=_extract_latlng(leg.get("endLocation", {})),
            distance_km=round(leg.get("distanceMeters", 0) / 1000, 2),
            duration_min=round(parse_duration_seconds(leg.get("duration")) / 60, 1),
            encoded_polyline=leg.get("polyline", {}).get("encodedPolyline"),
        ))

    static_duration = route.get("staticDuration")

    return RouteResponse(
        distance_km=round(route.get("distanceMeters", 0) / 1000, 2),
        duration_min=round(parse_duration_seconds(route.get("duration")) / 60, 1),
        static_duration_min=(
            round(parse_duration_seconds(static_duration) / 60, 1)
            if static_duration
            else None
        ),
        encoded_polyline=route.get("polyline", {}).get("encodedPolyline"),
        legs=legs,
        toll_info=_format_toll_info(route.get("travelAdvisory", {})),
        warnings=route.get("warnings", []),
    )


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------


def _address_component(components: list[dict], component_type: str) -> str | None:
    """Return the long_name of the first address component with the given type."""
    for component in components:
        if component_type in component.get("types", []):
            return component.get("long_name")
    return None


def format_geocode_results(results: list[dict], max_results: int = 5) -> GeocodeResponse:
    """Format Geocoding API results into a GeocodeResponse model."""
    formatted = []
    for result in results[: max(1, max_results)]:
        location = result.get("geometry", {}).get("location", {})
        components = result.get("address_components", [])

        formatted.append(GeocodedLocation(
            formatted_address=result.get("formatted_address"),
            latitude=location.get("lat"),
            longitude=location.get("lng"),
            place_id=result.get("place_id"),
            types=result.get("types", []),
            locality=(
                _address_component(components, "locality")
                or _address_component(components, "administrative_area_level_3")
                or _address_component(components, "administrative_area_level_2")
            ),
            region=_address_component(components, "administrative_area_level_1"),
            country=_address_component(components, "country"),
        ))

    return GeocodeResponse(
        count=len(formatted),
        results=formatted,
    )


# ---------------------------------------------------------------------------
# Elevation
# ---------------------------------------------------------------------------


def ascent_descent(elevations: list[float]) -> tuple[float, float]:
    """Total ascent and descent (metres) of an elevation sequence."""
    ascent = descent = 0.0
    for previous, current in itertools.pairwise(elevations):
        delta = current - previous
        if delta > 0:
            ascent += delta
        else:
            descent -= delta
    return ascent, descent


def format_elevation_profile(results: list[dict]) -> ElevationProfileResponse:
    """Format Elevation API path samples into an ElevationProfileResponse model."""
    coordinates = [
        (r.get("location", {}).get("lat", 0.0), r.get("location", {}).get("lng", 0.0))
        for r in results
    ]
    elevations = [float(r.get("elevation", 0.0)) for r in results]
    distances = cumulative_distances_km(coordinates)
    ascent, descent = ascent_descent(elevations)

    points = [
        ElevationPoint(
            latitude=lat,
            longitude=lng,
            elevation_m=round(elevation, 1),
            distance_km=round(distance, 2),
        )
        for (lat, lng), elevation, distance in zip(coordinates, elevations, distances)
    ]

    return ElevationProfileResponse(
        total_ascent_m=round(ascent, 1),
        total_descent_m=round(descent, 1),
        min_elevation_m=round(min(elevations), 1) if elevations else None,
        max_elevation_m=round(max(elevations), 1) if elevations else None,
        points=points,
    )
