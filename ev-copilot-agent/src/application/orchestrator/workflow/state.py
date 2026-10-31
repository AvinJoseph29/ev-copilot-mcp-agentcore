"""
LangGraph state definition for the EV Copilot orchestrator.

Extends the standard Router + ReAct pattern with reflection fields
for quality evaluation after tool execution.
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages

# Intent types for routing decisions
IntentType = Literal["trip_planning", "simple", "off_topic"]


class OrchestratorState(TypedDict):
    """
    State for the Orchestrator Agent with Router + ReAct + Reflection pattern.

    Architecture:
        START → Router → [conditional edge based on intent]
                         ├── "simple" → Simple Response → Memory Hook → END
                         ├── "off_topic" → Simple Response → Memory Hook → END
                         └── "trip_planning" → Trip Planner Agent → [tools or reflect]
                                               ├── tools → Tool Node → Trip Planner Agent (loop)
                                               └── reflect → Reflection → [search_more or done]
                                                             ├── search_more → Trip Planner Agent
                                                             └── done → Memory Hook → END

    Per-turn fields (tool_call_count, reflection_count, needs_more_data,
    reflection_feedback) are reset by the router node at the start of every
    turn, because the checkpointer persists all state across turns.
    """

    # Messages with reducer that appends new messages
    messages: Annotated[list[BaseMessage], add_messages]

    # Customer name for personalization
    customer_name: str

    # Intent classification for routing (set by router_node)
    intent: IntentType

    # Tool call tracking (for efficiency limits)
    tool_call_count: int  # Number of tool calls in current turn

    # Reflection tracking (for quality evaluation)
    reflection_count: int  # Number of reflection iterations completed
    needs_more_data: bool  # Set by reflection node if more tools needed
    reflection_feedback: str  # Reviewer critique passed back to the trip planner agent

    # User location coordinates (optional, from browser geolocation)
    latitude: float | None
    longitude: float | None
