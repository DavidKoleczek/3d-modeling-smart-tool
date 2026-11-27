"""MCP adapter: the app's MCP server over stdio, a thin surface over the library."""

import asyncio
from pathlib import Path

from mcp.server.stdio import stdio_server

from modeling_3d import lib


def run_stdio(workspace: Path | None = None) -> None:
    """Serve the MCP server over stdin and stdout until the client disconnects, then stop the app if it was opened.

    Args:
        workspace: The workspace whose models the app shows, as for `lib.app_server`; when omitted, the working
            directory, which is the session's own project.
    """
    asyncio.run(_serve(workspace or Path.cwd()))


async def _serve(workspace: Path) -> None:
    app_server = lib.app_server(workspace)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app_server.server.run(read_stream, write_stream, app_server.server.create_initialization_options())
    finally:
        app_server.close()
