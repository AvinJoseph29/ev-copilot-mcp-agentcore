/**
 * Map / trip panel state derived from `tool_end` results (spec §6.3, §7 behaviour 7–8).
 *
 * Replacement rule: within one user turn, results of the same category merge (e.g. two
 * charger searches); the first result of a category in a new turn replaces the previous
 * turn's data. A route or simulation for a different trip also clears chargers, places and
 * alerts left from earlier turns, so a new trip never shows stale chargers.
 */

import { decodePolyline, type LatLngLiteral } from "./polyline";
import type {
  Charger,
  ChargerSearchResponse,
  LatLng,
  Place,
  PlaceSearchResponse,
  RouteResponse,
  TripEnergyPlan,
  WeatherAlert,
  WeatherAlertsResponse,
} from "./types";

/** Tools whose `tool_end.result` carries data for the map / trip panel (spec §6.3). */
export const MAP_TOOLS = new Set([
  "routing_compute_route",
  "charging_search_chargers_along_route",
  "charging_search_chargers_nearby",
  "charging_get_charger_details",
  "charging_search_chargers_open_charge_map",
  "vehicle_simulate_trip_energy",
  "places_search_places",
  "places_search_nearby_places",
  "weather_get_weather_alerts",
]);

export interface RouteGeometry {
  path: LatLngLiteral[];
  origin: LatLngLiteral | null;
  destination: LatLngLiteral | null;
  distanceKm: number;
  durationMin: number;
  source: "route" | "simulation";
}

type Category = "route" | "chargers" | "places" | "plan" | "alerts";

export interface TripState {
  turn: number;
  route: RouteGeometry | null;
  chargers: Charger[];
  places: Place[];
  plan: TripEnergyPlan | null;
  alerts: WeatherAlert[];
  /** Turn number in which each category was last written. */
  stamps: Record<Category, number>;
  /** Incremented whenever the map should re-fit its bounds. */
  fitVersion: number;
}

export const EMPTY_TRIP: TripState = {
  turn: 0,
  route: null,
  chargers: [],
  places: [],
  plan: null,
  alerts: [],
  stamps: { route: 0, chargers: 0, places: 0, plan: 0, alerts: 0 },
  fitVersion: 0,
};

export function hasTripData(state: TripState): boolean {
  return Boolean(state.route || state.plan || state.chargers.length || state.places.length || state.alerts.length);
}

export function startTurn(state: TripState): TripState {
  return { ...state, turn: state.turn + 1 };
}

// ---------------------------------------------------------------------------
// Type guards (results are untrusted JSON)
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isLatLng(value: unknown): value is LatLng {
  return isRecord(value) && typeof value.latitude === "number" && typeof value.longitude === "number";
}

/** Chargers without coordinates cannot be drawn; place_id is optional in the MCP schema. */
function isCharger(value: unknown): value is Charger {
  return isRecord(value) && typeof value.name === "string" && isLatLng(value.location);
}

function isChargerSearch(value: unknown): value is ChargerSearchResponse {
  return isRecord(value) && Array.isArray(value.chargers);
}

function isRoute(value: unknown): value is RouteResponse {
  return (
    isRecord(value) &&
    (typeof value.encoded_polyline === "string" || value.encoded_polyline == null) &&
    Array.isArray(value.legs)
  );
}

function isPlan(value: unknown): value is TripEnergyPlan {
  return isRecord(value) && Array.isArray(value.soc_timeline) && Array.isArray(value.legs) && typeof value.feasible === "boolean";
}

function isPlaceSearch(value: unknown): value is PlaceSearchResponse {
  return isRecord(value) && Array.isArray(value.places);
}

function isAlerts(value: unknown): value is WeatherAlertsResponse {
  return isRecord(value) && Array.isArray(value.alerts);
}

const toLiteral = (p: LatLng): LatLngLiteral => ({ lat: p.latitude, lng: p.longitude });

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

function isFreshTurn(state: TripState, category: Category): boolean {
  return state.stamps[category] !== state.turn;
}

function stamp(state: TripState, category: Category): Record<Category, number> {
  return { ...state.stamps, [category]: state.turn };
}

