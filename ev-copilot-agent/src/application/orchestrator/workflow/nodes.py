"""
Workflow nodes for the EV Copilot orchestrator.

5 nodes implementing the Router + ReAct + Reflection pattern:
1. router_node - Intent classification (and per-turn state reset)
2. trip_planner_agent_node - ReAct loop for EV trip planning
3. simple_response_node - Direct response without tools
4. reflection_node - Quality evaluation after ReAct
5. memory_post_hook - Save conversation turn to memory
"""

import asyncio
import re

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

from src.application.orchestrator.workflow.chains import (
    get_reflection_chain,
    get_router_chain,
    get_simple_response_chain,
    get_trip_planner_agent_chain,
)
from src.application.orchestrator.workflow.edges import (
    MAX_REFLECTIONS,
    MAX_TOOL_CALLS_PER_TURN,
)
from src.application.orchestrator.workflow.state import IntentType, OrchestratorState
from src.application.orchestrator.workflow.tools import (
    SAVE_CONVERSATION_TURN_TOOL,
    call_mcp_tool,
)
from src.infrastructure.model import extract_text_content as _extract_text_content
from src.infrastructure.observability import get_observability_manager
from src.utils.trace_context import from_config, span_attrs

# Strong references to in-flight background memory saves. asyncio only keeps
# weak references to tasks, so an unreferenced task could be garbage-collected
# before it finishes.
_background_tasks: set[asyncio.Task] = set()

# Leading decision marker in the reviewer's output ("NEEDS_MORE_DATA - <instruction>")
_NEEDS_MORE_DATA_PREFIX = re.compile(r"^\s*NEEDS_MORE_DATA\s*[-:–—]*\s*", re.IGNORECASE)

# Transient user turns. Claude 4.6+ models on Bedrock reject a conversation that
# ends with an assistant message (prefill), so these are appended to the model
# input only — they are never written to the graph state.
_REVISE_DRAFT_INSTRUCTION = (
    "Please continue: address the reviewer feedback in your instructions and then "
    "give your complete, revised answer."
)
_REVIEW_INSTRUCTION = (
    "Review the assistant's latest response above against your checklist and reply "
    "with your decision."
)
_TOOL_BUDGET_INSTRUCTION = (
    "The tool call budget for this turn is used up, so no more tools can be called. "
    "Give your complete final answer now using the data gathered above, and briefly "
    "note anything you could not check."
)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def trip_planner_agent_node(
    state: OrchestratorState,
    config: RunnableConfig,
) -> dict:
    """
    Trip planner agent node implementing the ReAct (Reasoning + Acting) pattern.

    This node handles EV trip planning requests using the trip planner chain
    which has tools bound for routing, chargers, vehicle energy simulation,
    weather, amenities and user preferences.

    Once MAX_TOOL_CALLS_PER_TURN is reached the model is invoked without tools,
    so it gives a final answer from the data already gathered.
    """
    observability = get_observability_manager()
    ctx = from_config(config)

    tool_call_count = state.get("tool_call_count", 0)
    react_iteration = tool_call_count + 1
    messages = list(state["messages"])
    reflection_feedback = state.get("reflection_feedback", "")
    tool_budget_spent = tool_call_count >= MAX_TOOL_CALLS_PER_TURN

    if tool_budget_spent:
        logger.warning(
            f"Tool call limit ({MAX_TOOL_CALLS_PER_TURN}) reached, "
            "asking the trip planner agent for a final answer without tools"
        )

    chain_result = await get_trip_planner_agent_chain(
        customer_name=ctx.customer_name,
        actor_id=ctx.actor_id,
        latitude=state.get("latitude"),
        longitude=state.get("longitude"),
        reflection_feedback=reflection_feedback,
        with_tools=not tool_budget_spent,
    )
    pm = chain_result.prompt_metadata

    # After reflection routes back, the conversation ends with the draft answer.
    if (
        reflection_feedback
        and messages
        and isinstance(messages[-1], AIMessage)
        and not messages[-1].tool_calls
    ):
        messages.append(HumanMessage(content=_REVISE_DRAFT_INSTRUCTION))

    if tool_budget_spent:
        messages.append(HumanMessage(content=_TOOL_BUDGET_INSTRUCTION))

    logger.debug(
        f"Trip planner agent invoked: iteration={react_iteration}, "
        f"messages={len(messages)}, prompt_version={pm.version}"
    )

    with observability.traced_node(
        "trip_planner_agent.invoke",
        step_name="trip_planner_agent",
        attributes=span_attrs(
            ctx,
            **{
                "prompt.name": pm.name,
                "prompt.version": pm.version or "unknown",
                "react.iteration": react_iteration,
                "message.count": len(messages),
            },
        ),
    ) as trace_ctx:
        response = await chain_result.chain.ainvoke({"messages": messages}, config)

        has_tool_calls = hasattr(response, "tool_calls") and response.tool_calls
        tool_names = [tc.get("name", "unknown") for tc in response.tool_calls] if has_tool_calls else []

        trace_ctx["react.has_tool_calls"] = str(has_tool_calls)
        trace_ctx["react.tool_names"] = ",".join(tool_names) if tool_names else "none"

    new_tool_count = tool_call_count + (len(response.tool_calls) if has_tool_calls else 0)

    if has_tool_calls:
        logger.debug(f"Trip planner agent requested tools: {tool_names}")
    else:
        logger.debug("Trip planner agent provided Final Answer (no tool calls)")

    return {
        "messages": response,
        "tool_call_count": new_tool_count,
    }


