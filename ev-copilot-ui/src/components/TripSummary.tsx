"use client";

import { formatDuration, formatKm, formatKwh, formatPercent } from "@/lib/format";
import type { TripEnergyPlan } from "@/lib/types";

import BatteryChart from "./BatteryChart";
import { AlertIcon, CheckIcon } from "./Icons";

interface TripSummaryProps {
  plan: TripEnergyPlan;
  dark: boolean;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-2.5">
      <div className="text-[11px] font-medium tracking-wide text-ink-3 uppercase">{label}</div>
      <div className="mt-0.5 text-base font-semibold text-ink tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-ink-3">{sub}</div>}
    </div>
  );
}

/** Totals, feasibility, charging stops and the battery chart for a simulated plan. */
export default function TripSummary({ plan, dark }: TripSummaryProps) {
  const firstSoc = plan.legs[0]?.start_soc_percent ?? plan.soc_timeline[0]?.soc_percent;

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-ink">{plan.vehicle_name || "Trip plan"}</h2>
        {plan.feasible ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-good/10 px-2 py-0.5 text-[11px] font-semibold text-good">
            <CheckIcon size={12} strokeWidth={2.6} />
            Feasible plan
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-bad/10 px-2 py-0.5 text-[11px] font-semibold text-bad">
            <AlertIcon size={12} strokeWidth={2.4} />
            Needs changes
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Stat label="Distance" value={formatKm(plan.total_distance_km)} />
        <Stat label="Total time" value={formatDuration(plan.total_trip_min)} sub={`${formatDuration(plan.total_drive_min)} driving`} />
        <Stat label="Charging" value={formatDuration(plan.total_charge_min)} sub={`${plan.stops.length} stop${plan.stops.length === 1 ? "" : "s"}`} />
        <Stat label="Energy used" value={formatKwh(plan.energy_used_kwh)} />
        <Stat label="Start battery" value={formatPercent(firstSoc)} />
        <Stat label="Arrival battery" value={formatPercent(plan.arrival_soc_percent)} />
      </div>

      {plan.issues.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-xl border border-bad/30 bg-bad/5 px-3 py-2.5 text-xs text-ink">
          {plan.issues.map((issue, i) => (
            <li key={i} className="flex gap-2">
              <AlertIcon size={14} className="mt-px shrink-0 text-bad" />
              <span>{issue}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="rounded-xl border border-line bg-surface px-3 pt-2.5 pb-2">
        <BatteryChart plan={plan} dark={dark} />
      </div>

      {plan.stops.length > 0 && (
        <ol className="flex flex-col gap-2">
          {plan.stops.map((stop, i) => (
            <li key={`${stop.index}-${i}`} className="flex items-start gap-3 rounded-xl border border-line bg-surface px-3 py-2.5">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-xs font-bold text-white">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-ink">{stop.name || `Charging stop ${i + 1}`}</div>
                <div className="mt-0.5 text-xs text-ink-3 tabular-nums">
                  {Math.round(stop.arrival_soc_percent)}% → {Math.round(stop.departure_soc_percent)}% · {formatDuration(stop.charge_min)} at{" "}
                  {Math.round(stop.charger_power_kw)} kW · +{stop.energy_added_kwh.toFixed(1)} kWh
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}

      <details className="rounded-xl border border-line bg-surface text-xs">
        <summary className="cursor-pointer px-3 py-2 font-medium text-ink-2 select-none">Leg details & assumptions</summary>
        <div className="overflow-x-auto border-t border-line">
          <table className="w-full text-left tabular-nums">
            <thead className="text-ink-3">
              <tr>
                <th className="px-3 py-1.5 font-medium">Leg</th>
                <th className="px-3 py-1.5 font-medium">Distance</th>
                <th className="px-3 py-1.5 font-medium">Time</th>
                <th className="px-3 py-1.5 font-medium">Climb</th>
                <th className="px-3 py-1.5 font-medium">Energy</th>
                <th className="px-3 py-1.5 font-medium">Battery</th>
              </tr>
            </thead>
            <tbody className="text-ink-2">
              {plan.legs.map((leg, i) => (
                <tr key={`${leg.index}-${i}`} className="border-t border-line">
                  <td className="px-3 py-1.5">{i + 1}</td>
                  <td className="px-3 py-1.5">{formatKm(leg.distance_km)}</td>
                  <td className="px-3 py-1.5">{formatDuration(leg.duration_min)}</td>
                  <td className="px-3 py-1.5">+{Math.round(leg.ascent_m)} m</td>
                  <td className="px-3 py-1.5">{formatKwh(leg.energy_kwh)}</td>
                  <td className={`px-3 py-1.5 ${leg.below_buffer ? "font-semibold text-bad" : ""}`}>
                    {Math.round(leg.start_soc_percent)}% → {Math.round(leg.arrival_soc_percent)}%
                    {leg.below_buffer && " (below reserve)"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {plan.assumptions.length > 0 && (
          <ul className="list-disc border-t border-line py-2 pr-3 pl-7 text-ink-3">
            {plan.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        )}
      </details>
    </section>
  );
}
