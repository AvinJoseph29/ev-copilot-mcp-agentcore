"""
Bedrock Prompt Manager.

Manages the full lifecycle of Bedrock managed prompts:
- Sync local prompt definitions to Bedrock DRAFT on startup
- SHA-256 hash-based comparison (template text + model/inference config)
  to avoid unnecessary updates
- Auto-version creation when content changes
- 10-version limit management (delete oldest before creating new)
- Variable substitution at render time
- TTL-cached prompt retrieval

The boto3 bedrock-agent client is synchronous, so all calls are wrapped
in asyncio.to_thread() to avoid blocking the ASGI event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

import boto3
from loguru import logger

from src.config import settings
from src.prompts import PROMPT_REGISTRY, PromptDefinition

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_BEDROCK_VERSIONS = 10

# Bedrock UpdatePrompt limits the prompt description to 200 characters
MAX_DESCRIPTION_LENGTH = 200

# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_manager: BedrockPromptManager | None = None


def get_prompt_manager() -> BedrockPromptManager:
    """Return the global BedrockPromptManager singleton (lazy-init)."""
    global _manager
    if _manager is None:
        _manager = BedrockPromptManager(
            region_name=settings.AWS_REGION,
            cache_ttl_seconds=settings.PROMPT_CACHE_TTL_SECONDS,
        )
    return _manager


# ---------------------------------------------------------------------------
# Manager class
# ---------------------------------------------------------------------------


class BedrockPromptManager:
    """Manages Bedrock prompt lifecycle: sync, version, cache, render."""

    def __init__(
        self,
        region_name: str,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self._region_name = region_name
        self._cache_ttl = cache_ttl_seconds
        self._boto_client = None

        # Per-prompt cache: prompt_name -> (text, version, timestamp)
        self._cache: dict[str, tuple[str, str, float]] = {}

    def _get_boto_client(self):
        """Lazy-init the boto3 bedrock-agent client (called inside thread)."""
        if self._boto_client is None:
            self._boto_client = boto3.client(
                "bedrock-agent",
                region_name=self._region_name,
            )
        return self._boto_client

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    @staticmethod
    def _content_hash(
        text: str,
        model_id: str = "",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Compute SHA-256 hash of prompt text + variant configuration.

        Including the model and inference configuration ensures that a
        change to model_id / temperature / top_p / max_tokens alone is
        also synced to Bedrock (not only template text changes).
        """
        payload = {
            "text": (text or "").strip(),
            "model_id": model_id or "",
            "temperature": None if temperature is None else round(float(temperature), 4),
            "top_p": None if top_p is None else round(float(top_p), 4),
            "max_tokens": None if max_tokens is None else int(max_tokens),
        }
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def _definition_hash(cls, definition: PromptDefinition) -> str:
        """Hash of a local prompt definition."""
        return cls._content_hash(
            definition.template_text,
            model_id=definition.model_id,
            temperature=definition.temperature,
            top_p=definition.top_p,
            max_tokens=definition.max_tokens,
        )

    @classmethod
    def _draft_hash(cls, draft_response: dict) -> str:
        """Hash of the Bedrock DRAFT variant (same fields as the local hash)."""
        variant = draft_response["variants"][0]
        inference = variant.get("inferenceConfiguration", {}).get("text", {})
        return cls._content_hash(
            variant["templateConfiguration"]["text"]["text"],
            model_id=variant.get("modelId", ""),
            temperature=inference.get("temperature"),
            top_p=inference.get("topP"),
            max_tokens=inference.get("maxTokens"),
        )

    # ------------------------------------------------------------------
    # Bedrock API wrappers (all sync, run via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _get_draft(self, prompt_id: str) -> dict:
        """Fetch the DRAFT prompt from Bedrock (sync)."""
        client = self._get_boto_client()
        return client.get_prompt(promptIdentifier=prompt_id)

    def _update_draft(
        self,
        prompt_id: str,
        name: str,
        definition: PromptDefinition,
        description: str = "",
    ) -> dict:
        """Update the DRAFT prompt in Bedrock (sync).

        ``description`` is passed through so the description set by CDK is
        preserved (UpdatePrompt replaces the whole prompt resource).
        """
        client = self._get_boto_client()
        input_variables = [{"name": v} for v in definition.variables]
        kwargs: dict = {}
        if description:
            kwargs["description"] = description[:MAX_DESCRIPTION_LENGTH]
        return client.update_prompt(
            promptIdentifier=prompt_id,
            name=name,
            defaultVariant="default",
            variants=[
                {
                    "name": "default",
                    "templateType": "TEXT",
                    "modelId": definition.model_id,
                    "templateConfiguration": {
                        "text": {
                            "text": definition.template_text,
                            "inputVariables": input_variables,
                        },
                    },
                    "inferenceConfiguration": {
                        "text": {
                            "temperature": definition.temperature,
                            "topP": definition.top_p,
                            "maxTokens": definition.max_tokens,
                        },
                    },
                },
            ],
            **kwargs,
        )

    def _create_version(self, prompt_id: str, description: str) -> dict:
        """Create an immutable version from current DRAFT (sync)."""
        client = self._get_boto_client()
        return client.create_prompt_version(
            promptIdentifier=prompt_id,
            description=description,
        )

    def _list_versions(self, prompt_id: str) -> list[dict]:
        """List all versions for a prompt (sync, handles pagination)."""
        client = self._get_boto_client()
        summaries: list[dict] = []
        kwargs: dict = {"promptIdentifier": prompt_id}

        while True:
            response = client.list_prompts(**kwargs)
            summaries.extend(response.get("promptSummaries", []))
            next_token = response.get("nextToken")
            if not next_token:
                break
            kwargs["nextToken"] = next_token

        return summaries

    def _delete_version(self, prompt_id: str, version: str) -> None:
        """Delete a specific numbered version (sync)."""
        client = self._get_boto_client()
        client.delete_prompt(
            promptIdentifier=prompt_id,
            promptVersion=version,
        )

    # ------------------------------------------------------------------
    # Version limit management
    # ------------------------------------------------------------------

    def _enforce_version_limit(self, prompt_id: str) -> None:
        """If at MAX_BEDROCK_VERSIONS, delete the oldest numbered version."""
        summaries = self._list_versions(prompt_id)

        # Filter to numbered versions only (exclude DRAFT)
        numbered = [
            s for s in summaries
            if s.get("version", "DRAFT") != "DRAFT"
        ]

        if len(numbered) < MAX_BEDROCK_VERSIONS:
            return

        # Sort by version number ascending, delete the lowest
        numbered.sort(key=lambda s: int(s["version"]))
        oldest = numbered[0]
        oldest_version = oldest["version"]

        logger.warning(
            f"Bedrock version limit reached ({MAX_BEDROCK_VERSIONS}) for "
            f"prompt {prompt_id}. Deleting oldest version: {oldest_version}"
        )
        self._delete_version(prompt_id, oldest_version)

    # ------------------------------------------------------------------
    # Sync: local -> Bedrock
    # ------------------------------------------------------------------

    async def sync_prompt(self, definition: PromptDefinition) -> None:
        """Sync a single local prompt definition to Bedrock.

        Compares the local definition hash (template text + model and
        inference configuration) against the Bedrock DRAFT hash.
        If they differ, updates the DRAFT and creates a new immutable version.
        """
        prompt_id = getattr(settings, definition.bedrock_config_key, "")
        if not prompt_id:
            logger.warning(
                f"Skipping sync for {definition.name!r}: "
                f"{definition.bedrock_config_key} is not set."
            )
            return

        local_hash = self._definition_hash(definition)

        def _sync() -> None:
            # 1. Fetch current DRAFT
            try:
                draft_response = self._get_draft(prompt_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    f"Failed to fetch DRAFT for prompt {prompt_id}. "
                    f"Skipping sync for {definition.name!r}."
                )
                return

            draft_hash = self._draft_hash(draft_response)
            prompt_name = draft_response.get("name", definition.name)
            description = draft_response.get("description") or definition.description

            # 2. Compare hashes
            if local_hash == draft_hash:
                logger.info(
                    f"Prompt {definition.name!r} is up-to-date "
                    f"(hash={local_hash[:12]}...)."
                )
                return

            logger.info(
                f"Prompt {definition.name!r} content changed. "
                f"Local hash={local_hash[:12]}... vs "
                f"DRAFT hash={draft_hash[:12]}..."
            )

            # 3. Update DRAFT
            try:
                self._update_draft(prompt_id, prompt_name, definition, description)
                logger.info(
                    f"Updated DRAFT for prompt {definition.name!r}."
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    f"Failed to update DRAFT for prompt {definition.name!r}."
                )
                return

            # 4. Enforce version limit before creating new version
            try:
                self._enforce_version_limit(prompt_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    f"Failed to enforce version limit for "
                    f"prompt {definition.name!r}."
                )

            # 5. Create new immutable version
            try:
                version_response = self._create_version(
                    prompt_id,
                    description=(
                        f"Auto-synced from local source. "
                        f"Hash: {local_hash[:12]}"
                    ),
                )
                new_version = version_response.get("version", "unknown")
                logger.info(
                    f"Created version {new_version} for "
                    f"prompt {definition.name!r}."
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    f"Failed to create version for "
                    f"prompt {definition.name!r}."
                )

        await asyncio.to_thread(_sync)

    async def sync_all_prompts(self) -> None:
        """Sync all registered prompt definitions to Bedrock.

        Called once on application startup from tool_registry.initialize().
        """
        if not PROMPT_REGISTRY:
            logger.warning("No prompts registered. Nothing to sync.")
            return

        logger.info(
            f"Syncing {len(PROMPT_REGISTRY)} prompt(s) to Bedrock..."
        )
        for definition in PROMPT_REGISTRY.values():
            await self.sync_prompt(definition)
        logger.info("Prompt sync complete.")

    # ------------------------------------------------------------------
    # Cached retrieval
    # ------------------------------------------------------------------

    async def get_prompt_text(
        self,
        prompt_name: str,
        version: str | None = None,
    ) -> str:
        """Fetch prompt text from Bedrock with TTL caching.

        Falls back to local template text if Bedrock is unreachable.

        Args:
            prompt_name: Logical prompt name (key in PROMPT_REGISTRY).
            version: Optional Bedrock version. Omit for DRAFT.
        """
        now = time.monotonic()
        cached = self._cache.get(prompt_name)
        if cached is not None:
            cached_text, cached_ver, cached_ts = cached
            if (now - cached_ts) < self._cache_ttl:
                logger.debug(
                    f"Returning cached prompt {prompt_name!r} "
                    f"(version={cached_ver})."
                )
                return cached_text

        definition = PROMPT_REGISTRY.get(prompt_name)
        if definition is None:
            raise ValueError(f"Unknown prompt: {prompt_name!r}")

        prompt_id = getattr(settings, definition.bedrock_config_key, "")
        if not prompt_id:
            logger.warning(
                f"No Bedrock ID for {prompt_name!r}. "
                f"Returning local template text."
            )
            return definition.template_text

        def _fetch() -> tuple[str, str]:
            client = self._get_boto_client()
            kwargs: dict = {"promptIdentifier": prompt_id}
            if version:
                kwargs["promptVersion"] = version
            response = client.get_prompt(**kwargs)
            text = (
                response["variants"][0]
                ["templateConfiguration"]["text"]["text"]
            )
            ver = response.get("version", "DRAFT")
            return text, ver

        try:
            text, ver = await asyncio.to_thread(_fetch)
        except Exception:  # noqa: BLE001
            logger.exception(
                f"Failed to fetch prompt {prompt_name!r} from Bedrock. "
                f"Falling back to local template."
            )
            text = definition.template_text
            ver = "LOCAL"

        self._cache[prompt_name] = (text, ver, now)
        logger.info(
            f"Fetched prompt {prompt_name!r} (version={ver}, "
            f"length={len(text)})."
        )
        return text

    # ------------------------------------------------------------------
    # Render with variable substitution
    # ------------------------------------------------------------------

    async def render_prompt(
        self,
        prompt_name: str,
        **variables: str,
    ) -> str:
        """Fetch prompt text and substitute {{variables}}.

        Args:
            prompt_name: Logical prompt name (key in PROMPT_REGISTRY).
            **variables: Variable values to substitute into the template.
        """
        text = await self.get_prompt_text(prompt_name)
        definition = PROMPT_REGISTRY.get(prompt_name)
        if definition is None:
            return text

        # Only substitute supplied values: an unfilled placeholder (e.g.
        # {{user_name}}) is left for the agent's per-request substitution.
        for var_name in definition.variables:
            placeholder = "{{" + var_name + "}}"
            value = variables.get(var_name)
            if value:
                text = text.replace(placeholder, value)

        return text
