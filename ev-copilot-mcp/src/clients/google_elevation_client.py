"""
Google Elevation API HTTP client.

Wraps the core endpoint:
- GET /maps/api/elevation/json?path=enc:<polyline>&samples=N   (elevation along a path)
"""

import httpx
from loguru import logger

BASE_URL = "https://maps.googleapis.com/maps/api"

MAX_SAMPLES = 512


class GoogleElevationClient:
    """Async client for the Google Elevation API."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is not set.")
        self._api_key = api_key
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=10.0)

    async def get_elevation_along_path(
        self,
        encoded_path: str,
        samples: int = 64,
    ) -> list[dict]:
        """Sample elevations evenly along an encoded polyline path.

        Args:
            encoded_path: Google encoded polyline of the path (keep it short —
                the whole request URL must stay under 16 384 characters).
            samples: Number of equally spaced samples (2-512).

        Returns a list of ``{"elevation", "location": {"lat", "lng"}, "resolution"}``.
        """
        samples = max(2, min(samples, MAX_SAMPLES))
        params = {
            "path": f"enc:{encoded_path}",
            "samples": samples,
            "key": self._api_key,
        }

        logger.debug(f"Elevation along path: polyline_len={len(encoded_path)}, samples={samples}")
        response = await self._client.get("/elevation/json", params=params)
        response.raise_for_status()
        data = response.json()

        # The Elevation API reports errors in the body with HTTP 200
        status = data.get("status", "UNKNOWN_ERROR")
        if status != "OK":
            raise RuntimeError(
                f"Elevation API error: {status} — {data.get('error_message', 'no details')}"
            )
        return data.get("results", [])
