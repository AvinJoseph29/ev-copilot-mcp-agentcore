"use client";

import { useState } from "react";

import type { ToolActivityItem } from "@/lib/types";

import { CheckIcon, ChevronIcon, SpinnerIcon, XIcon } from "./Icons";

/** Friendly step labels for the MCP tools (spec §4.4); tool names are never shown raw. */
const TOOL_LABELS: Record<string, string> = {
  routing_geocode: "Looking up locations",
  routing_compute_route: "Planning the route",
  routing_get_elevation_profile: "Checking elevation along the way",
  charging_search_chargers_along_route: "Finding chargers along the route",
  charging_search_chargers_nearby: "Finding nearby chargers",
  charging_get_charger_details: "Checking charger details",
  charging_search_chargers_open_charge_map: "Searching more charger networks",
  vehicle_search_vehicles: "Identifying your vehicle",
  vehicle_get_vehicle_spec: "Loading vehicle specs",
  vehicle_simulate_trip_energy: "Simulating battery usage",
  weather_get_current_weather: "Checking current weather",
  weather_get_weather_forecast: "Checking the forecast",
  weather_get_hourly_forecast: "Checking hourly temperatures",
  weather_get_weather_alerts: "Checking weather alerts",
  places_search_places: "Searching places",
  places_search_nearby_places: "Finding food & amenities nearby",
  places_get_place_details: "Checking place details",
  preferences_get_user_preferences: "Recalling your preferences",
};

export function toolLabel(name: string): string {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name];
  const words = name.replace(/^[a-z]+_/, "").replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Working";
}

interface ToolActivityProps {
  tools: ToolActivityItem[];
  active: boolean;
}

/** Live list of agent steps; collapses to a one-line summary once the answer is complete. */
export default function ToolActivity({ tools, active }: ToolActivityProps) {
  const [expanded, setExpanded] = useState(false);
  if (tools.length === 0) return null;

  const failed = tools.filter((t) => t.status === "error").length;
  const showList = active || expanded;

  return (
    <div className="mb-2.5 rounded-xl border border-line bg-surface-2 text-xs">
      {!active && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="flex w-full items-center gap-2 px-3 py-2 text-ink-2 hover:text-ink"
        >
          <CheckIcon size={14} className="text-good" />
          <span>
            Completed {tools.length} step{tools.length === 1 ? "" : "s"}
            {failed > 0 && <span className="text-bad"> · {failed} failed</span>}
          </span>
          <ChevronIcon size={14} className={`ml-auto transition-transform ${expanded ? "rotate-180" : ""}`} />
        </button>
      )}
      {showList && (
        <ol className={`flex flex-col gap-1.5 px-3 py-2 ${!active ? "border-t border-line" : ""}`}>
          {tools.map((tool) => (
            <li key={tool.id} className="flex items-center gap-2">
              {tool.status === "running" ? (
                <SpinnerIcon size={14} className="text-accent" />
              ) : tool.status === "success" ? (
                <CheckIcon size={14} className="text-good" />
              ) : (
                <XIcon size={14} className="text-bad" />
              )}
              <span className={tool.status === "running" ? "font-medium text-ink" : "text-ink-2"}>
                {toolLabel(tool.name)}
                {tool.status === "running" && "…"}
                {tool.status === "error" && <span className="text-bad"> (failed)</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
