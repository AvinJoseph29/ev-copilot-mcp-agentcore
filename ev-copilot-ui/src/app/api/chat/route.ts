/**
 * POST /api/chat — streaming proxy from the browser to the EV Copilot agent.
 *
 * Request body (from the browser): {prompt, customer_name, conversation_id, latitude?, longitude?}
 * Response: `text/event-stream` of clean, single-encoded `data: {json}\n\n` events (spec §6.3),
 * regardless of whether the agent sent double-encoded SSE, plain SSE or a JSON error body.
 */

import { encodeSseEvent, invokeAgent } from "@/lib/agent-client";
import type { AgentPayload } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * SSE comment sent while the agent is silent (router, tools, reflection) so idle-timeout proxies
 * do not drop the connection. It does not extend a total request limit such as App Runner's fixed
 * 120 s: a turn cut off there ends without `done` and the browser shows it as interrupted.
 */
const KEEPALIVE_INTERVAL_MS = 15_000;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function buildPayload(body: unknown): AgentPayload | null {
  if (typeof body !== "object" || body === null) return null;
  const data = body as Record<string, unknown>;

  const prompt = typeof data.prompt === "string" ? data.prompt : "";
  if (!prompt.trim()) return null;

  const customerName = typeof data.customer_name === "string" && data.customer_name.trim() ? data.customer_name.trim() : "Guest";
  const conversationId =
    typeof data.conversation_id === "string" && data.conversation_id ? data.conversation_id : crypto.randomUUID();

  const payload: AgentPayload = { prompt, customer_name: customerName, conversation_id: conversationId };

  // Include coordinates only when both are valid
  const { latitude, longitude } = data;
  if (
    isFiniteNumber(latitude) &&
    isFiniteNumber(longitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180
  ) {
    payload.latitude = latitude;
    payload.longitude = longitude;
  }
  return payload;
}

export async function POST(request: Request): Promise<Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const payload = buildPayload(body);
  if (!payload) {
    return Response.json({ error: "No prompt provided in the payload." }, { status: 400 });
  }

  const encoder = new TextEncoder();
  const upstream = new AbortController();
  request.signal.addEventListener("abort", () => upstream.abort(), { once: true });

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      let closed = false;
      const send = (text: string) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(text));
        } catch {
          closed = true;
        }
      };

      const keepalive = setInterval(() => send(": keepalive\n\n"), KEEPALIVE_INTERVAL_MS);
      try {
        for await (const event of invokeAgent(payload, upstream.signal)) {
          send(encodeSseEvent(event));
          if (closed) break;
        }
      } finally {
        clearInterval(keepalive);
        if (!closed) {
          closed = true;
          try {
            controller.close();
          } catch {
            // already closed by a cancelled reader
          }
        }
      }
    },
    cancel() {
      upstream.abort();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      // no-transform keeps compression middleware from buffering the stream
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
