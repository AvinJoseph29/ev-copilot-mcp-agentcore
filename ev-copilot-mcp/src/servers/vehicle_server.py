"""
Vehicle MCP Server.

Self-contained FastMCP instance with EV vehicle tools:
- Vehicle catalog (bundled ``src/data/vehicles.json``, approximate public specs)
- Deterministic trip energy simulation (Google Routes legs + Google Elevation
  samples fed into the pure ``utils/energy_model.py``)
Mounted into the registry via tool_registry.py.
"""

import asyncio
import difflib
import json
import re
from pathlib import Path

from fastmcp import FastMCP
from loguru import logger

from src.clients.google_elevation_client import GoogleElevationClient
from src.clients.google_routes_client import GoogleRoutesClient
from src.config import settings
from src.infrastructure.trace_decorator import traced
from src.schemas.vehicle import (
    ChargingStopInput,
    TripEnergyPlan,
    VehicleSearchResponse,
    VehicleSpec,
)
from src.utils.energy_model import LegInput, StopInput, simulate_trip
from src.utils.polyline import shorten_polyline
from src.utils.route_formatters import ascent_descent, format_route
from src.utils.vehicle_formatters import (
    format_trip_energy_plan,
    format_vehicle_search,
    format_vehicle_spec,
)

vehicle_mcp = FastMCP("vehicle")

VEHICLES_PATH = Path(__file__).resolve().parent.parent / "data" / "vehicles.json"

# Minimum fuzzy-match score for a catalog entry to be returned
MIN_MATCH_SCORE = 0.35

# ---------------------------------------------------------------------------
# Lazy singletons (catalog + clients)
# ---------------------------------------------------------------------------

_catalog: dict[str, dict] | None = None
_routes_client: GoogleRoutesClient | None = None
_elevation_client: GoogleElevationClient | None = None


def _get_catalog() -> dict[str, dict]:
    global _catalog
    if _catalog is None:
        with VEHICLES_PATH.open(encoding="utf-8") as fh:
            _catalog = {v["vehicle_id"]: v for v in json.load(fh)}
        logger.info(f"Loaded {len(_catalog)} vehicles from {VEHICLES_PATH.name}")
    return _catalog


def _get_routes_client() -> GoogleRoutesClient:
    global _routes_client
    if _routes_client is None:
        _routes_client = GoogleRoutesClient(api_key=settings.GOOGLE_MAPS_API_KEY)
    return _routes_client


def _get_elevation_client() -> GoogleElevationClient:
    global _elevation_client
    if _elevation_client is None:
        _elevation_client = GoogleElevationClient(api_key=settings.GOOGLE_MAPS_API_KEY)
    return _elevation_client


# ---------------------------------------------------------------------------
# Fuzzy catalog search — users type "nexon 45", "ioniq5", "model y long range"
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase and replace punctuation with spaces ("ID.4" -> "id 4")."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _match_score(query: str, vehicle: dict) -> float:
    """Score how well ``query`` matches a catalog entry (0-1)."""
    q = _normalize(query)
    name = _normalize(f"{vehicle['make']} {vehicle['model']} {vehicle['variant']}")
    if not q:
        return 0.0
    if q == vehicle["vehicle_id"] or q == name:
        return 1.0

    name_tokens = set(name.split()) | set(vehicle["vehicle_id"].split("-"))
    # Also match glued tokens such as "ioniq5" / "ev6" / "id4"
    name_tokens |= {_normalize(vehicle["model"]).replace(" ", "")}

    query_tokens = q.split()
    hits = 0
    for token in query_tokens:
        if token in name_tokens or any(t.startswith(token) for t in name_tokens if len(token) >= 2):
            hits += 1
        elif difflib.get_close_matches(token, name_tokens, n=1, cutoff=0.8):
            hits += 0.8
    token_score = hits / len(query_tokens)
    ratio = difflib.SequenceMatcher(None, q, name).ratio()
    return 0.7 * token_score + 0.3 * ratio


