"""
Google Geocoding API HTTP client.

Wraps the core endpoint:
- GET /maps/api/geocode/json   (forward geocoding)
"""

import httpx
from loguru import logger

BASE_URL = "https://maps.googleapis.com/maps/api"

# Statuses that are not errors (ZERO_RESULTS simply returns an empty list)
_OK_STATUSES = {"OK", "ZERO_RESULTS"}


class GoogleGeocodingClient:
    """Async client for the Google Geocoding API."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is not set.")
        self._api_key = api_key
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=10.0)

    async def geocode(
        self,
        address: str,
        region: str | None = None,
    ) -> list[dict]:
        """Forward geocode — convert an address or place name to coordinates.

        Args:
            address: Address or place name to geocode.
            region: Optional ccTLD region bias (e.g. "in", "us").
        """
        params: dict = {"address": address, "key": self._api_key}
        if region:
            params["region"] = region

        logger.debug(f"Geocode: address={address!r}, region={region}")
        response = await self._client.get("/geocode/json", params=params)
        response.raise_for_status()
        data = response.json()

        # The Geocoding API reports errors in the body with HTTP 200
        status = data.get("status", "UNKNOWN_ERROR")
        if status not in _OK_STATUSES:
            raise RuntimeError(
                f"Geocoding API error: {status} — {data.get('error_message', 'no details')}"
            )
        return data.get("results", [])
