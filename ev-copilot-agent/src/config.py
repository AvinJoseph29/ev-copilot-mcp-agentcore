from __future__ import annotations

import boto3
from loguru import logger
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _fetch_secret(secret_arn: str, region: str) -> str:
    """Fetch a secret string from AWS Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_arn)
    return resp["SecretString"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Model configurations ---
    ORCHESTRATOR_MODEL_ID: str = Field(
        default="us.anthropic.claude-sonnet-4-6",
        description="Model for main orchestrator (tool selection, trip planning, conversation management).",
    )
    ROUTER_MODEL_ID: str = Field(
        default="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        description="Model for router/intent classification (lightweight, fast).",
    )
    REFLECTION_MODEL_ID: str = Field(
        default="us.anthropic.claude-sonnet-4-6",
        description="Model for reflection evaluation (quality review of the trip plan).",
    )

    # --- Guardrails (from CDK — agent does NOT create these) ---
    BEDROCK_GUARDRAIL_ID: str = Field(
        default="",
        description="Bedrock guardrail ID (from CDK stack output). Agent uses, does not create.",
    )
    BEDROCK_GUARDRAIL_VERSION: str = Field(
        default="LATEST",
        description="Bedrock guardrail version. Set to 'LATEST' to auto-resolve the latest published version at startup.",
    )
    GUARDRAIL_ENABLED: bool = Field(
        default=True,
        description="Enable or disable guardrails globally.",
    )

    # --- App ---
    APP_NAME: str = Field(
        default="evCopilot",
        description="Application name — must match the Cognito resource server identifier prefix and the Gateway target prefix.",
    )

    # --- AWS ---
    AWS_REGION: str = Field(
        default="us-east-2",
        description="The AWS region where services are hosted.",
    )

    # --- Local MCP (for local development — overrides Gateway + Runtime) ---
    LOCAL_MCP_URL: str = Field(
        default="",
        description="Local MCP server URL (e.g., http://localhost:8000/mcp). When set, bypasses Gateway and Runtime.",
    )

    # --- AgentCore Gateway (for tool proxy and invocation) ---
    GATEWAY_URL: str = Field(
        default="",
        description="AgentCore MCP Gateway URL for tool proxy and invocation.",
    )
    GATEWAY_ID: str = Field(
        default="",
        description="AgentCore Gateway ID.",
    )

    # --- AgentCore Runtime (for prompts and resources via direct MCP client) ---
    RUNTIME_URL: str = Field(
        default="",
        description="AgentCore Runtime URL for direct MCP access (prompts and resources).",
    )
    RUNTIME_ID: str = Field(
        default="",
        description="AgentCore Runtime ID.",
    )

    # --- Cognito (JWT for the Gateway and direct Runtime auth) ---
    COGNITO_CLIENT_ID: str = Field(
        default="",
        description="Cognito App Client ID for Gateway and direct Runtime auth.",
    )
    COGNITO_CLIENT_SECRET: str = Field(
        default="",
        description="Cognito App Client secret for Gateway and direct Runtime auth (local development only).",
    )
    COGNITO_CLIENT_SECRET_ARN: str = Field(
        default="",
        description="Secrets Manager ARN for the Cognito App Client secret (used in deployed environments).",
    )
    COGNITO_TOKEN_ENDPOINT: str = Field(
        default="",
        description="Cognito token endpoint URL for OAuth2 token exchange.",
    )

    # --- AgentCore Memory ---
    MEMORY_ID: str = Field(
        default="",
        description="AgentCore Memory ID. Must be set from CDK stack output.",
    )

    # --- Observability ---
    AGENT_OBSERVABILITY_ENABLED: bool = Field(
        default=True,
        description="Enable OpenTelemetry-based observability for CloudWatch GenAI Observability.",
    )
    OTEL_SERVICE_NAME: str = Field(
        default="ev-copilot-agent",
        description="Service name for OpenTelemetry tracing attribution.",
    )

    @model_validator(mode="after")
    def _resolve_secrets(self) -> Settings:
        """Resolve the Cognito client secret from Secrets Manager when only the ARN is available.

        In deployed environments the CDK stack passes the secret ARN (never the
        plaintext client secret) to the agent runtime. At startup the
        application fetches the actual value from Secrets Manager. In local
        development the direct COGNITO_CLIENT_SECRET env var is used instead.
        """
        if not self.COGNITO_CLIENT_SECRET and self.COGNITO_CLIENT_SECRET_ARN:
            logger.info("COGNITO_CLIENT_SECRET is empty — fetching from Secrets Manager")
            # AgentCoreStack stores the raw client secret (plain string, not JSON)
            self.COGNITO_CLIENT_SECRET = _fetch_secret(
                self.COGNITO_CLIENT_SECRET_ARN, self.AWS_REGION
            ).strip()

        return self


settings = Settings()