def _search_catalog(query: str, max_results: int) -> list[dict]:
    """Return the best matching catalog entries, most relevant first."""
    scored = [(_match_score(query, v), v) for v in _get_catalog().values()]
    scored = [(s, v) for s, v in scored if s >= MIN_MATCH_SCORE]
    scored.sort(key=lambda item: (-item[0], item[1]["vehicle_id"]))
    return [v for _, v in scored[: max(1, min(max_results, 25))]]


def _get_vehicle(vehicle_id: str) -> dict:
    """Look up a catalog entry by id (falls back to the best fuzzy match)."""
    catalog = _get_catalog()
    vehicle = catalog.get(vehicle_id.strip().lower())
    if vehicle is not None:
        return vehicle
    matches = _search_catalog(vehicle_id, max_results=3)
    if matches and _match_score(vehicle_id, matches[0]) >= 0.8:
        return matches[0]
    suggestions = ", ".join(v["vehicle_id"] for v in matches) or "none"
    raise ValueError(
        f"Unknown vehicle_id {vehicle_id!r}. Use vehicle_search_vehicles first. "
        f"Closest matches: {suggestions}."
    )


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@vehicle_mcp.tool(
    title="Search Vehicles",
    description=(
        "Search the EV catalog by make, model, or variant using fuzzy matching "
        "(e.g. 'nexon 45', 'ioniq 5', 'model y long range'). Returns matching "
        "vehicles with catalog ID, usable battery, and estimated range "
        "(approximate public specifications). Use this to identify the user's car "
        "and get the vehicle_id needed by the spec and trip simulation tools."
    ),
    tags={"vehicle", "catalog", "search", "ev"},
    annotations={
        "title": "Search Vehicles",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@traced(span_name="mcp.tool.search_vehicles", handler_type="tool")
async def search_vehicles(
    query: str,
    max_results: int = 5,
) -> VehicleSearchResponse:
    """Fuzzy-search the vehicle catalog.

    Args:
        query: Make / model / variant text (e.g. "Tata Nexon EV 45", "kia ev6").
        max_results: Maximum number of vehicles to return (1-25, default 5).
    """
    return format_vehicle_search(_search_catalog(query, max_results))


@vehicle_mcp.tool(
    title="Get Vehicle Spec",
    description=(
        "Get the full specification of a catalog vehicle: usable battery, typical "
        "consumption (Wh/km), mass, max AC and DC charging power, supported AC and "
        "DC connectors, DC charging curve, estimated range, and markets "
        "(approximate public specifications). Use this to know which charger "
        "connectors are compatible and how fast the car charges."
    ),
    tags={"vehicle", "catalog", "spec", "ev"},
    annotations={
        "title": "Get Vehicle Spec",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@traced(span_name="mcp.tool.get_vehicle_spec", handler_type="tool")
async def get_vehicle_spec(vehicle_id: str) -> VehicleSpec:
    """Get the specification of a catalog vehicle.

    Args:
        vehicle_id: Catalog vehicle ID (e.g. "tata-nexon-ev-45"), from vehicle search results.
    """
    return format_vehicle_spec(_get_vehicle(vehicle_id))


@vehicle_mcp.tool(
    title="Simulate Trip Energy",
    description=(
        "Simulate the battery state of charge along a trip for a specific vehicle, "
        "with optional charging stops. Uses the real driving route (traffic-aware "
        "leg times), elevation along each leg, outside temperature, and payload in a "
        "deterministic energy model. Returns battery % at the start and end of every "
        "leg, arrival / departure % and charging time at each stop, total drive and "
        "charge time, a battery timeline for charting, feasibility against the "
        "safety buffer, and concrete issues (e.g. where to add a stop). ALWAYS use "
        "this to verify the final charging plan, and re-run it after changing stops "
        "until the plan is feasible."
    ),
    tags={"vehicle", "energy", "simulation", "battery", "ev"},
    annotations={
        "title": "Simulate Trip Energy",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@traced(span_name="mcp.tool.simulate_trip_energy", handler_type="tool")
async def simulate_trip_energy(
    vehicle_id: str,
    origin_latitude: float,
    origin_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
    charging_stops: list[ChargingStopInput] = [],  # noqa: B006
    start_soc_percent: float = 90,
    buffer_percent: float = 15,
    charge_to_percent: float = 80,
    outside_temperature_c: float | None = None,
    payload_kg: float = 150,
) -> TripEnergyPlan:
    """Simulate battery state of charge for a trip with optional charging stops.

    Args:
        vehicle_id: Catalog vehicle ID (e.g. "tata-nexon-ev-45").
        origin_latitude: Start latitude (e.g. 18.5204 for Pune).
        origin_longitude: Start longitude (e.g. 73.8567 for Pune).
        destination_latitude: Destination latitude (e.g. 15.4909 for Panaji, Goa).
        destination_longitude: Destination longitude (e.g. 73.8278 for Panaji, Goa).
        charging_stops: Ordered charging stops as objects, e.g.
                        [{"latitude": 16.7050, "longitude": 74.2433,
                          "charger_power_kw": 60, "name": "Tata Power - Kolhapur"}].
        start_soc_percent: Battery % at departure (default 90).
        buffer_percent: Minimum battery % to arrive with at every stop (default 15).
        charge_to_percent: Battery % to charge to at each stop (default 80; raised
                           automatically when the next leg needs more).
        outside_temperature_c: Expected outside temperature in °C during the drive
                               (e.g. from the hourly forecast); omit if unknown.
        payload_kg: Passengers + luggage in kg (default 150).
    """
    vehicle = _get_vehicle(vehicle_id)

    # 1. One route with the charging stops as intermediates -> one leg per stretch
    route = await _get_routes_client().compute_route(
        origin=(origin_latitude, origin_longitude),
        destination=(destination_latitude, destination_longitude),
        intermediates=[(s.latitude, s.longitude) for s in charging_stops],
    )
    route_model = format_route(route)

    # 2. Elevation samples per leg (in parallel)
    elevation_client = _get_elevation_client()

    async def _leg_elevation(encoded: str | None, distance_km: float) -> tuple[float, float]:
        if not encoded:
            return 0.0, 0.0
        samples = min(64, max(2, int(distance_km / 2) + 2))
        results = await elevation_client.get_elevation_along_path(
            encoded_path=shorten_polyline(encoded),
            samples=samples,
        )
        return ascent_descent([float(r.get("elevation", 0.0)) for r in results])

    elevations = await asyncio.gather(
        *(_leg_elevation(leg.encoded_polyline, leg.distance_km) for leg in route_model.legs)
    )

    # 3. Deterministic energy model
    legs = [
        LegInput(
            start=(leg.start.latitude, leg.start.longitude),
            end=(leg.end.latitude, leg.end.longitude),
            distance_km=leg.distance_km,
            duration_min=leg.duration_min,
            ascent_m=ascent,
            descent_m=descent,
        )
        for leg, (ascent, descent) in zip(route_model.legs, elevations)
    ]
    stops = [
        StopInput(
            location=(s.latitude, s.longitude),
            charger_power_kw=s.charger_power_kw,
            name=s.name,
        )
        for s in charging_stops
    ]
    simulation = simulate_trip(
        vehicle=vehicle,
        legs=legs,
        stops=stops,
        start_soc_percent=start_soc_percent,
        buffer_percent=buffer_percent,
        charge_to_percent=charge_to_percent,
        temperature_c=outside_temperature_c,
        payload_kg=payload_kg,
    )
    return format_trip_energy_plan(
        vehicle,
        simulation,
        encoded_polyline=route_model.encoded_polyline,
    )
