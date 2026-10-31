"""
MCP Prompt Loader.

Loads all agent prompts from the MCP server's prompt endpoint.
The MCP server is the single source of truth — if it is unreachable
the agent will raise an error instead of silently using stale prompts.
"""

from typing import Any

from loguru import logger

from src.config import settings
from src.domain.prompts import PROMPT_NAMES

# Module-level cache: prompt_name -> prompt_text
_prompt_cache: dict[str, str] = {}


async def load_all_prompts() -> dict[str, str]:
    """
    Load all prompts from the MCP server via direct Runtime connection.

    Returns:
        Dictionary of prompt_name -> prompt_text for all loaded prompts.

    Raises:
        RuntimeError: If the MCP server is unreachable or returns no prompts.
    """
    global _prompt_cache

    if _prompt_cache:
        logger.debug(f"Returning {len(_prompt_cache)} cached prompts")
        return dict(_prompt_cache)

    if not settings.LOCAL_MCP_URL and not settings.RUNTIME_URL:
        raise RuntimeError(
            "No MCP server configured for prompts. "
            "Set LOCAL_MCP_URL (local dev) or RUNTIME_URL (deployed) in your environment."
        )

    mcp_prompts = await _load_from_mcp()
    if not mcp_prompts:
        raise RuntimeError(
            "MCP server is configured but returned no prompts. "
            "Check that the MCP server is running and the prompt endpoints are registered."
        )

    _prompt_cache.update(mcp_prompts)
    logger.info(f"Loaded {len(mcp_prompts)} prompts from MCP server")
    return dict(_prompt_cache)


async def get_prompt(name: str) -> str:
    """
    Get a cached prompt by name. Loads from MCP if not cached.

    Args:
        name: Prompt name (e.g., "ev_copilot_agent_scope").

    Returns:
        The prompt text.

    Raises:
        RuntimeError: If the MCP server is unreachable.
        KeyError: If prompt name is not found.
    """
    if not _prompt_cache:
        await load_all_prompts()

    if name in _prompt_cache:
        return _prompt_cache[name]

    # Try loading just this one prompt from MCP
    text = await _load_single_from_mcp(name)
    if text:
        _prompt_cache[name] = text
        return text

    raise KeyError(
        f"Prompt '{name}' not found in MCP server. "
        f"Available: {list(_prompt_cache.keys())}"
    )


async def _load_from_mcp() -> dict[str, str]:
    """
    Load all prompts from the MCP server via direct Runtime connection.

    Returns:
        Dictionary of prompt_name -> prompt_text.
    """
    from src.infrastructure.mcp_client import get_prompt_client

    results: dict[str, str] = {}

    client = await get_prompt_client()

    server_name = "local_mcp" if settings.LOCAL_MCP_URL else "agentcore_runtime"

    async with client.session(server_name) as session:
        # Discover available prompt names from the server
        available = await _list_available_prompts(session)
        if available:
            logger.info(f"MCP server exposes prompts: {available}")

        for prompt_name in PROMPT_NAMES:
            try:
                text = await _fetch_prompt(session, prompt_name, available)
                if text:
                    results[prompt_name] = text
                    logger.debug(f"Loaded prompt '{prompt_name}' from MCP ({len(text)} chars)")
                else:
                    logger.warning(f"Prompt '{prompt_name}' returned empty content")
            except Exception as e:
                logger.warning(f"Failed to load prompt '{prompt_name}': {e}")

    return results


async def _list_available_prompts(session: Any) -> list[str]:
    """List all prompt names available on the MCP server."""
    try:
        result = await session.list_prompts()
        if result and hasattr(result, "prompts"):
            return [p.name for p in result.prompts]
        if isinstance(result, list):
            return [p.name for p in result if hasattr(p, "name")]
    except Exception as e:
        logger.warning(f"Failed to list prompts from MCP server: {e}")
    return []


async def _load_single_from_mcp(name: str) -> str | None:
    """Load a single prompt from the MCP server."""
    from src.infrastructure.mcp_client import get_prompt_client

    client = await get_prompt_client()

    server_name = "local_mcp" if settings.LOCAL_MCP_URL else "agentcore_runtime"

    async with client.session(server_name) as session:
        available = await _list_available_prompts(session)
        return await _fetch_prompt(session, name, available)


async def _fetch_prompt(
    session: Any,
    prompt_name: str,
    available: list[str] | None = None,
) -> str | None:
    """
    Fetch a single prompt from the MCP session.

    Tries multiple name variants to account for namespace prefixing:
    - prompts_{name}  (FastMCP underscore namespace mount)
    - prompts.{name}  (dot namespace)
    - {name}          (no namespace)

    If a server prompt list is provided, picks the matching name directly.
    """
    # Build candidate names
    candidates = [
        f"prompts_{prompt_name}",
        f"prompts.{prompt_name}",
        prompt_name,
    ]

    # If we have the server's prompt list, find the actual name
    if available:
        for avail in available:
            if avail.endswith(prompt_name) and avail not in candidates:
                candidates.insert(0, avail)

    last_error: Exception | None = None
    for name_variant in candidates:
        try:
            result = await session.get_prompt(name_variant, arguments={})
            text = _extract_prompt_text(result)
            if text:
                logger.debug(f"Prompt '{prompt_name}' resolved as '{name_variant}'")
                return text
        except Exception as e:
            last_error = e
            logger.debug(f"Prompt variant '{name_variant}' failed: {e}")
            continue

    if last_error:
        logger.warning(
            f"All name variants failed for prompt '{prompt_name}': {last_error}"
        )
    return None


def _extract_prompt_text(result: Any) -> str | None:
    """Extract prompt text from MCP get_prompt response."""
    if result is None:
        return None

    # MCP GetPromptResult has a 'messages' field
    if hasattr(result, "messages"):
        messages = result.messages
        if messages:
            first_msg = messages[0]
            if hasattr(first_msg, "content"):
                content = first_msg.content
                if isinstance(content, str):
                    return content
                if hasattr(content, "text"):
                    return content.text
                if isinstance(content, list) and content:
                    first_content = content[0]
                    if hasattr(first_content, "text"):
                        return first_content.text
                    if isinstance(first_content, dict):
                        return first_content.get("text", str(first_content))

    # Plain string result
    if isinstance(result, str):
        return result

    return None
