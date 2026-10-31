"use client";

/**
 * Client-side chat controller: the Next.js equivalent of the reference Chainlit
 * `on_chat_start` / `on_settings_update` / `on_message` / `_invoke_agent` handlers.
 *
 * Must only be used in a component rendered on the client (the app shell is loaded with
 * `ssr: false`), because the initial state is read from browser storage.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  detectBrowserLocation,
  getConversationId,
  getCustomerName,
  getStoredLocation,
  newConversationId,
  parseLocationCommand,
  setCustomerName,
  storeLocation,
  uuid4,
} from "./session";
import { readSseEvents } from "./sse";
import { EMPTY_TRIP, MAP_TOOLS, applyToolResult, startTurn, type TripState } from "./trip-state";
import type { AgentPayload, ChatMessage, ToolActivityItem, ToolStatus, UserLocation } from "./types";

export type LocationStatus = "detecting" | "granted" | "unavailable";

// --- Message copy (kept from the reference app, reworded for EV Copilot) ---

const LOCATION_EXAMPLE = "Example: `!location 40.7128 -74.0060` (New York City)";

const DETECTING_MESSAGE = "Detecting your location...";

function locationDetectedMessage(location: UserLocation, name: string): string {
  return (
    `Location detected: **(${location.latitude.toFixed(4)}, ${location.longitude.toFixed(4)})**\n\n` +
    `Welcome, **${name}**! I'm EV Copilot, your electric road-trip assistant. ` +
    "I can plan routes with charging stops, find chargers with live availability, " +
    "estimate your battery at every stop and check the weather for your drive.\n\n" +
    "Where are we driving today?\n\n" +
    "*Tip: To use a different location, type `!location <lat> <lng>` (e.g., `!location 40.7128 -74.0060`). " +
    "Click the settings icon to update your name.*"
  );
}

const LOCATION_FAILED_MESSAGE =
  "Could not detect your location automatically.\n\n" +
  "Please provide your coordinates by typing:\n" +
  "`!location <latitude> <longitude>`\n\n" +
  `${LOCATION_EXAMPLE}\n\n` +
  "*Or click **Use my location** and allow location access in your browser.*";

const LOCATION_INVALID_MESSAGE =
  "Invalid format. Use: `!location <latitude> <longitude>`\n\nExample: `!location 40.7128 -74.0060`";

const LOCATION_GATE_MESSAGE =
  "Please set your location first by typing:\n" +
  "`!location <latitude> <longitude>`\n\n" +
  "Example: `!location 40.7128 -74.0060`";

function locationUpdatedMessage(location: UserLocation): string {
  return `Location updated to **(${location.latitude.toFixed(4)}, ${location.longitude.toFixed(4)})**. You're all set — ask me anything!`;
}

const NO_RESPONSE_MESSAGE = "No response received.";
const INTERRUPTED_MESSAGE = "The response was interrupted. Please try again.";
const INTERRUPTED_NOTE = "\n\n_(Response interrupted — please try again.)_";
const UNEXPECTED_ERROR_MESSAGE = "An unexpected error occurred. Please try again.";

function notice(content: string, id: string = uuid4()): ChatMessage {
  return { id, role: "notice", content };
}

function initialMessages(location: UserLocation | null, detectingId: string): ChatMessage[] {
  return location ? [] : [notice(DETECTING_MESSAGE, detectingId)];
}

export interface EvCopilotController {
  messages: ChatMessage[];
  trip: TripState;
  customerName: string;
  location: UserLocation | null;
  locationStatus: LocationStatus;
  isStreaming: boolean;
  sendMessage: (text: string) => Promise<void>;
  newChat: () => void;
  updateCustomerName: (name: string) => void;
  requestBrowserLocation: () => Promise<void>;
}

export function useEvCopilot(): EvCopilotController {
  // Initial state comes straight from browser storage (client-only render).
  const [storedLocation] = useState(getStoredLocation);
  const [detectingId] = useState(uuid4);
  const [customerName, setCustomerNameState] = useState(getCustomerName);
  const [location, setLocation] = useState<UserLocation | null>(storedLocation);
  const [locationStatus, setLocationStatus] = useState<LocationStatus>(storedLocation ? "granted" : "detecting");
  const [messages, setMessages] = useState<ChatMessage[]>(() => initialMessages(storedLocation, detectingId));
  const [trip, setTrip] = useState<TripState>(EMPTY_TRIP);
  const [isStreaming, setIsStreaming] = useState(false);

  const conversationIdRef = useRef<string>("");
  const abortRef = useRef<AbortController | null>(null);
  const locationRef = useRef<UserLocation | null>(storedLocation);
  const nameRef = useRef(customerName);
  const streamingRef = useRef(false);

  const updateMessage = useCallback((id: string, patch: (message: ChatMessage) => ChatMessage) => {
    setMessages((current) => current.map((m) => (m.id === id ? patch(m) : m)));
  }, []);

  const applyLocation = useCallback((next: UserLocation) => {
    locationRef.current = next;
    setLocation(next);
    setLocationStatus("granted");
    storeLocation(next);
  }, []);

  /** Turn the "Detecting your location..." notice into the detection result message. */
  const handleDetection = useCallback(
    (noticeId: string, detected: UserLocation | null) => {
      if (detected) {
        applyLocation(detected);
        updateMessage(noticeId, (m) => ({ ...m, content: locationDetectedMessage(detected, nameRef.current) }));
      } else {
        setLocationStatus(locationRef.current ? "granted" : "unavailable");
        updateMessage(noticeId, (m) => ({ ...m, content: LOCATION_FAILED_MESSAGE }));
      }
    },
    [applyLocation, updateMessage],
  );

  // on_chat_start: conversation id + location detection (only when no location is stored yet).
  const startedRef = useRef(false);
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    conversationIdRef.current = getConversationId();
    if (!storedLocation) {
      void detectBrowserLocation().then((detected) => handleDetection(detectingId, detected));
    }
  }, [handleDetection, detectingId, storedLocation]);

  const requestBrowserLocation = useCallback(async () => {
    const id = uuid4();
    setLocationStatus("detecting");
    setMessages((current) => [...current, notice(DETECTING_MESSAGE, id)]);
    handleDetection(id, await detectBrowserLocation());
  }, [handleDetection]);

  const updateCustomerName = useCallback((name: string) => {
    const saved = setCustomerName(name);
    nameRef.current = saved;
    setCustomerNameState(saved);
    setMessages((current) => [...current, notice(`Settings updated! Welcome, **${saved}**!`)]);
  }, []);

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    streamingRef.current = false;
    setIsStreaming(false);
    conversationIdRef.current = newConversationId();
    setMessages([]);
    setTrip(EMPTY_TRIP);
  }, []);

  /** Invoke the agent through /api/chat and stream the answer into one assistant bubble. */
  const invokeAgent = useCallback(
    async (prompt: string, current: UserLocation) => {
      const assistantId = uuid4();
      setMessages((list) => [...list, { id: assistantId, role: "assistant", content: "", status: "streaming", tools: [] }]);
      setTrip(startTurn);

      const controller = new AbortController();
      abortRef.current = controller;
      streamingRef.current = true;
      setIsStreaming(true);

      if (!conversationIdRef.current) conversationIdRef.current = getConversationId();
      const payload: AgentPayload = {
        prompt,
        customer_name: nameRef.current,
        conversation_id: conversationIdRef.current,
        latitude: current.latitude,
        longitude: current.longitude,
      };

      let content = "";
      // Steps still running when the turn ends succeed only on a normal `done`.
      const finish = (finalContent: string, status: ChatMessage["status"], toolStatus: ToolStatus) => {
        updateMessage(assistantId, (m) => ({
          ...m,
          content: finalContent,
          status,
          tools: (m.tools ?? []).map((t): ToolActivityItem => (t.status === "running" ? { ...t, status: toolStatus } : t)),
        }));
      };

      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });

        if (!response.ok || !response.body) {
          finish(`API Error (status ${response.status}). Please try again.`, "error", "error");
          return;
        }

        let gotDone = false;
        for await (const event of readSseEvents(response.body)) {
          switch (event.type) {
            case "chunk":
              content += event.text;
              updateMessage(assistantId, (m) => ({ ...m, content }));
              break;
            case "reset":
              // Reflection asked for more data: discard the draft answer, keep tools/map.
              content = "";
              updateMessage(assistantId, (m) => ({ ...m, content }));
              break;
            case "tool_start":
              updateMessage(assistantId, (m) => {
                const tools = m.tools ?? [];
                if (tools.some((t) => t.id === event.id && event.id)) return m;
                return { ...m, tools: [...tools, { id: event.id || uuid4(), name: event.name, status: "running" }] };
              });
              break;
            case "tool_end":
              updateMessage(assistantId, (m) => {
                const tools = m.tools ?? [];
                const index = tools.findIndex((t) => t.id === event.id && t.status === "running");
                const fallback = index < 0 ? tools.findIndex((t) => t.name === event.name && t.status === "running") : index;
                if (fallback < 0) return { ...m, tools: [...tools, { id: event.id || uuid4(), name: event.name, status: event.status }] };
                return { ...m, tools: tools.map((t, i) => (i === fallback ? { ...t, status: event.status } : t)) };
              });
              if (event.status === "success" && MAP_TOOLS.has(event.name) && event.result) {
                setTrip((state) => applyToolResult(state, event.name, event.result));
              }
              break;
            case "blocked":
              finish(event.message, "blocked", "error");
              controller.abort();
              return;
            case "error":
              finish(event.mapped ? event.message : `Error: ${event.message}`, "error", "error");
              controller.abort();
              return;
            case "done":
              gotDone = true;
              break;
          }
        }

        if (gotDone) {
          finish(content || NO_RESPONSE_MESSAGE, "done", "success");
        } else {
          // Stream closed without `done` (e.g. a proxy request time limit): keep the partial answer.
          finish(content ? content + INTERRUPTED_NOTE : INTERRUPTED_MESSAGE, "error", "error");
        }
      } catch {
        // Aborted by "New chat": the bubble is already gone.
        if (controller.signal.aborted) return;
        // A connection dropped mid-answer is an interruption too: keep the partial answer.
        finish(content ? content + INTERRUPTED_NOTE : UNEXPECTED_ERROR_MESSAGE, "error", "error");
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
          streamingRef.current = false;
          setIsStreaming(false);
        }
      }
    },
    [updateMessage],
  );

  // on_message: !location command → location gate → agent call.
  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || streamingRef.current) return;
      setMessages((list) => [...list, { id: uuid4(), role: "user", content: text }]);

      const command = parseLocationCommand(text);
      if (command !== undefined) {
        if (command) {
          applyLocation(command);
          setMessages((list) => [...list, notice(locationUpdatedMessage(command))]);
        } else {
          setMessages((list) => [...list, notice(LOCATION_INVALID_MESSAGE)]);
        }
        return;
      }

      const current = locationRef.current;
      if (!current) {
        setMessages((list) => [...list, notice(LOCATION_GATE_MESSAGE)]);
        return;
      }

      await invokeAgent(text, current);
    },
    [applyLocation, invokeAgent],
  );

  // Abort any in-flight stream when the app unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);

  return {
    messages,
    trip,
    customerName,
    location,
    locationStatus,
    isStreaming,
    sendMessage,
    newChat,
    updateCustomerName,
    requestBrowserLocation,
  };
}
