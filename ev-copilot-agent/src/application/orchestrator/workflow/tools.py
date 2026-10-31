"""
Tool registry for the EV Copilot workflow.

All tools are auto-discovered from the MCP server — no agent-side wrappers.
The LLM sees MCP tools' native names, descriptions, and schemas directly.
Adding a new tool to the MCP server automatically makes it available to the
agent with zero code changes here.

The only exclusion is save_conversation_turn, which is internal to the
memory_post_hook node and should not be LLM-callable.
"""

import json
from typing import Any

from loguru import logger

from src.infrastructure.mcp_client import (
    get_tool_client,
    get_tool_name,
    is_gateway_configured,
)

# =============================================================================
# Internal-only MCP tool name used by the memory_post_hook node.
# This is the only hardcoded tool reference — everything else is auto-discovered.
# =============================================================================

SAVE_CONVERSATION_TURN_TOOL = "preferences_save_conversation_turn"


# =============================================================================
# MCP Tool Execution (used by the memory_post_hook node)
# =============================================================================

async def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Call a tool via the MCP gateway client.

    Used by internal nodes (e.g. memory_post_hook) that need to invoke
    MCP tools programmatically — not by the LLM.
    """
    if not is_gateway_configured():
        raise RuntimeError("MCP gateway not configured. Set GATEWAY_URL.")

    try:
        client = get_tool_client()
        tools = await client.get_tools()

        # Resolve the tool name for gateway/local invocation:
        # local → "preferences_save_conversation_turn"
        # gateway → "evCopilot-McpTarget___preferences_save_conversation_turn"
        resolved_name = get_tool_name(tool_name)

        # Exact match only — a loose substring match could pick an unintended tool.
        target_tool = next((t for t in tools if t.name == resolved_name), None)

        if not target_tool:
            available = [t.name for t in tools]
            logger.warning(f"Tool '{tool_name}' (resolved: '{resolved_name}') not found. Available: {available}")
            raise RuntimeError(f"Tool '{tool_name}' not found in MCP")

        logger.info(f"Invoking MCP tool: {target_tool.name}")
        result = await target_tool.ainvoke(arguments)

        return _parse_mcp_result(result)

    except Exception as e:
        # The MCP transport wraps failures (e.g. a 401 or a token endpoint error)
        # in an ExceptionGroup; report the underlying error.
        root = _root_cause(e)
        logger.error(f"MCP tool call failed: {type(root).__name__}: {root}")
        raise RuntimeError(f"Failed to call MCP tool '{tool_name}': {type(root).__name__}: {root}") from e


def _root_cause(e: BaseException) -> BaseException:
    """Unwrap single-exception ExceptionGroups to the error that actually occurred."""
    while isinstance(e, BaseExceptionGroup) and len(e.exceptions) == 1:
        e = e.exceptions[0]
    return e


def _parse_mcp_result(result: Any) -> dict[str, Any]:
    """Parse MCP tool result into a dictionary."""
    if isinstance(result, list) and len(result) > 0:
        first_item = result[0]
        if isinstance(first_item, dict) and first_item.get("type") == "text":
            text_content = first_item.get("text", "")
            try:
                parsed = json.loads(text_content)
                if isinstance(parsed, dict) and "body" in parsed:
                    body = parsed.get("body")
                    if isinstance(body, str):
                        inner = json.loads(body)
                        return inner if isinstance(inner, dict) else {"result": inner}
                    return body if isinstance(body, dict) else {"result": body}
                return parsed if isinstance(parsed, dict) else {"result": parsed}
            except json.JSONDecodeError:
                return {"result": text_content}
        return {"result": str(result)}

    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            return parsed if isinstance(parsed, dict) else {"result": parsed}
        except json.JSONDecodeError:
            return {"result": result}

    if isinstance(result, dict):
        return result

    return {"result": str(result)}


# =============================================================================
# Auto-Discovery — internal-only tools excluded from LLM access
# =============================================================================

_EXCLUDED_BASE_NAMES: set[str] = {
    SAVE_CONVERSATION_TURN_TOOL,
}


def _matches_any_excluded(tool_name: str) -> bool:
    """Check if a discovered tool matches any excluded base name."""
    for base in _EXCLUDED_BASE_NAMES:
        if tool_name == base or tool_name.endswith(f"___{base}"):
            return True
    return False


# =============================================================================
# Tool Registry — pure MCP auto-discovery
# =============================================================================

async def get_orchestrator_tools() -> list:
    """
    Auto-discover all tools from the MCP server.

    Tools are discovered dynamically via the gateway or local connection.
    Adding a new tool to the MCP server automatically makes it available
    to the agent — no agent-side code changes needed.

    The LLM receives actor_id via the system prompt so it can pass it
    to preference tools that require it.

    Returns:
        List of LangChain-compatible tools for the orchestrator.
    """
    client = get_tool_client()
    mcp_tools = await client.get_tools()

    tools = [t for t in mcp_tools if not _matches_any_excluded(t.name)]

    logger.info(f"Orchestrator tools (auto-discovered): {[t.name for t in tools]}")
    return tools
