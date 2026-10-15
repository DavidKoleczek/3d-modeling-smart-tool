"""MCP adapter: the app as a Claude Code channel, a thin surface over the library."""

import asyncio
from typing import Any

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification, TextContent, Tool

from modeling_3d import lib
from modeling_3d.core.skill import DISTRIBUTION
from modeling_3d.schemas import Modeling3dError

# Claude Code's extension to MCP: declaring the capability makes a session started with this server in `--channels`
# deliver its channel notifications to the model.
CHANNEL_CAPABILITY = "claude/channel"
CHANNEL_NOTIFICATION = "notifications/claude/channel"
INSTRUCTIONS = """\
Modeling 3d has an app: a chat page on this machine where the user talks to you.

Call `open_app` when the user asks for the app, and give them the URL it returns. Messages they type there arrive as \
<channel> events from this server. They read the app, not this terminal, so answer those messages with `reply`."""

OPEN_APP = Tool(
    name="open_app",
    description="Open the Modeling 3d app, a chat page for the user, and return its URL. Opening it again returns the "
    "same URL.",
    inputSchema={"type": "object", "properties": {}},
)
REPLY = Tool(
    name="reply",
    description="Show a message to the user in the app. The app must be open.",
    inputSchema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
)


def run_stdio() -> None:
    """Serve the MCP server over stdin and stdout until the client disconnects, then stop the app if it was opened."""
    asyncio.run(_serve())


async def _serve() -> None:
    server = Server(DISTRIBUTION, version=lib.version(), instructions=INSTRUCTIONS)
    loop = asyncio.get_running_loop()
    app: lib.App | None = None

    async with stdio_server() as (read_stream, write_stream):

        async def notify(text: str) -> None:
            # The SDK sends only the notifications MCP defines, so the channel's goes onto the stream directly.
            notification = JSONRPCNotification(jsonrpc="2.0", method=CHANNEL_NOTIFICATION, params={"content": text})
            await write_stream.send(SessionMessage(JSONRPCMessage(notification)))

        def forward(text: str) -> None:
            # The app calls this from its own thread, and the stream belongs to this one.
            asyncio.run_coroutine_threadsafe(notify(text), loop)

        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return [OPEN_APP, REPLY]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            nonlocal app
            if name == OPEN_APP.name:
                if app is None:
                    app = lib.serve_app(on_message=forward)
                return [TextContent(type="text", text=app.url)]
            if name != REPLY.name:
                raise Modeling3dError(f"'{name}' is not a tool of this server. The tools are: open_app, reply.")
            if app is None:
                raise Modeling3dError("The app is not open. Call open_app and give the user its URL first.")
            pages = app.send(arguments["text"])
            return [TextContent(type="text", text="sent" if pages else "sent, but no page of the app is open")]

        options = server.create_initialization_options(experimental_capabilities={CHANNEL_CAPABILITY: {}})
        try:
            await server.run(read_stream, write_stream, options)
        finally:
            if app is not None:
                app.stop()
