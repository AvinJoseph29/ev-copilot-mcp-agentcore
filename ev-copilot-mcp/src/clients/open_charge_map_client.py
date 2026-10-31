"""
Open Charge Map API (v3) HTTP client.

Wraps the core endpoint:
- GET /v3/poi   (charging locations near a point)

Open Charge Map is a community-maintained registry used as a coverage
fallback when Google Places returns no chargers. It has no live
connector availability.
"""

import httpx
from loguru import logger

BASE_URL = "https://api.openchargemap.io/v3"

MAX_RESULTS = 100


class OpenChargeMapClient:
    """Async client for the Open Charge Map API."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("OPEN_CHARGE_MAP_API_KEY is not set.")
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "X-API-Key": api_key,
                "Accept": "application/json",
                "User-Agent": "evcopilot-mcp",
            },
            timeout=15.0,
        )

    async def search_poi(
        self,
        latitude: float,
        longitude: float,
        distance_km: float = 15,
        max_results: int = 10,
    ) -> list[dict]:
        """Find charging locations within a radius of a point.

        ``compact=false`` keeps nested reference objects (ConnectionType,
        StatusType, OperatorInfo) so connector titles can be filtered;
        ``verbose=false`` drops null fields.

        Args:
            latitude: Center point latitude.
            longitude: Center point longitude.
            distance_km: Search radius in kilometres.
            max_results: Maximum number of POIs to return.
        """
        params: dict = {
            "output": "json",
            "latitude": latitude,
            "longitude": longitude,
            "distance": distance_km,
            "distanceunit": "km",
            "maxresults": min(max_results, MAX_RESULTS),
            "compact": "false",
            "verbose": "false",
            "client": "evcopilot-mcp",
        }

        logger.debug(
            f"OCM POI search: lat={latitude}, lng={longitude}, "
            f"distance_km={distance_km}, max_results={max_results}"
        )
        response = await self._client.get("/poi", params=params)
        response.raise_for_status()
        return response.json()
