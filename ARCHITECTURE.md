# EV Copilot — Architecture and Connection Guide

This document covers the system architecture, how the components connect,
and all the ways to interact with the deployed services.

---

## System Architecture

```
                                Browser
                     (chat + Google Map + battery chart)
                                  |
                                  v
                    +----------------------------+
                    |        Next.js UI          |
                    |      (AWS App Runner)      |
                    |      Port 8000 / AMD64     |
                    +--------------+-------------+
                                   |
                  AWS SDK InvokeAgentRuntime (IAM SigV4)
                                   |
                                   v
                    +----------------------------+
                    |      LangGraph Agent       |
                    |  (AgentCore Runtime HTTP)  |
                    |      Port 8080 / ARM64     |
                    |                            |
                    | Router -> ReAct -> Reflect |
                    |   Bedrock Guardrails       |
                    +-----+----------------+-----+
                          |                |
             Tool calls   |                |  Prompt reads
             (MCP)        |                |  (MCP direct)
                          |                |
                          v                v
           +-----------------+  +-----------------------+
           |   MCP Gateway   |  |  AgentCore Runtime    |
           | (JWT Authorizer)|  |  (JWT Authorizer)     |
           +--------+--------+  +-----------+-----------+
                    |                       ^
      OAuth2 token  |                       |  Cognito JWT
      (auto, via    |                       |
       Token Vault) |                       |
                    v                       |
           +-------------------------------+--------+
           |            MCP Server                  |
           |      (AgentCore Runtime MCP)           |
           |      FastMCP on 0.0.0.0:8000           |
           |      Port 8000 / ARM64                 |
           +--+--------+--------+--------+--------+-+
              |        |        |        |        |
              v        v        v        v        v
           Google   Google   Google    Open    AgentCore
           Routes / Places  Weather   Charge    Memory
           Geocoding (New,           Map
           Elevation EV data)
```

### Data Flow

1. **User** opens the Next.js UI in a browser; the browser shares its location (or the user types `!location <lat> <lng>`).
2. **UI** server route (`POST /api/chat`) sends the message to the **Agent Runtime** with `InvokeAgentRuntime` (SigV4, App Runner instance role).
3. **Agent** checks the input with the **Bedrock Guardrail**, then classifies intent with the **Router** node (`trip_planning` / `simple` / `off_topic`).
4. For `trip_planning`, the **ReAct trip planner** calls tools through the **MCP Gateway**: preferences → vehicle → geocode → route → chargers along the route (live availability) → hourly weather → **energy simulation** → amenities.
5. The **Gateway** validates the agent's Cognito JWT (inbound `CUSTOM_JWT` authorizer), fetches its own OAuth2 token from Cognito (via Token Vault) and forwards the request to the **MCP Runtime**.
6. The **MCP Server** calls external APIs (Google Routes / Geocoding / Elevation, Places API (New), Weather API, Open Charge Map) or AgentCore Memory. The energy simulation itself is deterministic Python (no LLM).
7. Results flow back through the chain. The **Reflection** node verifies the plan (simulation feasible, every leg arrives above the buffer, connectors compatible) and may send the planner back with specific feedback (at most one revision round; 2 reflection passes).
8. The answer is streamed back token by token, together with `tool_start` / `tool_end` events that drive the map, the battery chart and the live tool-progress list. The conversation turn is saved to memory in the background.

---

## Component Details

### MCP Server (`ev-copilot-mcp/`)

| Property | Value |
|----------|-------|
| Framework | FastMCP 3 (Python 3.11) |
| Port | 8000 |
| Protocol | MCP over Streamable HTTP (`/mcp`) |
| Architecture | ARM64 |
| Deployment | AgentCore Runtime (MCP protocol, Cognito JWT authorizer) |

**7 Mounted Servers (namespaces):**

