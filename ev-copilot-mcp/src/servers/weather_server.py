"""
Weather MCP Server.

Self-contained FastMCP instance with Google Weather API tools
(current conditions, daily and hourly forecasts, public alerts).
Temperature affects EV range, and severe weather affects route safety.
Mounted into the registry via tool_registry.py.
"""

from fastmcp import FastMCP

from src.clients.google_weather_client import GoogleWeatherClient
from src.config import settings
from src.infrastructure.trace_decorator import traced
from src.schemas.weather import (
    CurrentWeatherResponse,
    ForecastResponse,
    HourlyForecastResponse,
    WeatherAlertsResponse,
)
from src.utils.weather_formatters import (
    format_current_weather,
    format_forecast,
    format_hourly_forecast,
    format_weather_alerts,
)

weather_mcp = FastMCP("weather")

# ---------------------------------------------------------------------------
# Lazy client singleton
# ---------------------------------------------------------------------------

_client: GoogleWeatherClient | None = None


def _get_client() -> GoogleWeatherClient:
    global _client
    if _client is None:
        _client = GoogleWeatherClient(api_key=settings.GOOGLE_MAPS_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@weather_mcp.tool(
    title="Get Current Weather",
    description=(
        "Get real-time weather conditions for any location on Earth. "
        "Returns temperature, humidity, wind, precipitation, UV index, "
        "cloud cover, visibility, and atmospheric pressure. "
        "Use this when the user asks about current weather at the origin, "
        "a charging stop, or the destination."
    ),
    tags={"weather", "current", "conditions", "google"},
    annotations={
        "title": "Get Current Weather",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.get_current_weather", handler_type="tool")
async def get_current_weather(
    latitude: float,
    longitude: float,
) -> CurrentWeatherResponse:
    """Get current weather conditions for a location.

    Args:
        latitude: Location latitude (e.g. 18.5204 for Pune).
        longitude: Location longitude (e.g. 73.8567 for Pune).
    """
    client = _get_client()
    data = await client.get_current_conditions(latitude=latitude, longitude=longitude)
    return format_current_weather(data)


@weather_mcp.tool(
    title="Get Weather Forecast",
    description=(
        "Get a multi-day weather forecast for any location on Earth. "
        "Returns daily high/low temperatures, daytime and nighttime conditions, "
        "precipitation probability, wind, UV index, and sunrise/sunset times. "
        "Use this when the user plans a road trip days ahead and needs to know "
        "the expected weather along the way."
    ),
    tags={"weather", "forecast", "planning", "google"},
    annotations={
        "title": "Get Weather Forecast",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.get_weather_forecast", handler_type="tool")
async def get_weather_forecast(
    latitude: float,
    longitude: float,
    forecast_days: int = 5,
) -> ForecastResponse:
    """Get daily weather forecast for a location (up to 10 days).

    Args:
        latitude: Location latitude (e.g. 18.5204 for Pune).
        longitude: Location longitude (e.g. 73.8567 for Pune).
        forecast_days: Number of forecast days (1-10, default 5).
    """
    client = _get_client()
    data = await client.get_daily_forecast(
        latitude=latitude,
        longitude=longitude,
        days=min(forecast_days, 10),
    )
    return format_forecast(data)


@weather_mcp.tool(
    title="Get Hourly Forecast",
    description=(
        "Get an hour-by-hour weather forecast (up to 240 hours) for any location. "
        "Returns temperature, conditions, precipitation probability, wind speed, "
        "and day/night for each hour. Use this for the hours the user will be "
        "driving — the temperature is an input to the battery simulation (cold "
        "and extreme heat increase consumption) and rain or strong wind affects "
        "range and safety."
    ),
    tags={"weather", "forecast", "hourly", "range", "google"},
    annotations={
        "title": "Get Hourly Forecast",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.get_hourly_forecast", handler_type="tool")
async def get_hourly_forecast(
    latitude: float,
    longitude: float,
    hours: int = 24,
) -> HourlyForecastResponse:
    """Get hourly weather forecast for a location (up to 240 hours).

    Args:
        latitude: Location latitude (e.g. 15.8497 for Belagavi).
        longitude: Location longitude (e.g. 74.4977 for Belagavi).
        hours: Number of hours from now to return (1-240, default 24).
    """
    client = _get_client()
    data = await client.get_hourly_forecast(
        latitude=latitude,
        longitude=longitude,
        hours=min(max(hours, 1), 240),
    )
    return format_hourly_forecast(data)


@weather_mcp.tool(
    title="Get Weather Alerts",
    description=(
        "Get active public weather alerts (warnings, watches, advisories) issued "
        "by official authorities for a location — e.g. floods, storms, heat waves, "
        "snow or fog. Returns title, severity, urgency, certainty, affected area, "
        "validity window and issuing authority. Use this for the origin, the "
        "destination and long stretches of the route before confirming a trip."
    ),
    tags={"weather", "alerts", "safety", "google"},
    annotations={
        "title": "Get Weather Alerts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.get_weather_alerts", handler_type="tool")
async def get_weather_alerts(
    latitude: float,
    longitude: float,
) -> WeatherAlertsResponse:
    """Get active public weather alerts for a location.

    Args:
        latitude: Location latitude (e.g. 15.3173 for Hubballi).
        longitude: Location longitude (e.g. 75.7139 for Hubballi).
    """
    client = _get_client()
    data = await client.get_public_alerts(latitude=latitude, longitude=longitude)
    return format_weather_alerts(data)
