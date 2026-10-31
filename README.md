# EV Copilot: building a production-ready AI road-trip planner for electric vehicles with MCP on Amazon Bedrock AgentCore

EV Copilot is a conversational trip planner for electric-vehicle drivers. Tell it where you're going and what
you drive. It plans the route, finds chargers along the way with **live connector availability**, simulates your
**battery level at every stop** (elevation, speed and temperature included), picks stops with food and amenities,
warns you about the weather, and **remembers your car and preferences** for next time.

Under the hood it's a full agentic system on AWS:
- a **LangGraph** agent on **Amazon Bedrock AgentCore Runtime**, using Claude models on **Amazon Bedrock**;
- **19 Model Context Protocol (MCP) tools** served by a FastMCP server, also on AgentCore Runtime, and reached
  through the **AgentCore Gateway**;
- **Bedrock Guardrails** for safety, **AgentCore Memory** for personalisation, and **OpenTelemetry** tracing end
  to end;
- a **Next.js** chat UI with a live map and battery chart;
- **AWS CDK** stacks plus a GitHub Actions pipeline to deploy everything.

This README is written as an article. The first part is a quick reference (what it does, the architecture,
components and project structure). The middle part walks through how and why the system is built the way it is,
one diagram at a time. The last part covers setup, deployment and configuration.

<img width="2550" height="2340" alt="ev-copilot-architecture" src="https://github.com/user-attachments/assets/433dc86f-ba95-47e9-91bd-4db5f0f4d67b" />

---

## Contents

