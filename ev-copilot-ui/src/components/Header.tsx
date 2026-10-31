"use client";

import type { UserLocation } from "@/lib/types";
import type { LocationStatus as LocationStatusValue } from "@/lib/use-ev-copilot";

import { BoltIcon, PlusIcon, SettingsIcon } from "./Icons";
import LocationStatus from "./LocationStatus";

interface HeaderProps {
  customerName: string;
  location: UserLocation | null;
  locationStatus: LocationStatusValue;
  onUseMyLocation: () => void;
  onNewChat: () => void;
  onOpenSettings: () => void;
}

export default function Header({
  customerName,
  location,
  locationStatus,
  onUseMyLocation,
  onNewChat,
  onOpenSettings,
}: HeaderProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4 sm:px-5">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-white shadow-sm">
          <BoltIcon size={17} strokeWidth={2.2} />
        </span>
        <div className="min-w-0 leading-tight">
          <div className="text-[15px] font-semibold tracking-tight">EV Copilot</div>
          <div className="hidden truncate text-xs text-ink-3 sm:block">Electric road-trip planner</div>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <LocationStatus location={location} status={locationStatus} onUseMyLocation={onUseMyLocation} />

        <span className="hidden items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs text-ink-2 md:flex">
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent-soft text-[10px] font-semibold text-accent-ink uppercase">
            {customerName.slice(0, 1)}
          </span>
          <span className="max-w-[10rem] truncate">{customerName}</span>
        </span>

        <button
          type="button"
          onClick={onNewChat}
          className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm font-medium text-ink transition hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          <PlusIcon size={16} />
          <span className="hidden sm:inline">New chat</span>
        </button>

        <button
          type="button"
          onClick={onOpenSettings}
          aria-label="Settings"
          title="Settings"
          className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-2 transition hover:bg-surface-3 hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          <SettingsIcon size={18} />
        </button>
      </div>
    </header>
  );
}
