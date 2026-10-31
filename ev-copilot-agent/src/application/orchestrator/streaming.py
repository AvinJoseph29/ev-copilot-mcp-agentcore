"""
Orchestrator streaming — response generation and streaming.

Provides the public entry point (get_streaming_response) and the two streaming
strategies (token-level via astream_events, buffered via ainvoke).

Node filtering is required because LangGraph's astream_events emits tokens from
every model call in the graph. Without filtering, internal outputs (router text,
reflection evaluation, memory hook) would leak to the user.

Besides answer text (``str``), the token-level strategy yields typed event
dicts that the API layer forwards to the UI unchanged:
- {"tool_start": {"id", "name"}}                       — a tool call started
- {"tool_end": {"id", "name", "status", "result"}}     — a tool call finished
- {"reset": True}                                      — discard the streamed draft
"""

import json
import re
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from loguru import logger

from src.application.orchestrator.workflow.edges import MAX_REFLECTIONS
from src.application.orchestrator.workflow.graph import create_orchestrator_graph
from src.infrastructure.model import extract_text_content

# ---------------------------------------------------------------------------
# Node classification — which nodes produce user-facing output
# ---------------------------------------------------------------------------
_RESPONSE_NODES = {"trip_planner_agent_node", "simple_response_node"}
_INTERNAL_NODES = {"router_node", "reflection_node", "memory_post_hook"}
_TOOL_NODE = "tool_node"
_REFLECTION_NODE = "reflection_node"

# Patterns that indicate internal content that should not be shown to the user
_FILTERED_PATTERNS = [
    "<function", "</function",
    "<antml", "</antml", "antml::", "antml:invoke", "antml:parameter",
    "<tml", "</tml",
    'name="charging', 'name="routing', 'name="vehicle', 'name="weather',
    'name="places', 'name="preference', 'name="charger', 'name="route',
    "<tool_call>", "</tool_call>",
    "<thinking", "</thinking>",
]

# Tools whose parsed output is forwarded to the UI (map markers, route
# polyline, battery chart, weather banner). Every other tool_end carries
# result=None to keep the stream small.
_RESULT_TOOLS = {
    "routing_compute_route",
    "charging_search_chargers_along_route",
    "charging_search_chargers_nearby",
    "charging_get_charger_details",
    "charging_search_chargers_open_charge_map",
    "vehicle_simulate_trip_energy",
    "places_search_places",
    "places_search_nearby_places",
    "weather_get_weather_alerts",
}

# Gateway tool names are "<APP_NAME>-McpTarget___<base_name>"
_GATEWAY_SEPARATOR = "___"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def get_streaming_response(
    messages: str | list[str],
    customer_name: str = "Guest",
    conversation_id: str | None = None,
    enable_true_streaming: bool = True,
    latitude: float | None = None,
    longitude: float | None = None,
) -> AsyncGenerator[str | dict, None]:
    """
    Run the orchestrator workflow and yield response tokens and typed events.

    Args:
        messages: User message(s) to process.
        customer_name: Name of the customer for personalization.
        conversation_id: Unique ID for the conversation thread (the API layer
            always passes the same value it uses as the tracing session ID).
        enable_true_streaming: Token streaming (True) or buffer mode (False).
        latitude: User's latitude from browser geolocation.
        longitude: User's longitude from browser geolocation.

    Yields:
        Response content tokens/chunks (str) and typed event dicts.
    """
    graph = await create_orchestrator_graph()

    try:
        thread_id = conversation_id or str(uuid.uuid4())
        actor_id = _sanitize_actor_id(customer_name)

        config = {
            "configurable": {
                "thread_id": thread_id,
                "customer_name": customer_name,
                "actor_id": actor_id,
            }
        }

        input_data = {
            "messages": _format_messages(messages),
            "customer_name": customer_name,
            "latitude": latitude,
            "longitude": longitude,
        }

        logger.info(f"Starting workflow execution (thread_id={thread_id}, streaming={enable_true_streaming})")

        streamer = _stream_with_events if enable_true_streaming else _stream_buffered
        async for chunk in streamer(graph, input_data, config):
            yield chunk

    except Exception as e:
        logger.error(f"Error in get_streaming_response: {type(e).__name__}: {e!s}")
        logger.exception("Full traceback:")
        raise RuntimeError(f"Error running conversation workflow: {e!s}") from e