function mergeByKey<T>(existing: T[], incoming: T[], key: (item: T) => string): T[] {
  const map = new Map<string, T>();
  for (const item of existing) map.set(key(item), item);
  for (const item of incoming) map.set(key(item), item);
  return Array.from(map.values());
}

function routeFromLegs(
  encoded: string | null | undefined,
  legs: { start: LatLng; end: LatLng }[],
  distanceKm: number,
  durationMin: number,
  source: RouteGeometry["source"],
): RouteGeometry | null {
  const path = decodePolyline(encoded ?? "");
  if (path.length === 0 && legs.length === 0) return null;
  const firstLeg = legs[0];
  const lastLeg = legs[legs.length - 1];
  return {
    path,
    origin: firstLeg && isLatLng(firstLeg.start) ? toLiteral(firstLeg.start) : (path[0] ?? null),
    destination: lastLeg && isLatLng(lastLeg.end) ? toLiteral(lastLeg.end) : (path[path.length - 1] ?? null),
    distanceKm,
    durationMin,
    source,
  };
}

/** Great-circle distance in km. */
export function haversineKm(a: LatLngLiteral, b: LatLngLiteral): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

const SAME_TRIP_TOLERANCE_KM = 5;

function sameTrip(plan: TripEnergyPlan, route: RouteGeometry): boolean {
  const first = plan.legs[0];
  const last = plan.legs[plan.legs.length - 1];
  if (!first || !last || !route.origin || !route.destination) return false;
  return (
    haversineKm(toLiteral(first.start), route.origin) <= SAME_TRIP_TOLERANCE_KM &&
    haversineKm(toLiteral(last.end), route.destination) <= SAME_TRIP_TOLERANCE_KM
  );
}

function sameEndpoints(a: RouteGeometry, b: RouteGeometry): boolean {
  if (!a.origin || !a.destination || !b.origin || !b.destination) return false;
  return (
    haversineKm(a.origin, b.origin) <= SAME_TRIP_TOLERANCE_KM &&
    haversineKm(a.destination, b.destination) <= SAME_TRIP_TOLERANCE_KM
  );
}

/** Drop chargers / places / alerts from earlier turns when `route` is a different trip. */
function clearStaleForRoute(state: TripState, route: RouteGeometry): TripState {
  if (!state.route || sameEndpoints(state.route, route)) return state;
  return {
    ...state,
    chargers: isFreshTurn(state, "chargers") ? [] : state.chargers,
    places: isFreshTurn(state, "places") ? [] : state.places,
    alerts: isFreshTurn(state, "alerts") ? [] : state.alerts,
  };
}

function withChargers(state: TripState, incoming: Charger[]): TripState {
  const valid = incoming.filter(isCharger);
  const base = isFreshTurn(state, "chargers") ? [] : state.chargers;
  const chargers = mergeByKey(base, valid, chargerKey);
  const refit = !state.route && chargers.length > 0;
  return {
    ...state,
    chargers,
    stamps: stamp(state, "chargers"),
    fitVersion: refit ? state.fitVersion + 1 : state.fitVersion,
  };
}

