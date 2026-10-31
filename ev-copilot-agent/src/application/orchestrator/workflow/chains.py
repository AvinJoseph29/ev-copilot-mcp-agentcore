"""
Chain builders for the EV Copilot workflow.

Creates LangChain chains (prompt | model) for each workflow node:
1. Trip Planner Agent chain (with tools)
2. Router chain (intent classification)
3. Simple Response chain
4. Reflection chain (quality evaluation)

All chain builders are async to support loading prompts from MCP server.
"""

from datetime import UTC, datetime
from typing import NamedTuple

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable
from loguru import logger

from src.application.orchestrator.workflow.tools import get_orchestrator_tools
from src.infrastructure.model import ModelType, get_model
from src.infrastructure.prompt_loader import get_prompt


class PromptMetadata(NamedTuple):
    """Metadata about the prompt used for observability tracing."""
    name: str
    version: str | None
    id: str | None
    arn: str | None


class TripPlannerAgentChainResult(NamedTuple):
    """Result containing the trip planner agent chain and its prompt metadata."""
    chain: Runnable
    prompt_metadata: PromptMetadata


def _escape_braces(text: str) -> str:
    """
    Escape curly braces to prevent ChatPromptTemplate from interpreting
    them as variables.
    """
    return text.replace("{", "{{").replace("}", "}}")


async def get_trip_planner_agent_chain(
    customer_name: str = "Guest",
    actor_id: str = "user:default",
    latitude: float | None = None,
    longitude: float | None = None,
    reflection_feedback: str = "",
    with_tools: bool = True,
) -> TripPlannerAgentChainResult:
    """
    Create the trip planner agent chain with bound tools for EV trip planning.

    Loads the agent scope prompt from the MCP server (no local fallback).
    Injects runtime context (actor_id, current date/time, location, reviewer
    feedback) into the system prompt so the LLM can pass them to MCP tools
    that require them.

    with_tools=False builds the chain without bound tools, so the model has to
    answer from the data already gathered (used once the tool budget is spent).
    """
    logger.info("Creating trip planner agent chain")

    model = get_model(temperature=0.5, model_type=ModelType.ORCHESTRATOR)

    tools = await get_orchestrator_tools() if with_tools else []
    tool_names = [t.name for t in tools]

    # Bind the tools to the model
    if with_tools:
        model = model.bind_tools(tools)

    # Load prompt from MCP
    prompt_text = await get_prompt("ev_copilot_agent_scope")

    # Substitute {{user_name}} with the customer name (braces are escaped once, below)
    system_message = prompt_text.replace("{{user_name}}", customer_name)

    # Inject runtime context the LLM needs to pass to MCP tools
    system_message += (
        f"\n\n<user_context>"
        f"\nThe current user's actor_id is: {actor_id}"
        f"\nWhen calling any preference or memory tools, use this exact actor_id value."
        f"\nThe current date and time (UTC) is: "
        f"{datetime.now(UTC).isoformat(timespec='seconds')}"
        f"\n</user_context>"
    )

    # Inject user location context if coordinates are available
    if latitude is not None and longitude is not None:
        system_message += (
            "\n\n<user_location>"
            f"\nThe user's current location coordinates are:"
            f"\n- Latitude: {latitude}"
            f"\n- Longitude: {longitude}"
            "\nUse these coordinates when the user asks about nearby chargers or places, "
            "weather at their location, or a trip starting from their current location. "
            "You do not need to ask the user for their location — you already have it."
            "\n</user_location>"
        )

    # Inject the reviewer's critique when reflection sent the agent back for more work
    if reflection_feedback:
        system_message += (
            "\n\n<reviewer_feedback>"
            "\nA quality reviewer checked your previous draft answer and found it incomplete:"
            f"\n{reflection_feedback}"
            "\nAddress every point above (call more tools if needed, e.g. re-run the trip "
            "energy simulation), then write a complete, revised final answer that replaces "
            "the previous draft. Do not mention the reviewer."
            "\n</reviewer_feedback>"
        )

    # Escape all braces for ChatPromptTemplate
    system_message = _escape_braces(system_message)

    prompt_metadata = PromptMetadata(
        name="ev_copilot_agent_scope",
        version=None,
        id=None,
        arn=None,
    )

    logger.debug(
        f"Trip planner agent prompt: name={prompt_metadata.name}, tools={tool_names}"
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_message),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    return TripPlannerAgentChainResult(
        chain=prompt | model,
        prompt_metadata=prompt_metadata,
    )


async def get_router_chain() -> Runnable:
    """
    Create the router chain for intent classification.

    Classifies user intent into:
    - trip_planning: EV trips, routes, chargers, range, battery, vehicles, weather for a drive
    - simple: Greetings, thanks, questions about the assistant
    - off_topic: Unrelated questions

    Uses a fast model for low latency routing decisions.
    """
    logger.debug("Creating router chain for intent classification")

    model = get_model(temperature=0.0, model_type=ModelType.ROUTER)

    prompt_text = await get_prompt("router_intent_classifier")
    system_message = _escape_braces(prompt_text)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_message),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    return prompt | model


async def get_simple_response_chain(customer_name: str = "Guest") -> Runnable:
    """
    Create the simple response chain for non-trip queries.

    Handles greetings, thanks, capabilities questions, off-topic redirections.
    """
    logger.debug(f"Creating simple response chain for {customer_name}")

    model = get_model(temperature=0.7, model_type=ModelType.ORCHESTRATOR)

    prompt_text = await get_prompt("simple_response")

    # Substitute {{user_name}} with the customer name, then escape braces once
    system_message = prompt_text.replace("{{user_name}}", customer_name)
    system_message = _escape_braces(system_message)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_message),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    return prompt | model


async def get_reflection_chain() -> Runnable:
    """
    Create the reflection chain for quality evaluation.

    Reviews the gathered information and the draft trip plan and decides
    if more tool calls are needed. Uses temperature 0.0 for deterministic
    evaluation.
    """
    logger.debug("Creating reflection chain for quality evaluation")

    model = get_model(temperature=0.0, model_type=ModelType.REFLECTION)

    prompt_text = await get_prompt("reflection_quality_review")
    system_message = _escape_braces(prompt_text)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_message),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    return prompt | model
