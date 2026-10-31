"""
Google Routes API (v2) HTTP client.

Wraps the core endpoint:
- POST /directions/v2:computeRoutes   (electric-vehicle, traffic-aware routing)

Only the response fields actually used are requested via X-Goog-FieldMask.
"""

from datetime import UTC, datetime

import httpx
from loguru import logger

BASE_URL = "https://routes.googleapis.com"

_ROUTE_FIELDS = [
    "routes.distanceMeters",
    "routes.duration",
    "routes.staticDuration",
    "routes.polyline.encodedPolyline",
    "routes.legs.distanceMeters",
    "routes.legs.duration",
    "routes.legs.polyline.encodedPolyline",
    "routes.legs.startLocation",
    "routes.legs.endLocation",
    "routes.warnings",
    "routes.travelAdvisory.tollInfo",
]

ROUTE_FIELD_MASK = ",".join(_ROUTE_FIELDS)


def _waypoint(latitude: float, longitude: float) -> dict:
    """Build a Routes API Waypoint from coordinates."""
    return {"location": {"latLng": {"latitude": latitude, "longitude": longitude}}}


def _departure_time_problem(departure_time: str) -> str | None:
    """Why a departure time cannot be sent to the Routes API (None if valid).

    The API rejects past timestamps, so these are dropped instead of
    failing the whole request.
    """
    try:
        parsed = datetime.fromisoformat(departure_time)  # 3.11+ accepts a trailing Z
    except ValueError:
        return "not a valid RFC 3339 timestamp"
    if parsed.tzinfo is None:
        return "missing UTC offset"
    if parsed <= datetime.now(UTC):
        return "in the past"
    return None


class GoogleRoutesClient:
    """Async client for the Google Routes API."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is not set.")
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "X-Goog-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )

    async def compute_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        intermediates: list[tuple[float, float]] | None = None,
        departure_time: str = "",
        avoid_tolls: bool = False,
        avoid_highways: bool = False,
    ) -> dict:
        """Compute a driving route for an electric vehicle.

        Args:
            origin: (latitude, longitude) of the start.
            destination: (latitude, longitude) of the end.
            intermediates: Optional (latitude, longitude) stops; each one
                splits the route into an additional leg.
            departure_time: Optional RFC 3339 timestamp (must be in the
                future, with a UTC offset; otherwise it is dropped and a
                note is added to the route warnings). Empty means "now".
            avoid_tolls: Avoid toll roads where reasonable.
            avoid_highways: Avoid highways where reasonable.

        Returns the first route of the response (raw dict).
        """
        body: dict = {
            "origin": _waypoint(*origin),
            "destination": _waypoint(*destination),
            "intermediates": [_waypoint(*p) for p in (intermediates or [])],
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "polylineQuality": "OVERVIEW",
            "extraComputations": ["TOLLS"],
            "routeModifiers": {
                "vehicleInfo": {"emissionType": "ELECTRIC"},
                "avoidTolls": avoid_tolls,
                "avoidHighways": avoid_highways,
            },
        }
        departure_note = None
        if departure_time:
            problem = _departure_time_problem(departure_time)
            if problem:
                departure_note = (
                    f"departure_time {departure_time!r} ignored ({problem}); "
                    f"route computed for departing now."
                )
                logger.warning(departure_note)
            else:
                body["departureTime"] = departure_time

        logger.debug(
            f"Compute route: origin={origin}, destination={destination}, "
            f"intermediates={len(body['intermediates'])}"
        )
        response = await self._client.post(
            "/directions/v2:computeRoutes",
            json=body,
            headers={"X-Goog-FieldMask": ROUTE_FIELD_MASK},
        )
        response.raise_for_status()
        routes = response.json().get("routes", [])
        if not routes:
            raise ValueError("No drivable route found between the given points.")
        route = routes[0]
        if departure_note:
            route["warnings"] = [*route.get("warnings", []), departure_note]
        return route
