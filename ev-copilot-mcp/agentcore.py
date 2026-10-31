# Entrypoint for `agentcore dev` (loaded as agentcore:app by Uvicorn)
from src.servers.tool_registry import McpServersRegistry

app = McpServersRegistry().create_app(eager_init=False)
