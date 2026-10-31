"use client";

import { AdvancedMarker, AdvancedMarkerAnchorPoint, InfoWindow, useAdvancedMarkerRef } from "@vis.gl/react-google-maps";

import { formatConnector, formatKm, formatKw, formatDuration } from "@/lib/format";
import {
  availableConnectors,
  chargerAvailability,
  chargerKey,
  chargerMapsUrl,
  totalConnectors,
  type AvailabilityLevel,
} from "@/lib/trip-state";
import type { Charger } from "@/lib/types";

import { BoltIcon, ExternalIcon, StarIcon } from "./Icons";

/** Availability colours (green = free connectors, amber = no live data, red = none free). */
export const AVAILABILITY_STYLES: Record<AvailabilityLevel, { color: string; label: string }> = {
  available: { color: "#16a34a", label: "Connectors available" },
  unknown: { color: "#d97706", label: "No live availability" },
  unavailable: { color: "#dc2626", label: "None available" },
};

interface ChargerMarkerProps {
  charger: Charger;
  selected: boolean;
  highlighted: boolean;
  /** Called with the charger key (see chargerKey) or null to deselect. */
  onSelect: (chargerId: string | null) => void;
}

export default function ChargerMarker({ charger, selected, highlighted, onSelect }: ChargerMarkerProps) {
  const [markerRef, marker] = useAdvancedMarkerRef();
  const level = chargerAvailability(charger);
  const { color, label } = AVAILABILITY_STYLES[level];

  return (
    <>
      <AdvancedMarker
        ref={markerRef}
        position={{ lat: charger.location.latitude, lng: charger.location.longitude }}
        anchorPoint={AdvancedMarkerAnchorPoint.CENTER}
        zIndex={selected ? 1000 : level === "available" ? 30 : 20}
        title={`${charger.name} — ${label}`}
        onClick={() => onSelect(selected ? null : chargerKey(charger))}
      >
        <div
          className={`flex h-7 w-7 items-center justify-center rounded-full border-2 border-white text-white shadow-md transition-transform ${
            selected ? "scale-125" : highlighted ? "scale-110" : ""
          }`}
          style={{ background: color, boxShadow: highlighted || selected ? `0 0 0 3px ${color}55, 0 2px 6px rgba(0,0,0,.3)` : undefined }}
        >
          <BoltIcon size={14} strokeWidth={2.4} />
        </div>
      </AdvancedMarker>

      {selected && marker && (
        <InfoWindow anchor={marker} onCloseClick={() => onSelect(null)} maxWidth={300}>
          <ChargerInfo charger={charger} level={level} />
        </InfoWindow>
      )}
    </>
  );
}

/** InfoWindow body. Google renders info windows on white, so explicit light colours are used. */
function ChargerInfo({ charger, level }: { charger: Charger; level: AvailabilityLevel }) {
  const { color, label } = AVAILABILITY_STYLES[level];
  const available = availableConnectors(charger);
  const total = totalConnectors(charger);

  return (
    <div className="w-[270px] p-3.5 font-sans text-slate-800">
      <div className="pr-6 text-sm leading-snug font-semibold text-slate-900">{charger.name}</div>
      {charger.address && <div className="mt-0.5 text-xs text-slate-500">{charger.address}</div>}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span className="flex items-center gap-1.5 font-medium" style={{ color }}>
          <span className="h-2 w-2 rounded-full" style={{ background: color }} />
          {level === "unknown" ? label : `${available ?? 0}/${total} available`}
        </span>
        {formatKw(charger.max_charge_rate_kw) && <span className="text-slate-600">up to {formatKw(charger.max_charge_rate_kw)}</span>}
        {typeof charger.rating === "number" && (
          <span className="flex items-center gap-0.5 text-slate-600">
            <StarIcon size={12} className="text-amber-500" />
            {charger.rating.toFixed(1)}
            {typeof charger.review_count === "number" && <span className="text-slate-400"> ({charger.review_count})</span>}
          </span>
        )}
      </div>

      {charger.connectors.length > 0 && (
        <ul className="mt-2.5 divide-y divide-slate-100 rounded-lg border border-slate-200 text-xs">
          {charger.connectors.map((c, i) => (
            <li key={`${c.type}-${i}`} className="flex items-center justify-between gap-2 px-2.5 py-1.5">
              <span className="font-medium text-slate-800">
                {formatConnector(c.type)}
                {formatKw(c.max_charge_rate_kw) && <span className="font-normal text-slate-500"> · {formatKw(c.max_charge_rate_kw)}</span>}
              </span>
              <span className="text-slate-600">
                {typeof c.available_count === "number" ? `${c.available_count}/${c.count ?? "?"} free` : `${c.count ?? "?"} total`}
                {typeof c.out_of_service_count === "number" && c.out_of_service_count > 0 && (
                  <span className="text-red-600"> · {c.out_of_service_count} out of service</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {(typeof charger.detour_duration_min === "number" || typeof charger.detour_distance_km === "number") && (
        <div className="mt-2 text-xs text-slate-600">
          Detour: {typeof charger.detour_duration_min === "number" ? `+${formatDuration(charger.detour_duration_min)}` : ""}
          {typeof charger.detour_distance_km === "number" ? ` (${formatKm(charger.detour_distance_km, 1)})` : ""}
        </div>
      )}
      {charger.amenity_summary && <div className="mt-1.5 text-xs text-slate-600">{charger.amenity_summary}</div>}
      {charger.source === "open_charge_map" && (
        <div className="mt-1.5 text-[11px] text-slate-400">Source: Open Charge Map (no live availability)</div>
      )}

      <a
        href={chargerMapsUrl(charger)}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-emerald-700 hover:underline"
      >
        Open in Google Maps
        <ExternalIcon size={12} />
      </a>
    </div>
  );
}
