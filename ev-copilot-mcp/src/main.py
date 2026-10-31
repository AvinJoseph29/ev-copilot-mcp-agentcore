"""Container entrypoint for the MCP server (invoked by Dockerfile CMD)."""

import uvicorn

from src.servers.tool_registry import McpServersRegistry

app = McpServersRegistry().create_app(eager_init=True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
