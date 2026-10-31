/** Display formatting helpers shared by the trip panel, chart and map info windows. */

export function formatDuration(minutes: number | null | undefined): string {
  if (typeof minutes !== "number" || !Number.isFinite(minutes)) return "—";
  const total = Math.max(0, Math.round(minutes));
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

export function formatKm(km: number | null | undefined, digits = 0): string {
  if (typeof km !== "number" || !Number.isFinite(km)) return "—";
  return `${km.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 })} km`;
}

export function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${Math.round(value)}%`;
}

export function formatKw(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return "";
  return `${Math.round(value)} kW`;
}

export function formatKwh(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value.toFixed(1)} kWh`;
}

/** "CCS2" / "TYPE_2" / "CHADEMO" → "CCS2" / "Type 2" / "CHAdeMO". */
export function formatConnector(type: string): string {
  const labels: Record<string, string> = {
    CCS1: "CCS1",
    CCS2: "CCS2",
    CHADEMO: "CHAdeMO",
    TYPE_2: "Type 2",
    J1772: "J1772",
    TESLA: "Tesla",
    NACS: "NACS",
    GB_T: "GB/T",
    OTHER: "Other",
  };
  return labels[type] ?? type.replace(/_/g, " ");
}
