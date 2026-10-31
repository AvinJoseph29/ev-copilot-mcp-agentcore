"""
Main entry point for the EV Copilot Agent.

Designed to be run with OpenTelemetry auto-instrumentation:
    opentelemetry-instrument python -m src.main
"""

from src.infrastructure.api import app

if __name__ == "__main__":
    app.run()