| Namespace | Tools | External API |
|-----------|-------|-------------|
| `charging` | `search_chargers_along_route`, `search_chargers_nearby`, `get_charger_details`, `search_chargers_open_charge_map` | Google Places API (New) `evChargeOptions`; Open Charge Map (fallback) |
| `places` | `search_places`, `search_nearby_places`, `get_place_details` | Google Places API (amenities near chargers) |
| `routing` | `geocode`, `compute_route`, `get_elevation_profile` | Google Routes API (EV routing), Geocoding API, Elevation API |
| `vehicle` | `search_vehicles`, `get_vehicle_spec`, `simulate_trip_energy` | Bundled vehicle catalog + Routes/Elevation for the simulation |
| `weather` | `get_current_weather`, `get_weather_forecast`, `get_hourly_forecast`, `get_weather_alerts` | Google Weather API |
| `preferences` | `get_user_preferences`, `save_conversation_turn` (internal — hidden from the LLM) | AgentCore Memory |
| `prompts` | 4 MCP prompts (below) | Amazon Bedrock Prompt Management |

Full tool names are `<namespace>_<tool>` (e.g. `vehicle_simulate_trip_energy`). See the
[README tool table](README.md#mcp-tools) for arguments and return types.

**MCP prompts** (Bedrock-managed; the Python files in `src/prompts/` are the source of truth and are synced to Bedrock at startup):

| Prompt | Bedrock prompt (env var) | Purpose |
|--------|--------------------------|---------|
| `ev_copilot_agent_scope` | `BEDROCK_PROMPT_ID` | Trip-planner system prompt (rules, input requirements, output format) |
| `router_intent_classifier` | `BEDROCK_PROMPT_ROUTER_ID` | One-word intent: `trip_planning` / `simple` / `off_topic` |
| `simple_response` | `BEDROCK_PROMPT_SIMPLE_ID` | Greetings, thanks, off-topic replies |
| `reflection_quality_review` | `BEDROCK_PROMPT_REFLECTION_ID` | `COMPLETE - …` or `NEEDS_MORE_DATA - <instruction>` |

**Energy simulation** (`vehicle_simulate_trip_energy`): one Routes call with the charging stops as
intermediates, an elevation profile per leg, then a pure, deterministic model in `src/utils/energy_model.py`
(base consumption × speed factor × temperature factor + climb − regen, charging time integrated over the
vehicle's charging curve). It returns per-leg arrival state of charge, charging minutes per stop, a
`feasible` flag with human-readable `issues`, an SoC timeline for the chart and the model `assumptions`.

### Agent (`ev-copilot-agent/`)

| Property | Value |
|----------|-------|
| Framework | LangGraph + LangChain (`ChatBedrockConverse`) |
| Port | 8080 |
| Protocol | HTTP (`POST /invocations`, `GET /ping`) |
| Architecture | ARM64 |
| Deployment | AgentCore Runtime (HTTP protocol, IAM SigV4 inbound auth) |

**Workflow Nodes:**

| Node | Model (env var, default) | Purpose |
|------|--------------------------|---------|
| Router | `ROUTER_MODEL_ID` — Claude Haiku 4.5 | Intent classification (trip_planning / simple / off_topic); resets per-turn counters |
| Trip Planner Agent | `ORCHESTRATOR_MODEL_ID` — Claude Sonnet 4.6 | ReAct reasoning + MCP tool invocation (max 30 tool calls per turn) |
| Simple Response | `ORCHESTRATOR_MODEL_ID` — Claude Sonnet 4.6 | Direct answer for greetings, thanks, off-topic |
| Reflection | `REFLECTION_MODEL_ID` — Claude Sonnet 4.6 | Verifies the plan; on `NEEDS_MORE_DATA` its critique is fed back to the planner as `<reviewer_feedback>` (at most one revision round; 2 reflection passes) |
| Memory Hook | — | Saves the conversation turn to AgentCore Memory (background task) |

Model IDs are Bedrock cross-region inference profiles (`us.anthropic.claude-sonnet-4-6`,
`us.anthropic.claude-haiku-4-5-20251001-v1:0`) and are set as runtime environment variables by the AgentStack.

**Safety:** Bedrock Guardrail with HIGH-strength content filters, prompt-attack detection, denied topics
(vehicle tampering / defeating safety systems, personalised financial-medical-legal advice, politics),
profanity filter and PII protection (anonymize email/phone, block SSN/credit card/bank/PIN/password).

### UI (`ev-copilot-ui/`)

| Property | Value |
|----------|-------|
| Framework | Next.js (App Router, TypeScript, Tailwind CSS) |
| Port | 8000 |
| Architecture | AMD64 |
| Deployment | AWS App Runner (TCP health check) |

**Features:**
- Streaming chat (markdown) with a live tool-activity list (`tool_start` / `tool_end` events)
- Google Map (`@vis.gl/react-google-maps`): route polyline, charger markers coloured by live availability (green = available, amber = no live data, red = none available), numbered planned charging stops, amenity markers
- Battery chart (Recharts) of the simulated state of charge with the buffer line, trip summary with stop cards, weather-alert banner
- Settings dialog (display name, stored in `localStorage`), per-chat `conversation_id` (`sessionStorage`), "New chat"
- Browser geolocation, `!location <lat> <lng>` manual override, "Use my location" button
- Two connection modes: `local` (direct HTTP to `AGENTCORE_API_URL`) and `aws` (AWS SDK `InvokeAgentRuntime`)
- The browser gets the Maps key and Map ID at runtime from `GET /api/config` (no build-time variables, one image for every environment)

---

## Infrastructure Stacks (CDK)

All infrastructure is defined in `ev-copilot-infra/` using AWS CDK v2 (TypeScript).

### Stack Dependency Order

```
EcrStack ─────────────────────────────┐
    :  (CI deploys it first so        |  agent / ui repo ARNs
    :   images can be pushed)         |
    v                                 |
AgentCoreStack ──────────────┐        |
    |                        |        |
    v                        |        |
GatewayStack                 |        |
    |                        |        |
    v                        v        v
AgentStack <─────────────────┴────────┤
    |                                 |
    v                                 v
UiStack <─────────────────────────────┘
```

### Stack Resources

#### EcrStack
- 3 ECR repositories: `evcopilot-mcp`, `evcopilot-agent`, `evcopilot-ui`
- Lifecycle: keep last 10 images, scan on push
- Removal policy: RETAIN

#### AgentCoreStack
- **Secrets Manager**: `evCopilot/google-maps-api-key`, `evCopilot/openchargemap-api-key` (JSON `{"api_key": ""}`, set after deploy), `evCopilot/cognito-client-secret` (Cognito client secret, plain string, managed by CDK)
- **AgentCore Memory**: `evCopilot_memory` with User Preference (`/preferences/{actorId}/`) + Semantic (`/facts/{actorId}/`) strategies
- **Bedrock Prompts** (4, + V1 versions): agent-scope, router, simple-response, reflection
- **Cognito**: User Pool + App Client (client_credentials flow, scope `evCopilot-api/mcp`), domain `evcopilot-<region>`
- **AgentCore Runtime**: `evCopilot_mcp`, MCP protocol, JWT authorizer (Cognito), ARM64 container
- **IAM**: ECR pull, Secrets read, Memory access, Bedrock prompts, S3 vectors, CloudWatch
- **Observability**: X-Ray → CloudWatch Logs resource policy (`aws/spans`)

#### GatewayStack
- **Lambda**: OAuth2 credential provider custom resource (`evCopilot-cognito-oauth`)
- **AgentCore Gateway**: MCP protocol, inbound `CUSTOM_JWT` authorizer (Cognito user pool discovery URL, allowed client = the app client)
- **Gateway Target**: `evCopilot-McpTarget`, points to the MCP Runtime, OAuth2 CLIENT_CREDENTIALS
- **IAM**: InvokeRuntime, OAuth token exchange, Secrets read

#### AgentStack
- **Bedrock Guardrail**: `evCopilot-agent-guardrail` — content + topic + PII + profanity filters
- **AgentCore Runtime**: `evCopilot_agent`, HTTP protocol, IAM (SigV4) inbound auth, ARM64 container
- **IAM**: ECR pull, Bedrock InvokeModel (foundation models + inference profiles), Guardrails, read of the Cognito client secret, Memory, Gateway invoke, S3 vectors, CloudWatch

#### UiStack
- **Secrets Manager**: `evCopilot/google-maps-browser-key` (plain string, seeded with `REPLACE_ME`), injected as `GOOGLE_MAPS_BROWSER_API_KEY`
- **App Runner**: `evCopilot-ui`, AMD64 container, 1 vCPU / 2 GB RAM, TCP health check, `GOOGLE_MAPS_MAP_ID` from context `mapsMapId` (default `DEMO_MAP_ID`)
- **IAM**: ECR pull (access role), InvokeAgentRuntime + read of the browser-key secret (instance role)

---

## Connecting to the MCP Server

There are three ways to connect to the MCP server depending on your use case.

### Option 1: Via the MCP Gateway (JWT auth)

The Gateway requires a Cognito access token issued to the app client — the same token as Option 2
(see Steps 1–2 there to get `TOKEN`). Requests without a valid token get `401`.
It exposes **tools only** (no prompts or resources).

**MCP Inspector:**

```bash
npx @modelcontextprotocol/inspector --header "Authorization: Bearer ${TOKEN}"
# Transport: Streamable HTTP
# URL: <Gateway URL from CDK output: evCopilot-GatewayStack.GatewayUrl>  (already ends in /mcp)
# Click Connect
```

In the Inspector UI you can instead add the header under Server Settings → Headers
(`Authorization` = `Bearer <token>`). Don't use the Inspector's OAuth/Authorization flow — the token
comes from the Cognito `client_credentials` call in Option 2.

**curl:**

```bash
# CDK output evCopilot-GatewayStack.GatewayUrl, e.g.
# https://<gateway-id>.gateway.bedrock-agentcore.us-east-2.amazonaws.com/mcp
GATEWAY_URL="<your-gateway-url>"
TOKEN="<Cognito access token — Option 2, Steps 1–2>"

# Initialize
curl -s -X POST "${GATEWAY_URL}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-03-26",
      "capabilities": {},
      "clientInfo": { "name": "test", "version": "1.0.0" }
    }
  }'

# List tools
curl -s -X POST "${GATEWAY_URL}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}'

# Call a tool
curl -s -X POST "${GATEWAY_URL}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "evCopilot-McpTarget___routing_geocode",
      "arguments": { "address": "Pune, Maharashtra", "region": "in" }
    }
  }'
```

> **Note:** The Gateway prepends `evCopilot-McpTarget___` to tool names
> (`evCopilot-McpTarget___<namespace>_<tool>`). The agent strips this prefix and matches tool names exactly.

### Option 2: Direct to the AgentCore Runtime (JWT auth)

Bypasses the Gateway. Gives **full MCP capabilities** — tools, prompts, and resources.
Requires a Cognito JWT token.

```bash
# Step 1: Get the Cognito client secret (stored in Secrets Manager by the AgentCoreStack)
CLIENT_SECRET=$(aws secretsmanager get-secret-value \
  --secret-id evCopilot/cognito-client-secret \
  --query SecretString \
  --output text)

# Step 2: Request a JWT — CognitoTokenEndpoint already ends in /oauth2/token
TOKEN=$(curl -s -X POST "<COGNITO_TOKEN_ENDPOINT>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=<COGNITO_CLIENT_ID>&client_secret=${CLIENT_SECRET}&scope=evCopilot-api/mcp" \
  | jq -r '.access_token')

# Step 3: Connect
RUNTIME_URL="https://bedrock-agentcore.<REGION>.amazonaws.com/runtimes/<URL_ENCODED_RUNTIME_ARN>/invocations?qualifier=DEFAULT"

curl -s -X POST "${RUNTIME_URL}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-03-26",
      "capabilities": {},
      "clientInfo": { "name": "test", "version": "1.0.0" }
    }
  }'

# List prompts (not available through the Gateway)
curl -s -X POST "${RUNTIME_URL}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{"jsonrpc": "2.0", "id": 2, "method": "prompts/list", "params": {}}'
```

`<URL_ENCODED_RUNTIME_ARN>` is the `RuntimeArn` output with `:` → `%3A` and `/` → `%2F`.

> Tokens expire after 1 hour (3600 seconds).

### Option 3: Run locally (no auth, no AWS)

```bash
cd ev-copilot-mcp
cp .env.example .env
# Fill in GOOGLE_MAPS_API_KEY and OPEN_CHARGE_MAP_API_KEY

docker build -t evcopilot-mcp .
docker run -p 8000:8000 --env-file .env evcopilot-mcp

# Connect
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP → URL: http://localhost:8000/mcp
```

Without AWS credentials the prompt sync to Bedrock and the preference (memory) tools are unavailable;
everything else works with just the two API keys.

### Connection Mode Comparison

| | Gateway | Runtime (direct) | Local |
|---|---|---|---|
| **Auth from client** | Cognito JWT (Bearer) | Cognito JWT (Bearer) | None |
| **Tools** | Yes | Yes | Yes |
| **Prompts** | No | Yes | Yes |
| **Resources** | No | Yes | Yes |
| **Tool name prefix** | `evCopilot-McpTarget___` | Original names | Original names |
| **Best for** | Production clients, external integrations | Testing deployed infra, prompt access | Development |

---

## Connecting to the Agent

The agent accepts one JSON payload per turn:

| Field | Type | Notes |
|-------|------|-------|
| `prompt` | string | The user message (required) |
| `customer_name` | string | Display name, used as the memory `actor_id` (default `Guest`) |
| `conversation_id` | string | UUID4 per chat — LangGraph `thread_id`, tracing session id and `runtimeSessionId` |
| `latitude` / `longitude` | number | Optional user location ("near me" requests, origin default) |

### Option 1: Via the UI

Open the App Runner URL from the CDK output (`evCopilot-UiStack.UiServiceUrl`) in a browser.

### Option 2: Direct HTTP (local)

```bash
curl -N -s -X POST "http://localhost:8080/invocations" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Plan a trip from Pune to Goa in my Tata Nexon EV 45. I start at 90% and want lunch on the way.",
    "customer_name": "Test User",
    "conversation_id": "5b7e9c3a-2f4d-4e8a-9c1b-6d2f8a4e7b10",
    "latitude": 18.5204,
    "longitude": 73.8567
  }'
```

### Option 3: Via boto3 (AWS mode)

The agent runtime uses **IAM (SigV4) inbound auth** — the caller needs
`bedrock-agentcore:InvokeAgentRuntime` on the runtime.

```python
import boto3, json, uuid

client = boto3.client("bedrock-agentcore", region_name="us-east-2")

conversation_id = str(uuid.uuid4())  # runtimeSessionId must be at least 33 characters

response = client.invoke_agent_runtime(
    agentRuntimeArn="<AGENT_RUNTIME_ARN>",
    qualifier="DEFAULT",
    runtimeSessionId=conversation_id,
    payload=json.dumps({
        "prompt": "Find fast chargers near me with a free CCS2 connector",
        "customer_name": "Demo User",
        "conversation_id": conversation_id,
        "latitude": 12.9716,
        "longitude": 77.5946,
    }).encode(),
)

# response["response"] is a streaming body of SSE lines
for raw in response["response"].iter_lines():
    if not raw.startswith(b"data: "):
        continue
    event = json.loads(raw[len(b"data: "):])
    if isinstance(event, str):  # double-encoded: the inner value is itself an SSE line
        event = json.loads(event.removeprefix("data: ").strip())
    if "chunk" in event:
        print(event["chunk"], end="", flush=True)
    elif event.get("done") or "error" in event:
        break
```

### Response stream

The agent yields `data: {json}` SSE events; the AgentCore runtime re-wraps each one, so on the wire a
line usually looks like `data: "data: {\"chunk\": \"...\"}\n\n"`. Consumers must accept both the
double-encoded and the plain `data: {json}` form.

| Event | Shape | When |
|-------|-------|------|
| chunk | `{"chunk": "<markdown text>"}` | Streamed answer tokens |
| done | `{"done": true}` | End of turn (also after `blocked`) |
| error | `{"error": "<msg>"}` | Failure (terminal) |
| blocked | `{"blocked": true, "message": "<text>"}` | Input guardrail intervened |
| tool_start | `{"tool_start": {"id": "<run_id>", "name": "<tool>"}}` | A tool call started |
| tool_end | `{"tool_end": {"id": "<run_id>", "name": "<tool>", "status": "success" \| "error", "result": <object or null>}}` | A tool call finished; `result` is the parsed tool output for map/chart tools only (`routing_compute_route`, `charging_*`, `vehicle_simulate_trip_energy`, `places_search_places`, `places_search_nearby_places`, `weather_get_weather_alerts`) |
| reset | `{"reset": true}` | Reflection asked for more work after a draft answer was streamed — clear the draft text (keep map/tool state) |

Tool names in `tool_start` / `tool_end` are the base names with the Gateway prefix stripped.

---

## CDK Outputs Reference

After deployment, retrieve outputs with:

```bash
# All stacks
for STACK in EcrStack AgentCoreStack GatewayStack AgentStack UiStack; do
  echo "--- evCopilot-${STACK} ---"
  aws cloudformation describe-stacks \
    --stack-name "evCopilot-${STACK}" \
    --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
    --output table
done
```

Key outputs:

| Stack | Output | Description |
|-------|--------|-------------|
| EcrStack | `EcrRepositoryUri` / `AgentEcrRepositoryUri` / `UiEcrRepositoryUri` | ECR repository URIs |
| AgentCoreStack | `RuntimeId` / `RuntimeArn` | MCP Runtime identifier / ARN |
| AgentCoreStack | `MemoryId` | AgentCore Memory identifier |
| AgentCoreStack | `GoogleApiSecretArn` | Google Maps Platform key secret ARN |
| AgentCoreStack | `OpenChargeMapSecretArn` | Open Charge Map key secret ARN |
| AgentCoreStack | `CognitoClientSecretArn` | Cognito client secret ARN (Secrets Manager) |
| AgentCoreStack | `CognitoUserPoolId` / `CognitoClientId` | Cognito User Pool / App Client |
| AgentCoreStack | `CognitoTokenEndpoint` | Cognito OAuth2 token URL (ends in `/oauth2/token`) |
| AgentCoreStack | `AgentScopePromptId`, `RouterPromptId`, `SimpleResponsePromptId`, `ReflectionPromptId` | Bedrock Prompt IDs (+ `…Arn`) |
| GatewayStack | `GatewayId` | MCP Gateway identifier |
| GatewayStack | `GatewayUrl` | Gateway URL (ends in `/mcp`; requires a Cognito bearer token) |
| GatewayStack | `GatewayTargetId` | Gateway Target identifier |
| GatewayStack | `OAuth2ProviderArn` | OAuth2 credential provider ARN |
| AgentStack | `AgentRuntimeId` / `AgentRuntimeArn` | Agent Runtime identifier / ARN |
| AgentStack | `GuardrailId` / `GuardrailVersion` | Bedrock Guardrail identifier / version |
| UiStack | `UiServiceUrl` | App Runner URL for the UI |
| UiStack | `UiServiceArn` | App Runner service ARN |

---

## Observability

All services export telemetry via **OpenTelemetry** (AWS Distro for OpenTelemetry):

| Signal | Exporter | Destination |
|--------|----------|-------------|
| Traces | OTLP/HTTP | AWS X-Ray → CloudWatch (`aws/spans`) |
| Metrics | OTLP/HTTP | CloudWatch Metrics (`bedrock-agentcore` namespace) |
| Logs | OTLP/HTTP | CloudWatch Logs |

Each MCP tool is instrumented with the `@traced()` decorator, creating spans that flow through:

```
UI Request → Agent Runtime → MCP Gateway → MCP Runtime → [Tool Span] → External API
```

The agent records LangGraph node spans, tool calls and model invocations under one session id
(the `conversation_id`), so a whole conversation can be followed end to end.

### One-time setup: enable CloudWatch Transaction Search

The CDK stacks create the X-Ray → CloudWatch Logs resource policy, but **Transaction Search** itself is an
account/region setting that must be enabled once (it is not part of the IaC):

```bash
aws xray update-trace-segment-destination --destination CloudWatchLogs --region us-east-2
aws xray update-indexing-rule --name "Default" \
  --rule '{"Probabilistic": {"DesiredSamplingPercentage": 1}}' --region us-east-2
```

(or CloudWatch console → **Application Signals → Transaction Search → Enable**). Spans then appear in
CloudWatch **GenAI Observability → Bedrock AgentCore** and in Transaction Search; runtime logs are in the
`/aws/bedrock-agentcore/runtimes/...` log groups.

---

## CI/CD Workflows

### Deploy (`deploy.yml`)

**Triggers:** Push to `main` (auto-detects changed paths under `ev-copilot-*/`) or manual dispatch.

**Jobs:**
1. **Detect Changes** — determines which components need deploying
2. **Ensure ECR Repositories** — deploys the EcrStack (cleans up orphaned repos only when the stack does not own them)
3. **Build MCP/Agent/UI** — Docker builds + push to ECR (parallel; MCP and agent `linux/arm64`, UI `linux/amd64`)
4. **Deploy CDK Stacks** — CDK deploy in dependency order (AgentCore → Gateway → Agent → UI)
5. **Configure API Key Secrets** — (manual dispatch only) runs after the stacks exist and only calls `put-secret-value` for the provided keys; the browser key also triggers an App Runner redeployment
6. **Sync Gateway Target** — updates the gateway target so it re-lists the MCP tools (waits for Configure API Key Secrets when that job runs)

Stack health checks treat every `*_COMPLETE` state except `ROLLBACK_COMPLETE` as healthy, so a normal
`UPDATE_ROLLBACK_COMPLETE` never triggers deletion of live ECR repositories or secrets. Orphan cleanup runs
only when the stack is gone or failed on create (`ROLLBACK_COMPLETE` / `ROLLBACK_FAILED`); any in-progress
or other failed state (e.g. `UPDATE_ROLLBACK_FAILED`) stops the job instead of deleting anything. Workflow inputs are
passed to scripts through `env:` (never interpolated into shell code). API key inputs are masked in logs by a first
step that reads them from the event payload, before any step receives them through `env:`; note the inputs are
still stored in the run's event payload.

### Destroy (`destroy.yml`)

**Trigger:** Manual dispatch only.

**Safety:** Requires typing `destroy` as confirmation.

**Options:**
- Scope: `all`, or individual stacks (`ui-only`, `agent-only`, `gateway-only`, `agentcore-only`, `ecr-only`)
- Optionally delete all ECR images before removing repositories

Stacks are destroyed in reverse dependency order: UI → Agent → Gateway → AgentCore → ECR. Secrets are
force-deleted (no recovery window) so a redeploy can recreate them immediately.

---

## Known Limitations

These are deliberate simplifications carried over from the reference architecture (dev/demo scope):

- **Identity is the typed display name.** The UI has no login; the name is the memory `actor_id`, so anyone
  who types the same name shares that user's remembered vehicle and preferences. The App Runner UI is public.
- **The output guardrail is advisory.** The answer is streamed token by token; the output check runs after
  the stream and can only log an intervention — it cannot retract text that was already shown.
- **Static AWS keys in GitHub Actions** (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`), no OIDC role.
- **No automated test suites.**
- **Browser map key placeholder.** Secrets Manager does not accept an empty value, so
  `evCopilot/google-maps-browser-key` starts as `REPLACE_ME`; the map only works after the real key is set
  and the App Runner service is redeployed.
- **App Runner 120 s request limit.** The whole agent turn streams back in one `/api/chat` request, and App Runner
  closes any request after a fixed 120 s (not configurable; keepalives do not extend it). Very long turns are cut
  off, and the UI reports them as interrupted.
- **Estimates, not guarantees.** The vehicle catalog uses approximate public specifications and the energy
  model is a physics-based estimate; live connector availability depends on what Google Places reports
  (Open Charge Map results carry no live availability).
