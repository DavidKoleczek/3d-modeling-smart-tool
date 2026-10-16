"""MCP adapter: the app's MCP server over stdio, a thin surface over the library."""

import asyncio

from mcp.server.stdio import stdio_server

from modeling_3d import lib
from modeling_3d.adapters.inbox import session_inbox

FROM_APP = (
    "The user wrote this in the Modeling 3D app. They read the app, not this conversation, so answer with the "
    "modeling-3d `reply` tool.\n\n{text}"
)


def run_stdio() -> None:
    """Serve the MCP server over stdin and stdout until the client disconnects, then stop the app if it was opened."""
    asyncio.run(_serve())


async def _serve() -> None:
    inbox = session_inbox()
    deliver = None if inbox is None else lambda text: inbox.post(FROM_APP.format(text=text))
    app_server = lib.app_server(deliver)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app_server.server.run(read_stream, write_stream, app_server.server.create_initialization_options())
    finally:
        app_server.close()
