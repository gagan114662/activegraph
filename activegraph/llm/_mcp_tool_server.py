"""In-process HTTP MCP tool server for ClaudeCodeCliProvider v2.

Spawned BY the provider in a background thread when `complete(tools=...)`
is called with a non-empty tool list. Exposes those tools as MCP tools
over HTTP so the claude CLI subprocess can invoke them. Tool callables
live in the SAME Python process as the provider, so when claude calls
a tool via MCP HTTP, this server invokes the function directly and
returns the result.

Design:
  - Uses the official Python MCP SDK (`pip install mcp`).
  - Streamable HTTP transport (claude supports it; same transport as
    Pentagon's https://auth.pentagon.run/functions/v1/mcp).
  - Random localhost port chosen at startup; provider reads it from the
    returned `serve_url`.
  - Tools list passed in via the `tool_callables` dict mapping name ->
    {"function": <callable>, "description": str, "input_schema": dict}.

Usage from provider:
  >>> ctx = start_tool_server(tool_callables)
  >>> # ctx.url is something like http://127.0.0.1:54321/mcp
  >>> # spawn claude with --mcp-config '{"mcpServers":{"activegraph":{"type":"http","url":ctx.url}}}'
  >>> # claude calls tools; this server invokes them
  >>> ctx.shutdown()
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolServerContext:
    url: str
    port: int
    server_task: Any = None
    loop: Optional[asyncio.AbstractEventLoop] = None
    thread: Optional[threading.Thread] = None
    stop_event: Optional[threading.Event] = field(default=None)
    invocations: list[dict[str, Any]] = field(default_factory=list)

    def shutdown(self) -> None:
        if self.stop_event:
            self.stop_event.set()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)


def _find_free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_tool_server(tool_callables: dict[str, dict[str, Any]]) -> ToolServerContext:
    """Start an MCP HTTP server exposing the given tools. Returns context
    with `url` for `--mcp-config` injection. Call `.shutdown()` to stop.

    `tool_callables` maps tool name to:
      {"function": Callable, "description": str, "input_schema": dict}.
    The function receives the keyword args from claude's tool call and
    must return a value JSON-serializable to a string (str(result) is
    used).
    """
    # Defer imports so callers that never use tools don't pay the cost.
    from mcp.server.lowlevel import Server
    import mcp.types as types
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.routing import Mount, Route

    # Build the MCP server.
    server = Server("activegraph-tools")
    invocations: list[dict[str, Any]] = []

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=name,
                description=spec.get("description", ""),
                inputSchema=spec.get("input_schema") or {
                    "type": "object",
                    "properties": {},
                },
            )
            for name, spec in tool_callables.items()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        spec = tool_callables.get(name)
        if not spec:
            return [types.TextContent(type="text", text=f"unknown tool: {name}")]
        fn: Callable = spec["function"]
        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(**(arguments or {}))
            else:
                result = fn(**(arguments or {}))
            invocations.append({"name": name, "arguments": arguments, "result": str(result)[:2000]})
            return [types.TextContent(type="text", text=str(result))]
        except Exception as e:
            invocations.append({"name": name, "arguments": arguments, "error": str(e)})
            return [types.TextContent(type="text", text=f"tool error: {e}")]

    # Use streamable HTTP transport — claude's default for HTTP MCP.
    try:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    except ImportError as e:
        raise RuntimeError(f"MCP SDK missing streamable HTTP support: {e}")

    session_manager = StreamableHTTPSessionManager(app=server)

    async def handle_mcp(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    starlette_app = Starlette(
        debug=False,
        routes=[Mount("/mcp", app=handle_mcp)],
    )

    port = _find_free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    stop_event = threading.Event()

    def run_server():
        # Each thread needs its own event loop; uvicorn manages this.
        config = uvicorn.Config(
            app=starlette_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="on",
        )
        server_instance = uvicorn.Server(config)
        # Run the server until stop_event is set.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def runner():
                async with session_manager.run():
                    server_task = asyncio.create_task(server_instance.serve())
                    # Watch stop_event.
                    while not stop_event.is_set():
                        await asyncio.sleep(0.1)
                    server_instance.should_exit = True
                    try:
                        await asyncio.wait_for(server_task, timeout=2.0)
                    except asyncio.TimeoutError:
                        server_task.cancel()
            loop.run_until_complete(runner())
        finally:
            loop.close()

    thread = threading.Thread(target=run_server, daemon=True, name=f"mcp-tools-{port}")
    thread.start()

    # Block until server is ready (poll the port).
    import time
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                s.settimeout(0.1)
                s.connect(("127.0.0.1", port))
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)

    return ToolServerContext(
        url=url,
        port=port,
        thread=thread,
        stop_event=stop_event,
        invocations=invocations,
    )