async def router_node(
    state: OrchestratorState,
    config: RunnableConfig,
) -> dict:
    """
    Router node that classifies user intent for routing decisions.

    Intent types:
    - trip_planning: Route to the trip planner agent with tools
    - simple: Route to simple response (no tools needed)
    - off_topic: Route to simple response with redirect

    The router is the first node of every turn, so it also resets the
    per-turn counters that the checkpointer would otherwise carry over
    from the previous turn on the same thread.
    """
    observability = get_observability_manager()
    messages = list(state["messages"])
    router_chain = await get_router_chain()

    with observability.traced_node(
        "router.classify",
        step_name="router",
        attributes={"message.count": len(messages)},
    ) as trace_ctx:
        response = await router_chain.ainvoke({"messages": messages}, config)
        response_text = _extract_text_content(response.content).strip().lower()

        if "trip_planning" in response_text:
            intent: IntentType = "trip_planning"
        elif "simple" in response_text:
            intent = "simple"
        elif "off_topic" in response_text:
            intent = "off_topic"
        else:
            logger.warning(f"Unclear intent: {response_text}, defaulting to trip_planning")
            intent = "trip_planning"

        trace_ctx["intent"] = intent

    logger.info(f"Router classified intent: {intent}")
    return {
        "intent": intent,
        # Per-turn state reset
        "tool_call_count": 0,
        "reflection_count": 0,
        "needs_more_data": False,
        "reflection_feedback": "",
    }


async def simple_response_node(
    state: OrchestratorState,
    config: RunnableConfig,
) -> dict:
    """
    Simple response node for handling non-trip queries.

    Generates responses for greetings, thanks, capabilities questions,
    and off-topic redirections. No tools are invoked.
    """
    observability = get_observability_manager()
    ctx = from_config(config)
    intent = state.get("intent", "simple")
    messages = list(state["messages"])

    simple_chain = await get_simple_response_chain(customer_name=ctx.customer_name)

    with observability.traced_node(
        "simple_response.generate",
        step_name="simple_response",
        attributes=span_attrs(ctx, intent=intent),
    ):
        response = await simple_chain.ainvoke({"messages": messages}, config)

    logger.debug(f"Simple response generated for intent: {intent}")
    return {"messages": response}


async def reflection_node(
    state: OrchestratorState,
    config: RunnableConfig,
) -> dict:
    """
    Reflection node: Reviews the trip plan for completeness and correctness.

    After the ReAct loop completes (agent has no more tool calls), this node
    reviews all tool results and the draft answer and decides if more calls
    are needed. The reviewer's critique is stored in ``reflection_feedback``
    so the trip planner agent knows what to fix. Maximum MAX_REFLECTIONS
    iterations to prevent infinite loops.
    """
    observability = get_observability_manager()
    reflection_count = state.get("reflection_count", 0)

    if reflection_count >= MAX_REFLECTIONS:
        logger.info(f"Reflection limit ({MAX_REFLECTIONS}) reached, passing through")
        return {"needs_more_data": False, "reflection_count": reflection_count}

    messages = list(state["messages"])
    messages.append(HumanMessage(content=_REVIEW_INSTRUCTION))
    reflection_chain = await get_reflection_chain()

    with observability.traced_node(
        "reflection.evaluate",
        step_name="reflection",
        attributes={
            "reflection.iteration": reflection_count + 1,
            "message.count": len(messages),
        },
    ) as trace_ctx:
        response = await reflection_chain.ainvoke({"messages": messages}, config)
        response_text = _extract_text_content(response.content).strip()
        needs_more = "NEEDS_MORE_DATA" in response_text.upper()

        trace_ctx["reflection.needs_more"] = str(needs_more)
        trace_ctx["reflection.decision"] = response_text[:100]

    level = "needs more data" if needs_more else "response is complete"
    logger.info(f"Reflection {reflection_count + 1}: {level}")

    feedback = _NEEDS_MORE_DATA_PREFIX.sub("", response_text).strip() if needs_more else ""

    result = {
        "needs_more_data": needs_more,
        "reflection_count": reflection_count + 1,
        "reflection_feedback": feedback or (response_text if needs_more else ""),
    }
    # The revision round gets a fresh tool budget
    if needs_more:
        result["tool_call_count"] = 0
    return result


async def memory_post_hook(
    state: OrchestratorState,
    config: RunnableConfig,
) -> dict:
    """
    Post-hook node: Fire-and-forget memory save.

    Extracts the latest user input and agent response, then spawns a
    background task to persist them via MCP. Returns immediately so the
    graph reaches END without blocking on the write.

    The scan stops at the current turn's HumanMessage, so this turn's input
    is never paired with an answer from an earlier turn.
    """
    ctx = from_config(config)
    messages = state.get("messages", [])

    user_input = ""
    agent_response = ""

    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not agent_response:
            if msg.content and not msg.tool_calls:
                agent_response = _extract_text_content(msg.content)
        elif isinstance(msg, HumanMessage):
            user_input = _extract_text_content(msg.content)
            break

    if not user_input or not agent_response:
        logger.debug("Missing user input or agent response, skipping memory save")
        return {}

    task = asyncio.create_task(
        _save_memory_in_background(ctx, user_input, agent_response)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {}


async def _save_memory_in_background(ctx, user_input: str, agent_response: str) -> None:
    """Background task that persists a conversation turn to MCP memory."""
    observability = get_observability_manager()

    try:
        with observability.traced_node(
            "memory.save_turn_via_mcp",
            step_name="memory_post_hook",
            step_type="background",
            attributes=span_attrs(ctx),
        ):
            await call_mcp_tool(SAVE_CONVERSATION_TURN_TOOL, {
                "actor_id": ctx.actor_id,
                "session_id": ctx.session_id,
                "user_input": user_input,
                "agent_response": agent_response,
            })

        logger.info(f"Memory saved in background for actor={ctx.actor_id}")

    except Exception as e:
        logger.error(f"Background memory save failed: {e}")
