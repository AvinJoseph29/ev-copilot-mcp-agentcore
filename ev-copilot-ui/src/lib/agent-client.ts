/**
 * Server-side agent client: invokes the EV Copilot agent locally (HTTP) or on AWS
 * (Bedrock AgentCore Runtime) and yields decoded stream events.
 *
 * Mirrors the reference Chainlit app's transport layer (`_local_sse_lines`,
 * `_aws_sse_lines`, `_invoke_agent`), including its error-message mapping, but reads the
 * stream asynchronously so one long agent turn never blocks other users.
 *
 * Never import this module from client components: AWS credentials stay on the server.
 */

import "server-only";

import { BedrockAgentCoreClient, InvokeAgentRuntimeCommand } from "@aws-sdk/client-bedrock-agentcore";

import { parseNonSseBody, readSseEvents } from "./sse";
import type { AgentEvent, AgentPayload } from "./types";

export { encodeSseEvent, parseSseLine, parseNonSseBody, readSseEvents } from "./sse";

// --- Connection mode configuration ---
// Set AGENT_CONNECTION_MODE to "aws" to invoke the deployed AgentCore Runtime on AWS.
// Set to "local" (or leave unset) to call the local API server.
// Settings are read at request time so a single image works in every environment.
export interface AgentSettings {
  mode: "local" | "aws";
  agentCoreApiUrl: string;
  agentRuntimeArn: string;
  awsRegion: string;
}

export function getAgentSettings(): AgentSettings {
  return {
    mode: (process.env.AGENT_CONNECTION_MODE ?? "local").toLowerCase() === "aws" ? "aws" : "local",
    // Local mode settings
    agentCoreApiUrl: process.env.AGENTCORE_API_URL || "http://localhost:8080/invocations",
    // AWS mode settings
    agentRuntimeArn: process.env.AGENT_RUNTIME_ARN ?? "",
    awsRegion: process.env.AWS_REGION || "us-east-2",
  };
}

// Lazily initialized AgentCore client for AWS mode (default credential provider chain:
// App Runner instance role in AWS, profile/env vars locally).
let agentCoreClient: BedrockAgentCoreClient | null = null;

function getAgentCoreClient(region: string): BedrockAgentCoreClient {
  if (agentCoreClient === null) {
    agentCoreClient = new BedrockAgentCoreClient({ region });
  }
  return agentCoreClient;
}

class AgentHttpError extends Error {
  constructor(public readonly status: number) {
    super(`Agent API returned HTTP ${status}`);
    this.name = "AgentHttpError";
  }
}

class AgentConnectionError extends Error {
  constructor(cause: unknown) {
    super("Could not connect to the agent API", { cause });
    this.name = "AgentConnectionError";
  }
}

// ---------------------------------------------------------------------------
// Event generators (local vs AWS)
// ---------------------------------------------------------------------------

/** Yield events from the local HTTP API (`POST AGENTCORE_API_URL`). */
async function* localEvents(
  settings: AgentSettings,
  payload: AgentPayload,
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  let response: Response;
  try {
    response = await fetch(settings.agentCoreApiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new AgentConnectionError(error);
  }

  if (!response.ok) {
    await response.body?.cancel().catch(() => undefined);
    throw new AgentHttpError(response.status);
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream") && response.body) {
    yield* readSseEvents(response.body);
  } else {
    // e.g. {"error": "No prompt provided in the payload."} returned as application/json
    yield* parseNonSseBody(await response.text());
  }
}

/** Yield events from the AWS Bedrock AgentCore Runtime (`InvokeAgentRuntime`). */
async function* awsEvents(
  settings: AgentSettings,
  payload: AgentPayload,
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const client = getAgentCoreClient(settings.awsRegion);
  const response = await client.send(
    new InvokeAgentRuntimeCommand({
      agentRuntimeArn: settings.agentRuntimeArn,
      qualifier: "DEFAULT",
      runtimeSessionId: payload.conversation_id,
      contentType: "application/json",
      payload: new TextEncoder().encode(JSON.stringify(payload)),
    }),
    { abortSignal: signal },
  );

  const body = response.response;
  if (!body) return;

  const contentType = response.contentType ?? "";
  if (contentType.includes("text/event-stream")) {
    yield* readSseEvents(body.transformToWebStream());
  } else {
    yield* parseNonSseBody(await body.transformToString());
  }
}

// ---------------------------------------------------------------------------
// Agent invocation
// ---------------------------------------------------------------------------

/**
 * Invoke the agent via the local API or AWS AgentCore Runtime and yield stream events.
 *
 * Transport failures are converted into a terminal `{type: "error", mapped: true}` event
 * whose message is shown verbatim by the UI (same copy as the reference app); agent-side
 * `{"error": ...}` events are passed through and shown as `Error: <msg>`.
 */
export async function* invokeAgent(payload: AgentPayload, signal: AbortSignal): AsyncGenerator<AgentEvent> {
  const settings = getAgentSettings();

  if (settings.mode === "aws" && !settings.agentRuntimeArn) {
    yield {
      type: "error",
      mapped: true,
      message: "Configuration Error: `AGENT_RUNTIME_ARN` is required when `AGENT_CONNECTION_MODE=aws`.",
    };
    return;
  }

  try {
    const events = settings.mode === "aws" ? awsEvents(settings, payload, signal) : localEvents(settings, payload, signal);
    for await (const event of events) {
      yield event;
    }
  } catch (error) {
    // The browser went away (New chat, tab closed): nothing left to report.
    if (signal.aborted) return;

    const errorName = error instanceof Error ? error.name : typeof error;
    console.error(`[agent-client] ${settings.mode} invocation failed: ${errorName}`, error);

    let message: string;
    if (error instanceof AgentHttpError) {
      message = `API Error (status ${error.status}). Please try again.`;
    } else if (error instanceof AgentConnectionError) {
      message =
        "Connection Error: Could not connect to the agent API. " +
        `Please ensure the API server is running at \`${settings.agentCoreApiUrl}\`.`;
    } else if (settings.mode === "aws") {
      message = `AWS Runtime Error (${errorName}). Please try again or contact support.`;
    } else {
      message = "An unexpected error occurred. Please try again.";
    }
    yield { type: "error", mapped: true, message };
  }
}
