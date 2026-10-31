"""
Agent Prompts MCP Server.

Self-contained FastMCP instance with MCP prompts that serve
managed prompt templates from Bedrock Prompt Management.
Variables are substituted at render time from prompt arguments.
Mounted into the registry via tool_registry.py.
"""

from fastmcp import FastMCP

from src.infrastructure.bedrock_prompt_manager import get_prompt_manager
from src.infrastructure.trace_decorator import traced

# Import prompt modules to trigger registration in PROMPT_REGISTRY
from src.prompts import ev_copilot_agent_scope as _agent_scope  # noqa: F401
from src.prompts import reflection_quality_review as _reflection  # noqa: F401
from src.prompts import router_intent_classifier as _router  # noqa: F401
from src.prompts import simple_response as _simple  # noqa: F401

prompt_mcp = FastMCP("agent_prompts")


# ---------------------------------------------------------------------------
# MCP Prompts
# ---------------------------------------------------------------------------


@prompt_mcp.prompt(
    name="ev_copilot_agent_scope",
    title="EV Copilot Agent Scope Prompt",
    description=(
        "Comprehensive XML-structured agent scope prompt that guides the LLM on how to "
        "orchestrate all available tools (preferences, vehicle, routing, charging, "
        "weather, places) to deliver a verified EV road-trip plan. "
        "Supports optional variable: user_name."
    ),
    tags={"agent-scope", "orchestration", "ev-copilot"},
)
@traced(span_name="mcp.prompt.ev_copilot_agent_scope", handler_type="prompt")
async def ev_copilot_agent_scope(
    user_name: str = "",
) -> str:
    """Fetch and return the agent scope prompt with variable substitution.

    Args:
        user_name: Optional user name for personalized greeting.
    """
    manager = get_prompt_manager()
    return await manager.render_prompt(
        "ev_copilot_agent_scope",
        user_name=user_name,
    )


@prompt_mcp.prompt(
    name="router_intent_classifier",
    title="Router Intent Classifier Prompt",
    description=(
        "XML-structured intent classification prompt that routes user messages "
        "to the appropriate workflow node: trip_planning, simple, or off_topic."
    ),
    tags={"router", "intent-classification", "ev-copilot"},
)
@traced(span_name="mcp.prompt.router_intent_classifier", handler_type="prompt")
async def router_intent_classifier() -> str:
    """Fetch and return the router intent classifier prompt."""
    manager = get_prompt_manager()
    return await manager.render_prompt("router_intent_classifier")


@prompt_mcp.prompt(
    name="simple_response",
    title="Simple Response Prompt",
    description=(
        "XML-structured prompt for generating friendly responses to "
        "greetings, thanks, capability questions, and off-topic messages. "
        "Supports optional variable: user_name."
    ),
    tags={"simple-response", "conversational", "ev-copilot"},
)
@traced(span_name="mcp.prompt.simple_response", handler_type="prompt")
async def simple_response(
    user_name: str = "",
) -> str:
    """Fetch and return the simple response prompt with variable substitution.

    Args:
        user_name: Optional user name for personalized greeting.
    """
    manager = get_prompt_manager()
    return await manager.render_prompt(
        "simple_response",
        user_name=user_name,
    )


@prompt_mcp.prompt(
    name="reflection_quality_review",
    title="Reflection Quality Review Prompt",
    description=(
        "XML-structured quality review prompt that evaluates response "
        "completeness after the ReAct loop. Decides COMPLETE or NEEDS_MORE_DATA."
    ),
    tags={"reflection", "quality-review", "ev-copilot"},
)
@traced(span_name="mcp.prompt.reflection_quality_review", handler_type="prompt")
async def reflection_quality_review() -> str:
    """Fetch and return the reflection quality review prompt."""
    manager = get_prompt_manager()
    return await manager.render_prompt("reflection_quality_review")