# ---------------------------------------------------------------------------
# Streaming strategies
# ---------------------------------------------------------------------------

async def _stream_with_events(
    graph,
    input_data: dict,
    config: dict,
) -> AsyncGenerator[str | dict, None]:
    """
    Token-by-token streaming via LangGraph astream_events.

    Filters events so that only user-facing response nodes are streamed, and
    emits tool progress / reset events for the UI.
    """
    has_tool_calls_pending = False
    streamed_any = False
    emitted_any = False  # any text or event already sent to the client
    draft_streamed = False  # answer text streamed since the last reset
    logged_first_stream_event = False
    final_state = None

    try:
        async for event in graph.astream_events(
            input=input_data, config=config, version="v2",
        ):
            event_type = event.get("event")
            event_data = event.get("data", {})
            tags = event.get("tags", [])
            langgraph_node = event.get("metadata", {}).get("langgraph_node", "")

            # Capture final state for fallback extraction
            if event_type == "on_chain_end":
                output = event_data.get("output")
                if output and isinstance(output, dict) and "messages" in output:
                    final_state = output
                event_name = event.get("name", "")
                if "tool" in event_name.lower():
                    has_tool_calls_pending = False

                # Reflection sent the agent back for more work after a draft
                # answer was already streamed → tell the UI to discard the draft.
                if (
                    event_name == _REFLECTION_NODE
                    and langgraph_node == _REFLECTION_NODE
                    and draft_streamed
                    and _will_search_more(output)
                ):
                    draft_streamed = False
                    emitted_any = True
                    logger.info("Reflection requested more data — resetting streamed draft")
                    yield {"reset": True}

            # Reset tool-call flag when a response-node model starts a new generation
            # This prevents the flag from staying stuck after a ReAct tool-call round
            elif event_type == "on_chat_model_start":
                tag_str = str(tags)
                combined = f"{tag_str} {langgraph_node}"
                if any(n in combined for n in _RESPONSE_NODES):
                    has_tool_calls_pending = False

            # Tool progress events (only for tools executed by the graph's ToolNode)
            elif event_type == "on_tool_start":
                if langgraph_node != _TOOL_NODE:
                    continue
                emitted_any = True
                yield {
                    "tool_start": {
                        "id": str(event.get("run_id", "")),
                        "name": _base_tool_name(event.get("name", "")),
                    }
                }

            elif event_type in ("on_tool_end", "on_tool_error"):
                if langgraph_node != _TOOL_NODE:
                    continue
                emitted_any = True
                yield _tool_end_event(event)

            elif event_type == "on_chat_model_stream":
                tag_str = str(tags)
                event_name = event.get("name", "")

                # Log the first stream event for diagnostics
                if not streamed_any and not logged_first_stream_event:
                    logged_first_stream_event = True
                    logger.debug(
                        f"Stream event: name={event_name}, node={langgraph_node}, tags={tags}"
                    )

                # Determine which node produced this event (check tags, metadata, and name)
                node_id = langgraph_node or event_name
                combined = f"{tag_str} {node_id}"

                if any(n in combined for n in _INTERNAL_NODES):
                    continue

                if not any(n in combined for n in _RESPONSE_NODES):
                    continue

                chunk = event_data.get("chunk")
                if not chunk or not isinstance(chunk, AIMessageChunk):
                    continue

                # Tool call chunks — mark pending, don't stream
                if chunk.tool_calls or chunk.tool_call_chunks:
                    has_tool_calls_pending = True
                    continue

                if has_tool_calls_pending:
                    continue

                content = extract_text_content(chunk.content)
                if content and not _should_filter(content):
                    streamed_any = True
                    draft_streamed = True
                    emitted_any = True
                    yield content

        if streamed_any:
            logger.info("Streaming complete")
        elif final_state:
            logger.warning("No content streamed, extracting from final state")
            final_response = _extract_final_response(final_state)
            if final_response:
                yield final_response

    except Exception as e:
        if emitted_any:
            # Re-running the graph now would append the user message again,
            # repeat tool calls and duplicate output already shown to the user.
            logger.error(
                f"Streaming error after output was already streamed: "
                f"{type(e).__name__}: {e!s} — not falling back to buffer mode"
            )
            raise

        logger.error(f"Streaming error: {type(e).__name__}: {e!s}, falling back to buffer mode")
        async for chunk in _stream_buffered(graph, input_data, config):
            yield chunk


