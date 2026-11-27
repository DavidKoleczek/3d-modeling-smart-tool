"""The Windows app's settings, updates, agent providers, and Agent Skill, through the app's tools, with a stand-in for
the app by the clock."""

from collections.abc import Iterator
import json
import os
import socket
import threading
from typing import Any

from mcp import Client
from mcp.types import TextContent
import pytest

from modeling_3d import lib
from modeling_3d.capabilities.app import windows_app

TOKEN = "0f1e2d3c4b5a"
STATE = {"version": "0.5.0", "update": None, "updating": False, "start_at_sign_in": False, "skill": None}
TOOLS = [
    "read_windows_app",
    "change_windows_app",
    "check_for_update",
    "install_update",
    "install_agent_provider",
    "list_skill_agents",
    "install_skill",
    "remove_skill",
]
# What each tool needs to be called at all.
ARGUMENTS: dict[str, dict[str, Any]] = {
    "install_agent_provider": {"agent_provider": "codex"},
    "install_skill": {"agents": [], "mode": "symlink"},
}
AGENTS = {
    "home": "C:\\Users\\me",
    "shared": "C:\\Users\\me\\.agents\\skills",
    "agents": [
        {"id": "codex", "name": "Codex", "folder": "C:\\Users\\me\\.agents\\skills", "shares": True, "detected": True},
        {
            "id": "claude-code",
            "name": "Claude Code",
            "folder": "C:\\Users\\me\\.claude\\skills",
            "shares": False,
            "detected": True,
        },
    ],
    "installed": ["codex"],
}


class StandIn:
    """Listens as the Windows app does, keeps what it was asked, and answers with `answer`."""

    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []
        self.answer: Any = {"ok": True, "state": STATE}
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port = int(self._listener.getsockname()[1])
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self._listener.accept()
            except OSError:
                return
            with connection, connection.makefile("rwb") as lines:
                self.asked.append(json.loads(lines.readline()))
                answer = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
                lines.write(answer.encode() + b"\n")

    def close(self) -> None:
        self._listener.close()


@pytest.fixture
def stand_in(monkeypatch: pytest.MonkeyPatch) -> Iterator[StandIn]:
    """A stand-in for the Windows app, told to the next app server made, as the Windows app tells the one it starts."""
    app = StandIn()
    monkeypatch.setenv(windows_app.PORT_VARIABLE, str(app.port))
    monkeypatch.setenv(windows_app.TOKEN_VARIABLE, TOKEN)
    yield app
    app.close()


async def call(client: Client, tool: str, **arguments: Any) -> Any:
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def refused(client: Client, tool: str, **arguments: Any) -> tuple[str, Any]:
    result = await client.call_tool(tool, arguments)
    assert result.is_error
    message = result.content[0]
    assert isinstance(message, TextContent)
    reason = (result.structured_content or {}).get("reason")
    return message.text, reason


async def test_a_server_started_any_other_way_has_no_windows_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(windows_app.PORT_VARIABLE, raising=False)
    monkeypatch.delenv(windows_app.TOKEN_VARIABLE, raising=False)
    async with Client(lib.app_server().server) as client:
        assert await call(client, "read_windows_app") == {"windows_app": None}
        for tool in TOOLS[1:]:
            message, reason = await refused(client, tool, **ARGUMENTS.get(tool, {}))
            assert "isn't what started this server" in message
            assert reason == "no-windows-app"


async def test_nothing_the_server_starts_inherits_where_the_windows_app_listens(stand_in: StandIn) -> None:
    app_server = lib.app_server()
    assert windows_app.PORT_VARIABLE not in os.environ
    assert windows_app.TOKEN_VARIABLE not in os.environ
    # The server still reaches it, from what it took.
    async with Client(app_server.server) as client:
        assert await call(client, "read_windows_app") == {"windows_app": STATE}
    assert stand_in.asked == [{"token": TOKEN, "do": "state"}]


