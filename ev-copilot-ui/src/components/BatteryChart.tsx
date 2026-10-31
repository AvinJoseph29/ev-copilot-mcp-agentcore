"use client";

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";

import { formatKm } from "@/lib/format";
import { planBufferPercent } from "@/lib/trip-state";
import type { TripEnergyPlan } from "@/lib/types";

const PALETTE = {
  light: { line: "#059669", grid: "#e2e8f0", axis: "#64748b", buffer: "#d97706", stop: "#94a3b8", bad: "#dc2626", surface: "#ffffff" },
  dark: { line: "#10b981", grid: "#263244", axis: "#8592a6", buffer: "#f59e0b", stop: "#475569", bad: "#f87171", surface: "#111827" },
};

interface BatteryChartProps {
  plan: TripEnergyPlan;
  dark: boolean;
}

function ChartTooltip({ active, payload }: TooltipContentProps<ValueType, NameType>) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload as { distance_km: number; soc_percent: number };
  return (
    <div className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs shadow-md">
      <div className="font-semibold text-ink">{Math.round(point.soc_percent)}% battery</div>
      <div className="text-ink-3">at {formatKm(point.distance_km)}</div>
    </div>
  );
}

/** State of charge along the trip (soc_timeline) with the reserve buffer and charging stops marked. */
export default function BatteryChart({ plan, dark }: BatteryChartProps) {
  const colors = dark ? PALETTE.dark : PALETTE.light;
  const buffer = planBufferPercent(plan);

  const data = useMemo(
    () => plan.soc_timeline.filter((p) => Number.isFinite(p.distance_km) && Number.isFinite(p.soc_percent)),
    [plan.soc_timeline],
  );

  // Each charging stop sits at the end of the leg with the same index.
  const stopDistances = useMemo(() => {
    const legs = plan.legs.slice(0, plan.stops.length);
    return legs.map((_, i) => legs.slice(0, i + 1).reduce((sum, leg) => sum + leg.distance_km, 0));
  }, [plan.legs, plan.stops.length]);

  // End the axis at the rounded trip distance so its last tick matches the "Distance" stat
  // (the timeline is rounded to 0.1 km and can overshoot the total by a few metres).
  const maxDistance = Math.max(
    Math.round(plan.total_distance_km || Math.max(...data.map((p) => p.distance_km), 0)),
    1,
  );

  if (data.length < 2) {
    return <div className="py-6 text-center text-xs text-ink-3">Not enough data to chart the battery level.</div>;
  }

  return (
    <figure className="m-0">
      <figcaption className="mb-1 flex items-center justify-between text-xs text-ink-3">
        <span className="font-medium text-ink-2">Battery along the route</span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0 w-4 border-t-2 border-dashed" style={{ borderColor: colors.buffer }} />
          Reserve {buffer}%
        </span>
      </figcaption>
      <div className="h-[190px] w-full" role="img" aria-label={`Battery level from ${Math.round(data[0].soc_percent)}% to ${Math.round(plan.arrival_soc_percent)}% over ${Math.round(maxDistance)} km`}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 16, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke={colors.grid} strokeWidth={1} vertical={false} />
            <XAxis
              dataKey="distance_km"
              type="number"
              domain={[0, maxDistance]}
              allowDataOverflow
              tickFormatter={(v: number) => `${Math.round(v)} km`}
              tick={{ fill: colors.axis, fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: colors.grid }}
              minTickGap={24}
            />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              tickFormatter={(v: number) => `${v}%`}
              tick={{ fill: colors.axis, fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={48}
            />
            {stopDistances.map((x, i) => (
              <ReferenceLine
                key={`stop-${i}`}
                x={x}
                stroke={colors.stop}
                strokeWidth={1}
                label={{ value: String(i + 1), position: "top", fill: colors.axis, fontSize: 11, fontWeight: 600 }}
              />
            ))}
            <ReferenceLine y={buffer} stroke={colors.buffer} strokeWidth={1.5} strokeDasharray="5 4" ifOverflow="extendDomain" />
            <Tooltip
              content={ChartTooltip}
              cursor={{ stroke: colors.axis, strokeWidth: 1 }}
              isAnimationActive={false}
            />
            <Area
              type="linear"
              dataKey="soc_percent"
              stroke={colors.line}
              strokeWidth={2}
              fill={colors.line}
              fillOpacity={0.12}
              isAnimationActive={false}
              dot={false}
              activeDot={{ r: 4, fill: colors.line, stroke: colors.surface, strokeWidth: 2 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
