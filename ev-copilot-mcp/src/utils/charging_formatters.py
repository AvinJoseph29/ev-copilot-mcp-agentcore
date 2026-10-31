"""Formatting helpers for EV charger data (Google Places evChargeOptions / Open Charge Map)."""

from src.schemas.charging import Charger, ChargerSearchResponse, ConnectorAggregation
from src.schemas.routing import LatLng
from src.utils.route_formatters import parse_duration_seconds

# ---------------------------------------------------------------------------
# Connector normalization
# ---------------------------------------------------------------------------

NORMALIZED_CONNECTOR_TYPES = [
    "CCS2", "CCS1", "CHADEMO", "TYPE_2", "J1772", "TESLA", "NACS", "GB_T", "OTHER",
]

# Google Places EVConnectorType enum -> normalized type
_GOOGLE_CONNECTOR_TYPES: dict[str, str] = {
    "EV_CONNECTOR_TYPE_CCS_COMBO_2": "CCS2",
    "EV_CONNECTOR_TYPE_CCS_COMBO_1": "CCS1",
    "EV_CONNECTOR_TYPE_CHADEMO": "CHADEMO",
    "EV_CONNECTOR_TYPE_TYPE_2": "TYPE_2",
    "EV_CONNECTOR_TYPE_J1772": "J1772",
    "EV_CONNECTOR_TYPE_TESLA": "TESLA",
    "EV_CONNECTOR_TYPE_NACS": "NACS",
    "EV_CONNECTOR_TYPE_UNSPECIFIED_GB_T": "GB_T",
    "EV_CONNECTOR_TYPE_UNSPECIFIED_WALL_OUTLET": "OTHER",
    "EV_CONNECTOR_TYPE_OTHER": "OTHER",
    "EV_CONNECTOR_TYPE_UNSPECIFIED": "OTHER",
}

# Tesla connectors in North America are NACS (SAE J3400) — treat as compatible
_COMPATIBLE_TYPES: dict[str, set[str]] = {
    "TESLA": {"TESLA", "NACS"},
    "NACS": {"NACS", "TESLA"},
}

# Common names / spellings LLMs and users use -> normalized type
_CONNECTOR_ALIASES: dict[str, str] = {
    "ccs": "CCS2",
    "ccs2": "CCS2",
    "ccs 2": "CCS2",
    "ccs-2": "CCS2",
    "combo 2": "CCS2",
    "combo2": "CCS2",
    "ccs combo 2": "CCS2",
    "ccs type 2": "CCS2",
    "ccs1": "CCS1",
    "ccs 1": "CCS1",
    "ccs-1": "CCS1",
    "combo 1": "CCS1",
    "combo1": "CCS1",
    "ccs combo 1": "CCS1",
    "ccs type 1": "CCS1",
    "chademo": "CHADEMO",
    "type2": "TYPE_2",
    "type 2": "TYPE_2",
    "type-2": "TYPE_2",
    "type_2": "TYPE_2",
    "mennekes": "TYPE_2",
    "iec 62196": "TYPE_2",
    "j1772": "J1772",
    "j-1772": "J1772",
    "type 1": "J1772",
    "type1": "J1772",
    "type-1": "J1772",
    "tesla": "TESLA",
    "supercharger": "TESLA",
    "tesla supercharger": "TESLA",
    "nacs": "NACS",
    "j3400": "NACS",
    "sae j3400": "NACS",
    "gbt": "GB_T",
    "gb/t": "GB_T",
    "gb-t": "GB_T",
    "gb_t": "GB_T",
}


def normalize_connector_type(value: str | None) -> str:
    """Resolve a connector name, alias, Google enum or OCM title to a normalized type.

    Returns "OTHER" when the value cannot be recognized.
    """
    if not value:
        return "OTHER"
    raw = value.strip()
    if raw.upper() in _GOOGLE_CONNECTOR_TYPES:
        return _GOOGLE_CONNECTOR_TYPES[raw.upper()]
    if raw.upper() in NORMALIZED_CONNECTOR_TYPES:
        return raw.upper()

    text = raw.lower()
    if text in _CONNECTOR_ALIASES:
        return _CONNECTOR_ALIASES[text]

    # Free-text titles (e.g. Open Charge Map "CCS (Type 2)", "Type 1 (J1772)")
    if "ccs" in text or "combo" in text:
        return "CCS1" if ("type 1" in text or "combo 1" in text or "sae" in text) else "CCS2"
    if "chademo" in text:
        return "CHADEMO"
    if "nacs" in text or "j3400" in text:
        return "NACS"
    if "tesla" in text or "supercharger" in text:
        return "TESLA"
    if "gb-t" in text or "gb/t" in text or "gbt" in text:
        return "GB_T"
    if "j1772" in text or "type 1" in text:
        return "J1772"
    if "type 2" in text or "mennekes" in text:
        return "TYPE_2"
    return "OTHER"


