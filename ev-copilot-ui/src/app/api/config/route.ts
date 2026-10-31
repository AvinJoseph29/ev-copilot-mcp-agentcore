/**
 * GET /api/config — runtime browser configuration.
 *
 * The Maps JavaScript API key and Map ID are read from the server environment at request
 * time (not NEXT_PUBLIC_* build-time variables), so one container image works everywhere.
 * The browser key is meant to be public but HTTP-referrer restricted.
 */

import type { MapsConfig } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(): Response {
  // The infra seeds the key secret with "REPLACE_ME"; treat it as unset so the map placeholder shows.
  const rawKey = (process.env.GOOGLE_MAPS_BROWSER_API_KEY ?? "").trim();
  const config: MapsConfig = {
    mapsApiKey: rawKey === "REPLACE_ME" ? "" : rawKey,
    mapId: process.env.GOOGLE_MAPS_MAP_ID || "DEMO_MAP_ID",
  };
  return Response.json(config, { headers: { "Cache-Control": "no-store" } });
}
