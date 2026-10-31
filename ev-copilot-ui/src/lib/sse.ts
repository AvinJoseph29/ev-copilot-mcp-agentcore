/**
 * Tolerant SSE parsing for the agent stream (isomorphic: used by the server proxy and the browser).
 *
 * The agent yields strings that are already SSE frames (`data: {...}\n\n`) and
 * BedrockAgentCoreApp re-wraps every yielded item as SSE, so each wire line is
 * double-encoded:
 *
 *     data: "data: {\"chunk\": \"Hello\"}\n\n"
 *
 * This module accepts both that form and the plain `data: {json}` form (which is also
 * what the `/api/chat` proxy re-emits to the browser), plus non-SSE JSON bodies such as
 * `{"error": "No prompt provided in the payload."}`. Malformed lines are skipped silently,
 * matching the reference UI.
 */

import type { AgentEvent, ToolStatus } from "./types";

export const DEFAULT_BLOCKED_MESSAGE = "Your message was blocked by the safety filter.";

/** Max nesting of string-wrapped SSE frames we are willing to unwrap. */
const MAX_DECODE_DEPTH = 3;

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Strip the AgentCore Gateway target prefix (`<appName>-McpTarget___`) from a tool name. */
export function baseToolName(name: string): string {
  const idx = name.lastIndexOf("___");
  return idx >= 0 ? name.slice(idx + 3) : name;
}

function parseToolResult(result: unknown): unknown {
  if (typeof result !== "string") return result ?? null;
  try {
    return JSON.parse(result);
  } catch {
    return null;
  }
}

/**
 * Map an inner JSON event (spec §6.3) to a typed {@link AgentEvent}.
 * Returns null for objects that are not a known event.
 */
export function normalizeAgentEvent(data: unknown): AgentEvent | null {
  if (!isObject(data)) return null;

  if ("chunk" in data) {
    const chunk = data.chunk;
    return { type: "chunk", text: typeof chunk === "string" ? chunk : String(chunk ?? "") };
  }
  if (data.blocked) {
    const message = typeof data.message === "string" && data.message ? data.message : DEFAULT_BLOCKED_MESSAGE;
    return { type: "blocked", message };
  }
  if ("error" in data) {
    const error = data.error;
    return {
      type: "error",
      message: typeof error === "string" ? error : JSON.stringify(error),
      mapped: data.mapped === true,
    };
  }
  if (isObject(data.tool_start)) {
    const start = data.tool_start;
    return { type: "tool_start", id: String(start.id ?? ""), name: baseToolName(String(start.name ?? "")) };
  }
  if (isObject(data.tool_end)) {
    const end = data.tool_end;
    const status: ToolStatus = end.status === "error" ? "error" : "success";
    return {
      type: "tool_end",
      id: String(end.id ?? ""),
      name: baseToolName(String(end.name ?? "")),
      status,
      result: parseToolResult(end.result),
    };
  }
  if (data.reset) return { type: "reset" };
  if (data.done) return { type: "done" };
  return null;
}

function decodePayload(raw: string, depth: number): AgentEvent[] {
  if (depth > MAX_DECODE_DEPTH) return [];
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return [];
  }
  return decodeValue(data, depth);
}

function decodeValue(data: unknown, depth: number): AgentEvent[] {
  if (typeof data === "string") {
    const inner = data.trim();
    // Nested SSE frame(s): 'data: {"chunk": "Hello"}\n\n'
    if (inner.startsWith("data:")) {
      return inner.split(/\r?\n/).flatMap((line) => {
        const trimmed = line.trim();
        return trimmed.startsWith("data:") ? decodePayload(trimmed.slice(5).trimStart(), depth + 1) : [];
      });
    }
    // JSON-encoded JSON object without the SSE prefix
    if (inner.startsWith("{")) return decodePayload(inner, depth + 1);
    return [];
  }
  const event = normalizeAgentEvent(data);
  return event ? [event] : [];
}

/**
 * Parse one SSE line. Lines that are not `data:` fields (comments, blank separators,
 * `event:`/`id:` fields) and malformed JSON yield no events.
 */
export function parseSseLine(line: string): AgentEvent[] {
  const trimmed = line.trim();
  if (!trimmed.startsWith("data:")) return [];
  return decodePayload(trimmed.slice(5).trimStart(), 0);
}

/**
 * Parse a non-`text/event-stream` response body (e.g. `application/json`).
 * A JSON event object maps to that event (`{"error": ...}` → error); other JSON or plain
 * text is surfaced as a single chunk so nothing is silently lost.
 */
export function parseNonSseBody(text: string): AgentEvent[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith("data:")) return trimmed.split(/\r?\n/).flatMap(parseSseLine);
  let data: unknown;
  try {
    data = JSON.parse(trimmed);
  } catch {
    return [{ type: "chunk", text: trimmed }];
  }
  if (typeof data === "string") {
    return data.trim().startsWith("data:") ? decodeValue(data, 0) : [{ type: "chunk", text: data }];
  }
  const event = normalizeAgentEvent(data);
  return event ? [event] : [{ type: "chunk", text: trimmed }];
}

/**
 * Read an SSE byte stream and yield decoded events.
 * Uses a streaming TextDecoder so multi-byte UTF-8 characters split across network
 * chunks are decoded correctly. If the consumer stops early (blocked/error event, client
 * disconnect), the underlying stream is cancelled so the upstream connection is released.
 */
export async function* readSseEvents(stream: ReadableStream<Uint8Array>): AsyncGenerator<AgentEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let finished = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        finished = true;
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline >= 0) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        yield* parseSseLine(line);
        newline = buffer.indexOf("\n");
      }
    }
    buffer += decoder.decode();
    if (buffer) yield* parseSseLine(buffer);
  } finally {
    if (!finished) await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

/** Serialize an event back to the clean (single-encoded) §6.3 wire shape. */
export function encodeSseEvent(event: AgentEvent): string {
  let body: JsonObject;
  switch (event.type) {
    case "chunk":
      body = { chunk: event.text };
      break;
    case "done":
      body = { done: true };
      break;
    case "error":
      body = event.mapped ? { error: event.message, mapped: true } : { error: event.message };
      break;
    case "blocked":
      body = { blocked: true, message: event.message };
      break;
    case "tool_start":
      body = { tool_start: { id: event.id, name: event.name } };
      break;
    case "tool_end":
      body = { tool_end: { id: event.id, name: event.name, status: event.status, result: event.result ?? null } };
      break;
    case "reset":
      body = { reset: true };
      break;
  }
  return `data: ${JSON.stringify(body)}\n\n`;
}