/** Apply one map-tool result to the trip state. Unknown or malformed results are ignored. */
export function applyToolResult(state: TripState, toolName: string, result: unknown): TripState {
  if (!MAP_TOOLS.has(toolName) || result === null || result === undefined) return state;

  switch (toolName) {
    case "routing_compute_route": {
      if (!isRoute(result)) return state;
      const route = routeFromLegs(result.encoded_polyline, result.legs, result.distance_km, result.duration_min, "route");
      if (!route) return state;
      // A plan from this turn already carries the authoritative geometry (with stops).
      if (state.plan && !isFreshTurn(state, "plan")) return state;
      // A route for a different trip makes an older plan and older chargers/places/alerts stale.
      const plan = state.plan && sameTrip(state.plan, route) ? state.plan : null;
      return { ...clearStaleForRoute(state, route), route, plan, stamps: stamp(state, "route"), fitVersion: state.fitVersion + 1 };
    }

    case "vehicle_simulate_trip_energy": {
      if (!isPlan(result)) return state;
      const route = routeFromLegs(
        result.encoded_polyline,
        result.legs,
        result.total_distance_km,
        result.total_drive_min,
        "simulation",
      );
      return {
        ...(route ? clearStaleForRoute(state, route) : state),
        plan: result,
        route: route ?? state.route,
        stamps: { ...stamp(state, "plan"), route: state.turn },
        fitVersion: state.fitVersion + 1,
      };
    }

    case "charging_search_chargers_along_route":
    case "charging_search_chargers_nearby":
    case "charging_search_chargers_open_charge_map":
      return isChargerSearch(result) ? withChargers(state, result.chargers) : state;

    case "charging_get_charger_details":
      return isCharger(result) ? withChargers(state, [result]) : state;

    case "places_search_places":
    case "places_search_nearby_places": {
      if (!isPlaceSearch(result)) return state;
      const valid = result.places.filter(
        (p) => isRecord(p) && isRecord(p.location) && typeof p.location.latitude === "number" && typeof p.location.longitude === "number",
      );
      const base = isFreshTurn(state, "places") ? [] : state.places;
      const places = mergeByKey(base, valid, (p) => p.place_id || `${p.name}@${p.location.latitude},${p.location.longitude}`);
      return { ...state, places, stamps: stamp(state, "places") };
    }

    case "weather_get_weather_alerts": {
      if (!isAlerts(result)) return state;
      const base = isFreshTurn(state, "alerts") ? [] : state.alerts;
      const alerts = mergeByKey(base, result.alerts.filter(isRecord), (a) => `${a.title}|${a.area ?? ""}|${a.start_time ?? ""}`);
      return { ...state, alerts, stamps: stamp(state, "alerts") };
    }

    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Charger helpers shared by the map and trip panel
// ---------------------------------------------------------------------------

/** Stable charger identity for merging, React keys and selection (place_id is optional). */
export function chargerKey(charger: Charger): string {
  return charger.place_id || `${charger.name}@${charger.location.latitude},${charger.location.longitude}`;
}

export type AvailabilityLevel = "available" | "unknown" | "unavailable";

/** green = available > 0, amber = no live data, red = 0 available / all out of service. */
export function chargerAvailability(charger: Charger): AvailabilityLevel {
  if (!charger.has_live_availability) return "unknown";
  if (typeof charger.available_connectors === "number") {
    return charger.available_connectors > 0 ? "available" : "unavailable";
  }
  const counted = charger.connectors.filter((c) => typeof c.available_count === "number");
  if (counted.length === 0) return "unknown";
  return counted.some((c) => (c.available_count ?? 0) > 0) ? "available" : "unavailable";
}

export function totalConnectors(charger: Charger): number {
  if (typeof charger.connector_count === "number") return charger.connector_count;
  return charger.connectors.reduce((sum, c) => sum + (c.count ?? 0), 0);
}

export function availableConnectors(charger: Charger): number | null {
  if (typeof charger.available_connectors === "number") return charger.available_connectors;
  const counted = charger.connectors.filter((c) => typeof c.available_count === "number");
  if (counted.length === 0) return null;
  return counted.reduce((sum, c) => sum + (c.available_count ?? 0), 0);
}

export function chargerMapsUrl(charger: Charger): string {
  if (charger.google_maps_uri) return charger.google_maps_uri;
  const { latitude, longitude } = charger.location;
  return `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`;
}

// ---------------------------------------------------------------------------
// Plan helpers
// ---------------------------------------------------------------------------

/** Default reserve of vehicle_simulate_trip_energy (`buffer_percent: float = 15`). */
export const DEFAULT_BUFFER_PERCENT = 15;

/**
 * Reserve buffer used for a simulated plan. TripEnergyPlan (§4.4) does not carry the buffer
 * as a field, but the energy model always states it in `assumptions`
 * ("Arrive with ≥15% buffer; …") and in buffer `issues` ("(< 15% buffer)").
 */
export function planBufferPercent(plan: TripEnergyPlan): number {
  for (const text of [...plan.assumptions, ...plan.issues]) {
    const match = /(?:≥|>=|<)\s*(\d+(?:\.\d+)?)\s*%\s*buffer/i.exec(text);
    if (match) {
      const value = Number(match[1]);
      if (Number.isFinite(value) && value >= 0 && value <= 100) return value;
    }
  }
  return DEFAULT_BUFFER_PERCENT;
}
