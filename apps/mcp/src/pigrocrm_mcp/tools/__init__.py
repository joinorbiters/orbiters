from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer

from pigrocrm_mcp.context import McpContext


def register_entity_tools(mcp: MCPServer, context: McpContext, guard: Callable[..., Any]) -> None:
    """Filled in by Task 17."""
    return None
