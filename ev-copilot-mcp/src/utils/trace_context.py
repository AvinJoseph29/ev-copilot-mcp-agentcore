"""
Centralized span attribute building for MCP handlers.

Provides a single place to construct consistent span attribute dicts
from handler metadata and function arguments, used by the @traced
decorator and any manual tracing in the MCP server.
"""

from __future__ import annotations

from typing import Any


def handler_attrs(
    handler_type: str,
    handler_name: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build standard MCP handler span attributes.

    Args:
        handler_type: "tool" or "prompt".
        handler_name: The function name (e.g. "search_chargers_along_route").
        params: Bound function arguments to record as span attributes.

    Returns:
        Flat attribute dict ready for ``traced_handler()`` or ``create_span()``.
    """
    attrs: dict[str, Any] = {
        "mcp.handler.type": handler_type,
        "mcp.handler.name": handler_name,
    }

    if params:
        for name, value in params.items():
            attrs[f"mcp.{handler_type}.param.{name}"] = str(value)

    return attrs
