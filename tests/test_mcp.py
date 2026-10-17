"""The MCP adapter on the wire, spoken to over stdio the way Claude Code and MCP Apps hosts speak to it."""

import asyncio
from collections.abc import Callable, Iterator
import json
from multiprocessing.connection import Listener
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
from typing import Any
import uuid

from mcp import Client
from mcp.client.context import ClientRequestContext
from mcp.client.stdio import StdioServerParameters
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
from mcp.types import ElicitRequestParams, ElicitRequestURLParams, ElicitResult, TextContent
import pytest

from modeling_3d import lib
from modeling_3d.adapters.inbox import SOCKET_VARIABLE, TOKEN_VARIABLE
from modeling_3d.capabilities.app.mcp_server import VIEW_URI

TIMEOUT_SECONDS = 10
# What Claude Code 2.1 asks for in `initialize`.
PROTOCOL_VERSION = "2025-11-25"
MCP_APPS_HOST = {"extensions": {EXTENSION_ID: {"mimeTypes": [APP_MIME_TYPE]}}}
TOKEN = "test-token"


class FakeInbox:
    """A Claude Code session inbox: a named pipe on Windows, a Unix socket elsewhere. Collects what is posted."""

    def __init__(self) -> None:
        self.posts: queue.Queue[list[dict[str, Any]]] = queue.Queue()
        if sys.platform == "win32":
            self.address = rf"\\.\pipe\modeling-3d-test-{uuid.uuid4().hex}"
            listener = Listener(self.address, family="AF_PIPE")
            threading.Thread(target=self._accept_pipe, args=(listener,), daemon=True).start()
        else:
            # Unix socket paths are capped near 100 bytes, which pytest's tmp_path can pass on macOS.
            self.address = str(Path(tempfile.mkdtemp(dir="/tmp")) / "inbox.sock")
            server = socket.socket(socket.AF_UNIX)
            server.bind(self.address)
            server.listen()
            threading.Thread(target=self._accept_socket, args=(server,), daemon=True).start()

    def _accept_pipe(self, listener: Listener) -> None:
        while True:
            with listener.accept() as connection:
                self._collect(connection.recv_bytes())

    def _accept_socket(self, server: socket.socket) -> None:
        while True:
            connection, _ = server.accept()
            with connection, connection.makefile("rb") as stream:
                self._collect(stream.read())

    def _collect(self, payload: bytes) -> None:
        self.posts.put([json.loads(line) for line in payload.decode("utf-8").splitlines()])


def server_environment(inbox: FakeInbox | None = None) -> dict[str, str]:
    # Run inside Claude Code, the tests inherit its session's inbox, and must never post into it.
    environment = {name: value for name, value in os.environ.items() if name not in (SOCKET_VARIABLE, TOKEN_VARIABLE)}
    if inbox is not None:
        environment |= {SOCKET_VARIABLE: inbox.address, TOKEN_VARIABLE: TOKEN}
    return environment