def compatible_connector_types(connector_type: str) -> set[str]:
    """Normalized connector types a car with ``connector_type`` can use."""
    normalized = normalize_connector_type(connector_type)
    return _COMPATIBLE_TYPES.get(normalized, {normalized})


def to_google_connector_types(connector_type: str) -> list[str]:
    """Map a connector name to the Google Places EVConnectorType enum values."""
    wanted = compatible_connector_types(connector_type)
    return [
        google
        for google, normalized in _GOOGLE_CONNECTOR_TYPES.items()
        if normalized in wanted and normalized != "OTHER"
    ]


def _wanted_connector_types(connector_type: str) -> set[str] | None:
    """Normalized types to filter on (None = do not filter on type)."""
    wanted = compatible_connector_types(connector_type) if connector_type else None
    if wanted == {"OTHER"}:
        wanted = None  # Unrecognized connector name — do not filter on it
    return wanted


def _matching_connectors(
    charger: Charger,
    min_power_kw: float,
    wanted: set[str] | None,
) -> list[ConnectorAggregation]:
    """Connectors of a charger meeting the power / type filters."""
    return [
        connector
        for connector in charger.connectors
        if (wanted is None or connector.type in wanted)
        and not (min_power_kw and (connector.max_charge_rate_kw or 0) < min_power_kw)
    ]


def charger_matches(
    charger: Charger,
    min_power_kw: float = 0,
    connector_type: str = "",
) -> bool:
    """Return True if the charger has a connector meeting the power / type filters."""
    wanted = _wanted_connector_types(connector_type)
    if not min_power_kw and wanted is None:
        return True
    return bool(_matching_connectors(charger, min_power_kw, wanted))


def restrict_to_matching(
    charger: Charger,
    min_power_kw: float = 0,
    connector_type: str = "",
) -> Charger:
    """Recompute station-level power / count / availability over matching connectors.

    ``connectors`` is left intact; only the summary fields are narrowed so a
    busy compatible connector is not hidden by free incompatible ones.
    """
    wanted = _wanted_connector_types(connector_type)
    if not min_power_kw and wanted is None:
        return charger

    matching = _matching_connectors(charger, min_power_kw, wanted)
    live = [c for c in matching if c.available_count is not None]
    return charger.model_copy(update={
        "max_charge_rate_kw": max(
            (c.max_charge_rate_kw for c in matching if c.max_charge_rate_kw is not None),
            default=None,
        ),
        "connector_count": sum(c.count for c in matching) or None,
        "has_live_availability": bool(live),
        "available_connectors": sum(c.available_count for c in live) if live else None,
    })


# ---------------------------------------------------------------------------
# Google Places (evChargeOptions)
# ---------------------------------------------------------------------------


def _format_google_connector(aggregation: dict) -> ConnectorAggregation:
    """Format a Google ConnectorAggregation.

    Proto3 JSON omits zero values, so when ``availabilityLastUpdateTime`` is
    present a missing ``availableCount`` / ``outOfServiceCount`` means 0.
    """
    has_live = "availabilityLastUpdateTime" in aggregation
    return ConnectorAggregation(
        type=normalize_connector_type(aggregation.get("type")),
        max_charge_rate_kw=aggregation.get("maxChargeRateKw"),
        count=aggregation.get("count", 0),
        available_count=aggregation.get("availableCount", 0) if has_live else None,
        out_of_service_count=aggregation.get("outOfServiceCount", 0) if has_live else None,
        availability_updated_at=aggregation.get("availabilityLastUpdateTime"),
    )


def _format_amenity_summary(summary: dict) -> str | None:
    """Flatten an EvChargeAmenitySummary into one short text."""
    if not summary:
        return None
    parts = []
    for key in ("overview", "coffee", "restaurant", "store"):
        text = summary.get(key, {}).get("content", {}).get("text")
        if text:
            parts.append(text if key == "overview" else f"{key.capitalize()}: {text}")
    return " ".join(parts) or None


