"""
MCP Tool Registry.

Aggregates all MCP servers into a single FastMCP instance with prefix namespacing.
Initializes observability and syncs local prompt definitions to Bedrock on startup.
"""

import asyncio

from fastmcp import FastMCP
from loguru import logger

from src.infrastructure.bedrock_prompt_manager import get_prompt_manager
from src.infrastructure.observability import initialize_observability
from src.servers.charging_server import charging_mcp
from src.servers.place_finder_server import place_finder_mcp
from src.servers.prompt_server import prompt_mcp
from src.servers.routing_server import routing_mcp
from src.servers.user_preferences_server import user_preferences_mcp
from src.servers.vehicle_server import vehicle_mcp
from src.servers.weather_server import weather_mcp


class McpServersRegistry:
    def __init__(self) -> None:
        self.registry = FastMCP("tool_registry")
        self._is_initialized = False
        # Guards initialize() so concurrent first requests (lazy init) run it once
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Import all MCP servers into the registry with namespaces."""
        if self._is_initialized:
            return

        async with self._init_lock:
            if self._is_initialized:
                return

            logger.info("Initializing MCP tool registry...")

            # --- Initialize observability ---
            try:
                from src.config import settings

                initialize_observability(
                    service_name=settings.OTEL_SERVICE_NAME,
                    enabled=settings.AGENT_OBSERVABILITY_ENABLED,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Observability initialization failed. "
                    "Tracing will be disabled."
                )

            # --- Sync prompts to Bedrock before mounting ---
            try:
                manager = get_prompt_manager()
                await manager.sync_all_prompts()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Prompt sync failed. Server will continue with "
                    "existing Bedrock DRAFT content."
                )

            # --- Mount servers ---
            self.registry.mount(charging_mcp, namespace="charging")
            self.registry.mount(place_finder_mcp, namespace="places")
            self.registry.mount(routing_mcp, namespace="routing")
            self.registry.mount(vehicle_mcp, namespace="vehicle")
            self.registry.mount(weather_mcp, namespace="weather")
            self.registry.mount(user_preferences_mcp, namespace="preferences")
            self.registry.mount(prompt_mcp, namespace="prompts")

            self._is_initialized = True

        all_tools = await self.registry.list_tools()
        tool_names = [t.name for t in all_tools]
        logger.info(f"Registry initialized with {len(all_tools)} tools: {tool_names}")

        all_prompts = await self.registry.list_prompts()
        prompt_names = [p.name for p in all_prompts]
        logger.info(f"Registry initialized with {len(all_prompts)} prompts: {prompt_names}")

    def get_registry(self) -> FastMCP:
        return self.registry

    def create_app(self, *, eager_init: bool = True):
        """Create an ASGI app from the registry.

        Args:
            eager_init: If True, initialize during ASGI lifespan startup
                        (production). If False, initialize lazily on the
                        first request (local dev / agentcore dev).
        """
        inner = self.registry.http_app(stateless_http=True)

        if eager_init:
            async def app(scope, receive, send):
                if scope["type"] == "lifespan":
                    async def startup_then_send(message):
                        if (
                            message["type"] == "lifespan.startup.complete"
                            and not self._is_initialized
                        ):
                            await self.initialize()
                        await send(message)

                    await inner(scope, receive, startup_then_send)
                    return
                await inner(scope, receive, send)
        else:
            async def app(scope, receive, send):
                if scope["type"] == "lifespan":
                    await inner(scope, receive, send)
                    return
                if not self._is_initialized:
                    await self.initialize()
                await inner(scope, receive, send)

        return app
