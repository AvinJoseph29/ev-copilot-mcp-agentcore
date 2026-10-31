"""
Google Weather API HTTP client.

Wraps the core endpoints:
- GET /v1/currentConditions:lookup   (current weather)
- GET /v1/forecast/days:lookup       (daily forecast)
- GET /v1/forecast/hours:lookup      (hourly forecast, paginated)
- GET /v1/publicAlerts:lookup        (active public weather alerts)

Uses the same Google Maps Platform API key as Places / Routes.
"""

import httpx
from loguru import logger

BASE_URL = "https://weather.googleapis.com/v1"

MAX_FORECAST_HOURS = 240
HOURLY_PAGE_SIZE = 24


class GoogleWeatherClient:
    """Async client for the Google Weather API."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is not set (used for Weather API too).")
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=10.0)

    async def get_current_conditions(
        self, latitude: float, longitude: float
    ) -> dict:
        """Get current weather conditions for a location."""
        logger.debug(f"Current conditions: lat={latitude}, lng={longitude}")
        response = await self._client.get(
            f"{BASE_URL}/currentConditions:lookup",
            params={
                "key": self._api_key,
                "location.latitude": latitude,
                "location.longitude": longitude,
            },
        )
        response.raise_for_status()
        return response.json()

    async def get_daily_forecast(
        self,
        latitude: float,
        longitude: float,
        days: int = 5,
    ) -> dict:
        """Get daily weather forecast for a location (up to 10 days)."""
        logger.debug(f"Daily forecast: lat={latitude}, lng={longitude}, days={days}")
        response = await self._client.get(
            f"{BASE_URL}/forecast/days:lookup",
            params={
                "key": self._api_key,
                "location.latitude": latitude,
                "location.longitude": longitude,
                "days": min(days, 10),
                # Default page size is 5 days; request all days in one page
                "pageSize": min(days, 10),
            },
        )
        response.raise_for_status()
        return response.json()

    async def get_hourly_forecast(
        self,
        latitude: float,
        longitude: float,
        hours: int = 24,
    ) -> dict:
        """Get hourly weather forecast for a location (up to 240 hours).

        The endpoint returns 24 hours per page; pages are followed via
        ``nextPageToken`` and merged into a single ``forecastHours`` list.
        """
        hours = max(1, min(hours, MAX_FORECAST_HOURS))
        logger.debug(f"Hourly forecast: lat={latitude}, lng={longitude}, hours={hours}")

        params: dict = {
            "key": self._api_key,
            "location.latitude": latitude,
            "location.longitude": longitude,
            "hours": hours,
            "pageSize": HOURLY_PAGE_SIZE,
        }
        merged: dict = {"forecastHours": []}

        while True:
            response = await self._client.get(
                f"{BASE_URL}/forecast/hours:lookup",
                params=params,
            )
            response.raise_for_status()
            page = response.json()
            merged["forecastHours"].extend(page.get("forecastHours", []))
            merged.setdefault("timeZone", page.get("timeZone"))

            next_token = page.get("nextPageToken")
            if not next_token or len(merged["forecastHours"]) >= hours:
                break
            params["pageToken"] = next_token

        merged["forecastHours"] = merged["forecastHours"][:hours]
        return merged

    async def get_public_alerts(
        self,
        latitude: float,
        longitude: float,
        language_code: str = "en",
    ) -> dict:
        """Get active public weather alerts (warnings, watches) for a location.

        When no alert is active the response contains only ``regionCode``.
        """
        logger.debug(f"Public alerts: lat={latitude}, lng={longitude}")
        response = await self._client.get(
            f"{BASE_URL}/publicAlerts:lookup",
            params={
                "key": self._api_key,
                "location.latitude": latitude,
                "location.longitude": longitude,
                "languageCode": language_code,
            },
        )
        response.raise_for_status()
        return response.json()
