"""Formatting helpers for AgentCore Memory responses."""

from src.schemas.preferences import (
    PreferenceListResponse,
    PreferenceRecord,
)


def _record_to_dict(record) -> dict:
    """Normalize a memory record into a plain dict.

    ``MemorySession.search_long_term_memories`` returns SDK ``MemoryRecord``
    wrapper objects (dict-like ``DictWrapper``, not ``dict`` subclasses)
    around the ``RetrieveMemoryRecords`` summaries.
    """
    if isinstance(record, dict):
        return record
    if hasattr(record, "items"):
        return dict(record.items())
    return {"content": {"text": str(record)}}


def _format_memory_record(record: dict) -> PreferenceRecord:
    """Format a single memory record summary into a PreferenceRecord model.

    AgentCore memory record summaries use ``memoryRecordId``,
    ``content: {"text": ...}``, ``namespaces: [...]``, ``createdAt``
    (datetime) and ``score``.
    """
    content = record.get("content")
    if isinstance(content, dict):
        content = content.get("text")

    namespaces = record.get("namespaces") or []
    namespace = namespaces[0] if namespaces else record.get("namespace")

    created_at = record.get("createdAt")
    score = record.get("score")

    return PreferenceRecord(
        record_id=record.get("memoryRecordId"),
        content=str(content) if content is not None else None,
        namespace=namespace,
        created_at=str(created_at) if created_at is not None else None,
        relevance_score=float(score) if score is not None else None,
    )


def format_memory_records(records: list) -> PreferenceListResponse:
    """Format a list of memory records into a PreferenceListResponse model."""
    formatted = [_format_memory_record(_record_to_dict(record)) for record in records]

    return PreferenceListResponse(
        count=len(formatted),
        preferences=formatted,
    )
