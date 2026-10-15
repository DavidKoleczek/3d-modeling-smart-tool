"""App: a chat page on this machine where a person and an agent talk, served from a background thread."""

import asyncio
from collections.abc import Callable
import contextlib
import json
from pathlib import Path
import socket
import threading

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
import uvicorn

from modeling_3d.schemas import Modeling3dError

PAGE = Path(__file__).parent / "static" / "index.html"
HOST = "127.0.0.1"
STOP_TIMEOUT_SECONDS = 5


class App:
    """The app being served: where to open it, and how to show the agent's messages on it."""

    def __init__(
        self,
        url: str,
        server: uvicorn.Server,
        loop: asyncio.AbstractEventLoop,
        thread: threading.Thread,
        pages: set[WebSocket],
    ) -> None:
        self.url = url
        self._server = server
        self._loop = loop
        self._thread = thread
        self._pages = pages

    def send(self, text: str) -> int:
        """Show `text` as the agent's on every open page and return how many are open. Safe to call from any thread."""
        asyncio.run_coroutine_threadsafe(_broadcast(self._pages, "agent", text), self._loop)
        return len(self._pages)

    def stop(self) -> None:
        """Disconnect every page and stop serving."""
        self._server.should_exit = True
        self._thread.join(STOP_TIMEOUT_SECONDS)


def serve_app(on_message: Callable[[str], None] | None = None, port: int | None = None) -> App:
    """Serve the app from a daemon thread and return it once the port is listening."""
    # Bound and listening before this returns, so the URL answers at once and a held port is a named failure.
    sock = _bind(port)
    bound_port = int(sock.getsockname()[1])
    url = f"http://{HOST}:{bound_port}"
    pages: set[WebSocket] = set()
    api = _create_api({url, f"http://localhost:{bound_port}"}, pages, on_message)
    # Without a log config uvicorn leaves logging alone. Its default one writes access lines to stdout, which the MCP
    # adapter needs for MCP messages alone.
    server = uvicorn.Server(uvicorn.Config(api, log_config=None, log_level="warning", lifespan="off"))
    loop = asyncio.new_event_loop()

    def run() -> None:
        try:
            loop.run_until_complete(server.serve(sockets=[sock]))
        finally:
            loop.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return App(url, server, loop, thread, pages)


def _create_api(origins: set[str], pages: set[WebSocket], on_message: Callable[[str], None] | None) -> FastAPI:
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.get("/", include_in_schema=False)
    def page() -> FileResponse:
        return FileResponse(PAGE)

    @api.websocket("/ws")
    async def connect(websocket: WebSocket) -> None:
        # Browsers let any website open a WebSocket to this machine, so only the app's own page may type into it.
        if websocket.headers.get("origin") not in origins:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        pages.add(websocket)
        try:
            async for raw in websocket.iter_text():
                text = raw.strip()
                if not text:
                    continue
                await _broadcast(pages, "you", text)
                if on_message is not None:
                    on_message(text)
        finally:
            pages.discard(websocket)

    return api


async def _broadcast(pages: set[WebSocket], sender: str, text: str) -> None:
    message = json.dumps({"from": sender, "text": text})
    for page in list(pages):
        # A page that closed while this was sending is dropped by its own handler.
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await page.send_text(message)


def _bind(port: int | None) -> socket.socket:
    # SO_REUSEADDR stays off: on Windows it lets a second app bind a port the first still holds.
    sock = socket.socket(socket.AF_INET)
    try:
        sock.bind((HOST, port or 0))
    except OSError as error:
        sock.close()
        raise Modeling3dError(
            f"The app could not bind {HOST}:{port}: {error.strerror or error}. "
            "Omit the port to have a free one chosen, or pass one nothing else holds."
        ) from error
    sock.listen()
    return sock
