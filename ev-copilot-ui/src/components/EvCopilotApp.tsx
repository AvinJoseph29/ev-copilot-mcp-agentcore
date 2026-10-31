"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { hasTripData } from "@/lib/trip-state";
import type { MapsConfig } from "@/lib/types";
import { useEvCopilot } from "@/lib/use-ev-copilot";
import { usePrefersDark } from "@/lib/use-prefers-dark";

import ChatPanel from "./ChatPanel";
import Header from "./Header";
import { ChatIcon, MapIcon } from "./Icons";
import MapPanel from "./MapPanel";
import SettingsDialog from "./SettingsDialog";
import TripPanel from "./TripPanel";

export type MapsConfigState = { status: "loading" } | { status: "ready"; config: MapsConfig };

/** Fetch the runtime map configuration (browser key + map id) once. */
function useMapsConfig(): MapsConfigState {
  const [state, setState] = useState<MapsConfigState>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    fetch("/api/config", { cache: "no-store" })
      .then((res) => (res.ok ? (res.json() as Promise<MapsConfig>) : Promise.reject(new Error(String(res.status)))))
      .catch((): MapsConfig => ({ mapsApiKey: "", mapId: "DEMO_MAP_ID" }))
      .then((config) => {
        if (!cancelled) setState({ status: "ready", config });
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}

export default function EvCopilotApp() {
  const chat = useEvCopilot();
  const mapsConfig = useMapsConfig();
  const dark = usePrefersDark();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mobileView, setMobileView] = useState<"chat" | "map">("chat");
  const [draft, setDraft] = useState("");
  const [selectedChargerId, setSelectedChargerId] = useState<string | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  // Badge the mobile "Map" tab when new trip data arrives while the chat tab is shown.
  const [seenFitVersion, setSeenFitVersion] = useState(0);
  const tripUpdated = chat.trip.fitVersion > seenFitVersion;
  const showMobileView = (view: "chat" | "map") => {
    setMobileView(view);
    if (view === "map") setSeenFitVersion(chat.trip.fitVersion);
  };

  const handleNewChat = useCallback(() => {
    chat.newChat();
    setDraft("");
    setSelectedChargerId(null);
    setSeenFitVersion(0);
    setMobileView("chat");
  }, [chat]);

  const handleSend = useCallback(
    (text: string) => {
      setDraft("");
      void chat.sendMessage(text);
    },
    [chat],
  );

  const handlePickExample = useCallback((text: string) => {
    setDraft(text);
    requestAnimationFrame(() => composerRef.current?.focus());
  }, []);

  return (
    <div className="flex h-dvh flex-col bg-bg text-ink">
      <Header
        customerName={chat.customerName}
        location={chat.location}
        locationStatus={chat.locationStatus}
        onUseMyLocation={() => void chat.requestBrowserLocation()}
        onNewChat={handleNewChat}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      {/* Mobile view switcher */}
      <div className="flex gap-1 border-b border-line bg-surface px-4 py-2 lg:hidden" role="tablist" aria-label="View">
        {(
          [
            { id: "chat", label: "Chat", icon: <ChatIcon size={16} /> },
            { id: "map", label: "Map & trip", icon: <MapIcon size={16} /> },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={mobileView === tab.id}
            onClick={() => showMobileView(tab.id)}
            className={`relative flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              mobileView === tab.id ? "bg-surface-3 text-ink" : "text-ink-3 hover:text-ink"
            }`}
          >
            {tab.icon}
            {tab.label}
            {tab.id === "map" && tripUpdated && mobileView !== "map" && (
              <span className="absolute top-1.5 right-3 h-2 w-2 rounded-full bg-accent" aria-label="New trip data" />
            )}
          </button>
        ))}
      </div>

      <main className="flex min-h-0 flex-1 lg:grid lg:grid-cols-[minmax(380px,2fr)_3fr]">
        <section
          aria-label="Chat"
          className={`${mobileView === "chat" ? "flex" : "hidden"} min-h-0 min-w-0 flex-1 flex-col border-line lg:flex lg:border-r`}
        >
          <ChatPanel
            messages={chat.messages}
            isStreaming={chat.isStreaming}
            hasLocation={chat.location !== null}
            draft={draft}
            onDraftChange={setDraft}
            onSend={handleSend}
            onPickExample={handlePickExample}
            composerRef={composerRef}
          />
        </section>

        <section
          aria-label="Map and trip"
          className={`${mobileView === "map" ? "flex" : "hidden"} min-h-0 min-w-0 flex-1 flex-col lg:flex`}
        >
          <MapPanel
            configState={mapsConfig}
            trip={chat.trip}
            userLocation={chat.location}
            selectedChargerId={selectedChargerId}
            onSelectCharger={setSelectedChargerId}
            dark={dark}
          />
          <TripPanel
            trip={chat.trip}
            hasData={hasTripData(chat.trip)}
            selectedChargerId={selectedChargerId}
            onSelectCharger={(id) => {
              setSelectedChargerId(id);
              setMobileView("map");
            }}
            dark={dark}
          />
        </section>
      </main>

      <SettingsDialog
        open={settingsOpen}
        initialName={chat.customerName}
        onClose={() => setSettingsOpen(false)}
        onSave={(name) => {
          chat.updateCustomerName(name);
          setSettingsOpen(false);
        }}
      />
    </div>
  );
}