**Quick reference**
- [What EV Copilot does](#what-ev-copilot-does)
- [Architecture at a glance](#architecture-at-a-glance)
- [Components](#components)
- [Project structure](#project-structure)

**The build, step by step**
1. [Why MCP?](#1-why-mcp)
2. [Designing EV Copilot with MCP](#2-designing-ev-copilot-with-mcp)
3. [Building the MCP server](#3-building-the-mcp-server)
4. [The agent: the MCP host](#4-the-agent-the-mcp-host)
5. [Deploying on AgentCore Runtime](#5-deploying-on-agentcore-runtime)
6. [Connecting the agent to the MCP server](#6-connecting-the-agent-to-the-mcp-server)
7. [Observability](#7-observability)
8. [The user interface](#8-the-user-interface)

**Run it yourself**
- [Getting started](#getting-started)
- [Local development](#local-development)
- [Cloud deployment (AWS)](#cloud-deployment-aws)
- [Configuration reference](#configuration-reference)
- [Known limitations](#known-limitations)
- [Further reading](#further-reading)

---

## What EV Copilot does

Planning a long drive in an EV raises questions a normal route planner doesn't answer. Will I make it? Where
should I charge? Is that charger actually free? How long will I wait? Will the mountain pass or the cold eat my
range? EV Copilot answers all of them in one conversation:

| Capability | How |
|---|---|
| **Route and charging stops** | Google Routes (traffic-aware), plus chargers *along* the route that have a connector compatible with your car |
| **Live charger availability** | Google Places API (New) EV charge data: free / busy / out-of-service connectors and detour time. Open Charge Map is the fallback where Google has no data |
| **Battery at every stop** | A deterministic energy model simulates state of charge leg by leg (elevation profile, speed, outside temperature, payload, charging curve) and returns arrival %, charge time per stop and whether the plan is feasible |
| **Weather and amenities** | Hourly forecast (fed into the simulation) and official weather alerts; restaurants, cafés and restrooms near each stop |
| **Memory** | Remembers your car, preferred networks, battery buffer and food preferences across sessions |
| **Safety** | Bedrock Guardrails block unsafe requests (e.g. tampering with the battery management system) before the agent sees them |

A typical exchange (numbers are illustrative):

> **You:** Plan a trip from Mumbai to Lonavala
> **EV Copilot:** Happy to plan Mumbai → Lonavala! Which EV will you be driving, and how much charge do you have?
> **You:** Tata Nexon EV 45, I'm at 35% battery
> **EV Copilot:** **Mumbai → Lonavala** — 83 km | 1 h 29 min drive | 20 min charging | 1 h 49 min total | arrive with 48%.
> Starting at 35% you'd reach Lonavala with only 8% (the Khandala ghat climbs ~620 m), so stop at
> **Tata Power EZ Charge, Khalapur** (60 kW CCS2, 1 of 2 free now): arrive 20% → leave 60% in 20 min…

Behind that answer the agent geocoded both places, computed the route, pulled the elevation profile, searched
chargers along the route, checked the weather, simulated the battery twice (the first plan failed the safety
buffer) and assembled the plan. The UI showed each step live and drew the route, chargers and battery curve.

---

## Architecture at a glance

The architecture diagram above reads from the bottom up:

| Layer | What runs there |
|---|---|
| **Customer device** | A browser running the **Next.js UI** (AWS App Runner): chat, a live Google Map and a battery chart. The UI server calls the agent with `InvokeAgentRuntime` (IAM SigV4) and streams the answer back over server-sent events. |
| **MCP Host: the EV Copilot agent** | A **LangGraph** workflow on **AgentCore Runtime (HTTP)**. An *LLM gateway* (`ChatBedrockConverse`) talks to **Claude Haiku 4.5** (intent router) and **Claude Sonnet 4.6** (trip planner, reviewer, simple replies). An *MCP client* (`langchain-mcp-adapters`) talks to the tools and prompts. **Bedrock Guardrails** check input and output. |
| **MCP Connection Layer** | A hybrid. **Tools** go through the **AgentCore Gateway**, which proxies them as `evCopilot-McpTarget___<tool>` (Cognito JWT inbound, OAuth2 outbound). **Prompts** come over a **direct MCP connection** to the server runtime (Cognito JWT). |
| **MCP Servers** | One **FastMCP "global server"** on **AgentCore Runtime (MCP protocol)** that mounts seven servers: routing, charging, places, vehicle & energy, weather, user preferences and prompts. **19 tools in 6 namespaces**, plus **4 prompts**. |
| **External services** | Google Routes / Geocoding / Elevation, Google Places API (New) with EV data, Google Weather, Open Charge Map, the bundled EV catalog, **AgentCore Memory** and **Bedrock Prompt Management**. API keys live in **AWS Secrets Manager**. |
| **Observability** | Every service is instrumented with **OpenTelemetry (ADOT)**. Traces, prompt versions and metrics land in **CloudWatch / X-Ray / GenAI Observability**. |

---

## Components

| Component | Directory | Description |
|---|---|---|
| **MCP Server** | [`ev-copilot-mcp/`](ev-copilot-mcp) | FastMCP server with 19 tools across 6 namespaces (routing, charging, vehicle, weather, places, preferences) plus 4 prompts managed in Bedrock Prompt Management |
| **Agent** | [`ev-copilot-agent/`](ev-copilot-agent) | LangGraph workflow: input guardrail → router → simple response *or* ReAct trip planner ⇄ tools → reflection → memory hook → output guardrail |
| **UI** | [`ev-copilot-ui/`](ev-copilot-ui) | Next.js chat with a Google Map, battery chart, trip summary and live tool progress |
| **Infrastructure** | [`ev-copilot-infra/`](ev-copilot-infra) | AWS CDK (TypeScript): 5 stacks for the full deployment |
| **CI/CD** | [`.github/workflows/`](.github/workflows) | GitHub Actions deploy (path-filtered, per component) and destroy workflows |

### MCP tools

Coordinates are always `(latitude, longitude)`. Waypoints and charging stops are passed as structured objects
(`{latitude, longitude}`), never as encoded polylines.

| Namespace | Tool | Description |
|---|---|---|
| `routing` | `routing_geocode` | Address / place name → coordinates (`address`, `max_results=5`, `region` ccTLD bias) |
| `routing` | `routing_compute_route` | Traffic-aware driving route (Google Routes) with per-leg distance, duration and polyline; optional `waypoints`, `departure_time`, `avoid_tolls`, `avoid_highways` |
| `routing` | `routing_get_elevation_profile` | Elevation samples along the route with total ascent / descent (`samples=64`, max 512) |
| `charging` | `charging_search_chargers_along_route` | Chargers along the route with live connector availability and detour time. Detour is only reported when no `waypoints` are passed (`min_power_kw`, `connector_type`, `max_results=10`) |
| `charging` | `charging_search_chargers_nearby` | Chargers around a point (`radius_meters=10000`, `min_power_kw`, `connector_type`) |
| `charging` | `charging_get_charger_details` | Full details for one charger by Google Place ID |
| `charging` | `charging_search_chargers_open_charge_map` | Fallback charger search via Open Charge Map (no live availability) |
| `vehicle` | `vehicle_search_vehicles` | Fuzzy search of the bundled EV catalog (approximate public specifications) |
| `vehicle` | `vehicle_get_vehicle_spec` | Battery, efficiency, charging curve and connectors for a `vehicle_id` |
| `vehicle` | `vehicle_simulate_trip_energy` | Deterministic state-of-charge simulation per leg (elevation, speed, temperature) and charging time per stop; returns `feasible`, `issues` and an SoC timeline |
| `weather` | `weather_get_current_weather` | Current conditions at coordinates |
| `weather` | `weather_get_weather_forecast` | Daily forecast (`forecast_days=5`) |
| `weather` | `weather_get_hourly_forecast` | Hourly forecast (`hours=24`, max 240), used for the simulation temperature |
| `weather` | `weather_get_weather_alerts` | Active public weather alerts for a location |
| `places` | `places_search_places` | Text search for food, cafés, restrooms and hotels near a charging stop |
| `places` | `places_search_nearby_places` | Nearby places by coordinates and type |
| `places` | `places_get_place_details` | Full details for a Google Place ID |
| `preferences` | `preferences_get_user_preferences` | Searches remembered vehicle, connector, battery buffer, networks, food preferences and home location |
| `preferences` | `preferences_save_conversation_turn` | Saves a conversation turn to memory (internal: called by the agent's memory hook, hidden from the LLM) |

**MCP prompts:** `ev_copilot_agent_scope`, `router_intent_classifier`, `simple_response`, `reflection_quality_review`.
Through the Gateway, tool names carry the prefix `evCopilot-McpTarget___`, e.g.
`evCopilot-McpTarget___vehicle_simulate_trip_energy`.

---

## Project structure

```
.
├── .github/workflows/
│   ├── deploy.yml           # Build and deploy workflow (path-filtered per component)
│   └── destroy.yml          # Infrastructure teardown workflow
├── ev-copilot-mcp/          # MCP Server (FastMCP)
│   ├── src/
│   │   ├── main.py          # Uvicorn entry point (port 8000)
│   │   ├── config.py        # Environment settings (+ Secrets Manager ARN resolution)
│   │   ├── clients/         # API clients (Google Routes/Geocoding/Elevation/Places/Weather, Open Charge Map, Memory)
│   │   ├── data/            # Bundled EV catalog (vehicles.json)
│   │   ├── servers/         # MCP server definitions + tool registry
│   │   ├── schemas/         # Pydantic models (the tools' structured outputs)
│   │   ├── prompts/         # Prompt definitions (source of truth, synced to Bedrock)
│   │   ├── infrastructure/  # Observability, Bedrock prompt manager, @traced decorator
│   │   └── utils/           # Formatters, polyline helpers, energy model
│   ├── Dockerfile
│   └── pyproject.toml
├── ev-copilot-agent/        # LangGraph Agent (MCP host)
│   ├── src/
│   │   ├── main.py          # BedrockAgentCoreApp entry point (port 8080)
│   │   ├── config.py        # Environment settings
│   │   ├── application/     # Orchestrator workflow (graph, nodes, edges, chains, streaming)
│   │   ├── domain/          # Domain models, prompt names
│   │   ├── infrastructure/  # API server, MCP client, guardrails, memory, model, observability
│   │   └── utils/           # Helpers
│   ├── Dockerfile
│   └── pyproject.toml
├── ev-copilot-ui/           # Next.js Web UI
│   ├── src/app/             # Pages + API routes (/api/chat, /api/config, /api/health)
│   ├── src/components/      # Chat, map, battery chart, trip summary, tool activity
│   ├── src/lib/             # Agent client, SSE parser, types, polyline decoder, session
│   ├── Dockerfile
│   └── package.json
├── ev-copilot-infra/        # AWS CDK Infrastructure
│   ├── bin/cdk.ts           # CDK app entry point
│   ├── lib/stacks/          # 5 CDK stacks
│   ├── lib/lambda/          # OAuth2 credential-provider custom resource
│   └── package.json
├── ARCHITECTURE.md          # Detailed architecture and connection guide
└── README.md                # This article
```

---

## 1. Why MCP?

An agent is only as useful as the tools it can call. EV Copilot needs routing, chargers, weather, places, a
vehicle catalog, memory and managed prompts, and it might use more than one model.

<img width="2550" height="1350" alt="ev-copilot-before-after-mcp" src="https://github.com/user-attachments/assets/497185b5-6c45-4a26-82c5-7ac76954871a" />

**Before MCP**, every model needs its own bespoke integration with every API: its own client code, auth, schemas
and error handling. Three models and five data sources means **15 integrations**, and adding a model or a source
multiplies the work.

**After MCP**, models and data sources meet at one standard protocol (`tools/list`, `tools/call`, `prompts/list`,
`prompts/get`). Three models and five sources means **8 standard connections**. A model can be swapped, or a new
data source added, without touching the others.

### How tool calling works

<img width="2670" height="1320" alt="ev-copilot-tool-calling-flow" src="https://github.com/user-attachments/assets/09f268ed-0293-47fe-8c41-467fc043a09c" />


The **MCP host** (our agent) contains an **MCP client** and the **LLM**. A tool call happens in five steps:

1. **Discover.** The client asks the server which tools and prompts it offers.
2. **Bind.** The tool schemas are bound to the LLM, so the model knows each tool's name, description and arguments.
3. **Select.** Given the user's request, the model picks a tool and fills in the arguments, e.g.
   `charging_search_chargers_along_route(origin…, destination…, min_power_kw=50, connector_type="CCS2")`.
4. **Invoke.** The client sends `tools/call` to the server.
5. **Execute.** The server runs the tool (here, calling Google Places) and returns a structured result that goes
   back to the model.

In EV Copilot, 18 of the 19 tools are bound to the model. `preferences_save_conversation_turn` is reserved for the
memory hook so the model can't call it directly.

### Many servers, one host

<img width="2640" height="1350" alt="ev-copilot-multiple-mcp-servers" src="https://github.com/user-attachments/assets/3eea6ed1-16e2-4d4a-87a2-35c99cb7c0c3" />

One host can talk to many MCP servers, each with a different kind of backing:
- a **prompt server** backed by Bedrock Prompt Management;
- a **vehicle & energy server** backed by local data (the bundled `vehicles.json` catalog and an energy model);
- a **charging server** backed by external APIs (Google Places, Open Charge Map).

The host doesn't need to know how each server works inside. In EV Copilot these servers are mounted as
namespaces in one FastMCP global server (see [section 2](#2-designing-ev-copilot-with-mcp)); the figure is the
conceptual view.

### Servers scale independently

<img width="2640" height="1350" alt="ev-copilot-independent-scaling" src="https://github.com/user-attachments/assets/647e3ccc-d890-4779-b791-5cfb35c645e0" />

Because the protocol separates hosts from servers, each side scales on its own. A charging server used by
several agents can add replicas without anyone changing the agents. The other agents in the figure are
illustrative: EV Copilot itself is one agent, and AgentCore Runtime handles scaling by giving each session its
own microVM.

---

## 2. Designing EV Copilot with MCP

### The end-to-end flow

<img width="2550" height="2400" alt="ev-copilot-end-to-end-flow" src="https://github.com/user-attachments/assets/bcb5246e-0ba2-41f1-8c04-7e44ff9a18ce" />

Here's what happens when a user types *"Plan a trip from Mumbai to Lonavala"*:

1. **Send the prompt through the UI.** The Next.js server calls the agent runtime with `InvokeAgentRuntime`
   (SigV4), passing the user's location and a `conversation_id`.
2. **Fetch prompts and tools.** The agent loads its system prompts over the direct MCP connection and the tool
   catalog through the Gateway (both are cached).
3. **Query the LLM with the user's prompt.** Guardrails check the input; the router (Haiku 4.5) classifies it as
   `trip_planning`; the planner (Sonnet 4.6) starts reasoning.
4. **Select tools and arguments.** The model decides what it needs: preferences, vehicle, geocodes, route.
5. **Invoke tools through the Gateway.** `tools/call` goes to the AgentCore Gateway, which authenticates the agent
   and forwards the call to the MCP runtime with its own OAuth token.
6. **Execute tools and return results.** The MCP server calls Google, Open Charge Map, the catalog or AgentCore
   Memory and returns structured JSON.
7. **Query the LLM with tool results.** Steps 4–7 repeat in a ReAct loop until the plan is simulated and feasible.
   A reviewer step then checks the draft.
8. **Stream the final answer to the UI.** Tokens and tool events stream back over SSE. The UI renders the answer,
   the map and the battery chart as they arrive.

### Zooming into the MCP server

<img width="2737" height="1122" alt="ev-copilot-mcp-servers-layer" src="https://github.com/user-attachments/assets/6acc6b31-fc0f-4341-a3ee-bba21da68342" />

The MCP server is one deployable unit: a **FastMCP global server (registry)** that mounts seven domain servers,
each under its own namespace:

| Server | Namespace | Backed by |
|---|---|---|
| Routing | `routing_*` (3 tools) | Google Routes, Geocoding and Elevation APIs |
| Charging | `charging_*` (4 tools) | Google Places API (New) EV charge data; Open Charge Map as fallback |
| Places | `places_*` (3 tools) | Google Places API (New) |
| Vehicle & Energy | `vehicle_*` (3 tools) | Bundled EV catalog + the energy model (which also calls Routes and Elevation) |
| Weather | `weather_*` (4 tools) | Google Weather API |
| User Preferences | `preferences_*` (2 tools) | AgentCore Memory (long-term) |
| Prompts | `prompts_*` (4 prompts) | Bedrock Prompt Management (synced from code) |

Splitting by domain keeps each server small and testable. Mounting them in one registry keeps deployment simple:
one container image, one runtime and one Gateway target. API keys are resolved at startup from **AWS Secrets
Manager**, so no key is ever baked into an image or passed through the agent.

---

## 3. Building the MCP server

### Tools are designed for a model, not a human

<img width="2250" height="1150" alt="ev-copilot-inspector-tool" src="https://github.com/user-attachments/assets/a864973b-2012-465f-9c34-daa7e5d29a98" />

Every tool is a typed Python function with a docstring. FastMCP turns these into the JSON schema the model sees,
shown above as the MCP Inspector form for `charging_search_chargers_along_route`. A few rules shape every tool:

- **Explicit, named arguments.** `origin_latitude`, `origin_longitude` and so on, never "lat,lng" strings or
  encoded polylines, which models get wrong.
- **Structured outputs.** Each tool returns a Pydantic model (e.g. `ChargerSearchResponse`, `TripEnergyPlan`). The
  agent forwards the result to the UI unchanged, and the map, chart and trip panel are built from it.
- **Descriptions that teach.** Docstrings say when to use a tool and what the defaults are, e.g. "Detour is only
  reported when no waypoints are passed".
- **Fail clearly.** Bad input raises a clear error message (e.g. asking Google for details of an Open Charge Map
  station), which the agent can recover from.

The **energy model** (`vehicle_simulate_trip_energy`) is plain, deterministic Python, not an LLM. For each leg it
combines:
- base consumption from the vehicle catalog;
- an aerodynamic correction for the leg's average speed;
- climbing at 90% drivetrain efficiency and regeneration at 60% on descents;
- a temperature factor and the payload;
- charging time from the vehicle's charging curve, capped by the charger's power, at 92% efficiency.

It returns arrival % per leg, charge minutes per stop, an SoC timeline for the chart, a `feasible` flag and
`issues` such as *"Leg 1 arrives at 8% (< 15% buffer) — add a charging stop before km 61"*. The agent must
simulate every plan before presenting it.

### Prompts live in code and are versioned in Bedrock

<img width="2250" height="1363" alt="ev-copilot-inspector-prompt" src="https://github.com/user-attachments/assets/1f45e126-c80e-4413-9dc2-75c873f42d35" />

The four prompts (agent scope, router, simple response, reflection) are defined in Python in
`ev-copilot-mcp/src/prompts/` and served as MCP prompts; above, the agent-scope prompt is fetched with
`user_name = Asha`. On startup the server **syncs them to Amazon Bedrock Prompt Management**:
- it compares a SHA-256 hash of the text and model settings with the Bedrock draft;
- it updates the draft and creates a new version only when something changed, keeping the newest 10;
- it caches prompts for 5 minutes and falls back to the local text if Bedrock is unreachable.

The result: prompts are reviewed in pull requests like code, every change gets a Bedrock version, and every
trace records which prompt version was used.

---

## 4. The agent: the MCP host

The agent is a LangGraph state machine with a deliberately small number of nodes:

```
User message
     │
     ▼
 [Input guardrail] ── blocked? → safe refusal
     │
     ▼
 [Router · Claude Haiku 4.5] → trip_planning | simple | off_topic
     │
     ├──► [Simple response · Sonnet 4.6]   greetings, thanks, off-topic (no tools)
     │
     └──► [Trip planner · Sonnet 4.6]  ⇄  [Tools via MCP]     ReAct loop
                 │      preferences → vehicle → geocode → route → chargers (live)
                 │      → hourly weather + alerts → simulate → re-plan → amenities
                 ▼
          [Reflection · Sonnet 4.6]  COMPLETE ─────────────► [Memory hook] → answer
                 │                                            (saves the turn)
                 └─ NEEDS_MORE_DATA → feedback → back to the planner (max 1 revision round;
                                                 the UI receives `reset` and discards the draft)
     │
     ▼
 [Output guardrail]
```

- **Router.** A small, fast model classifies intent, so greetings and off-topic chat take a cheap path with no
  tools and no planning loop.
- **ReAct trip planner.** Sonnet 4.6 follows the rules in the agent-scope prompt: preferences first, geocode
  before routing, only compatible connectors, always simulate the final plan, prefer live availability, warn about
  weather. It may call several tools in parallel. A **budget of 30 tool calls per turn** keeps cost bounded; when
  it's spent, the model must answer from the data it has. Tool failures are returned to the model as errors it can
  work around, never as crashes.
- **Reflection.** A reviewer step checks the draft against hard rules: was the plan simulated, does every leg stay
  above the buffer, do the connectors fit the car, is the format right. If not, it sends specific feedback back to
  the planner, at most once, so latency stays bounded.
- **Guardrails.** **Amazon Bedrock Guardrails** check the input before anything else runs: harmful content,
  prompt attacks, PII and denied topics such as vehicle tampering. The output is checked after streaming.
- **Memory.** Long-term preferences live in **AgentCore Memory** (user-preference and semantic strategies, scoped
  by actor). After each turn, a background hook saves the exchange through
  `preferences_save_conversation_turn`. Short-term conversation state (the message history of the current chat) is
  checkpointed to AgentCore Memory, keyed by the conversation id.
- **Clock.** The current date and time are injected into the planner's context, so "tomorrow at 6 am" becomes a
  valid departure time.

The agent streams a small set of events to the UI: `chunk` (answer text), `tool_start` / `tool_end` (with the
structured result for the nine map and panel tools), `reset`, `blocked`, `error` and `done`.

---

## 5. Deploying on AgentCore Runtime

Both the MCP server and the agent run on **Amazon Bedrock AgentCore Runtime**: the server with the MCP protocol,
the agent with HTTP. Both are ARM64 containers built by CI and pushed to ECR.

### Session isolation

<img width="2580" height="1470" alt="ev-copilot-session-isolation" src="https://github.com/user-attachments/assets/7f5904d6-4f2b-401b-9b9d-11d8bf456719" />

Every conversation gets its own **microVM**. The UI passes the chat's `conversation_id` as the
`runtimeSessionId`, so each driver's session has isolated CPU, memory and state, and one user's data can't leak
into another's. Idle sessions are recycled (AWS defaults: 15 minutes idle, 8 hours maximum). Durable state, such
as conversation history and preferences, lives in AgentCore Memory, not in the microVM.

### Versions and endpoints

<img width="2580" height="1395" alt="ev-copilot-runtime-versioning" src="https://github.com/user-attachments/assets/a964a4f0-29d2-4132-8461-baa0c6983f3e" />

Each deployment of a new image creates an **immutable runtime version**. EV Copilot uses the `DEFAULT` endpoint,
which follows the latest version. The same mechanism supports separate endpoints, such as production pinned to a
tested version and QA on the newest one, and rolling back by pointing an endpoint at an older version. The prod/QA
split in the figure is illustrative; it isn't provisioned here.

---

## 6. Connecting the agent to the MCP server

### A hybrid connection layer

<img width="2100" height="2085" alt="ev-copilot-mcp-connection-layer" src="https://github.com/user-attachments/assets/f6bf8be0-3723-4b58-876b-95720e289de9" />

There are two ways for an agent to reach an MCP server on AgentCore Runtime, and EV Copilot uses both:
- **Prompts** come over a **direct MCP connection** to the server runtime, because the Gateway proxies tools only.
- **Tools** go through the **AgentCore Gateway**, which adds a managed tool catalog, credential handling and a
  single stable endpoint.

### Option 1: direct connection

!<img width="2550" height="1440" alt="ev-copilot-direct-connection-auth" src="https://github.com/user-attachments/assets/9fbead0f-6b1b-421c-a576-3b2e58cd1ae7" />


The MCP runtime has a **JWT authorizer** backed by **Amazon Cognito**. The agent gets an access token with the
OAuth2 client-credentials flow (scope `evCopilot-api/mcp`) and sends it as a Bearer token with `prompts/list` and
`prompts/get`. The runtime verifies the token's signature, issuer and allowed client before answering. Tokens are
cached and refreshed shortly before they expire.

### Option 2: the AgentCore Gateway

<img width="2820" height="1117" alt="ev-copilot-gateway-architecture" src="https://github.com/user-attachments/assets/da8cda41-3efc-497f-b1f5-78344bc08b6b" />

The **AgentCore Gateway** sits between the agent and the MCP runtime. It has a **target** (`evCopilot-McpTarget`)
pointing at the MCP server, and it keeps a **tools catalog**. The agent lists tools and invokes them by their
prefixed names (`evCopilot-McpTarget___<tool>`), and the Gateway routes each call to the right target.

The catalog is a cached copy of the server's tools, so it has to be kept in sync:

<img width="2580" height="1215" alt="ev-copilot-gateway-catalog-out-of-sync" src="https://github.com/user-attachments/assets/2f4fdd49-5f92-4ea0-8dcf-244bed4a15f0" />

If a new tool is deployed to the MCP server but the catalog isn't refreshed, the agent can't see it. EV Copilot
avoids this by **re-syncing the target in CI** after every MCP deployment (the `sync-gateway` job):

<img width="2580" height="1215" alt="ev-copilot-gateway-sync-target" src="https://github.com/user-attachments/assets/0d7c6e93-31ee-4c8c-b050-1242b350f936" />

The Gateway can also do **semantic tool search**, returning only the tools relevant to a natural-language query.
That helps when there are hundreds of tools:

<img width="2820" height="1095" alt="ev-copilot-gateway-semantic-search" src="https://github.com/user-attachments/assets/1017e79c-7646-4bce-a191-e769d70fb6c6" />

With 19 tools, EV Copilot doesn't need it: the feature is **not enabled**, and the agent binds the full catalog.

### Authentication: inbound and outbound

<img width="2820" height="1072" alt="ev-copilot-gateway-authentication" src="https://github.com/user-attachments/assets/c9cad03f-7481-4d63-8150-9cddd41b94e2" />

Authentication happens twice on the Gateway path:
- **Inbound (agent → Gateway):** a `CUSTOM_JWT` authorizer accepts only Cognito access tokens issued to EV
  Copilot's app client. Without a valid token the Gateway returns `401`, so nobody can call the tools, spend the
  Google quota or read users' preferences.
- **Outbound (Gateway → MCP runtime):** the Gateway gets its own OAuth2 token from **AgentCore Identity** (the
  token vault, using Cognito client credentials) and presents it to the runtime's JWT authorizer.

The agent never handles target credentials, and the Google / Open Charge Map API keys never leave Secrets Manager
and the MCP server.

### Which one to use?

<img width="2370" height="1557" alt="ev-copilot-direct-vs-gateway" src="https://github.com/user-attachments/assets/7d2f94d2-6ea5-4f97-b92f-d5e55c52fd77" />

The direct connection is simpler, faster and gives access to everything the server offers (tools *and* prompts).
The Gateway adds managed authentication, a tool catalog, a stable endpoint and support for non-MCP targets, but it
proxies tools only. EV Copilot takes the best of both: **prompts direct, all 19 tools through the Gateway**.

---

## 7. Observability

An agent that calls a dozen tools per answer is hard to debug without tracing. Every service in EV Copilot is
instrumented with **OpenTelemetry** through the **AWS Distro for OpenTelemetry (ADOT)**. Traces, metrics and logs
land in **Amazon CloudWatch**, **X-Ray** and **CloudWatch GenAI Observability**.

### Metrics and alerts

<img width="2400" height="1095" alt="ev-copilot-cloudwatch-alerting" src="https://github.com/user-attachments/assets/187148af-f51f-40d4-bf3d-353f2c3c4aac" />

AgentCore publishes runtime metrics such as invocations, errors, latency and throttles to CloudWatch, and these can
drive alarms that notify a team through SNS (Slack, email). The figure shows the pattern; the alarms themselves
aren't provisioned by the CDK stacks.

### Sessions, traces and spans

<img width="2640" height="1305" alt="ev-copilot-session-trace-span" src="https://github.com/user-attachments/assets/a230a326-41a1-4cd4-8f16-4d06dbf6b4c1" />

- A **session** is a whole conversation, identified by the `conversation_id`.
- Each user message produces a **trace**.
- Each unit of work inside it is a **span**: `guardrail.input`, `router.classify`, `trip_planner_agent.invoke`,
  every `tools/call`, `reflection.evaluate`, `memory.save_turn_via_mcp` and `guardrail.output`.

The follow-up question in Trace 2 needs no repeated context, because the conversation state from Trace 1 is
restored from the checkpointer.

### Tracing the MCP server

<img width="2670" height="1327" alt="ev-copilot-mcp-tracing-decorator" src="https://github.com/user-attachments/assets/ea3c1b41-49c0-4b42-b07c-1f78ef2c8cf8" />

On the server side, every tool and prompt handler is wrapped by a small `@traced` decorator. It opens a span
(`mcp.tool.<tool>` or `mcp.prompt.<prompt>`), records arguments, timing and errors, and links the span to the
caller's trace. Here is the trace of a prompt fetch, from the MCP request down to Bedrock Prompt Management:

<img width="2250" height="1146" alt="ev-copilot-trace-prompt-fetch" src="https://github.com/user-attachments/assets/8552819c-49d3-4824-a16a-9f785c369c32" />

### End-to-end request tracing

<img width="2820" height="1974" alt="ev-copilot-end-to-end-tracing" src="https://github.com/user-attachments/assets/d7856b73-9ff7-46ed-a357-016fb0fc65eb" />

The same session id travels from the UI through the agent, the Gateway and the MCP server, carried in OpenTelemetry
baggage. One request can therefore be followed across every hop: guardrails, each model call, each tool call, and
the outbound HTTP call to Google:

<img width="2400" height="2280" alt="ev-copilot-trace-trip-planning" src="https://github.com/user-attachments/assets/b4acb7d9-58d6-4550-b19a-3245efa56357" />

That makes it easy to answer questions like "why was this answer slow?" (find the longest span: a model call or a
tool call) or "which prompt version produced this?" (it's recorded on the span).

> **One-time setup:** enable CloudWatch **Transaction Search** in the account and region (it isn't part of the CDK
> stacks), so spans are indexed and appear in GenAI Observability:
>
> ```bash
> aws xray update-trace-segment-destination --destination CloudWatchLogs --region us-east-2
> aws xray update-indexing-rule --name "Default" \
>   --rule '{"Probabilistic": {"DesiredSamplingPercentage": 1}}' --region us-east-2
> ```

---

## 8. The user interface

The UI ([`ev-copilot-ui/`](ev-copilot-ui)) is a Next.js 16 / React 19 app on AWS App Runner:

- **Chat** with streamed markdown answers and a live list of the agent's tool steps ("Planning the route",
  "Finding chargers along the route", "Simulating battery usage" …).
- **Live map** (Google Maps JavaScript API): the route, start and destination pins, chargers coloured by live
  availability (green = free, red = busy, amber = no live data), numbered planned stops and nearby places.
- **Trip panel:** summary cards (distance, drive time, charging time, arrival %), weather alerts and a **battery
  chart** that shows the state of charge falling on climbs, jumping at each stop, and the reserve line.
- **Self-correction is visible:** when the reviewer sends a draft back, the UI receives `reset` and replaces the
  draft with the revised answer.
- **Location** comes from the browser (or `!location <lat> <lng>`), so "chargers near me" works.

The browser never talks to AWS directly. The Next.js server route `/api/chat` invokes the agent with IAM
credentials and re-streams clean SSE events, and the Maps key is served at runtime from Secrets Manager via
`/api/config`.

---

## Getting started

### Prerequisites

- **Python 3.11+**
- **Docker** (to run services locally or build images)
- **Node.js 22+** and **npm** (the Next.js UI requires Node 22+; the CDK infrastructure also runs on Node 20)
- **AWS CLI v2** (for cloud deployment)
- **uv** (Python package manager, used in the Python Dockerfiles)

### API keys

| Key | Where to get it |
|---|---|
| Google Maps Platform server key | [Google Cloud Console](https://console.cloud.google.com/apis/credentials). Enable **Places API (New)**, **Routes API**, **Geocoding API**, **Elevation API** and **Weather API** |
| Google Maps browser key | Same console. Enable **Maps JavaScript API** and restrict the key by **HTTP referrer** (your UI URL). Create a Map ID for Advanced Markers, or use `DEMO_MAP_ID` for development |
| Open Charge Map API key | [openchargemap.org](https://openchargemap.org/site/develop/api) (free; sign in → My Profile → My Apps) |

The agent also needs **Amazon Bedrock model access** to Claude Sonnet 4.6 and Claude Haiku 4.5 in your region. It
authenticates to Bedrock with IAM (the runtime role in AWS, your AWS credentials locally), so there are no model
API keys.

---

## Local development

Every service ships a `.env.example`. Copy it to `.env` (git-ignored) and fill in the values; API keys and AWS
identifiers are blank by default.

### 1. Clone

```bash
git clone <repo-url>
cd ev-copilot-agentcore
```

### 2. Run the MCP server

```bash
cd ev-copilot-mcp
cp .env.example .env
# Fill in: GOOGLE_MAPS_API_KEY, OPEN_CHARGE_MAP_API_KEY

# Option A: Docker (recommended)
docker build -t evcopilot-mcp .
docker run -p 8000:8000 --env-file .env evcopilot-mcp

# Option B: Local Python
uv sync
uv run python -m src.main
```

The MCP server is available at `http://localhost:8000/mcp`. You can explore it with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP → URL: http://localhost:8000/mcp → Connect
```

### 3. Run the agent

```bash
cd ev-copilot-agent
cp .env.example .env
# For local dev, set:
#   LOCAL_MCP_URL=http://localhost:8000/mcp   (bypasses Gateway + Runtime; tools AND prompts from the local MCP)
#   GUARDRAIL_ENABLED=false                   (unless you have a deployed guardrail ID)
# AWS credentials (AWS_PROFILE or access keys) are needed for Bedrock model calls.

# Option A: Docker
docker build -t evcopilot-agent .
docker run -p 8080:8080 --env-file .env evcopilot-agent

# Option B: Local Python
uv sync
uv run python -m src.main
```

The agent API is available at `http://localhost:8080/invocations`.

> **Docker networking:** inside a container, `localhost` is the container itself. When the agent runs in Docker
> and the MCP server runs on your machine (or in another container with a published port), use
> `LOCAL_MCP_URL=http://host.docker.internal:8000/mcp`. On Linux, add
> `--add-host=host.docker.internal:host-gateway` to `docker run`. The same applies to the UI
> (`AGENTCORE_API_URL=http://host.docker.internal:8080/invocations`).

### 4. Run the UI

```bash
cd ev-copilot-ui
cp .env.example .env
# Set: AGENT_CONNECTION_MODE=local
# Set: AGENTCORE_API_URL=http://localhost:8080/invocations
# Optional: GOOGLE_MAPS_BROWSER_API_KEY (blank = chat without the map), GOOGLE_MAPS_MAP_ID=DEMO_MAP_ID

# Option A: Node.js (dev server with hot reload)
npm install
npx next dev --port 3000    # `npm run dev` uses port 8000, which the local MCP server already uses

# Option B: Docker (the container listens on 8000; publish it on 3000 to avoid the MCP port)
docker build -t evcopilot-ui .
docker run -p 3000:8000 --env-file .env evcopilot-ui
```

Open `http://localhost:3000`, allow location access (or type `!location <lat> <lng>`) and start planning a trip.

---

## Cloud deployment (AWS)

The project deploys with **AWS CDK** and a **GitHub Actions** workflow.

### AWS resources created

| Stack | Resources |
|---|---|
| **EcrStack** | 3 ECR repositories (mcp, agent, ui) |
| **AgentCoreStack** | MCP Runtime, AgentCore Memory, 4 Bedrock Prompts, Cognito (User Pool, App Client, OAuth2), Secrets Manager (Google Maps key, Open Charge Map key, Cognito client secret), OpenTelemetry config |
| **GatewayStack** | MCP Gateway (Cognito JWT authorizer), Gateway Target, OAuth2 credential provider Lambda |
| **AgentStack** | Agent Runtime (HTTP), Bedrock Guardrail (content filtering, topic blocking, PII protection) |
| **UiStack** | App Runner service (Next.js UI), Secrets Manager (Google Maps browser key) |

### CI/CD pipeline

[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) runs on every push to `main` and deploys only what
changed. The jobs, in order:
1. `detect-changes` works out which components changed.
2. `deploy-ecr` creates the ECR repositories.
3. `build-mcp`, `build-agent` (ARM64) and `build-ui` (AMD64) build and push the images.
4. `deploy-stacks` runs the CDK deploys.
5. `configure-secrets` writes any API keys supplied with a manual run.
6. `sync-gateway` refreshes the Gateway's tool catalog after MCP changes.

[`.github/workflows/destroy.yml`](.github/workflows/destroy.yml) tears everything down behind a typed confirmation.

### GitHub secrets and variables

Add these secrets under `Settings > Secrets and variables > Actions`:

| Secret | Description |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM access key with permissions for CDK deployment |
| `AWS_SECRET_ACCESS_KEY` | Corresponding secret key |

Optionally, add this repository variable under `Settings > Secrets and variables > Actions > Variables`:

| Variable | Description |
|---|---|
| `MAPS_MAP_ID` | Google Maps Map ID passed to every CI UiStack deploy as `-c mapsMapId` (default `DEMO_MAP_ID`) |

### Deploy

**Automatic:** push to `main`. The workflow detects changed paths and deploys only the affected components.

**Manual:** go to `Actions > Deploy EV Copilot > Run workflow` and choose:
- **Components:** `all`, `infra-only`, `mcp`, `agent` or `ui`
- **Image tag:** a custom tag, or blank for the commit SHA
- **API keys:** optionally `google_maps_api_key`, `openchargemap_api_key` and `google_maps_browser_api_key`. They're
  masked in the logs and written to Secrets Manager after the stacks deploy (the browser key also redeploys the UI).

### First-time deployment

```bash
# 1. Bootstrap CDK (one-time per account/region)
cd ev-copilot-infra
npm ci
npx cdk bootstrap aws://<ACCOUNT_ID>/us-east-2

# 2. Create the ECR repositories, then build and push the three images
#    (runtimes cannot be created before their images exist)
npx cdk deploy evCopilot-EcrStack --exclusively
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com
docker buildx build --platform linux/arm64 -t <ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com/evcopilot-mcp:latest --push ../ev-copilot-mcp
docker buildx build --platform linux/arm64 -t <ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com/evcopilot-agent:latest --push ../ev-copilot-agent
docker buildx build --platform linux/amd64 -t <ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com/evcopilot-ui:latest --push ../ev-copilot-ui

# 3. Deploy all stacks (optional: -c mapsMapId=<your-map-id>; also set the MAPS_MAP_ID
#    repository variable, or the next CI UiStack deploy resets it to DEMO_MAP_ID)
npx cdk deploy --all \
  -c imageUri=<ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com/evcopilot-mcp:latest \
  -c agentImageUri=<ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com/evcopilot-agent:latest \
  -c uiImageUri=<ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com/evcopilot-ui:latest

# 4. Set API keys in Secrets Manager
aws secretsmanager put-secret-value \
  --secret-id "evCopilot/google-maps-api-key" \
  --secret-string '{"api_key":"YOUR_GOOGLE_MAPS_SERVER_KEY"}'

aws secretsmanager put-secret-value \
  --secret-id "evCopilot/openchargemap-api-key" \
  --secret-string '{"api_key":"YOUR_OPEN_CHARGE_MAP_KEY"}'

# The browser key is a plain string (not JSON); redeploy the UI so App Runner loads it
aws secretsmanager put-secret-value \
  --secret-id "evCopilot/google-maps-browser-key" \
  --secret-string 'YOUR_MAPS_JAVASCRIPT_BROWSER_KEY'
aws apprunner start-deployment --service-arn <UiServiceArn from evCopilot-UiStack outputs>

# 5. One-time: enable CloudWatch Transaction Search (see Observability)
```

AgentCore Runtime sessions start in fresh microVMs, so the MCP server picks up updated API keys on new sessions.

> **Upgrading a deployment that predates Gateway auth:** the Gateway now requires a Cognito JWT, and only the
> updated agent sends one. If GatewayStack is updated before the new agent image is live (the CI order), tool calls
> fail for a few minutes, and chats already open on the old agent keep failing until they've been idle for 15
> minutes; start a new chat. To avoid the gap, deploy the agent first
> (`npx cdk deploy evCopilot-AgentStack --exclusively -c agentImageUri=<new image>`), then GatewayStack. Fresh
> deployments aren't affected.

### Destroy

**Via GitHub Actions:** go to `Actions > Destroy EV Copilot Infrastructure > Run workflow`:
- Select the scope (`all` or individual stacks)
- Type `destroy` in the confirmation field
- Optionally enable ECR image deletion

**Via the CLI:**

```bash
cd ev-copilot-infra
npx cdk destroy --all
# ECR repositories are retained (RETAIN) and secrets enter a recovery window. The destroy workflow
# also force-deletes the secrets and the repositories so a redeploy starts clean.
```

---

## Configuration reference

Each service has a `.env.example` file. The key variables are below.

<details>
<summary><b>MCP server</b> (<code>ev-copilot-mcp/.env.example</code>)</summary>

| Variable | Description |
|---|---|
| `AWS_REGION` | AWS region (default `us-east-2`) |
| `GOOGLE_MAPS_API_KEY` | Google Maps Platform server key (local dev) |
| `GOOGLE_MAPS_SECRET_ARN` | Secrets Manager ARN of the Google key (cloud; set by CDK) |
| `OPEN_CHARGE_MAP_API_KEY` | Open Charge Map key (local dev) |
| `OPEN_CHARGE_MAP_SECRET_ARN` | Secrets Manager ARN of the Open Charge Map key (cloud; set by CDK) |
| `AGENTCORE_MEMORY_ID` | Memory ID from the CDK output `MemoryId` |
| `BEDROCK_PROMPT_ID` / `BEDROCK_PROMPT_ROUTER_ID` / `BEDROCK_PROMPT_SIMPLE_ID` / `BEDROCK_PROMPT_REFLECTION_ID` | Prompt IDs from CDK outputs (blank = serve prompts from the local source only) |
| `PROMPT_CACHE_TTL_SECONDS` | Prompt cache TTL (default `300`) |
| `AGENT_OBSERVABILITY_ENABLED` / `OTEL_SERVICE_NAME` / `OTEL_*` | OpenTelemetry settings (`evcopilot-mcp` locally, `evCopilot-mcp` in AWS) |

</details>

<details>
<summary><b>Agent</b> (<code>ev-copilot-agent/.env.example</code>)</summary>

| Variable | Description |
|---|---|
| `APP_NAME` | `evCopilot`: Gateway tool prefix and Cognito scope prefix |
| `AWS_REGION` | AWS region (default `us-east-2`) |
| `LOCAL_MCP_URL` | Local MCP server URL (bypasses the Gateway and Runtime) |
| `GATEWAY_URL` / `GATEWAY_ID` | MCP Gateway URL and ID from CDK outputs |
| `RUNTIME_URL` / `RUNTIME_ID` | Direct MCP Runtime access for prompts |
| `COGNITO_CLIENT_ID` / `COGNITO_TOKEN_ENDPOINT` | Cognito auth (client credentials) for the Gateway and the direct Runtime |
| `COGNITO_CLIENT_SECRET_ARN` | Secrets Manager ARN of the Cognito client secret (cloud; set by CDK) |
| `COGNITO_CLIENT_SECRET` | Plain client secret (local dev only) |
| `MEMORY_ID` | AgentCore Memory ID from the CDK output |
| `BEDROCK_GUARDRAIL_ID` / `BEDROCK_GUARDRAIL_VERSION` / `GUARDRAIL_ENABLED` | Guardrail from the CDK output (`LATEST` resolves the newest version) |
| `ORCHESTRATOR_MODEL_ID` | Trip planner + simple response model (default `us.anthropic.claude-sonnet-4-6`) |
| `ROUTER_MODEL_ID` | Intent routing model (default `us.anthropic.claude-haiku-4-5-20251001-v1:0`) |
| `REFLECTION_MODEL_ID` | Reflection model (default `us.anthropic.claude-sonnet-4-6`) |
| `AGENT_OBSERVABILITY_ENABLED` / `OTEL_SERVICE_NAME` | Observability (`ev-copilot-agent` locally, `evCopilot-agent` in AWS) |

</details>

<details>
<summary><b>UI</b> (<code>ev-copilot-ui/.env.example</code>)</summary>

| Variable | Description |
|---|---|
| `AGENT_CONNECTION_MODE` | `local` or `aws` |
| `AGENTCORE_API_URL` | Agent URL for local mode (`http://localhost:8080/invocations`) |
| `AGENT_RUNTIME_ARN` | Agent Runtime ARN for AWS mode |
| `AWS_REGION` | AWS region (default `us-east-2`) |
| `GOOGLE_MAPS_BROWSER_API_KEY` | Maps JavaScript API key served to the browser via `/api/config` (in AWS, from the `evCopilot/google-maps-browser-key` secret) |
| `GOOGLE_MAPS_MAP_ID` | Map ID (default `DEMO_MAP_ID`; CDK context `mapsMapId`) |

</details>

<details>
<summary><b>CDK context</b> (<code>ev-copilot-infra</code>)</summary>

| Context key | Description |
|---|---|
| `imageUri` / `agentImageUri` / `uiImageUri` | Image URIs (default `<account>.dkr.ecr.<region>.amazonaws.com/evcopilot-<component>:latest`) |
| `mapsMapId` | Google Maps Map ID for the UI (default `DEMO_MAP_ID`) |

</details>

---

## Known limitations

These are deliberate simplifications for a development and demo scope (details in
[ARCHITECTURE.md](ARCHITECTURE.md#known-limitations)):

- **Identity is the typed display name.** The UI has no login; the name is the memory `actor_id`, so anyone who
  types the same name shares that user's remembered vehicle and preferences. The App Runner UI is public.
- **The output guardrail is advisory.** Answers stream token by token; the output check runs after the stream and
  can only log an intervention.
- **Static AWS keys in GitHub Actions**, no OIDC role.
- **No automated test suites.**
- **Browser map key placeholder.** `evCopilot/google-maps-browser-key` starts as `REPLACE_ME`; the map works once
  the real key is set and the UI is redeployed.
- **App Runner's 120-second request limit.** A very long turn can be cut off; the UI reports it as interrupted.
- **Estimates, not guarantees.** Vehicle specifications are approximate and the energy model is a physics-based
  estimate; live availability is only as good as what Google Places reports (Open Charge Map has no live data).

---

## Further reading

- [ARCHITECTURE.md](ARCHITECTURE.md): component details, CDK outputs, how to connect to the MCP server and the
  agent directly (curl and MCP Inspector examples), CI/CD and observability in depth.
- Reference: *Build Production Ready MCP Server From Scratch on AWS Bedrock AgentCore*, the "Place Finder"
  article whose architecture this project follows and extends.

---

## License

This project is provided as-is for educational and demonstration purposes.