def format_google_charger(
    place: dict,
    routing_summary: dict | None = None,
    route_duration_s: float | None = None,
    route_distance_m: float | None = None,
) -> Charger:
    """Format a Google Places charging station into a Charger model.

    When a ``routing_summary`` (origin -> charger -> destination legs) and
    the direct route totals are given, the detour is computed as the
    difference between the two.
    """
    location = place.get("location", {})
    ev_options = place.get("evChargeOptions", {})
    connectors = [_format_google_connector(a) for a in ev_options.get("connectorAggregation", [])]
    live = [c for c in connectors if c.available_count is not None]

    detour_min = detour_km = None
    legs = (routing_summary or {}).get("legs", [])
    if len(legs) >= 2 and route_duration_s is not None and route_distance_m is not None:
        via_s = sum(parse_duration_seconds(leg.get("duration")) for leg in legs)
        via_m = sum(leg.get("distanceMeters", 0) for leg in legs)
        detour_min = round(max(via_s - route_duration_s, 0) / 60, 1)
        detour_km = round(max(via_m - route_distance_m, 0) / 1000, 2)

    return Charger(
        place_id=place.get("id"),
        name=place.get("displayName", {}).get("text", "Unknown"),
        address=place.get("formattedAddress"),
        location=(
            LatLng(latitude=location["latitude"], longitude=location["longitude"])
            if "latitude" in location and "longitude" in location
            else None
        ),
        rating=place.get("rating"),
        review_count=place.get("userRatingCount"),
        max_charge_rate_kw=max(
            (c.max_charge_rate_kw for c in connectors if c.max_charge_rate_kw is not None),
            default=None,
        ),
        connector_count=ev_options.get("connectorCount", sum(c.count for c in connectors) or None),
        connectors=connectors,
        has_live_availability=bool(live),
        available_connectors=sum(c.available_count for c in live) if live else None,
        detour_duration_min=detour_min,
        detour_distance_km=detour_km,
        amenity_summary=_format_amenity_summary(place.get("evChargeAmenitySummary", {})),
        opening_hours=place.get("regularOpeningHours", {}).get("weekdayDescriptions", []),
        google_maps_uri=place.get("googleMapsUri"),
        source="google",
    )


def format_google_chargers(
    places: list[dict],
    routing_summaries: list[dict] | None = None,
    route_duration_s: float | None = None,
    route_distance_m: float | None = None,
) -> list[Charger]:
    """Format Google Places charging stations (routingSummaries align by index)."""
    summaries = routing_summaries or []
    return [
        format_google_charger(
            place,
            routing_summary=summaries[i] if i < len(summaries) else None,
            route_duration_s=route_duration_s,
            route_distance_m=route_distance_m,
        )
        for i, place in enumerate(places)
    ]


# ---------------------------------------------------------------------------
# Open Charge Map
# ---------------------------------------------------------------------------


def format_ocm_charger(poi: dict) -> Charger:
    """Format an Open Charge Map POI into a Charger model (no live availability)."""
    address_info = poi.get("AddressInfo", {}) or {}
    latitude = address_info.get("Latitude")
    longitude = address_info.get("Longitude")

    # Group connections by (normalized type, power) like Google's aggregations
    groups: dict[tuple[str, float | None], int] = {}
    for connection in poi.get("Connections", []) or []:
        connection_type = connection.get("ConnectionType") or {}
        normalized = normalize_connector_type(
            connection_type.get("Title") or connection_type.get("FormalName")
        )
        power = connection.get("PowerKW")
        key = (normalized, float(power) if power is not None else None)
        groups[key] = groups.get(key, 0) + int(connection.get("Quantity") or 1)

    connectors = [
        ConnectorAggregation(type=connector_type, max_charge_rate_kw=power, count=count)
        for (connector_type, power), count in sorted(
            groups.items(), key=lambda item: -(item[0][1] or 0)
        )
    ]

    title = address_info.get("Title") or "Charging station"
    operator = (poi.get("OperatorInfo") or {}).get("Title")
    if operator and "unknown" not in operator.lower() and operator.lower() not in title.lower():
        title = f"{title} ({operator})"

    country = (address_info.get("Country") or {}).get("Title")
    address_parts = [
        address_info.get("AddressLine1"),
        address_info.get("Town"),
        address_info.get("StateOrProvince"),
        address_info.get("Postcode"),
        country,
    ]
    address = ", ".join(str(p).strip() for p in address_parts if p and str(p).strip()) or None

    has_location = latitude is not None and longitude is not None

    return Charger(
        place_id=f"ocm:{poi.get('ID')}",
        name=title,
        address=address,
        location=LatLng(latitude=latitude, longitude=longitude) if has_location else None,
        rating=None,
        review_count=None,
        max_charge_rate_kw=max(
            (c.max_charge_rate_kw for c in connectors if c.max_charge_rate_kw is not None),
            default=None,
        ),
        connector_count=sum(c.count for c in connectors) or poi.get("NumberOfPoints"),
        connectors=connectors,
        has_live_availability=False,
        available_connectors=None,
        amenity_summary=None,
        opening_hours=[],
        google_maps_uri=(
            f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
            if has_location
            else None
        ),
        source="open_charge_map",
    )


def format_chargers(chargers: list[Charger]) -> ChargerSearchResponse:
    """Wrap a list of chargers into a ChargerSearchResponse model."""
    return ChargerSearchResponse(
        count=len(chargers),
        chargers=chargers,
    )
