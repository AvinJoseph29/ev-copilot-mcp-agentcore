"""
User Preferences MCP Server.

Self-contained FastMCP instance with Bedrock AgentCore Memory tools.
Mounted into the registry via tool_registry.py.
"""

from fastmcp import FastMCP

from src.clients.agentcore_memory_client import AgentCoreMemoryClient
from src.config import settings
from src.infrastructure.trace_decorator import traced
from src.schemas.preferences import (
    PreferenceListResponse,
    SaveConversationTurnResponse,
)
from src.utils.memory_formatters import format_memory_records

user_preferences_mcp = FastMCP("user_preferences")

# ---------------------------------------------------------------------------
# Lazy client singleton
# ---------------------------------------------------------------------------

_client: AgentCoreMemoryClient | None = None


def _get_client() -> AgentCoreMemoryClient:
    global _client
    if _client is None:
        _client = AgentCoreMemoryClient(
            memory_id=settings.AGENTCORE_MEMORY_ID,
            region_name=settings.AWS_REGION,
        )
    return _client


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@user_preferences_mcp.tool(
    title="Search User Preferences",
    description=(
        "Semantically search a user's stored preferences by topic. "
        "Use this at the start of trip planning to recall the user's vehicle "
        "model, connector type, preferred battery buffer, preferred charging "
        "networks, food and amenity preferences, and home location. For example, "
        "search for 'vehicle' to find the car they drive, or 'charging' to find "
        "network and buffer preferences."
    ),
    tags={"preferences", "memory", "search", "personalization"},
    annotations={
        "title": "Search User Preferences",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@traced(span_name="mcp.tool.get_user_preferences", handler_type="tool")
async def get_user_preferences(
    actor_id: str,
    query: str,
    max_results: int = 5,
) -> PreferenceListResponse:
    """Search for a user's stored preferences by semantic query.

    Returns the most relevant preferences matching the query.

    Args:
        actor_id: Unique identifier for the user (e.g. "user:guest").
        query: What to search for (e.g. "vehicle and connector", "charging buffer", "food").
        max_results: Maximum number of preferences to return (1-20, default 5).
    """
    client = _get_client()
    records = await client.search_preferences(
        actor_id=actor_id,
        query=query,
        top_k=max_results,
    )
    return format_memory_records(records)


@user_preferences_mcp.tool(
    title="Save Conversation Turn",
    description=(
        "Save a conversation turn (user input + agent response) to memory. "
        "This triggers the configured memory strategies: user preference "
        "extraction (vehicle, connector, buffer, networks, amenities) and "
        "semantic fact extraction. "
        "Called after each conversation turn to build the user's memory profile."
    ),
    tags={"memory", "conversation", "save"},
    annotations={
        "title": "Save Conversation Turn",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@traced(span_name="mcp.tool.save_conversation_turn", handler_type="tool")
async def save_conversation_turn(
    actor_id: str,
    session_id: str,
    user_input: str,
    agent_response: str,
) -> SaveConversationTurnResponse:
    """Save a full conversation turn to memory.

    Persists the user input and agent response, triggering all CDK-configured
    memory strategies (user preferences, semantic facts).

    Args:
        actor_id: Unique identifier for the user (e.g. "user:guest").
        session_id: Conversation session identifier.
        user_input: The user's message text.
        agent_response: The agent's response text.
    """
    client = _get_client()
    result = await client.save_conversation_turn(
        actor_id=actor_id,
        session_id=session_id,
        user_input=user_input,
        agent_response=agent_response,
    )
    return SaveConversationTurnResponse(
        status=result.get("status", "saved"),
        actor_id=result.get("actor_id"),
        session_id=result.get("session_id"),
    )
