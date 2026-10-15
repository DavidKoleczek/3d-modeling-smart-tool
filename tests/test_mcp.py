"""The MCP adapter on the wire, spoken to over stdio the way Claude Code speaks to a channel."""

from collections.abc import Callable, Iterator
import json
import queue
import subprocess
import sys
import threading
from typing import Any

import pytest
from websockets.sync.client import connect
from websockets.typing import Origin

from modeling_3d.adapters.mcp import CHANNEL_CAPABILITY, CHANNEL_NOTIFICATION

TIMEOUT_SECONDS = 10
# Claude Code asks stdio servers for this revision, and does not register a channel that accepts it.
UNREGISTRABLE_REVISION = "2026-07-28"


class Wire:
    """One `modeling-3d mcp` process, spoken to in newline-delimited JSON-RPC."""

    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "modeling_3d.cli", "mcp"],
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

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.next_id += 1
        request_id = self.next_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return self.receive(lambda message: message.get("id") == request_id)

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": UNREGISTRABLE_REVISION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        )["result"]
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})["result"]

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
    return result["content"][0]["text"]


def test_it_registers_as_a_channel_on_a_revision_claude_code_accepts(wire: Wire) -> None:
    initialized = wire.initialize()

    assert initialized["protocolVersion"] != UNREGISTRABLE_REVISION
    assert initialized["capabilities"]["experimental"] == {CHANNEL_CAPABILITY: {}}


def test_messages_flow_between_the_app_and_the_session(wire: Wire) -> None:
    wire.initialize()
    url = text_of(wire.call_tool("open_app", {}))

    assert text_of(wire.call_tool("open_app", {})) == url
    with connect(url.replace("http://", "ws://") + "/ws", origin=Origin(url)) as page:
        page.send("make a cube")
        notification = wire.receive(lambda message: message.get("method") == CHANNEL_NOTIFICATION)
        page.recv(timeout=TIMEOUT_SECONDS)

        assert notification["params"] == {"content": "make a cube"}
        assert text_of(wire.call_tool("reply", {"text": "a cube it is"})) == "sent"
        assert json.loads(page.recv(timeout=TIMEOUT_SECONDS)) == {"from": "agent", "text": "a cube it is"}


def test_reply_before_open_app_is_a_tool_error_naming_the_fix(wire: Wire) -> None:
    wire.initialize()
    result = wire.call_tool("reply", {"text": "hello"})

    assert result["isError"]
    assert "open_app" in text_of(result)


def test_it_exits_cleanly_when_the_client_disconnects(wire: Wire) -> None:
    wire.initialize()
    wire.call_tool("open_app", {})

    assert wire.close() == 0
