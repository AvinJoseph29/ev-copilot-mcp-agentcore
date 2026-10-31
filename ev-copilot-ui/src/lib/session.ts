/**
 * Browser session helpers (client only).
 *
 * - conversation_id: one uuid4 per chat, kept in sessionStorage so a page refresh continues
 *   the same agent thread (also used as AgentCore `runtimeSessionId`).
 * - customer name: persisted in localStorage (default "Guest").
 * - location: kept in sessionStorage for the tab's lifetime; detected via browser geolocation
 *   or set manually with `!location <lat> <lng>`.
 *
 * Every storage access is wrapped in try/catch: storage can be unavailable (private mode,
 * blocked site data) and the app must still work in-memory.
 */

import type { UserLocation } from "./types";

const CONVERSATION_KEY = "evcopilot.conversation_id";
const NAME_KEY = "evcopilot.customer_name";
const LOCATION_KEY = "evcopilot.location";

export const DEFAULT_CUSTOMER_NAME = "Guest";

function read(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

function write(storage: () => Storage, key: string, value: string | null): void {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    // storage unavailable: keep the value in memory only
  }
}

const session = () => window.sessionStorage;
const local = () => window.localStorage;

/** RFC 4122 v4 UUID (crypto.randomUUID is only available in secure contexts). */
export function uuid4(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function getConversationId(): string {
  const existing = read(session, CONVERSATION_KEY);
  if (existing) return existing;
  return newConversationId();
}

export function newConversationId(): string {
  const id = uuid4();
  write(session, CONVERSATION_KEY, id);
  return id;
}

export function getCustomerName(): string {
  return read(local, NAME_KEY)?.trim() || DEFAULT_CUSTOMER_NAME;
}

export function setCustomerName(name: string): string {
  const value = name.trim() || DEFAULT_CUSTOMER_NAME;
  write(local, NAME_KEY, value);
  return value;
}

export function isValidCoordinate(latitude: number, longitude: number): boolean {
  return (
    Number.isFinite(latitude) &&
    Number.isFinite(longitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180
  );
}

export function getStoredLocation(): UserLocation | null {
  const raw = read(session, LOCATION_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<UserLocation>;
    if (typeof parsed.latitude === "number" && typeof parsed.longitude === "number" && isValidCoordinate(parsed.latitude, parsed.longitude)) {
      return { latitude: parsed.latitude, longitude: parsed.longitude };
    }
  } catch {
    // ignore corrupt value
  }
  return null;
}

export function storeLocation(location: UserLocation | null): void {
  write(session, LOCATION_KEY, location ? JSON.stringify(location) : null);
}

/**
 * Parse a `!location <lat> <lng>` command.
 * Returns undefined when the text is not a location command, null when it is malformed.
 */
export function parseLocationCommand(text: string): UserLocation | null | undefined {
  const trimmed = text.trim();
  if (!trimmed.toLowerCase().startsWith("!location")) return undefined;
  const parts = trimmed.split(/\s+/);
  if (parts.length < 3) return null;
  const latitude = Number(parts[1]);
  const longitude = Number(parts[2]);
  if (parts[1] === "" || parts[2] === "" || !isValidCoordinate(latitude, longitude)) return null;
  return { latitude, longitude };
}

/** Promise wrapper around navigator.geolocation (requires HTTPS or localhost). */
export function detectBrowserLocation(timeoutMs = 10_000): Promise<UserLocation | null> {
  return new Promise((resolve) => {
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: timeoutMs, maximumAge: 5 * 60_000 },
    );
  });
}

export function formatCoordinates(location: UserLocation): string {
  return `${location.latitude.toFixed(4)}, ${location.longitude.toFixed(4)}`;
}
