"""
Root-level AgentCore entry point for the EV Copilot Agent.

This module exposes the BedrockAgentCoreApp instance at the package root level,
as required by the .bedrock_agentcore.yaml configuration.
"""

from src.infrastructure.api import app

__all__ = ["app"]

if __name__ == "__main__":
    app.run()
