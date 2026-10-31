"""Pydantic response models for AgentCore Memory / User Preferences tools."""

from pydantic import BaseModel, Field


class PreferenceRecord(BaseModel):
    record_id: str | None = Field(None, description="Unique record identifier.")
    content: str | None = Field(None, description="Preference text content.")
    namespace: str | None = Field(None, description="Memory namespace.")
    created_at: str | None = Field(None, description="Creation timestamp.")
    relevance_score: float | None = Field(None, description="Semantic search relevance score.")


class PreferenceListResponse(BaseModel):
    count: int = Field(description="Number of preferences returned.")
    preferences: list[PreferenceRecord] = Field(description="List of preference records.")


class SaveConversationTurnResponse(BaseModel):
    status: str = Field(description="Operation status (e.g. 'saved').")
    actor_id: str | None = Field(None, description="User identifier.")
    session_id: str | None = Field(None, description="Conversation session identifier.")
