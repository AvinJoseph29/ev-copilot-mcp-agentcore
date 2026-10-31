"use client";

import dynamic from "next/dynamic";

import { BoltIcon } from "./Icons";

/**
 * The app shell reads sessionStorage/localStorage and navigator.geolocation on first render,
 * so it is rendered on the client only (no hydration mismatch, no storage-reading effects).
 */
const EvCopilotApp = dynamic(() => import("./EvCopilotApp"), {
  ssr: false,
  loading: () => (
    <div className="flex h-dvh items-center justify-center bg-bg">
      <div className="flex items-center gap-3 text-ink-2">
        <span className="flex h-9 w-9 animate-pulse items-center justify-center rounded-xl bg-accent text-white">
          <BoltIcon size={18} />
        </span>
        <span className="text-sm font-medium">Starting EV Copilot…</span>
      </div>
    </div>
  ),
});

export default function ClientApp() {
  return <EvCopilotApp />;
}
