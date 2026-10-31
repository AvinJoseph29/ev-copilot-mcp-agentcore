"""Formatting helpers for Google Places API responses."""

from src.schemas.places import Location, Place, PlaceSearchResponse


def format_place(place: dict) -> Place:
    """Format a single place dict into a Place model."""
    location = place.get("location", {})
    hours_obj = place.get("regularOpeningHours", {})

    return Place(
        name=place.get("displayName", {}).get("text", "Unknown"),
        address=place.get("formattedAddress"),
        location=Location(
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
        ),
        rating=place.get("rating"),
        review_count=place.get("userRatingCount"),
        phone=place.get("nationalPhoneNumber"),
        website=place.get("websiteUri"),
        price_level=place.get("priceLevel"),
        types=place.get("types", []),
        summary=place.get("editorialSummary", {}).get("text"),
        opening_hours=hours_obj.get("weekdayDescriptions", []),
        place_id=place.get("id"),
    )


def format_places(places: list[dict]) -> PlaceSearchResponse:
    """Format a list of places into a PlaceSearchResponse model."""
    return PlaceSearchResponse(
        count=len(places),
        places=[format_place(p) for p in places],
    )
