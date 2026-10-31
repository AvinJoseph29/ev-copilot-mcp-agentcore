"""
LangGraph checkpointer using AgentCore Memory.

Memory is created and configured via CDK infrastructure (agentcore-stack.ts).
The MEMORY_ID environment variable must be set from the CDK stack output.

All memory read/write operations (preferences, conversation turns) go through
the MCP server. This module only provides the LangGraph checkpointer for
workflow state persistence.
"""

from langgraph_checkpoint_aws import AgentCoreMemorySaver
from loguru import logger

from src.config import settings


class ShortTermMemory:
    """
    LangGraph state checkpointer using AgentCore Memory.

    The MEMORY_ID must be provided via environment variable.
    Memory creation is handled by CDK infrastructure, not at runtime.
    """

    def __init__(self):
        if not settings.MEMORY_ID:
            raise RuntimeError(
                "MEMORY_ID environment variable is required. "
                "Deploy the CDK stack and set MEMORY_ID from the stack output."
            )

        self._memory_id = settings.MEMORY_ID
        logger.info(f"Using MEMORY_ID from environment: {self._memory_id}")

    @property
    def memory_id(self) -> str:
        """Return the configured memory ID."""
        return self._memory_id

    def get_memory(self) -> AgentCoreMemorySaver:
        """Get the LangGraph checkpointer for state persistence."""
        return AgentCoreMemorySaver(
            memory_id=self._memory_id,
            region_name=settings.AWS_REGION,
        )
