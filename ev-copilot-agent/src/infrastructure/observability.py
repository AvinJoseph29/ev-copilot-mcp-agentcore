"""
Observability configuration for AgentCore.

Provides OpenTelemetry-based observability with CloudWatch integration for:
- Distributed tracing across agent workflows
- Session ID propagation for conversation tracking
- Custom span creation for detailed monitoring
- CloudWatch GenAI Observability dashboard integration

Environment Variables Required:
    AGENT_OBSERVABILITY_ENABLED: Enable observability (default: true)
    OTEL_PYTHON_DISTRO: Set to "aws_distro" for ADOT
    OTEL_PYTHON_CONFIGURATOR: Set to "aws_configurator" for ADOT
    OTEL_EXPORTER_OTLP_PROTOCOL: Set to "http/protobuf"
    OTEL_PROPAGATORS: Set to "xray,tracecontext,baggage" for full trace propagation

Usage:
    Run with automatic instrumentation:
        opentelemetry-instrument python -m src.main
"""

import time
from contextlib import contextmanager

from loguru import logger

# OpenTelemetry imports - gracefully handle if not installed
try:
    from opentelemetry import baggage, context, trace
    from opentelemetry.context import attach, detach
    from opentelemetry.trace import SpanKind, Status, StatusCode
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = None  # type: ignore
    baggage = None  # type: ignore
    context = None  # type: ignore
    attach = None  # type: ignore
    detach = None  # type: ignore
    SpanKind = None  # type: ignore
    Status = None  # type: ignore
    StatusCode = None  # type: ignore
    logger.warning(
        "OpenTelemetry packages not installed. "
        "Observability features will be disabled."
    )


