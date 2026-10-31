"""
Routing MCP Server.

Self-contained FastMCP instance with Google Maps Platform routing tools:
geocoding (Geocoding API), electric-vehicle routing (Routes API) and
elevation profiles (Elevation API).
Mounted into the registry via tool_registry.py.
"""

from fastmcp import FastMCP

from src.clients.google_elevation_client import MAX_SAMPLES, GoogleElevationClient
from src.clients.google_geocoding_client import GoogleGeocodingClient
from src.clients.google_routes_client import GoogleRoutesClient
from src.config import settings
from src.infrastructure.trace_decorator import traced
from src.schemas.routing import (
    ElevationProfileResponse,
    GeocodeResponse,
    RouteResponse,
    Waypoint,
)
from src.utils.polyline import shorten_polyline
from src.utils.route_formatters import (
    format_elevation_profile,
    format_geocode_results,
    format_route,
)

routing_mcp = FastMCP("routing")

# ---------------------------------------------------------------------------
# Lazy client singletons
# ---------------------------------------------------------------------------

_routes_client: GoogleRoutesClient | None = None
_geocoding_client: GoogleGeocodingClient | None = None
_elevation_client: GoogleElevationClient | None = None


def _get_routes_client() -> GoogleRoutesClient:
    global _routes_client
    if _routes_client is None:
        _routes_client = GoogleRoutesClient(api_key=settings.GOOGLE_MAPS_API_KEY)
    return _routes_client


def _get_geocoding_client() -> GoogleGeocodingClient:
    global _geocoding_client
    if _geocoding_client is None:
        _geocoding_client = GoogleGeocodingClient(api_key=settings.GOOGLE_MAPS_API_KEY)
    return _geocoding_client


def _get_elevation_client() -> GoogleElevationClient:
    global _elevation_client
    if _elevation_client is None:
        _elevation_client = GoogleElevationClient(api_key=settings.GOOGLE_MAPS_API_KEY)
    return _elevation_client


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@routing_mcp.tool(
    title="Geocode Address",
    description=(
        "Convert an address, city, place name, or landmark into geographic "
        "coordinates (latitude, longitude). Use this whenever the user mentions "
        "a location by name — origin, destination, or a via point — before "
        "calling routing, charging, vehicle simulation, weather, or nearby-search tools."
    ),
    tags={"geocoding", "address", "coordinates", "google"},
    annotations={
        "title": "Geocode Address",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.geocode", handler_type="tool")
async def geocode(
    address: str,
    max_results: int = 5,
    region: str = "",
) -> GeocodeResponse:
    """Convert an address or place name to geographic coordinates (forward geocoding).

    Args:
        address: Address or place name to geocode (e.g. "Pune, Maharashtra").
        max_results: Maximum number of results to return (1-10, default 5).
        region: Optional ccTLD region bias (e.g. "in" for India, "us" for the United States).
    """
    client = _get_geocoding_client()
    results = await client.geocode(
        address=address,
        region=region or None,
    )
    return format_geocode_results(results, max_results=max_results)


@routing_mcp.tool(
    title="Compute EV Route",
    description=(
        "Compute a traffic-aware driving route for an electric vehicle between an "
        "origin and a destination, optionally through intermediate waypoints "
        "(e.g. planned charging stops). Returns total distance, drive time with and "
        "without traffic, per-leg distance and duration, tolls, warnings, and the "
        "encoded route polyline. Use this after geocoding to get the base route "
        "before searching for chargers along it."
    ),
    tags={"routing", "directions", "ev", "google"},
    annotations={
        "title": "Compute EV Route",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.compute_route", handler_type="tool")
async def compute_route(
    origin_latitude: float,
    origin_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
    waypoints: list[Waypoint] = [],  # noqa: B006
    departure_time: str = "",
    avoid_tolls: bool = False,
    avoid_highways: bool = False,
) -> RouteResponse:
    """Compute an electric-vehicle driving route.

    Args:
        origin_latitude: Start latitude (e.g. 18.5204 for Pune).
        origin_longitude: Start longitude (e.g. 73.8567 for Pune).
        destination_latitude: Destination latitude (e.g. 15.4909 for Panaji, Goa).
        destination_longitude: Destination longitude (e.g. 73.8278 for Panaji, Goa).
        waypoints: Optional ordered intermediate stops as objects
                   (e.g. [{"latitude": 16.7050, "longitude": 74.2433}]).
        departure_time: Optional departure time in RFC 3339 format
                        (e.g. "YYYY-MM-DDT06:30:00+05:30" with a future date);
                        must be in the future and include a UTC offset, otherwise
                        it is ignored with a route warning. Leave empty to depart now.
        avoid_tolls: Avoid toll roads where reasonable (default False).
        avoid_highways: Avoid highways where reasonable (default False).
    """
    client = _get_routes_client()
    route = await client.compute_route(
        origin=(origin_latitude, origin_longitude),
        destination=(destination_latitude, destination_longitude),
        intermediates=[(w.latitude, w.longitude) for w in waypoints],
        departure_time=departure_time,
        avoid_tolls=avoid_tolls,
        avoid_highways=avoid_highways,
    )
    return format_route(route)


@routing_mcp.tool(
    title="Get Elevation Profile",
    description=(
        "Get the elevation profile along a driving route (origin, destination and "
        "optional waypoints). Returns total ascent and descent, minimum and maximum "
        "elevation, and evenly spaced elevation samples with distance from the "
        "origin. Use this when the user asks about hills or mountain passes on the "
        "route — climbing costs extra battery energy, descending regenerates some."
    ),
    tags={"routing", "elevation", "terrain", "google"},
    annotations={
        "title": "Get Elevation Profile",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.get_elevation_profile", handler_type="tool")
async def get_elevation_profile(
    origin_latitude: float,
    origin_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
    waypoints: list[Waypoint] = [],  # noqa: B006
    samples: int = 64,
) -> ElevationProfileResponse:
    """Get the elevation profile along a route.

    Args:
        origin_latitude: Start latitude (e.g. 18.5204 for Pune).
        origin_longitude: Start longitude (e.g. 73.8567 for Pune).
        destination_latitude: Destination latitude (e.g. 15.4909 for Panaji, Goa).
        destination_longitude: Destination longitude (e.g. 73.8278 for Panaji, Goa).
        waypoints: Optional ordered intermediate stops as objects
                   (e.g. [{"latitude": 16.7050, "longitude": 74.2433}]).
        samples: Number of evenly spaced elevation samples (2-512, default 64).
    """
    route = await _get_routes_client().compute_route(
        origin=(origin_latitude, origin_longitude),
        destination=(destination_latitude, destination_longitude),
        intermediates=[(w.latitude, w.longitude) for w in waypoints],
    )
    encoded = route.get("polyline", {}).get("encodedPolyline", "")
    results = await _get_elevation_client().get_elevation_along_path(
        encoded_path=shorten_polyline(encoded),
        samples=max(2, min(samples, MAX_SAMPLES)),
    )
    return format_elevation_profile(results)
