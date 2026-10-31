"""
Bedrock AgentCore Memory client.

Wraps the bedrock_agentcore.memory SDK for long-term memory operations:
- Create memory sessions
- Add conversational turns (store preferences)
- Search long-term memories

The SDK is boto3-based (synchronous), so all calls are wrapped in
asyncio.to_thread() to avoid blocking the ASGI event loop.
"""

import asyncio
import uuid

from bedrock_agentcore.memory.constants import ConversationalMessage, MessageRole
from bedrock_agentcore.memory.session import MemorySessionManager
from loguru import logger


class AgentCoreMemoryClient:
    """Async client for Bedrock AgentCore Long-Term Memory."""

    def __init__(self, memory_id: str, region_name: str) -> None:
        if not memory_id:
            raise ValueError("AGENTCORE_MEMORY_ID is not set.")
        self._memory_id = memory_id
        self._region_name = region_name
        self._manager = MemorySessionManager(
            memory_id=memory_id,
            region_name=region_name,
        )

    async def save_conversation_turn(
        self,
        actor_id: str,
        session_id: str,
        user_input: str,
        agent_response: str,
    ) -> dict:
        """Save a full conversation turn to trigger all memory strategies."""
        logger.debug(f"Saving conversation turn: actor={actor_id}, session={session_id}")

        def _save():
            session = self._manager.create_memory_session(
                actor_id=actor_id,
                session_id=session_id,
            )
            session.add_turns([
                ConversationalMessage(user_input, MessageRole.USER),
                ConversationalMessage(agent_response, MessageRole.ASSISTANT),
            ])
            return {"actor_id": actor_id, "session_id": session_id, "status": "saved"}

        return await asyncio.to_thread(_save)

    async def search_preferences(
        self,
        actor_id: str,
        query: str,
        top_k: int = 5,
    ) -> list:
        """Semantic search over a user's long-term memory records."""
        namespace = f"/preferences/{actor_id}/"
        logger.debug(f"Searching preferences: actor={actor_id}, query={query!r}")

        def _search():
            session = self._manager.create_memory_session(
                actor_id=actor_id,
                session_id=f"search-{uuid.uuid4().hex[:8]}",
            )
            return session.search_long_term_memories(
                query=query,
                namespace_prefix=namespace,
                top_k=top_k,
            )

        return await asyncio.to_thread(_search)
