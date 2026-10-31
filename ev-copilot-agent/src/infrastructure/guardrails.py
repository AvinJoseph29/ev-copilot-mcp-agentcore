"""
Guardrail infrastructure using AWS Bedrock Guardrails.

Production pattern: Guardrails are created in CDK infrastructure (agent-stack.ts)
and their IDs are passed to the agent via environment variables. The agent
only USES guardrails — it does NOT create them at runtime.

This is more production-ready than creating guardrails at runtime because:
- Guardrail lifecycle is managed by IaC (versioned, auditable)
- No race conditions on startup with multiple replicas
- Guardrail changes go through code review (PR → CDK deploy)
- Separation of concerns: infra team owns guardrails, agent team uses them
"""

import boto3
from botocore.exceptions import ClientError
from loguru import logger

from src.config import settings


class GuardrailManager:
    """
    Uses guardrail IDs from CDK infrastructure (env vars).

    Does NOT create guardrails — that's handled by the CDK AgentStack.
    Automatically resolves the latest published guardrail version from AWS.
    """

    def __init__(self):
        self._guardrail_id = settings.BEDROCK_GUARDRAIL_ID
        self._guardrail_version = settings.BEDROCK_GUARDRAIL_VERSION

        if self._guardrail_id:
            if self._guardrail_version.upper() == "LATEST":
                resolved = self._resolve_latest_version()
                self._guardrail_version = resolved or "1"
            logger.info(
                f"Guardrail configured from CDK: id={self._guardrail_id}, "
                f"version={self._guardrail_version}"
            )
        else:
            logger.warning(
                "BEDROCK_GUARDRAIL_ID not set. Guardrails will be inactive. "
                "Deploy the CDK AgentStack and set the ID from stack output."
            )

    def _resolve_latest_version(self) -> str | None:
        """Fetch the latest published guardrail version from AWS."""
        try:
            client = boto3.client("bedrock", region_name=settings.AWS_REGION)
            response = client.list_guardrails(
                guardrailIdentifier=self._guardrail_id
            )
            versions = [
                g["version"]
                for g in response.get("guardrails", [])
                if g.get("version", "DRAFT") != "DRAFT"
            ]
            if versions:
                latest = str(max(int(v) for v in versions))
                logger.info(f"Resolved latest guardrail version: {latest}")
                return latest
            logger.warning("No published guardrail versions found, using default")
            return None
        except Exception as e:
            logger.warning(f"Failed to resolve latest guardrail version: {e}")
            return None

    @property
    def guardrail_id(self) -> str | None:
        """Get the guardrail ID (from CDK)."""
        return self._guardrail_id or None

    @property
    def guardrail_version(self) -> str | None:
        """Get the guardrail version (from CDK)."""
        return self._guardrail_version or None

    def get_guardrail_config(self) -> dict | None:
        """
        Get the guardrail configuration for use with ChatBedrockConverse.

        Returns:
            Guardrail config dict or None if disabled/not configured.
        """
        if not settings.GUARDRAIL_ENABLED:
            return None

        if not self._guardrail_id:
            return None

        return {
            "guardrailIdentifier": self._guardrail_id,
            "guardrailVersion": self._guardrail_version or "1",
        }


# Singleton instance for application-wide use
_guardrail_manager: GuardrailManager | None = None


def get_guardrail_manager() -> GuardrailManager:
    """Get or create the singleton GuardrailManager instance."""
    global _guardrail_manager
    if _guardrail_manager is None:
        _guardrail_manager = GuardrailManager()
    return _guardrail_manager


# =============================================================================
# Graph-Level Guardrail Functions (ApplyGuardrail API)
# =============================================================================

class GuardrailResult:
    """Result of a guardrail check."""

    def __init__(
        self,
        allowed: bool,
        output: str,
        action: str,
        assessments: list | None = None,
    ):
        self.allowed = allowed
        self.output = output
        self.action = action
        self.assessments = assessments or []

    def __repr__(self) -> str:
        return f"GuardrailResult(allowed={self.allowed}, action={self.action})"


