"""
Centralized trace context extraction and span attribute building.

Provides a single place to:
- Extract common identifiers (customer, session, actor) from any source
- Build consistent span attribute dicts for observability

Used by workflow nodes (via LangGraph config) and the streaming layer
(via function arguments) so the same attribute keys and conventions are
shared across the entire agent.
"""

from typing import NamedTuple

from langchain_core.runnables import RunnableConfig


class TraceContext(NamedTuple):
    """Immutable bundle of identifiers that every traced operation needs."""
    customer_name: str
    session_id: str
    actor_id: str


def from_config(config: RunnableConfig) -> TraceContext:
    """Extract a TraceContext from a LangGraph RunnableConfig."""
    c = config.get("configurable", {})
    return TraceContext(
        customer_name=c.get("customer_name", "Guest"),
        session_id=c.get("thread_id", "unknown"),
        actor_id=c.get("actor_id", "unknown"),
    )


def from_request(
    customer_name: str = "Guest",
    session_id: str = "unknown",
    actor_id: str = "unknown",
) -> TraceContext:
    """Build a TraceContext from explicit request-level values."""
    return TraceContext(
        customer_name=customer_name,
        session_id=session_id,
        actor_id=actor_id,
    )


def span_attrs(ctx: TraceContext, **extra) -> dict:
    """
    Build span attributes from a TraceContext plus node-specific extras.

    Returns a flat dict ready to pass to ``traced_node()`` or
    ``create_span()``.
    """
    attrs: dict = {
        "customer.name": ctx.customer_name,
        "session.id": ctx.session_id,
        "actor.id": ctx.actor_id,
    }
    attrs.update(extra)
    return attrs
