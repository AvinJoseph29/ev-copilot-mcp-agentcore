"""
Charging MCP Server.

Self-contained FastMCP instance with EV charging station tools:
- Google Places API (New) ``evChargeOptions`` — connectors, power and
  live availability (search along a route, nearby, details)
- Open Charge Map — community registry used as a coverage fallback
Mounted into the registry via tool_registry.py.
"""

from fastmcp import FastMCP
from loguru import logger

from src.clients.google_places_client import GooglePlacesClient
from src.clients.google_routes_client import GoogleRoutesClient
from src.clients.open_charge_map_client import OpenChargeMapClient
from src.config import settings
from src.infrastructure.trace_decorator import traced
from src.schemas.charging import Charger, ChargerSearchResponse
from src.schemas.routing import Waypoint
from src.utils.charging_formatters import (
    charger_matches,
    format_chargers,
    format_google_charger,
    format_google_chargers,
    format_ocm_charger,
    normalize_connector_type,
    restrict_to_matching,
    to_google_connector_types,
)
from src.utils.polyline import haversine_km
from src.utils.route_formatters import parse_duration_seconds

charging_mcp = FastMCP("charging")

# ---------------------------------------------------------------------------
# Lazy client singletons
# ---------------------------------------------------------------------------

_places_client: GooglePlacesClient | None = None
_routes_client: GoogleRoutesClient | None = None
_ocm_client: OpenChargeMapClient | None = None


def _get_places_client() -> GooglePlacesClient:
    global _places_client
    if _places_client is None:
        _places_client = GooglePlacesClient(api_key=settings.GOOGLE_MAPS_API_KEY)
    return _places_client


def _get_routes_client() -> GoogleRoutesClient:
    global _routes_client
    if _routes_client is None:
        _routes_client = GoogleRoutesClient(api_key=settings.GOOGLE_MAPS_API_KEY)
    return _routes_client


def _get_ocm_client() -> OpenChargeMapClient:
    global _ocm_client
    if _ocm_client is None:
        _ocm_client = OpenChargeMapClient(api_key=settings.OPEN_CHARGE_MAP_API_KEY)
    return _ocm_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _distance_from(latitude: float, longitude: float, charger: Charger) -> float:
    """Straight-line distance (km) from a point to a charger (inf if unknown)."""
    if charger.location is None:
        return float("inf")
    return haversine_km(
        (latitude, longitude),
        (charger.location.latitude, charger.location.longitude),
    )


