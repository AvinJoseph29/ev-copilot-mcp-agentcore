/**
 * Shared types for the EV Copilot UI.
 *
 * - Agent payload / stream event types mirror the agent HTTP contract (spec §6.1–§6.3).
 * - Tool result shapes mirror the MCP Pydantic schemas (spec §4.4). Only the fields the UI
 *   renders are relied upon; everything optional is typed as nullable because the MCP
 *   formatters default missing vendor fields to None.
 */

// ---------------------------------------------------------------------------
// Agent request payload (POST /invocations)
// ---------------------------------------------------------------------------

export interface AgentPayload {
  prompt: string;
  customer_name: string;
  conversation_id: string;
  latitude?: number;
  longitude?: number;
}

// ---------------------------------------------------------------------------
// Agent stream events (inner JSON of each SSE frame)
// ---------------------------------------------------------------------------

export type ToolStatus = "success" | "error";

export type AgentEvent =
  | { type: "chunk"; text: string }
  | { type: "done" }
  | { type: "error"; message: string; mapped: boolean }
  | { type: "blocked"; message: string }
  | { type: "tool_start"; id: string; name: string }
  | { type: "tool_end"; id: string; name: string; status: ToolStatus; result: unknown }
  | { type: "reset" };

// ---------------------------------------------------------------------------
// Tool result shapes (spec §4.4)
// ---------------------------------------------------------------------------

export interface LatLng {
  latitude: number;
  longitude: number;
}

/** routing_compute_route */
export interface RouteLeg {
  index: number;
  start: LatLng;
  end: LatLng;
  distance_km: number;
  duration_min: number;
  encoded_polyline?: string | null;
}

export interface RouteResponse {
  distance_km: number;
  duration_min: number;
  static_duration_min?: number | null;
  encoded_polyline?: string | null;
  legs: RouteLeg[];
  toll_info?: string | null;
  warnings?: string[];
}

/** charging_* tools */
export interface ConnectorAggregation {
  type: string;
  max_charge_rate_kw?: number | null;
  count?: number | null;
  available_count?: number | null;
  out_of_service_count?: number | null;
  availability_updated_at?: string | null;
}

export interface Charger {
  place_id?: string | null;
  name: string;
  address?: string | null;
  location: LatLng;
  rating?: number | null;
  review_count?: number | null;
  max_charge_rate_kw?: number | null;
  connector_count?: number | null;
  connectors: ConnectorAggregation[];
  has_live_availability: boolean;
  available_connectors?: number | null;
  detour_duration_min?: number | null;
  detour_distance_km?: number | null;
  amenity_summary?: string | null;
  opening_hours?: string[];
  google_maps_uri?: string | null;
  source: "google" | "open_charge_map";
}

export interface ChargerSearchResponse {
  count: number;
  chargers: Charger[];
}

/** vehicle_simulate_trip_energy */
export interface EnergyLeg {
  index: number;
  start: LatLng;
  end: LatLng;
  distance_km: number;
  duration_min: number;
  avg_speed_kmh: number;
  ascent_m: number;
  descent_m: number;
  energy_kwh: number;
  start_soc_percent: number;
  arrival_soc_percent: number;
  below_buffer: boolean;
}

export interface ChargeStopResult {
  index: number;
  name: string;
  location: LatLng;
  arrival_soc_percent: number;
  departure_soc_percent: number;
  energy_added_kwh: number;
  charge_min: number;
  charger_power_kw: number;
}

export interface SocPoint {
  distance_km: number;
  soc_percent: number;
}

export interface TripEnergyPlan {
  vehicle_id: string;
  vehicle_name: string;
  feasible: boolean;
  issues: string[];
  total_distance_km: number;
  total_drive_min: number;
  total_charge_min: number;
  total_trip_min: number;
  energy_used_kwh: number;
  arrival_soc_percent: number;
  legs: EnergyLeg[];
  stops: ChargeStopResult[];
  soc_timeline: SocPoint[];
  encoded_polyline?: string | null;
  assumptions: string[];
}

/** places_search_places / places_search_nearby_places */
export interface PlaceLocation {
  latitude: number | null;
  longitude: number | null;
}

export interface Place {
  name: string;
  address?: string | null;
  location: PlaceLocation;
  rating?: number | null;
  review_count?: number | null;
  phone?: string | null;
  website?: string | null;
  price_level?: string | null;
  types?: string[];
  summary?: string | null;
  opening_hours?: string[];
  place_id?: string | null;
}

export interface PlaceSearchResponse {
  count: number;
  places: Place[];
}

/** weather_get_weather_alerts */
export interface WeatherAlert {
  title?: string | null;
  event_type?: string | null;
  severity?: string | null;
  urgency?: string | null;
  certainty?: string | null;
  description?: string | null;
  area?: string | null;
  start_time?: string | null;
  expiration_time?: string | null;
  source?: string | null;
}

export interface WeatherAlertsResponse {
  count: number;
  alerts: WeatherAlert[];
}

// ---------------------------------------------------------------------------
// Client UI state
// ---------------------------------------------------------------------------

export type ToolRunStatus = "running" | ToolStatus;

export interface ToolActivityItem {
  id: string;
  name: string;
  status: ToolRunStatus;
}

export type MessageRole = "user" | "assistant" | "notice";

export type AssistantStatus = "streaming" | "done" | "error" | "blocked";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  status?: AssistantStatus;
  tools?: ToolActivityItem[];
}

export interface UserLocation {
  latitude: number;
  longitude: number;
}

export interface MapsConfig {
  mapsApiKey: string;
  mapId: string;
}