def apply_input_guardrail(text: str) -> GuardrailResult:
    """
    Apply guardrail to user input at graph entry.

    Uses the ApplyGuardrail API to check content independently of model calls.
    """
    if not settings.GUARDRAIL_ENABLED:
        return GuardrailResult(allowed=True, output=text, action="NONE")

    manager = get_guardrail_manager()
    if not manager.guardrail_id:
        logger.warning("Guardrail not configured, skipping input check")
        return GuardrailResult(allowed=True, output=text, action="NONE")

    try:
        runtime_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.AWS_REGION,
        )

        response = runtime_client.apply_guardrail(
            guardrailIdentifier=manager.guardrail_id,
            guardrailVersion=manager.guardrail_version or "1",
            source="INPUT",
            content=[{"text": {"text": text}}],
        )

        action = response.get("action", "NONE")
        outputs = response.get("outputs", [])
        assessments = response.get("assessments", [])

        if outputs:
            output_text = outputs[0].get("text", text)
        else:
            output_text = text

        allowed = action != "GUARDRAIL_INTERVENED"

        if not allowed:
            logger.info(f"Input guardrail blocked content: action={action}")
            for assessment in assessments:
                if assessment.get("topicPolicy"):
                    topics = assessment["topicPolicy"].get("topics", [])
                    for topic in topics:
                        if topic.get("action") == "BLOCKED":
                            logger.warning(f"  Blocked by topic: {topic.get('name')}")
                if assessment.get("contentPolicy"):
                    filters = assessment["contentPolicy"].get("filters", [])
                    for f in filters:
                        if f.get("action") == "BLOCKED":
                            logger.warning(f"  Blocked by content filter: {f.get('type')}")

        return GuardrailResult(
            allowed=allowed,
            output=output_text,
            action=action,
            assessments=assessments,
        )

    except ClientError as e:
        logger.error(f"Error applying input guardrail: {e}")
        # Fail open - allow the request but log the error
        return GuardrailResult(allowed=True, output=text, action="ERROR")


def apply_output_guardrail(text: str) -> GuardrailResult:
    """
    Apply guardrail to model output at graph exit.

    Uses the ApplyGuardrail API to check content independently of model calls.
    """
    if not settings.GUARDRAIL_ENABLED:
        return GuardrailResult(allowed=True, output=text, action="NONE")

    manager = get_guardrail_manager()
    if not manager.guardrail_id:
        logger.warning("Guardrail not configured, skipping output check")
        return GuardrailResult(allowed=True, output=text, action="NONE")

    try:
        runtime_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.AWS_REGION,
        )

        response = runtime_client.apply_guardrail(
            guardrailIdentifier=manager.guardrail_id,
            guardrailVersion=manager.guardrail_version or "1",
            source="OUTPUT",
            content=[{"text": {"text": text}}],
        )

        action = response.get("action", "NONE")
        outputs = response.get("outputs", [])
        assessments = response.get("assessments", [])

        if outputs:
            output_text = outputs[0].get("text", text)
        else:
            output_text = text

        allowed = action != "GUARDRAIL_INTERVENED"

        if not allowed:
            logger.info(f"Output guardrail modified content: action={action}")

        return GuardrailResult(
            allowed=allowed,
            output=output_text,
            action=action,
            assessments=assessments,
        )

    except ClientError as e:
        logger.error(f"Error applying output guardrail: {e}")
        return GuardrailResult(allowed=True, output=text, action="ERROR")


def get_blocked_input_message() -> str:
    """Get the default message to show when input is blocked."""
    return (
        "I'm sorry, but I can't help with that request. "
        "I'm EV Copilot — I can plan electric-vehicle road trips, find chargers "
        "along your route, estimate your battery at each stop and check the "
        "weather for your drive."
    )


