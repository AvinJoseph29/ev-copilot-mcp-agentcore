"""
Conditional edge functions for the EV Copilot workflow graph.

Implements three routing decisions:
1. route_by_intent: Router → Trip Planner Agent or Simple Response
2. should_continue_trip_planner_agent: Trip Planner Agent → Tools or Reflection
3. should_continue_after_reflection: Reflection → Search More or Done
"""

from typing import Literal

from langchain_core.messages import AIMessage
from loguru import logger

from src.application.orchestrator.workflow.state import OrchestratorState

# Maximum tool calls per turn to prevent excessive latency
# A typical EV trip turn: prefs → vehicle → geocode ×2 → route → chargers → weather
# → simulate → amenities, plus 1–2 re-simulations, so 30 gives headroom without runaway loops
MAX_TOOL_CALLS_PER_TURN = 30

# Maximum reflection iterations to prevent infinite loops
MAX_REFLECTIONS = 2


def route_by_intent(
    state: OrchestratorState,
) -> Literal["trip_planner_agent", "simple_response"]:
    """
    Route based on the classified intent from the router node.

    - trip_planning → trip_planner_agent_node (full ReAct + Reflection with tools)
    - simple → simple_response_node (direct response, no tools)
    - off_topic → simple_response_node (redirect response, no tools)
    """
    intent = state.get("intent", "trip_planning")

    if intent == "trip_planning":
        logger.debug("Routing to trip_planner_agent (trip_planning intent)")
        return "trip_planner_agent"
    else:
        logger.debug(f"Routing to simple_response ({intent} intent)")
        return "simple_response"


def should_continue_trip_planner_agent(
    state: OrchestratorState,
) -> Literal["tools", "reflect"]:
    """
    Determine if the trip planner agent should continue to tools or go to reflection.

    ReAct + Reflection pattern:
    - If the agent has tool calls → route to tools → back to trip_planner_agent
    - If no tool calls → route to reflection (NOT directly to end)

    Pending tool calls are always executed, even past MAX_TOOL_CALLS_PER_TURN:
    an AIMessage whose tool calls have no ToolMessage breaks every later model
    call on the thread. The limit is enforced by trip_planner_agent_node, which
    answers without tools once it is reached.

    The reflection node decides whether to continue or finish.
    """
    messages = state.get("messages", [])
    tool_call_count = state.get("tool_call_count", 0)

    if not messages:
        logger.debug("No messages in state, routing to reflection")
        return "reflect"

    last_message = messages[-1]

    # Check if the last message is an AIMessage with tool calls
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        logger.debug(
            f"Trip planner agent: tool calls detected (count: {tool_call_count + 1}), "
            "routing to tools"
        )
        return "tools"

    # No tool calls — agent has finished its ReAct loop, go to reflection
    logger.debug("Trip planner agent: no tool calls, routing to reflection")
    return "reflect"


def should_continue_after_reflection(
    state: OrchestratorState,
) -> Literal["search_more", "done"]:
    """
    After reflection: decide whether more data is needed or response is complete.

    - If reflection says NEEDS_MORE_DATA and we haven't hit max reflections → search_more
    - Otherwise → done (proceed to memory hook and END)
    """
    needs_more = state.get("needs_more_data", False)
    reflection_count = state.get("reflection_count", 0)

    if needs_more and reflection_count < MAX_REFLECTIONS:
        logger.info(
            f"Reflection {reflection_count}: needs more data, "
            "routing back to trip planner agent"
        )
        return "search_more"

    if needs_more and reflection_count >= MAX_REFLECTIONS:
        logger.info(
            f"Reflection limit ({MAX_REFLECTIONS}) reached, proceeding to response"
        )

    logger.debug(f"Reflection {reflection_count}: complete, proceeding to memory hook")
    return "done"