class ObservabilityManager:
    """
    Manages OpenTelemetry observability for the AgentCore application.

    Provides utilities for:
    - Session ID propagation via OpenTelemetry baggage
    - Custom span creation for workflow steps
    - Trace context management

    Session ID propagation enables end-to-end tracing:
    Agent → MCP Gateway → MCP Server via baggage headers.
    """

    def __init__(
        self,
        service_name: str = "ev-copilot-agent",
        enabled: bool = True,
    ):
        self.service_name = service_name
        self.enabled = enabled and OTEL_AVAILABLE
        self._tracer = None

        if self.enabled and trace is not None:
            self._tracer = trace.get_tracer(
                instrumenting_module_name=service_name,
                tracer_provider=trace.get_tracer_provider(),
            )
            logger.info(f"Observability initialized for service: {service_name}")
        else:
            logger.info("Observability disabled or OpenTelemetry not available")

    def set_session_id(self, session_id: str) -> object | None:
        """
        Set session ID in OpenTelemetry baggage for trace correlation.

        Session IDs enable grouping of traces across multiple requests
        in the same conversation. The baggage is automatically propagated
        to downstream services (MCP server) via HTTP headers.
        """
        if not self.enabled or baggage is None or attach is None:
            return None

        try:
            ctx = baggage.set_baggage("session.id", session_id)
            token = attach(ctx)
            logger.debug(f"Session ID set in observability context: {session_id}")
            return token
        except Exception as e:
            logger.warning(f"Failed to set session ID in baggage: {e}")
            return None

    def clear_session_context(self, token: object) -> None:
        """Clear the session context from OpenTelemetry baggage."""
        if not self.enabled or token is None or detach is None:
            return

        try:
            detach(token)
            logger.debug("Session context cleared from observability")
        except Exception as e:
            logger.warning(f"Failed to clear session context: {e}")

    @contextmanager
    def session_context(self, session_id: str):
        """
        Context manager for session-scoped observability.

        Automatically sets and clears session ID in OpenTelemetry baggage.
        All traces within this block will be tagged with the session ID,
        including downstream MCP calls via trace context propagation.
        """
        token = self.set_session_id(session_id)
        try:
            yield
        finally:
            self.clear_session_context(token)

    @contextmanager
    def create_span(
        self,
        name: str,
        kind=None,
        attributes: dict | None = None,
    ):
        """
        Create a custom span for detailed workflow tracing.

        Args:
            name: Name of the span (e.g., "reflection.evaluate")
            kind: Type of span (INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER)
            attributes: Custom attributes to attach to the span
        """
        if not self.enabled or self._tracer is None:
            yield None
            return

        if kind is None and SpanKind is not None:
            kind = SpanKind.INTERNAL

        with self._tracer.start_as_current_span(
            name=name,
            kind=kind,
            attributes=attributes or {},
        ) as span:
            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise

    def add_span_attribute(self, key: str, value: str) -> None:
        """Add an attribute to the current span."""
        if not self.enabled or trace is None:
            return

        try:
            current_span = trace.get_current_span()
            if current_span:
                current_span.set_attribute(key, value)
        except Exception as e:
            logger.warning(f"Failed to add span attribute: {e}")

    def add_span_event(self, name: str, attributes: dict | None = None) -> None:
        """
        Add an event to the current span.

        Events represent discrete occurrences within a span, useful for
        logging tool invocations, LLM responses, or state transitions.
        """
        if not self.enabled or trace is None:
            return

        try:
            current_span = trace.get_current_span()
            if current_span:
                current_span.add_event(name, attributes=attributes or {})
        except Exception as e:
            logger.warning(f"Failed to add span event: {e}")

    def record_workflow_step(
        self,
        step_name: str,
        step_type: str,
        duration_ms: float | None = None,
        success: bool = True,
        metadata: dict | None = None,
    ) -> None:
        """
        Record a workflow step as a span event with standard attributes.

        Args:
            step_name: Name of the workflow step (e.g., "reflection", "router")
            step_type: Type of step (e.g., "node", "edge", "tool")
            duration_ms: Duration of the step in milliseconds
            success: Whether the step succeeded
            metadata: Additional metadata to record
        """
        attributes = {
            "workflow.step.name": step_name,
            "workflow.step.type": step_type,
            "workflow.step.success": success,
        }

        if duration_ms is not None:
            attributes["workflow.step.duration_ms"] = duration_ms

        if metadata:
            for key, value in metadata.items():
                attributes[f"workflow.step.{key}"] = str(value)

        self.add_span_event(f"workflow.{step_name}", attributes)

    @contextmanager
    def traced_node(
        self,
        span_name: str,
        step_name: str,
        step_type: str = "node",
        attributes: dict | None = None,
    ):
        """
        All-in-one context manager for tracing a workflow node.

        Combines span creation, timing, and step recording into a single
        call. The yielded ``result`` dict can be updated by the caller to
        attach post-execution metadata (e.g. tool names, decisions).

        Usage::

            with observability.traced_node(
                "router.classify",
                step_name="router",
                attributes={"message.count": len(messages)},
            ) as trace_ctx:
                response = await chain.ainvoke(...)
                trace_ctx["intent"] = intent

        Args:
            span_name: OTel span name (e.g. "search_agent.invoke").
            step_name: Workflow step name recorded in the completion event.
            step_type: Step category ("node", "background", "edge").
            attributes: Span attributes set at creation time.
        """
        result: dict = {}
        start = time.time()

        try:
            with self.create_span(span_name, attributes=attributes):
                yield result
            success = True
        except Exception:
            success = False
            raise
        finally:
            duration_ms = (time.time() - start) * 1000
            self.record_workflow_step(
                step_name=step_name,
                step_type=step_type,
                duration_ms=duration_ms,
                success=success,
                metadata=result,
            )


# Global observability manager instance
_observability_manager: ObservabilityManager | None = None


def get_observability_manager() -> ObservabilityManager:
    """Get the global observability manager instance."""
    global _observability_manager

    if _observability_manager is None:
        from src.config import settings

        _observability_manager = ObservabilityManager(
            service_name=settings.OTEL_SERVICE_NAME,
            enabled=settings.AGENT_OBSERVABILITY_ENABLED,
        )

    return _observability_manager


def initialize_observability(
    service_name: str = "ev-copilot-agent",
    enabled: bool = True,
) -> ObservabilityManager:
    """
    Initialize the global observability manager.

    Call this at application startup to configure observability.
    """
    global _observability_manager

    _observability_manager = ObservabilityManager(
        service_name=service_name,
        enabled=enabled,
    )

    return _observability_manager
