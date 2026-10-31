from __future__ import annotations

import json

import boto3
from loguru import logger
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _fetch_secret(secret_arn: str, region: str) -> dict:
    """Fetch a JSON secret from AWS Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_arn)
    return json.loads(resp["SecretString"])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- AWS ---
    AWS_REGION: str = Field(
        default="us-east-2",
        description="AWS region for all services.",
    )

    # --- AgentCore Memory ---
    AGENTCORE_MEMORY_ID: str = Field(
        default="",
        description="Bedrock AgentCore Memory resource ID for user preferences.",
    )

    # --- Google Maps Platform API ---
    GOOGLE_MAPS_API_KEY: str = Field(
        default="",
        description=(
            "Server-side API key for Google Maps Platform "
            "(Places API (New), Routes, Geocoding, Elevation, Weather)."
        ),
    )
    GOOGLE_MAPS_SECRET_ARN: str = Field(
        default="",
        description="Secrets Manager ARN for the Google Maps API key (used in deployed environments).",
    )

    # --- Open Charge Map API ---
    OPEN_CHARGE_MAP_API_KEY: str = Field(
        default="",
        description="API key for Open Charge Map (fallback charger coverage).",
    )
    OPEN_CHARGE_MAP_SECRET_ARN: str = Field(
        default="",
        description="Secrets Manager ARN for the Open Charge Map API key (used in deployed environments).",
    )

    # --- Bedrock Prompt Management ---
    BEDROCK_PROMPT_ID: str = Field(
        default="",
        description="Bedrock Prompt ID for the agent scope prompt.",
    )
    BEDROCK_PROMPT_ROUTER_ID: str = Field(
        default="",
        description="Bedrock Prompt ID for the router intent classifier prompt.",
    )
    BEDROCK_PROMPT_SIMPLE_ID: str = Field(
        default="",
        description="Bedrock Prompt ID for the simple response prompt.",
    )
    BEDROCK_PROMPT_REFLECTION_ID: str = Field(
        default="",
        description="Bedrock Prompt ID for the reflection quality review prompt.",
    )
    PROMPT_CACHE_TTL_SECONDS: int = Field(
        default=300,
        description="TTL in seconds for the prompt text cache.",
    )

    # --- Observability ---
    AGENT_OBSERVABILITY_ENABLED: bool = Field(
        default=True,
        description="Enable OpenTelemetry-based observability for CloudWatch GenAI Observability.",
    )
    OTEL_SERVICE_NAME: str = Field(
        default="evcopilot-mcp",
        description="Service name for OpenTelemetry tracing attribution.",
    )

    @model_validator(mode="after")
    def _resolve_secrets(self) -> Settings:
        """Resolve API keys from Secrets Manager when only the ARN is available.

        In deployed environments the CDK stack passes secret ARNs (not the
        resolved values) to avoid the CloudFormation dynamic-reference
        freeze problem.  At startup the application fetches the actual key
        from Secrets Manager.  In local development the direct API key env
        vars are used instead.
        """
        if not self.GOOGLE_MAPS_API_KEY and self.GOOGLE_MAPS_SECRET_ARN:
            logger.info("GOOGLE_MAPS_API_KEY is empty — fetching from Secrets Manager")
            secret = _fetch_secret(self.GOOGLE_MAPS_SECRET_ARN, self.AWS_REGION)
            self.GOOGLE_MAPS_API_KEY = secret.get("api_key", "")

        if not self.OPEN_CHARGE_MAP_API_KEY and self.OPEN_CHARGE_MAP_SECRET_ARN:
            logger.info("OPEN_CHARGE_MAP_API_KEY is empty — fetching from Secrets Manager")
            secret = _fetch_secret(self.OPEN_CHARGE_MAP_SECRET_ARN, self.AWS_REGION)
            self.OPEN_CHARGE_MAP_API_KEY = secret.get("api_key", "")

        return self


settings = Settings()
