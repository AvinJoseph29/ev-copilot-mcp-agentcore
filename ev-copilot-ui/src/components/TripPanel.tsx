"use client";

import { useState } from "react";

import { formatDuration, formatKm, formatKw } from "@/lib/format";
import { availableConnectors, chargerAvailability, chargerKey, totalConnectors, type TripState } from "@/lib/trip-state";
import type { WeatherAlert } from "@/lib/types";

import { AVAILABILITY_STYLES } from "./ChargerMarker";
import { AlertIcon, BoltIcon, ChevronIcon, RouteIcon } from "./Icons";
import TripSummary from "./TripSummary";

interface TripPanelProps {
  trip: TripState;
  hasData: boolean;
  selectedChargerId: string | null;
  onSelectCharger: (chargerId: string) => void;
  dark: boolean;
}

/** Trip panel under the map: weather alerts, plan summary + battery chart, route and charger list. */
export default function TripPanel({ trip, hasData, selectedChargerId, onSelectCharger, dark }: TripPanelProps) {
  const [collapsed, setCollapsed] = useState(false);

  if (!hasData) {
    return (
      <div className="flex shrink-0 items-center gap-3 border-t border-line bg-surface px-5 py-3.5 text-xs text-ink-3">
        <RouteIcon size={16} className="shrink-0 text-accent" />
        Your trip will appear here — ask for a route to see the battery plan, charging stops and live charger availability.
      </div>
    );
  }

  return (
    <div className={`flex shrink-0 flex-col border-t border-line bg-surface-2 ${collapsed ? "" : "max-h-[55%] min-h-[200px]"}`}>
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
        className="flex items-center gap-2 border-b border-line bg-surface px-5 py-2 text-xs font-semibold tracking-wide text-ink-2 uppercase hover:text-ink"
      >
        Trip details
        {trip.alerts.length > 0 && (
          <span className="rounded-full bg-warn/15 px-1.5 py-px text-[10px] font-semibold text-warn normal-case">
            {trip.alerts.length} weather alert{trip.alerts.length === 1 ? "" : "s"}
          </span>
        )}
        <ChevronIcon size={14} className={`ml-auto transition-transform ${collapsed ? "rotate-180" : ""}`} />
      </button>

      {!collapsed && (
        <div className="scroll-thin flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-4">
          {trip.alerts.length > 0 && <WeatherAlerts alerts={trip.alerts} />}

          {trip.plan ? (
            <TripSummary plan={trip.plan} dark={dark} />
          ) : (
            trip.route && (
              <div className="flex items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2.5">
                <RouteIcon size={18} className="text-accent" />
                <div className="text-sm">
                  <span className="font-semibold text-ink">{formatKm(trip.route.distanceKm)}</span>
                  <span className="text-ink-3"> · {formatDuration(trip.route.durationMin)} driving</span>
                </div>
              </div>
            )
          )}

          {trip.chargers.length > 0 && (
            <section>
              <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink-2">
                <BoltIcon size={13} className="text-accent" />
                Chargers found ({trip.chargers.length})
              </h3>
              <ul className="flex flex-col gap-1.5">
                {trip.chargers.map((charger) => {
                  const level = chargerAvailability(charger);
                  const { color, label } = AVAILABILITY_STYLES[level];
                  const available = availableConnectors(charger);
                  const id = chargerKey(charger);
                  const selected = id === selectedChargerId;
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        onClick={() => onSelectCharger(id)}
                        className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition ${
                          selected ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-ink-3/40"
                        }`}
                      >
                        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color }} aria-hidden="true" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-ink">{charger.name}</span>
                          <span className="block truncate text-xs text-ink-3">
                            {level === "unknown" ? label : `${available ?? 0}/${totalConnectors(charger)} available`}
                            {formatKw(charger.max_charge_rate_kw) && ` · ${formatKw(charger.max_charge_rate_kw)}`}
                            {charger.connectors.length > 0 && ` · ${Array.from(new Set(charger.connectors.map((c) => c.type))).join(", ")}`}
                          </span>
                        </span>
                        {typeof charger.detour_duration_min === "number" && (
                          <span className="shrink-0 text-xs text-ink-3 tabular-nums">+{formatDuration(charger.detour_duration_min)}</span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function WeatherAlerts({ alerts }: { alerts: WeatherAlert[] }) {
  return (
    <section className="flex flex-col gap-2 rounded-xl border border-warn/40 bg-warn/10 px-3 py-2.5" role="alert">
      {alerts.map((alert, i) => (
        <div key={`${alert.title ?? alert.event_type ?? "alert"}-${i}`} className="flex gap-2 text-xs">
          <AlertIcon size={15} className="mt-px shrink-0 text-warn" />
          <div className="min-w-0">
            <div className="font-semibold text-ink">
              {alert.title || alert.event_type || "Weather alert"}
              {alert.severity && <span className="font-normal text-ink-2"> · {alert.severity.toLowerCase()}</span>}
            </div>
            {alert.area && <div className="text-ink-2">{alert.area}</div>}
            {alert.expiration_time && <div className="text-ink-3">Until {formatAlertTime(alert.expiration_time)}</div>}
          </div>
        </div>
      ))}
    </section>
  );
}

function formatAlertTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
