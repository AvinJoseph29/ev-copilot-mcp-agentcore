"""
Agent prompt names.

All prompt content is managed exclusively by the MCP server —
the agent loads prompts at startup via the MCP prompt endpoint.
This module only defines the canonical prompt names for reference.
"""

PROMPT_NAMES: list[str] = [
    "ev_copilot_agent_scope",
    "router_intent_classifier",
    "simple_response",
    "reflection_quality_review",
]
