"""
MCP Connection Layer for AgentCore.

Three connection modes, auto-selected based on configuration:

1. LOCAL mode (LOCAL_MCP_URL set):
   - Single connection to local MCP server for both tools and prompts
   - No auth, no tool name prefixing
   - For local development

2. DEPLOYED mode (GATEWAY_URL + RUNTIME_URL set):
   - Gateway Client: For tool proxy and invocation (Cognito JWT, prefixed tool names)
   - Prompt Client: Direct to Runtime for prompts and resources (Cognito JWT)
   - Both connections active simultaneously

3. PARTIAL mode (only GATEWAY_URL or only RUNTIME_URL):
   - Whichever is configured works; the other raises RuntimeError
"""

import asyncio
import threading
import time
from typing import Any

import httpx
import requests
from langchain_mcp_adapters.client import MultiServerMCPClient
from loguru import logger

from src.config import settings

# Token cache for Cognito auth (shared by the gateway and prompt clients in deployed mode)
_token_cache: dict[str, Any] = {
    "access_token": None,
    "expires_at": 0,
}
# Serializes token fetches and invalidation across worker threads
_token_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Tool Client — Gateway or Local
# ---------------------------------------------------------------------------


def get_tool_client() -> MultiServerMCPClient:
    """
    Create MCP client for tool invocation.

    - If LOCAL_MCP_URL is set, connects to local MCP server (no auth, no prefix).
    - Otherwise, connects via AgentCore Gateway (Cognito JWT, prefixed tool names).
      The token is attached per request, so long-lived processes keep working
      after the token rotates.

    Returns:
        MultiServerMCPClient configured for tool invocation.
    """
    if settings.LOCAL_MCP_URL:
        logger.debug(f"Creating tool client for LOCAL MCP: {settings.LOCAL_MCP_URL}")
        return MultiServerMCPClient(
            {
                "local_mcp": {
                    "transport": "streamable_http",
                    "url": settings.LOCAL_MCP_URL,
                }
            }
        )

    if not settings.GATEWAY_URL:
        raise RuntimeError("Missing required configuration: GATEWAY_URL (or LOCAL_MCP_URL) for tool invocation")

    logger.debug(f"Creating tool client for gateway: {settings.GATEWAY_URL}")
    return MultiServerMCPClient(
        {
            "agentcore_gateway": {
                "transport": "streamable_http",
                "url": settings.GATEWAY_URL,
                "auth": _CognitoAuth(),
            }
        }
    )


# ---------------------------------------------------------------------------
# Prompt Client — Direct to Runtime, Local, or skipped
# ---------------------------------------------------------------------------


async def get_prompt_client() -> MultiServerMCPClient:
    """
    Create MCP client for prompt and resource fetching.

    - If LOCAL_MCP_URL is set, connects to local MCP server (no auth).
    - Otherwise, connects directly to AgentCore Runtime using Cognito JWT.

    The (synchronous) Cognito token request runs in a worker thread so it
    never blocks the event loop.

    Returns:
        MultiServerMCPClient configured for prompt/resource access.
    """
    if settings.LOCAL_MCP_URL:
        logger.debug(f"Creating prompt client for LOCAL MCP: {settings.LOCAL_MCP_URL}")
        return MultiServerMCPClient(
            {
                "local_mcp": {
                    "transport": "streamable_http",
                    "url": settings.LOCAL_MCP_URL,
                }
            }
        )

    if not settings.RUNTIME_URL:
        raise RuntimeError("Missing required configuration: RUNTIME_URL (or LOCAL_MCP_URL) for prompt fetching")

    logger.debug(f"Creating prompt client for runtime: {settings.RUNTIME_URL}")
    headers = await asyncio.to_thread(_get_cognito_headers)

    return MultiServerMCPClient(
        {
            "agentcore_runtime": {
                "transport": "streamable_http",
                "url": settings.RUNTIME_URL,
                "headers": headers,
            }
        }
    )


# ---------------------------------------------------------------------------
# Cognito Authentication (deployed mode only)
# ---------------------------------------------------------------------------