def _google_connector_filter(connector_type: str) -> list[str] | None:
    """Google EVConnectorType values for a connector name (None if unrecognized)."""
    if not connector_type:
        return None
    if normalize_connector_type(connector_type) == "OTHER":
        logger.warning(f"Unrecognized connector type {connector_type!r} — not filtering on it")
        return None
    return to_google_connector_types(connector_type) or None


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@charging_mcp.tool(
    title="Search Chargers Along Route",
    description=(
        "Find EV charging stations along the driving route between an origin and a "
        "destination (optionally via waypoints). Returns each charger's connectors "
        "with power (kW), live availability (available / out of service) where the "
        "network reports it, detour time and distance from the route (only when no "
        "waypoints are given), rating, amenities, and opening hours, sorted by "
        "smallest detour then highest power. "
        "Use this after computing the route to pick charging stops; filter by the "
        "vehicle's DC connector and a minimum power."
    ),
    tags={"charging", "ev", "route", "availability", "google"},
    annotations={
        "title": "Search Chargers Along Route",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.search_chargers_along_route", handler_type="tool")
async def search_chargers_along_route(
    origin_latitude: float,
    origin_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
    waypoints: list[Waypoint] = [],  # noqa: B006
    min_power_kw: float = 0,
    connector_type: str = "",
    max_results: int = 10,
) -> ChargerSearchResponse:
    """Search for EV chargers along a driving route.

    Args:
        origin_latitude: Start latitude (e.g. 18.5204 for Pune).
        origin_longitude: Start longitude (e.g. 73.8567 for Pune).
        destination_latitude: Destination latitude (e.g. 12.9716 for Bengaluru).
        destination_longitude: Destination longitude (e.g. 77.5946 for Bengaluru).
        waypoints: Optional ordered intermediate stops as objects
                   (e.g. [{"latitude": 16.7050, "longitude": 74.2433}]).
                   With waypoints, detour time/distance is not reported
                   (None) and results are sorted by highest power.
        min_power_kw: Minimum charger power in kW (e.g. 50 for DC fast charging; 0 = any).
        connector_type: Optional connector filter (e.g. "CCS2", "CCS1", "CHAdeMO",
                        "Type 2", "NACS", "Tesla").
        max_results: Maximum number of chargers to return (1-20, default 10).
    """
    route = await _get_routes_client().compute_route(
        origin=(origin_latitude, origin_longitude),
        destination=(destination_latitude, destination_longitude),
        intermediates=[(w.latitude, w.longitude) for w in waypoints],
    )
    encoded = route.get("polyline", {}).get("encodedPolyline", "")
    route_duration_s = parse_duration_seconds(
        route.get("staticDuration") or route.get("duration")
    )
    route_distance_m = float(route.get("distanceMeters", 0))

    data = await _get_places_client().search_chargers_along_route(
        encoded_polyline=encoded,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
        min_power_kw=min_power_kw,
        connector_types=_google_connector_filter(connector_type),
        max_results=20,
    )
    # Places routing summaries (origin -> charger -> polyline end) skip the
    # waypoints, so a detour against the via-waypoints route would be wrong
    chargers = format_google_chargers(
        data.get("places", []),
        routing_summaries=data.get("routingSummaries", []),
        route_duration_s=None if waypoints else route_duration_s,
        route_distance_m=None if waypoints else route_distance_m,
    )
    chargers = [c for c in chargers if charger_matches(c, min_power_kw, connector_type)]
    chargers = [restrict_to_matching(c, min_power_kw, connector_type) for c in chargers]
    chargers.sort(
        key=lambda c: (
            c.detour_duration_min if c.detour_duration_min is not None else float("inf"),
            -(c.max_charge_rate_kw or 0),
        )
    )
    return format_chargers(chargers[: max(1, min(max_results, 20))])


@charging_mcp.tool(
    title="Search Chargers Nearby",
    description=(
        "Find EV charging stations within a radius of a coordinate, nearest first. "
        "Returns connectors with power (kW), live availability where reported, "
        "rating, amenities, and opening hours. Use this for 'chargers near me', "
        "chargers near the destination or hotel, or to find alternatives around a "
        "planned stop."
    ),
    tags={"charging", "ev", "nearby", "availability", "google"},
    annotations={
        "title": "Search Chargers Nearby",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.search_chargers_nearby", handler_type="tool")
async def search_chargers_nearby(
    latitude: float,
    longitude: float,
    radius_meters: float = 10000,
    min_power_kw: float = 0,
    connector_type: str = "",
    max_results: int = 10,
) -> ChargerSearchResponse:
    """Search for EV chargers near a location.

    Args:
        latitude: Center point latitude (e.g. 12.9716 for Bengaluru).
        longitude: Center point longitude (e.g. 77.5946 for Bengaluru).
        radius_meters: Search radius in meters (default 10000, max 50000).
        min_power_kw: Minimum charger power in kW (e.g. 50 for DC fast charging; 0 = any).
        connector_type: Optional connector filter (e.g. "CCS2", "Type 2", "NACS").
        max_results: Maximum number of chargers to return (1-20, default 10).
    """
    places = await _get_places_client().search_chargers_nearby(
        latitude=latitude,
        longitude=longitude,
        radius=radius_meters,
        max_results=20,
    )
    chargers = [format_google_charger(p) for p in places]
    chargers = [c for c in chargers if charger_matches(c, min_power_kw, connector_type)]
    chargers = [restrict_to_matching(c, min_power_kw, connector_type) for c in chargers]
    chargers.sort(key=lambda c: _distance_from(latitude, longitude, c))
    return format_chargers(chargers[: max(1, min(max_results, 20))])


@charging_mcp.tool(
    title="Get Charger Details",
    description=(
        "Retrieve up-to-date details for a specific EV charging station using its "
        "Google Place ID: connectors, power, live availability, rating, amenities, "
        "opening hours, and Google Maps link. Use this to re-check availability of "
        "a chosen charging stop before finalizing the plan. Not for Open Charge Map "
        "('ocm:') ids."
    ),
    tags={"charging", "ev", "details", "availability", "google"},
    annotations={
        "title": "Get Charger Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.get_charger_details", handler_type="tool")
async def get_charger_details(place_id: str) -> Charger:
    """Get detailed information about a specific charging station.

    Args:
        place_id: The Google Place ID (obtained from charger search results).
    """
    if place_id.startswith("ocm:"):
        raise ValueError(
            "Open Charge Map stations have no live availability or Google details; "
            "use the data from the Open Charge Map search result."
        )
    place = await _get_places_client().get_charger_details(place_id=place_id)
    return format_google_charger(place)


@charging_mcp.tool(
    title="Search Chargers (Open Charge Map)",
    description=(
        "Find EV charging stations near a coordinate in the community Open Charge "
        "Map registry, nearest first. Returns connectors and power, but NO live "
        "availability. Use this only as a fallback when the Google charger searches "
        "return nothing suitable for an area (coverage gaps, rural highways)."
    ),
    tags={"charging", "ev", "nearby", "fallback", "openchargemap"},
    annotations={
        "title": "Search Chargers (Open Charge Map)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.search_chargers_open_charge_map", handler_type="tool")
async def search_chargers_open_charge_map(
    latitude: float,
    longitude: float,
    radius_km: float = 15,
    min_power_kw: float = 0,
    connector_type: str = "",
    max_results: int = 10,
) -> ChargerSearchResponse:
    """Search for EV chargers in Open Charge Map near a location.

    Args:
        latitude: Center point latitude (e.g. 15.8497 for Belagavi).
        longitude: Center point longitude (e.g. 74.4977 for Belagavi).
        radius_km: Search radius in kilometres (default 15).
        min_power_kw: Minimum charger power in kW (e.g. 50 for DC fast charging; 0 = any).
        connector_type: Optional connector filter (e.g. "CCS2", "CHAdeMO", "Type 2").
        max_results: Maximum number of chargers to return (1-50, default 10).
    """
    max_results = max(1, min(max_results, 50))
    pois = await _get_ocm_client().search_poi(
        latitude=latitude,
        longitude=longitude,
        distance_km=radius_km,
        # Over-fetch so client-side power / connector filters still fill the page
        max_results=max_results * 3 if (min_power_kw or connector_type) else max_results,
    )
    chargers = [format_ocm_charger(p) for p in pois]
    chargers = [c for c in chargers if charger_matches(c, min_power_kw, connector_type)]
    chargers = [restrict_to_matching(c, min_power_kw, connector_type) for c in chargers]
    chargers.sort(key=lambda c: _distance_from(latitude, longitude, c))
    return format_chargers(chargers[:max_results])
