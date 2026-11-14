"""MCP server (stdio) exposing the 6 lean browser tools.

Claude Code:  claude mcp add lean-browser -- /path/to/.venv/bin/leanb mcp
The browser starts lazily on the first tool call and shuts down when the client disconnects.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from lean_browser.tools import INSTRUCTIONS, TOOLS, Config, LeanBrowser

MCP_TOOLS = [types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"]) for t in TOOLS]


def build_server(config: Config | None = None) -> Server:
    state: dict = {}
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_server):
        try:
            yield state
        finally:
            lb = state.get("lb")
            if lb:
                await lb.__aexit__(None, None, None)

    async def get_lb() -> LeanBrowser:
        if "lb" not in state:
            lb = LeanBrowser(config)
            await lb.__aenter__()
            state["lb"] = lb
        return state["lb"]

    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=MCP_TOOLS)

    async def on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        async with lock:  # one browser session: serialize tool calls
            lb = await get_lb()
            parts = await lb.call(params.name, params.arguments or {})
        content = []
        is_error = False
        for p in parts:
            if isinstance(p, bytes):
                content.append(types.ImageContent(type="image", data=base64.b64encode(p).decode(), mime_type="image/png"))
            else:
                is_error = is_error or p.startswith("Error:")
                content.append(types.TextContent(type="text", text=p))
        return types.CallToolResult(content=content, is_error=is_error)

    return Server("lean-browser", version="0.1.0", instructions=INSTRUCTIONS, lifespan=lifespan,
                  on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def serve_stdio(config: Config | None = None):
    server = build_server(config)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
