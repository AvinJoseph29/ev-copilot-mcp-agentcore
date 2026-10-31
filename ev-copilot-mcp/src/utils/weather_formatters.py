"""Formatting helpers for Google Weather API responses."""

from src.schemas.weather import (
    CurrentWeatherResponse,
    ForecastDay,
    ForecastHour,
    ForecastPrecipitation,
    ForecastResponse,
    HourlyForecastResponse,
    Precipitation,
    Visibility,
    WeatherAlert,
    WeatherAlertsResponse,
    Wind,
)

# Google Weather speed units -> factor to km/h
_SPEED_TO_KMH: dict[str, float] = {
    "KILOMETERS_PER_HOUR": 1.0,
    "MILES_PER_HOUR": 1.609344,
}


def _extract_temp(temp_obj: dict) -> float | None:
    """Extract temperature value from a Google Weather temperature object."""
    if not temp_obj:
        return None
    return temp_obj.get("degrees")


def _extract_wind(wind_obj: dict) -> Wind | None:
    """Extract wind data from a Google Weather wind object."""
    if not wind_obj:
        return None
    speed = wind_obj.get("speed", {})
    direction = wind_obj.get("direction", {})
    gust = wind_obj.get("gust", {})

    return Wind(
        speed_value=speed.get("value"),
        speed_unit=speed.get("unit"),
        direction_cardinal=direction.get("cardinal"),
        direction_degrees=direction.get("degrees"),
        gust_value=gust.get("value"),
    )


def format_current_weather(data: dict) -> CurrentWeatherResponse:
    """Format Google Weather currentConditions into a CurrentWeatherResponse model."""
    condition = data.get("weatherCondition", {})
    visibility = data.get("visibility", {})
    pressure = data.get("airPressure", {})
    precip = data.get("precipitation", {})

    return CurrentWeatherResponse(
        condition=condition.get("description", {}).get("text"),
        condition_type=condition.get("type"),
        temperature_c=_extract_temp(data.get("temperature", {})),
        feels_like_c=_extract_temp(data.get("feelsLikeTemperature", {})),
        humidity_percent=data.get("relativeHumidity"),
        dew_point_c=_extract_temp(data.get("dewPoint", {})),
        cloud_cover_percent=data.get("cloudCover"),
        uv_index=data.get("uvIndex"),
        wind=_extract_wind(data.get("wind", {})),
        precipitation=Precipitation(
            type=precip.get("probability", {}).get("type"),
            probability_percent=precip.get("probability", {}).get("percent"),
        ),
        visibility=Visibility(
            value=visibility.get("distance"),
            unit=visibility.get("unit"),
        ),
        pressure_mbar=pressure.get("meanSeaLevelMillibars"),
        is_daytime=data.get("isDaytime"),
        timezone=data.get("timeZone", {}).get("id"),
        observation_time=data.get("currentTime"),
    )


def format_forecast(data: dict) -> ForecastResponse:
    """Format Google Weather daily forecast into a ForecastResponse model."""
    forecast_days = data.get("forecastDays", [])

    days = []
    for day in forecast_days:
        display_date = day.get("displayDate", {})
        daytime = day.get("daytimeForecast", {})
        nighttime = day.get("nighttimeForecast", {})
        # Humidity, UV, precipitation and wind are per day part (daytime used)
        precip = daytime.get("precipitation", {})
        precip_qty = precip.get("qpf", {})
        sun_events = day.get("sunEvents", {})

        days.append(ForecastDay(
            date=(
                f"{display_date.get('year', '')}-"
                f"{display_date.get('month', 0):02d}-"
                f"{display_date.get('day', 0):02d}"
            ),
            max_temperature_c=_extract_temp(day.get("maxTemperature", {})),
            min_temperature_c=_extract_temp(day.get("minTemperature", {})),
            daytime_condition=(
                daytime.get("weatherCondition", {})
                .get("description", {})
                .get("text")
            ),
            nighttime_condition=(
                nighttime.get("weatherCondition", {})
                .get("description", {})
                .get("text")
            ),
            humidity_percent=daytime.get("relativeHumidity"),
            uv_index=daytime.get("uvIndex"),
            precipitation=ForecastPrecipitation(
                probability_percent=precip.get("probability", {}).get("percent"),
                amount=precip_qty.get("quantity"),
                unit=precip_qty.get("unit"),
            ),
            wind=_extract_wind(daytime.get("wind", {})),
            sunrise=sun_events.get("sunriseTime"),
            sunset=sun_events.get("sunsetTime"),
        ))

    return ForecastResponse(
        timezone=data.get("timeZone", {}).get("id"),
        days=days,
    )


def _extract_wind_speed_kmh(wind_obj: dict) -> float | None:
    """Extract wind speed in km/h from a Google Weather wind object."""
    speed = (wind_obj or {}).get("speed", {})
    value = speed.get("value")
    if value is None:
        return None
    factor = _SPEED_TO_KMH.get(speed.get("unit", "KILOMETERS_PER_HOUR"), 1.0)
    return round(float(value) * factor, 1)


def format_hourly_forecast(data: dict) -> HourlyForecastResponse:
    """Format Google Weather hourly forecast into an HourlyForecastResponse model."""
    hours = []
    for hour in data.get("forecastHours", []):
        hours.append(ForecastHour(
            time=hour.get("interval", {}).get("startTime"),
            temperature_c=_extract_temp(hour.get("temperature", {})),
            condition=(
                hour.get("weatherCondition", {})
                .get("description", {})
                .get("text")
            ),
            precipitation_probability_percent=(
                hour.get("precipitation", {})
                .get("probability", {})
                .get("percent")
            ),
            wind_speed_kmh=_extract_wind_speed_kmh(hour.get("wind", {})),
            is_daytime=hour.get("isDaytime"),
        ))

    return HourlyForecastResponse(
        timezone=(data.get("timeZone") or {}).get("id"),
        hours=hours,
    )


def format_weather_alerts(data: dict) -> WeatherAlertsResponse:
    """Format Google Weather public alerts into a WeatherAlertsResponse model.

    When no alert is active the API returns only ``regionCode``.
    """
    alerts = []
    for alert in data.get("weatherAlerts", []):
        alerts.append(WeatherAlert(
            title=alert.get("alertTitle", {}).get("text"),
            event_type=alert.get("eventType"),
            severity=alert.get("severity"),
            urgency=alert.get("urgency"),
            certainty=alert.get("certainty"),
            description=alert.get("description"),
            area=alert.get("areaName"),
            start_time=alert.get("startTime"),
            expiration_time=alert.get("expirationTime"),
            source=alert.get("dataSource", {}).get("name"),
        ))

    return WeatherAlertsResponse(
        count=len(alerts),
        alerts=alerts,
    )
