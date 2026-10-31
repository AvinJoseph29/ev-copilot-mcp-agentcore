"""Pydantic response models for Google Weather tools."""

from pydantic import BaseModel, Field


class Wind(BaseModel):
    speed_value: float | None = Field(None, description="Wind speed value.")
    speed_unit: str | None = Field(None, description="Wind speed unit (e.g. km/h).")
    direction_cardinal: str | None = Field(None, description="Wind direction as cardinal (e.g. NW).")
    direction_degrees: float | None = Field(None, description="Wind direction in degrees.")
    gust_value: float | None = Field(None, description="Wind gust speed value.")


class Precipitation(BaseModel):
    type: str | None = Field(None, description="Precipitation type (e.g. RAIN, SNOW, NONE).")
    probability_percent: float | None = Field(None, description="Probability of precipitation (0-100).")


class Visibility(BaseModel):
    value: float | None = Field(None, description="Visibility distance value.")
    unit: str | None = Field(None, description="Visibility unit (e.g. km).")


class CurrentWeatherResponse(BaseModel):
    condition: str | None = Field(None, description="Weather condition description.")
    condition_type: str | None = Field(None, description="Weather condition type code.")
    temperature_c: float | None = Field(None, description="Current temperature in Celsius.")
    feels_like_c: float | None = Field(None, description="Feels-like temperature in Celsius.")
    humidity_percent: float | None = Field(None, description="Relative humidity percentage.")
    dew_point_c: float | None = Field(None, description="Dew point temperature in Celsius.")
    cloud_cover_percent: float | None = Field(None, description="Cloud cover percentage.")
    uv_index: float | None = Field(None, description="UV index value.")
    wind: Wind | None = Field(None, description="Wind conditions.")
    precipitation: Precipitation | None = Field(None, description="Precipitation details.")
    visibility: Visibility | None = Field(None, description="Visibility conditions.")
    pressure_mbar: float | None = Field(None, description="Atmospheric pressure in millibars.")
    is_daytime: bool | None = Field(None, description="Whether it is currently daytime.")
    timezone: str | None = Field(None, description="Timezone identifier (e.g. Europe/Paris).")
    observation_time: str | None = Field(None, description="Timestamp of the observation.")


class ForecastPrecipitation(BaseModel):
    probability_percent: float | None = Field(None, description="Probability of precipitation (0-100).")
    amount: float | None = Field(None, description="Precipitation quantity.")
    unit: str | None = Field(None, description="Precipitation unit (e.g. mm).")


class ForecastDay(BaseModel):
    date: str = Field(description="Forecast date (YYYY-MM-DD).")
    max_temperature_c: float | None = Field(None, description="Maximum temperature in Celsius.")
    min_temperature_c: float | None = Field(None, description="Minimum temperature in Celsius.")
    daytime_condition: str | None = Field(None, description="Daytime weather condition description.")
    nighttime_condition: str | None = Field(None, description="Nighttime weather condition description.")
    humidity_percent: float | None = Field(None, description="Relative humidity percentage.")
    uv_index: float | None = Field(None, description="UV index value.")
    precipitation: ForecastPrecipitation | None = Field(None, description="Precipitation details.")
    wind: Wind | None = Field(None, description="Wind conditions.")
    sunrise: str | None = Field(None, description="Sunrise time.")
    sunset: str | None = Field(None, description="Sunset time.")


class ForecastResponse(BaseModel):
    timezone: str | None = Field(None, description="Timezone identifier.")
    days: list[ForecastDay] = Field(description="Daily forecast entries.")


# --- Hourly forecast ---


class ForecastHour(BaseModel):
    time: str | None = Field(None, description="Start of the forecast hour (RFC 3339, UTC).")
    temperature_c: float | None = Field(None, description="Temperature in Celsius.")
    condition: str | None = Field(None, description="Weather condition description.")
    precipitation_probability_percent: float | None = Field(
        None, description="Probability of precipitation (0-100)."
    )
    wind_speed_kmh: float | None = Field(None, description="Wind speed in km/h.")
    is_daytime: bool | None = Field(None, description="Whether the hour is during daytime.")


class HourlyForecastResponse(BaseModel):
    timezone: str | None = Field(None, description="Timezone identifier.")
    hours: list[ForecastHour] = Field(description="Hourly forecast entries.")


# --- Public weather alerts ---


class WeatherAlert(BaseModel):
    title: str | None = Field(None, description="Alert title (e.g. 'Flash Flood Warning').")
    event_type: str | None = Field(None, description="Alert event type code (e.g. FLASH_FLOOD).")
    severity: str | None = Field(None, description="Severity: EXTREME, SEVERE, MODERATE, MINOR or UNKNOWN.")
    urgency: str | None = Field(None, description="Urgency: IMMEDIATE, EXPECTED, FUTURE, PAST or UNKNOWN.")
    certainty: str | None = Field(None, description="Certainty: OBSERVED, VERY_LIKELY, LIKELY, POSSIBLE, UNLIKELY or UNKNOWN.")
    description: str | None = Field(None, description="Full alert description text.")
    area: str | None = Field(None, description="Affected area names.")
    start_time: str | None = Field(None, description="Alert start time (RFC 3339).")
    expiration_time: str | None = Field(None, description="Alert expiration time (RFC 3339).")
    source: str | None = Field(
        None, description="Issuing authority (attribution required, e.g. 'National Weather Service')."
    )


class WeatherAlertsResponse(BaseModel):
    count: int = Field(description="Number of active alerts.")
    alerts: list[WeatherAlert] = Field(description="Active public weather alerts for the location.")
