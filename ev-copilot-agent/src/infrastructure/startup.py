"""
Application startup initialization.

Handles initialization of infrastructure components:
- Observability (OpenTelemetry)
- Guardrails validation (IDs from CDK, NOT created at runtime)
- MCP prompt loading (all 4 prompts from MCP server)

Guardrails are created in CDK infrastructure and their IDs are
passed via environment variables.
"""

from loguru import logger

from src.config import settings
from src.infrastructure.observability import initialize_observability

_startup_complete: bool = False


async def initialize_infrastructure() -> dict:
    """
    Initialize all infrastructure components on application startup.

    Idempotent — calling multiple times only initializes once.

    Returns:
        Dictionary with initialization status for each component.
    """
    global _startup_complete

    if _startup_complete:
        logger.debug("Infrastructure already initialized, skipping")
        return {"status": "already_initialized"}

    logger.info("Initializing application infrastructure...")

    results = {
        "observability": {"status": "pending"},
        "guardrails": {"status": "pending"},
        "prompts": {"status": "pending"},
    }

    # 1. Initialize Observability
    if settings.AGENT_OBSERVABILITY_ENABLED:
        try:
            logger.info("Initializing observability...")
            observability_manager = initialize_observability(
                service_name=settings.OTEL_SERVICE_NAME,
                enabled=settings.AGENT_OBSERVABILITY_ENABLED,
            )
            results["observability"] = {
                "status": "success",
                "service_name": settings.OTEL_SERVICE_NAME,
                "enabled": observability_manager.enabled,
            }
            logger.info(
                f"Observability initialized: service={settings.OTEL_SERVICE_NAME}, "
                f"enabled={observability_manager.enabled}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize observability: {e}")
            results["observability"] = {
                "status": "error",
                "error": str(e),
            }
    else:
        results["observability"] = {"status": "disabled"}
        logger.info("Observability disabled by configuration")

    # 2. Validate Guardrails (IDs from CDK, no runtime creation)
    if settings.GUARDRAIL_ENABLED:
        if settings.BEDROCK_GUARDRAIL_ID:
            results["guardrails"] = {
                "status": "success",
                "guardrail_id": settings.BEDROCK_GUARDRAIL_ID,
                "guardrail_version": settings.BEDROCK_GUARDRAIL_VERSION,
                "source": "cdk_infrastructure",
            }
            logger.info(
                f"Guardrails validated: {settings.BEDROCK_GUARDRAIL_ID} "
                f"(version: {settings.BEDROCK_GUARDRAIL_VERSION}, source: CDK)"
            )
        else:
            results["guardrails"] = {
                "status": "warning",
                "message": "BEDROCK_GUARDRAIL_ID not set. Deploy CDK AgentStack first.",
            }
            logger.warning(
                "BEDROCK_GUARDRAIL_ID not set. Guardrails will be disabled. "
                "Deploy the CDK AgentStack and set the ID from stack output."
            )
    else:
        results["guardrails"] = {"status": "disabled"}
        logger.info("Guardrails disabled by configuration")

    # 3. Load All MCP Prompts (from MCP server — no local fallback)
    try:
        from src.infrastructure.prompt_loader import load_all_prompts
        prompts = await load_all_prompts()
        prompt_names = list(prompts.keys())
        results["prompts"] = {
            "status": "success",
            "count": len(prompts),
            "loaded": prompt_names,
        }
        logger.info(f"Loaded {len(prompts)} prompts: {prompt_names}")
    except Exception as e:
        results["prompts"] = {"status": "error", "error": str(e)}
        logger.exception("Failed to load MCP prompts — agent cannot start without prompts")
        raise

    _startup_complete = True
    logger.info("Infrastructure initialization complete")

    return results
