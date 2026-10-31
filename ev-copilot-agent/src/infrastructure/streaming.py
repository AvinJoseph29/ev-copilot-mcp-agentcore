"""
SSE streaming and guardrail enforcement at the API boundary.

Wraps the orchestrator's response stream with:
- Input/output guardrail checks
- Server-Sent Event (SSE) formatting
- Observability session tracking for request-level tracing
"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

from loguru import logger

from src.application.orchestrator.streaming import get_streaming_response
from src.infrastructure.guardrails import (
    apply_input_guardrail,
    apply_output_guardrail,
    get_blocked_input_message,
)
from src.infrastructure.observability import get_observability_manager
from src.utils.trace_context import from_request, span_attrs


async def stream_response(
    user_input: str,
    customer_name: str = "Guest",
    conversation_id: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted events with guardrail protection.

    Applies guardrails at the API boundary:
    - Input guardrail: Checks user input before processing (blocking)
    - Output guardrail: Checks the complete response after streaming (advisory —
      content has already been streamed, so modifications are only logged)

    Observability:
    - Sets session ID in OpenTelemetry baggage for trace correlation
    - All traces within this request are tagged with the session ID
    - Baggage propagates to MCP server for end-to-end tracing

    The session ID is generated once here and passed down, so the tracing
    session.id and the LangGraph checkpointer thread_id are always identical.

    Yields:
        SSE-formatted strings with JSON payloads:
        - {"chunk": "..."} for content chunks
        - {"tool_start": {"id", "name"}} when a tool call starts
        - {"tool_end": {"id", "name", "status", "result"}} when a tool call ends
        - {"reset": true} when reflection discards the streamed draft answer
        - {"done": true} on completion
        - {"error": "..."} on failure
        - {"blocked": true, "message": "..."} if input blocked by guardrails
    """
    session_id = conversation_id or str(uuid.uuid4())
    observability = get_observability_manager()
    ctx = from_request(customer_name=customer_name, session_id=session_id)

    with observability.session_context(session_id):
        observability.add_span_event(
            "request.start",
            attributes=span_attrs(ctx, **{"input.length": len(user_input)}),
        )

        try:
            # --- Input guardrail ---
            with observability.traced_node(
                "guardrail.input",
                step_name="guardrail_input",
                attributes={"input.length": len(user_input)},
            ):
                input_result = await asyncio.to_thread(apply_input_guardrail, user_input)

            if not input_result.allowed:
                logger.info(f"Input blocked by guardrail: action={input_result.action}")
                observability.add_span_event(
                    "guardrail.blocked",
                    attributes={"action": str(input_result.action)},
                )
                blocked_message = get_blocked_input_message()
                yield f"data: {json.dumps({'blocked': True, 'message': blocked_message})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
                return

            # --- Workflow execution ---
            full_response = []

            with observability.create_span(
                "workflow.execution",
                attributes=span_attrs(ctx),
            ):
                async for chunk in get_streaming_response(
                    messages=user_input,
                    customer_name=customer_name,
                    conversation_id=session_id,
                    latitude=latitude,
                    longitude=longitude,
                ):
                    if not chunk:
                        continue

                    # Typed events (tool progress, reset) pass through unchanged
                    if isinstance(chunk, dict):
                        if chunk.get("reset"):
                            # The draft answer is discarded by the UI — the output
                            # guardrail must only see the final answer.
                            full_response = []
                        yield f"data: {json.dumps(chunk)}\n\n"
                        continue

                    full_response.append(chunk)
                    event_data = json.dumps({"chunk": chunk})
                    yield f"data: {event_data}\n\n"

            # --- Output guardrail ---
            complete_response = "".join(full_response)
            if complete_response:
                with observability.traced_node(
                    "guardrail.output",
                    step_name="guardrail_output",
                    attributes={"output.length": len(complete_response)},
                ):
                    output_result = await asyncio.to_thread(apply_output_guardrail, complete_response)

                if output_result.output != complete_response:
                    logger.info(f"Output modified by guardrail: action={output_result.action}")
                    observability.add_span_event(
                        "guardrail.modified",
                        attributes={"action": str(output_result.action)},
                    )

            observability.add_span_event(
                "request.complete",
                attributes=span_attrs(ctx, **{"output.length": len(complete_response)}),
            )

            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e) or "Unknown error occurred"
            logger.error(f"Error in stream_response: {error_type}: {error_msg}")
            logger.exception("Full stream_response traceback:")

            observability.add_span_event(
                "request.error",
                attributes={"error.type": error_type, "error.message": error_msg},
            )

            yield f"data: {json.dumps({'error': f'{error_type}: {error_msg}'})}\n\n"