class _CognitoAuth(httpx.Auth):
    """
    Bearer auth for the Gateway using the cached Cognito token.

    Each request gets the current token (refreshed shortly before expiry).
    A 401 drops the cached token and retries the request once with a new one.
    """

    def sync_auth_flow(self, request: httpx.Request):
        request.headers.update(_get_cognito_headers())
        response = yield request
        if response.status_code == 401:
            _invalidate_cognito_token(request.headers["Authorization"])
            request.headers.update(_get_cognito_headers())
            yield request

    async def async_auth_flow(self, request: httpx.Request):
        # Fetching a token is synchronous; keep it off the event loop when the cache misses.
        request.headers.update(_cached_cognito_headers() or await asyncio.to_thread(_get_cognito_headers))
        response = yield request
        if response.status_code == 401:
            _invalidate_cognito_token(request.headers["Authorization"])
            request.headers.update(await asyncio.to_thread(_get_cognito_headers))
            yield request


def _cached_cognito_headers() -> dict[str, str] | None:
    """Return the cached token's header if it is still valid (60s buffer), otherwise None."""
    access_token, expires_at = _token_cache["access_token"], _token_cache["expires_at"]
    if access_token and time.time() < expires_at - 60:
        return {"Authorization": f"Bearer {access_token}"}
    return None


def _invalidate_cognito_token(rejected_header: str) -> None:
    """Drop the cached token if it is the one that was rejected, so the next request fetches a new one."""
    logger.warning("Gateway rejected the Cognito token (401); fetching a new one")
    with _token_lock:
        # Another request may already have replaced the rejected token with a fresh one.
        if rejected_header == f"Bearer {_token_cache['access_token']}":
            _token_cache["access_token"] = None
            _token_cache["expires_at"] = 0


def _get_cognito_headers() -> dict[str, str]:
    """
    Get Cognito JWT token for Gateway and direct Runtime access.

    Caches the token and refreshes when expired (with 60s buffer). Concurrent
    callers share one token request. The client secret is resolved at startup
    from Secrets Manager (COGNITO_CLIENT_SECRET_ARN) or, in local development,
    read from COGNITO_CLIENT_SECRET.
    """
    cached = _cached_cognito_headers()
    if cached:
        return cached

    with _token_lock:
        # Another thread may have fetched a token while this one waited for the lock.
        cached = _cached_cognito_headers()
        if cached:
            return cached

        if not settings.COGNITO_TOKEN_ENDPOINT:
            raise RuntimeError("Missing COGNITO_TOKEN_ENDPOINT (required for Gateway and Runtime auth in deployed mode)")
        if not settings.COGNITO_CLIENT_ID:
            raise RuntimeError("Missing COGNITO_CLIENT_ID (required for Gateway and Runtime auth in deployed mode)")
        if not settings.COGNITO_CLIENT_SECRET:
            raise RuntimeError(
                "Missing Cognito client secret (required for Gateway and Runtime auth in deployed mode; "
                "set COGNITO_CLIENT_SECRET_ARN, or COGNITO_CLIENT_SECRET for local development)"
            )

        logger.debug("Fetching new Cognito token")

        response = requests.post(
            settings.COGNITO_TOKEN_ENDPOINT,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.COGNITO_CLIENT_ID,
                "client_secret": settings.COGNITO_CLIENT_SECRET,
                "scope": f"{settings.APP_NAME}-api/mcp",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        response.raise_for_status()

        token_data = response.json()
        access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)

        _token_cache["expires_at"] = time.time() + expires_in
        _token_cache["access_token"] = access_token

        logger.debug(f"Cognito token obtained, expires in {expires_in}s")

        return {"Authorization": f"Bearer {access_token}"}


# ---------------------------------------------------------------------------
# Tool Name Resolution
# ---------------------------------------------------------------------------


def get_tool_prefix() -> str:
    """
    Gateway tool name prefix for the MCP target.

    The Gateway prefixes every tool with "<targetName>___", and the CDK
    GatewayStack names the target "<APP_NAME>-McpTarget".
    """
    return f"{settings.APP_NAME}-McpTarget___"


def get_tool_name(base_name: str) -> str:
    """
    Resolve tool name for invocation.

    In LOCAL mode: tool names are NOT prefixed (direct MCP names).
    In DEPLOYED mode: Gateway prefixes with target name:
        "charging_search_chargers_along_route" → "evCopilot-McpTarget___charging_search_chargers_along_route"
    """
    if settings.LOCAL_MCP_URL:
        return base_name
    return f"{get_tool_prefix()}{base_name}"


# ---------------------------------------------------------------------------
# Configuration Checks
# ---------------------------------------------------------------------------


def is_gateway_configured() -> bool:
    """Check if tool invocation is available (local or gateway)."""
    return bool(settings.LOCAL_MCP_URL) or bool(settings.GATEWAY_URL)
