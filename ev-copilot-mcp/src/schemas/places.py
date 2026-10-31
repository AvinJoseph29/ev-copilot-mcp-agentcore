"""Pydantic response models for Google Places tools."""

from pydantic import BaseModel, Field


class Location(BaseModel):
    latitude: float | None = Field(None, description="Latitude coordinate.")
    longitude: float | None = Field(None, description="Longitude coordinate.")


class Place(BaseModel):
    name: str = Field(description="Display name of the place.")
    address: str | None = Field(None, description="Full formatted address.")
    location: Location = Field(description="Geographic coordinates.")
    rating: float | None = Field(None, description="Average user rating (1-5).")
    review_count: int | None = Field(None, description="Total number of user reviews.")
    phone: str | None = Field(None, description="National phone number.")
    website: str | None = Field(None, description="Website URL.")
    price_level: str | None = Field(None, description="Price level indicator.")
    types: list[str] = Field(default_factory=list, description="Place type categories.")
    summary: str | None = Field(None, description="Editorial summary text.")
    opening_hours: list[str] = Field(default_factory=list, description="Opening hours per weekday.")
    place_id: str | None = Field(None, description="Google Place ID for further lookups.")


class PlaceSearchResponse(BaseModel):
    count: int = Field(description="Number of places returned.")
    places: list[Place] = Field(description="List of matching places.")