@pytest.mark.parametrize(("port", "token"), [("", TOKEN), ("8790", ""), ("not a port", TOKEN)])
def test_half_an_address_is_none(monkeypatch: pytest.MonkeyPatch, port: str, token: str) -> None:
    monkeypatch.setenv(windows_app.PORT_VARIABLE, port)
    monkeypatch.setenv(windows_app.TOKEN_VARIABLE, token)
    assert windows_app.take_address() is None
    assert windows_app.PORT_VARIABLE not in os.environ


async def test_the_windows_app_is_read_and_changed_with_its_token(stand_in: StandIn) -> None:
    async with Client(lib.app_server().server) as client:
        assert await call(client, "read_windows_app") == {"windows_app": STATE}

        stand_in.answer = {"ok": True, "state": {**STATE, "start_at_sign_in": True}}
        assert (await call(client, "change_windows_app", start_at_sign_in=True))["start_at_sign_in"] is True
        await call(client, "change_windows_app")

        stand_in.answer = {"ok": True, "state": {**STATE, "update": "0.6.0"}}
        assert (await call(client, "check_for_update"))["update"] == "0.6.0"
        stand_in.answer = {"ok": True, "state": {**STATE, "update": "0.6.0", "updating": True}}
        assert (await call(client, "install_update"))["updating"] is True
        stand_in.answer = {"ok": True, "state": STATE}
        assert await call(client, "install_agent_provider", agent_provider="codex") == STATE

    # A setting that isn't given isn't sent, so the Windows app leaves it as it is.
    assert stand_in.asked == [
        {"token": TOKEN, "do": "state"},
        {"token": TOKEN, "do": "set", "start_at_sign_in": True},
        {"token": TOKEN, "do": "set"},
        {"token": TOKEN, "do": "check_for_update"},
        {"token": TOKEN, "do": "install_update"},
        {"token": TOKEN, "do": "install_agent_provider", "agent_provider": "codex"},
    ]


async def test_the_agent_skill_is_installed_for_the_agents_listed(stand_in: StandIn) -> None:
    async with Client(lib.app_server().server) as client:
        stand_in.answer = {"ok": True, "agents": AGENTS}
        assert await call(client, "list_skill_agents") == AGENTS

        skill = {"agents": ["Claude Code", "Codex"], "mode": "copy"}
        stand_in.answer = {"ok": True, "state": {**STATE, "skill": skill}}
        assert (await call(client, "install_skill", agents=["claude-code"], mode="copy"))["skill"] == skill
        stand_in.answer = {"ok": True, "state": STATE}
        assert (await call(client, "remove_skill"))["skill"] is None

    assert stand_in.asked == [
        {"token": TOKEN, "do": "list_agents"},
        {"token": TOKEN, "do": "install_skill", "agents": ["claude-code"], "mode": "copy"},
        {"token": TOKEN, "do": "remove_skill"},
    ]


async def test_a_list_of_agents_that_cant_be_read_is_said(stand_in: StandIn) -> None:
    stand_in.answer = {"ok": True, "agents": {"agents": "all"}}
    async with Client(lib.app_server().server) as client:
        message, _ = await refused(client, "list_skill_agents")
        assert "couldn't be read" in message


async def test_what_the_windows_app_cant_do_is_said_in_its_words(stand_in: StandIn) -> None:
    stand_in.answer = {"ok": False, "error": "Codex is installed already."}
    async with Client(lib.app_server().server) as client:
        message, reason = await refused(client, "install_agent_provider", agent_provider="codex")
        assert (message, reason) == ("Codex is installed already.", None)


@pytest.mark.parametrize("answer", ["", "not json", "[]", '{"ok": true}', '{"ok": true, "state": {"version": 1}}'])
async def test_an_answer_that_isnt_the_windows_apps_is_said(stand_in: StandIn, answer: str) -> None:
    stand_in.answer = answer
    async with Client(lib.app_server().server) as client:
        message, _ = await refused(client, "read_windows_app")
        assert "couldn't be read" in message


async def test_a_windows_app_that_is_gone_is_said(stand_in: StandIn) -> None:
    stand_in.close()
    async with Client(lib.app_server().server) as client:
        message, _ = await refused(client, "check_for_update")
        assert "didn't answer" in message