class Wire:
    """One `modeling-3d mcp` process, spoken to in newline-delimited JSON-RPC on the initialize handshake."""

    def __init__(self, inbox: FakeInbox | None = None, arguments: list[str] | None = None) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "modeling_3d.cli", "mcp", *(arguments or [])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=server_environment(inbox),
        )
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.messages.put(json.loads(line))

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def receive(self, matches: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        while True:
            message = self.messages.get(timeout=TIMEOUT_SECONDS)
            if matches(message):
                return message

    def start_request(self, method: str, params: dict[str, Any]) -> int:
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        return self.next_id

    def response(self, request_id: int) -> dict[str, Any]:
        return self.receive(lambda message: message.get("id") == request_id and "method" not in message)

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return self.response(self.start_request(method, params))["result"]

    def initialize(self, capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": capabilities or {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> int:
        assert self.process.stdin is not None
        self.process.stdin.close()
        return self.process.wait(timeout=TIMEOUT_SECONDS)


@pytest.fixture
def inbox() -> FakeInbox:
    return FakeInbox()


@pytest.fixture
def wire() -> Iterator[Wire]:
    server = Wire()
    yield server
    if server.process.poll() is None:
        server.process.kill()


@pytest.fixture
def wire_with_inbox(inbox: FakeInbox) -> Iterator[Wire]:
    server = Wire(inbox)
    yield server
    if server.process.poll() is None:
        server.process.kill()


def text_of(result: dict[str, Any]) -> str:
    return "\n".join(block["text"] for block in result["content"])


def message_from_the_browser(url: str, text: str) -> str:
    """Hand over `text` the way the browser host page does with the view's `ui/message`, over the app's own `/mcp`."""

    async def hand_over() -> str:
        async with Client(f"{url}/mcp") as client:
            result = (await client.call_tool("app_message", {"text": text})).content[0]
        assert isinstance(result, TextContent)
        return result.text

    return asyncio.run(hand_over())


def test_a_client_without_mcp_apps_sees_only_the_model_tools(wire: Wire) -> None:
    wire.initialize()
    tools = {tool["name"]: tool for tool in wire.request("tools/list", {})["tools"]}

    assert set(tools) == {"open_app", "reply"}
    assert tools["open_app"]["_meta"] == {"ui": {"resourceUri": VIEW_URI}}
    assert wire.request("resources/list", {})["resources"] == []
    assert wire.request("resources/templates/list", {})["resourceTemplates"] == []


def test_an_mcp_apps_host_gets_the_view_its_app_only_tools_and_the_model_files(wire: Wire) -> None:
    wire.initialize(MCP_APPS_HOST)
    tools = {tool["name"]: tool for tool in wire.request("tools/list", {})["tools"]}
    resources = wire.request("resources/list", {})["resources"]
    templates = wire.request("resources/templates/list", {})["resourceTemplates"]
    contents = wire.request("resources/read", {"uri": VIEW_URI})["contents"]

    app_only = ("app_updates", "app_message", "list_3d_models", "view_3d_model")
    assert set(tools) == {"open_app", "reply", *app_only}
    assert all(tools[name]["_meta"]["ui"]["visibility"] == ["app"] for name in app_only)
    assert [resource["uri"] for resource in resources] == [VIEW_URI]
    assert [template["uriTemplate"] for template in templates] == ["modeling-3d://models/{name}/{+path}"]
    assert contents == [{"uri": VIEW_URI, "mimeType": APP_MIME_TYPE, "text": lib.app_view()}]


def test_the_app_shows_the_directory_it_was_started_on_until_open_app_names_another(tmp_path: Path) -> None:
    (tmp_path / "first").mkdir()
    (tmp_path / "file").write_text("", encoding="utf-8")
    wire = Wire(arguments=["--directory", str(tmp_path / "first")])
    try:
        wire.initialize(MCP_APPS_HOST)
        started = wire.call_tool("list_3d_models", {})["structuredContent"]["directory"]
        opened = text_of(wire.call_tool("open_app", {"directory": str(tmp_path / "second")}))
        switched = wire.call_tool("list_3d_models", {})["structuredContent"]["directory"]
        refused = wire.call_tool("open_app", {"directory": str(tmp_path / "file")})
        kept = wire.call_tool("list_3d_models", {})["structuredContent"]["directory"]
    finally:
        wire.close()

    assert started == str((tmp_path / "first").resolve())
    assert f"It shows the models in {tmp_path / 'second'}." in opened
    assert switched == kept == str((tmp_path / "second").resolve())
    assert refused["isError"]
    assert "is a file, not a directory of models" in text_of(refused)


def test_the_view_in_an_mcp_apps_host_hears_the_agent(wire: Wire) -> None:
    wire.initialize(MCP_APPS_HOST)

    assert "inline" in text_of(wire.call_tool("open_app", {}))
    wire.call_tool("reply", {"text": "a cube it is"})
    assert wire.call_tool("app_updates", {"after": 0})["structuredContent"] == {"messages": ["a cube it is"]}


def test_a_message_from_the_browser_reaches_the_session_inbox(wire_with_inbox: Wire, inbox: FakeInbox) -> None:
    wire_with_inbox.initialize()
    url = text_of(wire_with_inbox.call_tool("open_app", {})).split("URL to open the app: ")[1].split()[0]

    assert text_of(wire_with_inbox.call_tool("open_app", {})).count(url) == 1
    assert message_from_the_browser(url, "make the legs longer") == "delivered to the agent"
    auth, posted = inbox.posts.get(timeout=TIMEOUT_SECONDS)

    assert auth == {"type": "auth", "token": TOKEN}
    assert posted["type"] == "user"
    assert posted["message"]["content"].endswith("\n\nmake the legs longer")
    assert "Modeling 3D app" in posted["message"]["content"]


def test_without_an_inbox_a_message_comes_back_with_the_next_tool_result(wire: Wire) -> None:
    wire.initialize()
    url = text_of(wire.call_tool("open_app", {})).split("URL to open the app: ")[1].split()[0]
    message_from_the_browser(url, "make the legs longer")

    assert "make the legs longer" in text_of(wire.call_tool("reply", {"text": "on it"}))
    assert "make the legs longer" not in text_of(wire.call_tool("reply", {"text": "done"}))


# "auto" lands on 2026-07-28, where the question rides back on the result and the client retries; "legacy" is the
# initialize handshake, where the server asks mid-call. Claude Code speaks the first.
@pytest.mark.parametrize(("mode", "era"), [("auto", "2026-07-28"), ("legacy", PROTOCOL_VERSION)])
async def test_open_app_asks_the_client_to_open_it_in_the_browser(mode: str, era: str) -> None:
    asked: list[ElicitRequestURLParams] = []

    async def open_it(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestURLParams)
        asked.append(params)
        return ElicitResult(action="accept")

    server = StdioServerParameters(
        command=sys.executable, args=["-m", "modeling_3d.cli", "mcp"], env=server_environment()
    )
    async with Client(server, mode=mode, elicitation_callback=open_it) as client:
        opened = (await client.call_tool("open_app", {})).content[0]
        again = (await client.call_tool("open_app", {})).content[0]
        negotiated = client.protocol_version

    assert negotiated == era
    assert isinstance(opened, TextContent)
    assert isinstance(again, TextContent)
    assert len(asked) == 1
    assert f"The user opened the app at {asked[0].url}." in opened.text
    assert f"Give the user this URL to open the app: {asked[0].url}" in again.text


def test_reply_before_open_app_is_a_tool_error_naming_the_fix(wire: Wire) -> None:
    wire.initialize()
    result = wire.call_tool("reply", {"text": "hello"})

    assert result["isError"]
    assert "open_app" in text_of(result)


def test_it_exits_cleanly_when_the_client_disconnects(wire: Wire) -> None:
    wire.initialize()
    wire.call_tool("open_app", {})

    assert wire.close() == 0
