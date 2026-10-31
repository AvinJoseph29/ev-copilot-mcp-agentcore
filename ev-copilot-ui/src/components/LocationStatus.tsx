"use client";

import { formatCoordinates } from "@/lib/session";
import type { UserLocation } from "@/lib/types";
import type { LocationStatus as LocationStatusValue } from "@/lib/use-ev-copilot";

import { LocateIcon, PinIcon, SpinnerIcon } from "./Icons";

interface LocationStatusProps {
  location: UserLocation | null;
  status: LocationStatusValue;
  onUseMyLocation: () => void;
}

/** Location pill: shows the coordinates sent to the agent and offers "Use my location". */
export default function LocationStatus({ location, status, onUseMyLocation }: LocationStatusProps) {
  if (status === "detecting") {
    return (
      <span className="flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs text-ink-2">
        <SpinnerIcon size={13} />
        <span className="hidden sm:inline">Detecting location…</span>
      </span>
    );
  }

  return (
    <div className="flex items-center gap-1">
      {location ? (
        <span
          className="hidden items-center gap-1.5 rounded-full border border-line px-2.5 py-1 font-mono text-xs text-ink-2 sm:flex"
          title="Location sent to EV Copilot with every message. Override with !location <lat> <lng>"
        >
          <PinIcon size={13} className="text-accent" />
          {formatCoordinates(location)}
        </span>
      ) : (
        <span className="hidden items-center gap-1.5 rounded-full border border-warn/40 bg-warn/10 px-2.5 py-1 text-xs font-medium text-ink sm:flex">
          <PinIcon size={13} className="text-warn" />
          Location needed
        </span>
      )}
      <button
        type="button"
        onClick={onUseMyLocation}
        title="Use my location"
        aria-label="Use my location"
        className="flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-ink-2 transition hover:bg-surface-3 hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
      >
        <LocateIcon size={16} />
        <span className="hidden xl:inline">Use my location</span>
      </button>
    </div>
  );
}