async def _stream_buffered(
    graph,
    input_data: dict,
    config: dict,
) -> AsyncGenerator[str, None]:
    """Run the workflow to completion, then yield the full response."""
    logger.info("Running workflow in buffer mode")

    result = await graph.ainvoke(input=input_data, config=config)
    final_response = _extract_final_response(result)

    if not final_response:
        logger.warning("No valid final response found in workflow result")
        final_response = "I apologize, but I wasn't able to generate a response. Please try again."

    logger.info(f"Final response ready: intent={result.get('intent', 'unknown')}, "
                f"tool_calls={result.get('tool_call_count', 0)}")
    yield final_response


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def _base_tool_name(tool_name: str) -> str:
    """Strip the Gateway target prefix: "evCopilot-McpTarget___routing_geocode" → "routing_geocode"."""
    return tool_name.rsplit(_GATEWAY_SEPARATOR, 1)[-1]


def _will_search_more(output: Any) -> bool:
    """Check whether a reflection_node output routes back to the trip planner agent."""
    if not isinstance(output, dict):
        return False
    return bool(output.get("needs_more_data")) and output.get("reflection_count", 0) < MAX_REFLECTIONS


def _tool_end_event(event: dict) -> dict:
    """Build a tool_end event from an on_tool_end / on_tool_error stream event."""
    name = _base_tool_name(event.get("name", ""))
    output = event.get("data", {}).get("output")

    status = "success"
    if event.get("event") == "on_tool_error" or isinstance(output, ToolMessage) and output.status == "error":
        status = "error"

    result = None
    if status == "success" and name in _RESULT_TOOLS:
        result = _parse_tool_result(output)

    return {
        "tool_end": {
            "id": str(event.get("run_id", "")),
            "name": name,
            "status": status,
            "result": result,
        }
    }


def _parse_tool_result(output: Any) -> Any:
    """
    Parse a tool output into a JSON object for the UI.

    Prefers MCP structured content (artifact) and falls back to parsing the
    JSON text content. Returns None when the output is not JSON.
    """
    content = output
    if isinstance(output, ToolMessage):
        artifact = output.artifact
        if isinstance(artifact, dict) and isinstance(artifact.get("structured_content"), dict):
            return artifact["structured_content"]
        content = output.content

    if isinstance(content, (dict, list)) and not _is_content_blocks(content):
        return content

    text = extract_text_content(content)
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.debug("Tool output is not JSON, omitting result from tool_end event")
        return None


def _is_content_blocks(content: Any) -> bool:
    """Check if content is a list of LangChain/MCP content blocks ({"type": "text", ...})."""
    return isinstance(content, list) and all(
        isinstance(block, dict) and "type" in block for block in content
    )


def _extract_final_response(state: dict) -> str:
    """Extract the last non-tool-call AI message of the current turn from a workflow state.

    The scan stops at the current turn's HumanMessage, so an earlier turn's
    answer is never returned for this turn.
    """
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            break
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = extract_text_content(msg.content)
            if content and not _should_filter(content):
                return _strip_thinking_tags(content)
    return ""


def _should_filter(content: str) -> bool:
    """Check if content is internal model output that shouldn't be shown."""
    if not content:
        return False
    lower = content.lower()
    return any(p.lower() in lower for p in _FILTERED_PATTERNS)


def _strip_thinking_tags(text: str) -> str:
    """Remove <thinking>...</thinking> blocks from text."""
    return re.sub(r'<thinking>.*?</thinking>\s*', '', text, flags=re.DOTALL)


def _sanitize_actor_id(name: str) -> str:
    """Format a customer name into an AgentCore actor ID."""
    sanitized = re.sub(r'[^a-zA-Z0-9\-_ ]', '', name)
    sanitized = sanitized.replace(' ', '-').lower()
    return f"user:{sanitized or 'guest'}"


def _format_messages(
    messages: str | list[dict[str, Any]],
) -> list[HumanMessage | AIMessage]:
    """Convert string / list / dict messages into LangChain message objects."""
    if isinstance(messages, str):
        return [HumanMessage(content=messages)]

    if isinstance(messages, list):
        if not messages:
            return []
        if isinstance(messages[0], dict) and "role" in messages[0]:
            result = []
            for msg in messages:
                if msg["role"] == "user":
                    result.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    result.append(AIMessage(content=msg["content"]))
            return result
        return [HumanMessage(content=m) for m in messages]

    return []
