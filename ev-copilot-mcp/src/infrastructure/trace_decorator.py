"""
Trace decorator for MCP tool and prompt handlers.

Provides a @traced decorator that wraps any async MCP handler with an
OpenTelemetry span. Automatically captures:
- Span name (e.g. "mcp.tool.simulate_trip_energy", "mcp.prompt.ev_copilot_agent_scope")
- Handler type (tool / prompt)
- Function arguments as span attributes
- Duration and success/failure status
- Exception details on errors

Usage:
    @mcp.tool(...)
    @traced(span_name="mcp.tool.search_chargers_along_route", handler_type="tool")
    async def search_chargers_along_route(...) -> ChargerSearchResponse:
        ...
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from loguru import logger

from src.infrastructure.observability import get_observability_manager
from src.utils.trace_context import handler_attrs


def traced(
    span_name: str,
    handler_type: str = "tool",
) -> Callable:
    """
    Decorator that wraps an async MCP handler with an OpenTelemetry span.

    Args:
        span_name: The span name (e.g. "mcp.tool.search_chargers_along_route").
        handler_type: Either "tool" or "prompt".
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            observability = get_observability_manager()

            # Bind arguments to build span attributes
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()

            attrs = handler_attrs(
                handler_type=handler_type,
                handler_name=func.__name__,
                params=dict(bound.arguments),
            )

            with observability.traced_handler(
                span_name,
                step_name=func.__name__,
                handler_type=handler_type,
                attributes=attrs,
            ):
                result = await func(*args, **kwargs)

            logger.debug(f"[trace] {span_name} completed")
            return result

        return wrapper

    return decorator
