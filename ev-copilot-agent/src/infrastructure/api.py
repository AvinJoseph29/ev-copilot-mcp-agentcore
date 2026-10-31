"""
API entrypoint for the EV Copilot Agent.

Provides the main entrypoint for BedrockAgentCoreApp with startup hooks
for initializing infrastructure components.
"""

from contextlib import asynccontextmanager

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from loguru import logger

from src.infrastructure.startup import initialize_infrastructure
from src.infrastructure.streaming import stream_response


async def startup_event():
    """
    Application startup hook.

    Initializes infrastructure components:
    - Observability (OpenTelemetry with CloudWatch GenAI Observability)
    - Guardrails validation (IDs from CDK, no runtime creation)
    - MCP prompt loading (from MCP server — no local fallback)
    """
    logger.info("Application startup initiated")
    results = await initialize_infrastructure()

    # Log initialization summary
    observability_status = results.get("observability", {}).get("status", "unknown")
    guardrail_status = results.get("guardrails", {}).get("status", "unknown")
    prompt_status = results.get("prompts", {}).get("status", "unknown")

    logger.info(
        f"Startup complete - Observability: {observability_status}, "
        f"Guardrails: {guardrail_status}, Prompt: {prompt_status}"
    )

    if observability_status == "error":
        logger.warning(
            f"Observability initialization error: {results['observability'].get('error')}"
        )

    if guardrail_status == "error":
        logger.warning(
            f"Guardrail validation error: {results['guardrails'].get('error')}"
        )


@asynccontextmanager
async def lifespan(_app):
    """
    Starlette lifespan handler.

    Starlette 1.x removed ``on_event("startup")``, so the startup hook runs
    from the lifespan context instead. If startup raises (e.g. prompts cannot
    be loaded) the server does not start — the agent cannot run without prompts.
    """
    await startup_event()
    yield


# Initialize BedrockAgentCoreApp
app = BedrockAgentCoreApp(lifespan=lifespan)


@app.entrypoint
async def invoke(payload: dict):
    """
    Main entrypoint for the agent.

    Expected payload:
    {
        "prompt": "<user input>",               # Required
        "customer_name": "<customer name>",     # Optional, defaults to "Guest"
        "conversation_id": "<conversation id>", # Optional, unique ID for conversation thread
        "latitude": 18.5204,                    # Optional, user's latitude from browser geolocation
        "longitude": 73.8567                    # Optional, user's longitude from browser geolocation
    }

    Returns an async generator for streaming, or dict for errors.
    """
    user_input = payload.get("prompt", "")
    if not user_input:
        return {"error": "No prompt provided in the payload."}

    # Extract optional customer context
    customer_name = payload.get("customer_name", "Guest")
    conversation_id = payload.get("conversation_id")

    # Extract optional location coordinates (both required or neither)
    latitude = None
    longitude = None
    raw_lat = payload.get("latitude")
    raw_lng = payload.get("longitude")
    if raw_lat is not None and raw_lng is not None:
        try:
            latitude = float(raw_lat)
            longitude = float(raw_lng)
        except (TypeError, ValueError):
            latitude = None
            longitude = None

    # Return async generator - BedrockAgentCoreApp handles streaming automatically
    return stream_response(
        user_input=user_input,
        customer_name=customer_name,
        conversation_id=conversation_id,
        latitude=latitude,
        longitude=longitude,
    )


if __name__ == "__main__":
    app.run()
