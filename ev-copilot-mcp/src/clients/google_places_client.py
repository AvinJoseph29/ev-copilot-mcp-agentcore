"""
Google Places API (New) HTTP client.

Wraps the core endpoints:
- POST /v1/places:searchText    (amenities; EV chargers along a route)
- POST /v1/places:searchNearby  (amenities; EV chargers near a point)
- GET  /v1/places/{place_id}    (place / charger details)

EV charging stations use the ``electric_vehicle_charging_station`` place type
and the ``evChargeOptions`` field (connector aggregations with live
availability where the network provides it).
"""

import httpx
from loguru import logger

BASE_URL = "https://places.googleapis.com/v1"

EV_CHARGING_STATION_TYPE = "electric_vehicle_charging_station"

_SEARCH_FIELDS = [
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.rating",
    "places.userRatingCount",
    "places.types",
    "places.regularOpeningHours",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.priceLevel",
    "places.editorialSummary",
]

SEARCH_FIELD_MASK = ",".join(_SEARCH_FIELDS)

_DETAIL_FIELDS = [
    "id",
    "displayName",
    "formattedAddress",
    "location",
    "rating",
    "userRatingCount",
    "types",
    "regularOpeningHours",
    "websiteUri",
    "nationalPhoneNumber",
    "priceLevel",
    "editorialSummary",
]

DETAIL_FIELD_MASK = ",".join(_DETAIL_FIELDS)

_CHARGER_FIELDS = [
    "id",
    "displayName",
    "formattedAddress",
    "location",
    "rating",
    "userRatingCount",
    "regularOpeningHours",
    "evChargeOptions",
    "evChargeAmenitySummary",
    "googleMapsUri",
]

CHARGER_SEARCH_FIELD_MASK = ",".join(f"places.{f}" for f in _CHARGER_FIELDS)

CHARGER_ALONG_ROUTE_FIELD_MASK = ",".join(
    [f"places.{f}" for f in _CHARGER_FIELDS] + ["routingSummaries"]
)

CHARGER_DETAIL_FIELD_MASK = ",".join(_CHARGER_FIELDS)


class GooglePlacesClient:
    """Async client for the Google Places API (New)."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is not set.")
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "X-Goog-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )

    # ------------------------------------------------------------------
    # General places (amenities)
    # ------------------------------------------------------------------

    async def search_text(
        self,
        query: str,
        location_bias: dict | None = None,
        max_results: int = 5,
    ) -> list[dict]:
        """Text Search — find places matching a free-text query."""
        body: dict = {
            "textQuery": query,
            "pageSize": min(max_results, 20),
        }
        if location_bias:
            body["locationBias"] = {
                "circle": {
                    "center": {
                        "latitude": location_bias["latitude"],
                        "longitude": location_bias["longitude"],
                    },
                    "radius": location_bias.get("radius", 5000.0),
                }
            }

        logger.debug(f"Text search: query={query!r}, max_results={max_results}")
        response = await self._client.post(
            "/places:searchText",
            json=body,
            headers={"X-Goog-FieldMask": SEARCH_FIELD_MASK},
        )
        response.raise_for_status()
        return response.json().get("places", [])

    async def search_nearby(
        self,
        latitude: float,
        longitude: float,
        radius: float,
        place_type: str | None = None,
        max_results: int = 5,
    ) -> list[dict]:
        """Nearby Search — find places within a radius of a point."""
        body: dict = {
            "maxResultCount": min(max_results, 20),
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude,
                    },
                    "radius": radius,
                }
            },
        }
        if place_type:
            body["includedTypes"] = [place_type]

        logger.debug(
            f"Nearby search: lat={latitude}, lng={longitude}, "
            f"radius={radius}, type={place_type}"
        )
        response = await self._client.post(
            "/places:searchNearby",
            json=body,
            headers={"X-Goog-FieldMask": SEARCH_FIELD_MASK},
        )
        response.raise_for_status()
        return response.json().get("places", [])

    async def get_place_details(self, place_id: str) -> dict:
        """Place Details — get detailed info about a specific place."""
        logger.debug(f"Place details: place_id={place_id!r}")
        response = await self._client.get(
            f"/places/{place_id}",
            headers={"X-Goog-FieldMask": DETAIL_FIELD_MASK},
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # EV charging stations
    # ------------------------------------------------------------------

    async def search_chargers_along_route(
        self,
        encoded_polyline: str,
        origin_latitude: float,
        origin_longitude: float,
        min_power_kw: float = 0,
        connector_types: list[str] | None = None,
        max_results: int = 10,
    ) -> dict:
        """Search Along Route — EV chargers along an encoded route polyline.

        ``routingParameters.origin`` makes Google return ``routingSummaries``
        (origin -> charger -> destination legs), aligned by index with
        ``places``, which are used to compute the detour.

        Returns the raw response dict with ``places`` and ``routingSummaries``.
        """
        body: dict = {
            "textQuery": "EV charging station",
            "includedType": EV_CHARGING_STATION_TYPE,
            # Without strict filtering includedType is only a preference
            "strictTypeFiltering": True,
            "pageSize": min(max_results, 20),
            "searchAlongRouteParameters": {
                "polyline": {"encodedPolyline": encoded_polyline},
            },
            "routingParameters": {
                "origin": {
                    "latitude": origin_latitude,
                    "longitude": origin_longitude,
                },
                "travelMode": "DRIVE",
            },
        }
        ev_options: dict = {}
        if min_power_kw > 0:
            ev_options["minimumChargingRateKw"] = min_power_kw
        if connector_types:
            ev_options["connectorTypes"] = connector_types
        if ev_options:
            body["evOptions"] = ev_options

        logger.debug(
            f"Chargers along route: polyline_len={len(encoded_polyline)}, "
            f"min_power_kw={min_power_kw}, connectors={connector_types}"
        )
        response = await self._client.post(
            "/places:searchText",
            json=body,
            headers={"X-Goog-FieldMask": CHARGER_ALONG_ROUTE_FIELD_MASK},
        )
        response.raise_for_status()
        return response.json()

    async def search_chargers_nearby(
        self,
        latitude: float,
        longitude: float,
        radius: float,
        max_results: int = 10,
    ) -> list[dict]:
        """Nearby Search — EV chargers within a radius, ranked by distance.

        Nearby Search does not support ``evOptions``; power / connector
        filters are applied by the caller on ``evChargeOptions``.
        """
        body: dict = {
            "includedTypes": [EV_CHARGING_STATION_TYPE],
            "maxResultCount": min(max_results, 20),
            "rankPreference": "DISTANCE",
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude,
                    },
                    "radius": min(radius, 50000.0),
                }
            },
        }

        logger.debug(f"Chargers nearby: lat={latitude}, lng={longitude}, radius={radius}")
        response = await self._client.post(
            "/places:searchNearby",
            json=body,
            headers={"X-Goog-FieldMask": CHARGER_SEARCH_FIELD_MASK},
        )
        response.raise_for_status()
        return response.json().get("places", [])

    async def get_charger_details(self, place_id: str) -> dict:
        """Place Details — EV charger details incl. live connector availability."""
        logger.debug(f"Charger details: place_id={place_id!r}")
        response = await self._client.get(
            f"/places/{place_id}",
            headers={"X-Goog-FieldMask": CHARGER_DETAIL_FIELD_MASK},
        )
        response.raise_for_status()
        return response.json()
