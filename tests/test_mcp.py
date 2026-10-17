"""The MCP adapter on the wire, spoken to over stdio the way Claude Code and MCP Apps hosts speak to it."""

from collections.abc import Callable, Iterator
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
from typing import Any

from mcp import Client
from mcp.client.context import ClientRequestContext
from mcp.client.stdio import StdioServerParameters
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
from mcp.types import ElicitRequestParams, ElicitRequestURLParams, ElicitResult, TextContent
import pytest

from modeling_3d import lib
from modeling_3d.capabilities.app.mcp_server import VIEW_URI

TIMEOUT_SECONDS = 10
# What Claude Code 2.1 asks for in `initialize`.
PROTOCOL_VERSION = "2025-11-25"
MCP_APPS_HOST = {"extensions": {EXTENSION_ID: {"mimeTypes": [APP_MIME_TYPE]}}}
VIEW_TOOLS = (
    "list_3d_models",
    "view_3d_model",
    "create_3d_model",
    "steer_3d_model",
    "cancel_3d_model",
    "read_3d_model_activity",
    "list_intelligence_models",
    "choose_intelligence_model",
)


class Wire:
    """One `modeling-3d mcp` process, spoken to in newline-delimited JSON-RPC on the initialize handshake."""

    def __init__(self, arguments: list[str] | None = None) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "modeling_3d.cli", "mcp", *(arguments or [])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
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
def wire() -> Iterator[Wire]:
    server = Wire()
    yield server
    if server.process.poll() is None:
        server.process.kill()


def text_of(result: dict[str, Any]) -> str:
    return "\n".join(block["text"] for block in result["content"])


def test_a_client_without_mcp_apps_sees_only_open_app(wire: Wire) -> None:
    initialized = wire.initialize()
    tools = {tool["name"]: tool for tool in wire.request("tools/list", {})["tools"]}

    assert set(tools) == {"open_app"}
    assert tools["open_app"]["_meta"] == {"ui": {"resourceUri": VIEW_URI}}
    assert "read-3d-model-activity" in initialized["instructions"]
    assert wire.request("resources/list", {})["resources"] == []
    assert wire.request("resources/templates/list", {})["resourceTemplates"] == []


def test_an_mcp_apps_host_gets_the_view_the_tools_it_calls_and_the_model_files(wire: Wire) -> None:
    wire.initialize(MCP_APPS_HOST)
    tools = {tool["name"]: tool for tool in wire.request("tools/list", {})["tools"]}
    resources = wire.request("resources/list", {})["resources"]
    templates = wire.request("resources/templates/list", {})["resourceTemplates"]
    contents = wire.request("resources/read", {"uri": VIEW_URI})["contents"]

    assert set(tools) == {"open_app", *VIEW_TOOLS}
    assert all(tools[name]["_meta"]["ui"]["visibility"] == ["app"] for name in VIEW_TOOLS)
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


@pytest.mark.parametrize(("capabilities", "where"), [(MCP_APPS_HOST, "inline"), (None, "URL to open the app: ")])
def test_open_app_says_the_user_acts_in_the_app_and_how_the_session_sees_it(
    wire: Wire, capabilities: dict[str, Any] | None, where: str
) -> None:
    wire.initialize(capabilities)
    opened = text_of(wire.call_tool("open_app", {}))

    assert where in opened
    assert "Nothing they do there is sent to you" in opened
    assert "modeling-3d read-3d-model-activity --name <name>" in opened


# "auto" lands on 2026-07-28, where the question rides back on the result and the client retries; "legacy" is the
# initialize handshake, where the server asks mid-call. Claude Code speaks the first.
@pytest.mark.parametrize(("mode", "era"), [("auto", "2026-07-28"), ("legacy", PROTOCOL_VERSION)])
async def test_open_app_asks_the_client_to_open_it_in_the_browser(mode: str, era: str) -> None:
    asked: list[ElicitRequestURLParams] = []

    async def open_it(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestURLParams)
        asked.append(params)
        return ElicitResult(action="accept")

    server = StdioServerParameters(command=sys.executable, args=["-m", "modeling_3d.cli", "mcp"])
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


def test_it_exits_cleanly_when_the_client_disconnects(wire: Wire) -> None:
    wire.initialize()
    wire.call_tool("open_app", {})

    assert wire.close() == 0
