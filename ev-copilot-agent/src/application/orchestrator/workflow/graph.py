"""
Workflow graph builder for the EV Copilot orchestrator.

Implements the Router + ReAct + Reflection pattern:

    START
      │
      ▼
┌───────────────┐
│    Router     │  (Intent Classification)
│   (Classify)  │
└───────┬───────┘
        │
        ▼
   [route by intent]
   │              │
   │trip          │simple/off_topic
   │_planning     │
   ▼              ▼
┌───────────────┐  ┌───────────────┐
│ Trip Planner  │  │Simple Response│
│ Agent (ReAct) │  │  (No Tools)   │
└───────┬───────┘  └───────┬───────┘
        │                  │
        ▼                  │
[has tool calls?]          │
   │         │             │
yes│       no│             │
   ▼         ▼             │
┌─────────┐ ┌──────────┐   │
│ToolNode │ │Reflection│   │
│ (Act)   │ │(Evaluate)│   │
└────┬────┘ └────┬─────┘   │
     │           │         │
     └───┐  [needs more?]  │
         │   │        │    │
         │ yes│     no│    │
         │   ▼        ▼    │
         └─►Trip    Memory │
            Planner Hook ←─┘
                     │
                     ▼
                    END
"""

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from loguru import logger

from src.application.orchestrator.workflow.edges import (
    route_by_intent,
    should_continue_after_reflection,
    should_continue_trip_planner_agent,
)
from src.application.orchestrator.workflow.nodes import (
    memory_post_hook,
    reflection_node,
    router_node,
    simple_response_node,
    trip_planner_agent_node,
)
from src.application.orchestrator.workflow.state import OrchestratorState
from src.application.orchestrator.workflow.tools import get_orchestrator_tools
from src.infrastructure.memory import ShortTermMemory

# Module-level graph instance (created lazily)
_graph_instance = None


def _tool_error_message(e: Exception) -> str:
    """
    Turn any tool failure (including MCP transport/session errors) into an
    error ToolMessage, so the turn continues and no tool call is left
    unanswered in the checkpointed state.
    """
    logger.warning(f"Tool call failed: {type(e).__name__}: {e!s}")
    return (
        f"Tool error: {type(e).__name__}: {e!s}. If the arguments were wrong, fix "
        "them and retry; otherwise continue with the data you have."
    )


async def create_orchestrator_graph(force_recreate: bool = False):
    """
    Create the workflow graph with Router + ReAct + Reflection pattern.

    Uses a module-level singleton pattern. Guardrails are applied at the
    API layer (streaming.py), not in the graph.

    Args:
        force_recreate: If True, recreates the graph even if one exists.
    """
    global _graph_instance

    if _graph_instance is not None and not force_recreate:
        return _graph_instance

    logger.info("Creating workflow graph (Router + ReAct + Reflection)...")

    graph_builder = StateGraph(OrchestratorState)

    # ── Nodes ──
    graph_builder.add_node("router_node", router_node)
    graph_builder.add_node("trip_planner_agent_node", trip_planner_agent_node)
    graph_builder.add_node("simple_response_node", simple_response_node)

    tools = await get_orchestrator_tools()
    tool_node = ToolNode(tools, handle_tool_errors=_tool_error_message)
    graph_builder.add_node("tool_node", tool_node)

    # Reflection node for quality evaluation
    graph_builder.add_node("reflection_node", reflection_node)

    graph_builder.add_node("memory_post_hook", memory_post_hook)

    # ── Edges ──

    # START → Router
    graph_builder.add_edge(START, "router_node")

    # Router → Trip Planner Agent or Simple Response
    graph_builder.add_conditional_edges(
        "router_node",
        route_by_intent,
        {
            "trip_planner_agent": "trip_planner_agent_node",
            "simple_response": "simple_response_node",
        },
    )

    # Trip Planner Agent → Tools (continue ReAct) or Reflection (evaluate)
    graph_builder.add_conditional_edges(
        "trip_planner_agent_node",
        should_continue_trip_planner_agent,
        {
            "tools": "tool_node",
            "reflect": "reflection_node",
        },
    )

    # After Tools → back to Trip Planner Agent (ReAct loop)
    graph_builder.add_edge("tool_node", "trip_planner_agent_node")

    # Reflection → Search More (back to agent) or Done (memory hook)
    graph_builder.add_conditional_edges(
        "reflection_node",
        should_continue_after_reflection,
        {
            "search_more": "trip_planner_agent_node",
            "done": "memory_post_hook",
        },
    )

    # Simple Response → Memory Post-Hook
    graph_builder.add_edge("simple_response_node", "memory_post_hook")

    # Memory Post-Hook → END
    graph_builder.add_edge("memory_post_hook", END)

    # ── Compile ──
    checkpointer = ShortTermMemory().get_memory()

    _graph_instance = graph_builder.compile(checkpointer=checkpointer)
    logger.info("Workflow graph (Router + ReAct + Reflection) created successfully")

    return _graph_instance
