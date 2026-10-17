"""Drives the Claude adapter with the SDK's client faked, so neither credentials nor a model are needed."""

import asyncio
import base64
from collections.abc import AsyncIterable, AsyncIterator, Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("claude_agent_sdk")

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    CLIConnectionError,
    Message,
    ResultMessage,
    SessionKey,
    SystemMessage,
    TextBlock,
    UserMessage,
)

from modeling_3d.intelligence import claude as adapter
from modeling_3d.intelligence import interface
from modeling_3d.intelligence.claude import (
    READ_ONLY_TOOLS,
    WRITE_TOOLS,
    ClaudeIntelligence,
    FolderSessionStore,
    scratch_directory,
)
from modeling_3d.intelligence.schemas import AgentEvent, AgentRequest, HostWorkspace
from modeling_3d.schemas import Modeling3dError

SESSION = "fake-session"
TIMEOUT_SECONDS = 5


def finished(
    text: str | None = "done",
    subtype: str = "success",
    is_error: bool = False,
    errors: list[str] | None = None,
    api_error_status: int | None = None,
    session_id: str = SESSION,
) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=0,
        duration_api_ms=0,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        result=text,
        errors=errors,
        api_error_status=api_error_status,
    )


class FakeClient:
    """Stands in for ClaudeSDKClient: echoes each user message by its uuid, as Claude Code does, then plays a script."""

    def __init__(self, world: "FakeWorld", options: ClaudeAgentOptions) -> None:
        self.world = world
        self.options = options
        self.messages: asyncio.Queue[Message] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.arrived = asyncio.Event()

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass

    async def connect(self) -> None:
        if self.world.connect_error is not None:
            raise self.world.connect_error
        self.messages.put_nowait(SystemMessage(subtype="init", data={"session_id": self.world.session_id}))

    async def disconnect(self) -> None:
        self.world.disconnected += 1

    async def get_server_info(self) -> dict[str, Any]:
        return {"account": self.world.account}

    async def query(self, prompt: AsyncIterable[dict[str, Any]]) -> None:
        async for message in prompt:
            self.sent.append(message)
        self.arrived.set()
        self.arrived = asyncio.Event()
        if len(self.sent) == 1:
            self.world.tasks.append(asyncio.create_task(self.world.script(self)))

    def echo(self, index: int) -> None:
        self.messages.put_nowait(UserMessage(content="echo", uuid=self.sent[index]["uuid"]))

    async def wait_for_message(self, count: int) -> None:
        while len(self.sent) < count:
            await self.arrived.wait()

    async def receive_messages(self) -> AsyncIterator[Message]:
        while True:
            yield await self.messages.get()

    async def interrupt(self) -> None:
        self.world.interrupted += 1


Script = Callable[[FakeClient], Coroutine[Any, Any, None]]


def answers(*results: ResultMessage) -> Script:
    async def script(client: FakeClient) -> None:
        client.echo(0)
        client.messages.put_nowait(AssistantMessage(content=[TextBlock(text="working")], model="fake"))
        for result in results:
            client.messages.put_nowait(result)

    return script


async def never_answers(client: FakeClient) -> None:
    client.echo(0)


class FakeWorld:
    def __init__(self, script: Script, account: dict[str, Any] | None, connect_error: Exception | None) -> None:
        self.script = script
        self.account = account
        self.connect_error = connect_error
        self.session_id = SESSION
        self.clients: list[FakeClient] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.interrupted = 0
        self.disconnected = 0

    def client(self, options: ClaudeAgentOptions) -> FakeClient:
        client = FakeClient(self, options)
        self.clients.append(client)
        return client


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[..., FakeWorld]:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(interface.sys, "platform", "linux")

    def install(
        script: Script | None = None,
        account: dict[str, Any] | None = None,
        connect_error: Exception | None = None,
    ) -> FakeWorld:
        fake = FakeWorld(script or answers(finished()), account, connect_error)
        monkeypatch.setattr(adapter, "ClaudeSDKClient", fake.client)
        return fake

    return install


def request(workspace: Path | None = None, **fields: Any) -> AgentRequest:
    return AgentRequest(
        prompt="Do the work.",
        model="claude-sonnet-5-5",
        workspace=HostWorkspace(path=workspace) if workspace is not None else None,
        reasoning_effort=fields.pop("reasoning_effort", "high"),
        timeout_seconds=fields.pop("timeout_seconds", TIMEOUT_SECONDS),
        **fields,
    )


async def collect(events: AsyncIterator[AgentEvent]) -> list[AgentEvent]:
    return [event async for event in events]


@pytest.mark.parametrize(
    ("writable", "tools"), [(False, READ_ONLY_TOOLS), (True, READ_ONLY_TOOLS + WRITE_TOOLS)], ids=["read", "write"]
)
async def test_a_workspace_run_gets_the_tools_its_access_allows_without_permission_prompts(
    world: Callable[..., FakeWorld], tmp_path: Path, writable: bool, tools: list[str]
) -> None:
    fake = world()

    run = await ClaudeIntelligence().start(request(tmp_path, writable=writable, reasoning_effort="max"))
    result = await run.result()

    assert result.error is None
    assert result.text == "done"
    assert result.session_id == run.session_id == SESSION
    options = fake.clients[0].options
    assert options.cwd == tmp_path.resolve()
    assert options.tools == tools
    assert options.model == "claude-sonnet-5-5"
    assert options.permission_mode == "bypassPermissions"
    assert options.effort == "max"
    assert options.resume is None
    assert options.setting_sources is None
    assert options.session_store is None
    assert options.extra_args == {"replay-user-messages": None}
    assert options.max_buffer_size == adapter.MAX_MESSAGE_BYTES
    assert (fake.interrupted, fake.disconnected) == (0, 1)


async def test_every_message_is_an_event_as_given_and_the_result_comes_last_once(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    world()

    run = await ClaudeIntelligence().start(request(tmp_path))
    events = await collect(run.events())

    assert [event.type for event in events] == [
        "SystemMessage",
        "UserMessage",
        "AssistantMessage",
        "ResultMessage",
        "terminal",
    ]
    assert events[2].data["content"] == [{"text": "working"}]
    assert events[-1].data["text"] == "done"
    assert await collect(run.events()) == events


async def test_a_plain_completion_has_no_tools_and_runs_in_one_stable_scratch_directory_never_the_callers(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world()

    first = await (await ClaudeIntelligence().start(request())).result()
    await (await ClaudeIntelligence().start(request(resume=first.session_id))).result()

    assert [client.options.tools for client in fake.clients] == [[], []]
    assert fake.clients[0].options.cwd == fake.clients[1].options.cwd == scratch_directory()
    assert scratch_directory() == tmp_path / "state" / "modeling-3d" / "claude"
    assert scratch_directory() != Path.cwd().resolve()
    assert scratch_directory().is_dir()
    assert fake.clients[1].options.resume == SESSION


async def test_images_go_with_the_prompt_and_a_session_directory_keeps_a_copy_of_the_session(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world()
    image = tmp_path / "bear.PNG"
    image.write_bytes(b"not really a png")

    run = await ClaudeIntelligence().start(request(tmp_path, images=[image], session_directory=tmp_path / "sessions"))
    await run.result()

    content = fake.clients[0].sent[0]["message"]["content"]
    assert content[0] == {"type": "text", "text": "Do the work."}
    assert content[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(b"not really a png").decode()},
    }
    store = fake.clients[0].options.session_store
    assert isinstance(store, FolderSessionStore)
    assert store.directory == tmp_path / "sessions"
    assert fake.clients[0].options.session_store_flush == "eager"


async def test_a_steering_message_joins_the_session_and_a_result_before_it_is_taken_does_not_end_the_run(
    world: Callable[..., FakeWorld],
) -> None:
    async def script(client: FakeClient) -> None:
        client.echo(0)
        await client.wait_for_message(2)
        client.messages.put_nowait(finished("first turn"))
        client.echo(1)
        client.messages.put_nowait(finished("second turn"))

    fake = world(script)

    run = await ClaudeIntelligence().start(request())
    await run.steer("Also do this.")
    result = await run.result()

    assert result.text == "second turn"
    assert fake.clients[0].sent[1]["message"] == {"role": "user", "content": "Also do this."}
    assert ClaudeIntelligence().steering == "queued"


async def test_steering_an_ended_run_names_the_session_to_resume(world: Callable[..., FakeWorld]) -> None:
    world()

    run = await ClaudeIntelligence().start(request())
    await run.result()

    with pytest.raises(Modeling3dError) as failure:
        await run.steer("Too late.")

    assert SESSION in str(failure.value)


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
async def test_a_stopped_run_is_interrupted_at_once_and_keeps_the_session(
    world: Callable[..., FakeWorld], stop: str
) -> None:
    fake = world(never_answers)

    run = await ClaudeIntelligence().start(request(timeout_seconds=600 if stop == "cancel" else 1))
    if stop == "cancel":
        await asyncio.wait_for(run.cancel(), TIMEOUT_SECONDS)
    result = await run.result()

    assert result.cancelled == (stop == "cancel")
    assert result.error == (None if stop == "cancel" else "The agent did not finish within 1 seconds.")
    assert result.session_id == SESSION
    assert (fake.interrupted, fake.disconnected) == (1, 1)


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (
            finished(subtype="error_during_execution", is_error=True, errors=["The tool failed."]),
            "The tool failed.",
        ),
        (
            finished("API Error: 401 API key is invalid.", is_error=True, api_error_status=401),
            "API Error: 401 API key is invalid.",
        ),
        (finished(None, subtype="error_max_turns", is_error=True), "The run ended error_max_turns."),
    ],
    ids=["errors", "api-error", "subtype-only"],
)
async def test_a_run_that_ended_in_error_carries_why_and_the_session(
    world: Callable[..., FakeWorld], result: ResultMessage, error: str
) -> None:
    world(answers(result))

    outcome = await (await ClaudeIntelligence().start(request())).result()

    assert outcome.error == error
    assert outcome.session_id == SESSION


async def test_a_runtime_failure_is_the_result_not_a_crash(world: Callable[..., FakeWorld]) -> None:
    fake = world(connect_error=CLIConnectionError("Claude Code exited."))

    run = await ClaudeIntelligence().start(request(resume="earlier-session"))
    result = await run.result()

    assert result.error == "CLIConnectionError: Claude Code exited."
    assert result.session_id == "earlier-session"
    assert fake.disconnected == 1
    assert [event.type for event in await collect(run.events())] == ["terminal"]


async def test_the_session_store_keeps_each_transcript_in_its_own_file(tmp_path: Path) -> None:
    store = FolderSessionStore(tmp_path / "sessions")
    main: SessionKey = {"project_key": "anything", "session_id": "one"}
    subagent: SessionKey = {"project_key": "anything", "session_id": "one", "subpath": "subagents/agent-a"}

    await store.append(main, [{"type": "user", "uuid": "a"}])
    await store.append(main, [{"type": "assistant", "uuid": "b"}])
    await store.append(subagent, [{"type": "user", "uuid": "c"}])

    assert await store.load(main) == [{"type": "user", "uuid": "a"}, {"type": "assistant", "uuid": "b"}]
    assert await store.load(subagent) == [{"type": "user", "uuid": "c"}]
    assert await store.load({"project_key": "anything", "session_id": "two"}) is None
    assert [entry["session_id"] for entry in await store.list_sessions("anything")] == ["one"]
    assert await store.list_subkeys({"project_key": "anything", "session_id": "one"}) == ["subagents/agent-a"]
    assert [summary["session_id"] for summary in await store.list_session_summaries("anything")] == ["one"]

    await store.delete(main)

    assert await store.load(main) is None
    assert await store.load(subagent) is None


@pytest.mark.parametrize(
    "account",
    [
        {"tokenSource": "none", "apiKeySource": "ANTHROPIC_API_KEY", "apiProvider": "firstParty"},
        {"apiProvider": "bedrock"},
        {"email": "user@example.com", "subscriptionType": "Claude Max", "apiProvider": "firstParty"},
    ],
    ids=["api-key", "cloud-provider", "subscription"],
)
def test_preflight_passes_with_an_api_key_or_a_cloud_provider(
    world: Callable[..., FakeWorld], account: dict[str, Any]
) -> None:
    world(account=account)

    ClaudeIntelligence().preflight()


def test_preflight_names_every_documented_way_to_authenticate_when_there_are_no_credentials(
    world: Callable[..., FakeWorld],
) -> None:
    world(account={"tokenSource": "none", "apiProvider": "firstParty"})

    with pytest.raises(Modeling3dError) as failure:
        ClaudeIntelligence().preflight()

    message = str(failure.value)
    assert "no credentials" in message
    assert "ANTHROPIC_API_KEY" in message
    assert "CLAUDE_CODE_USE_BEDROCK" in message
    assert adapter.AUTHENTICATION_DOCUMENTATION in message


def test_preflight_names_the_runtime_when_it_cannot_start(
    world: Callable[..., FakeWorld], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Unstartable:
        def __init__(self, options: ClaudeAgentOptions) -> None:
            pass

        async def __aenter__(self) -> None:
            raise FileNotFoundError("claude")

        async def __aexit__(self, *exc: object) -> None:
            pass

    monkeypatch.setattr(adapter, "ClaudeSDKClient", Unstartable)

    with pytest.raises(Modeling3dError) as failure:
        ClaudeIntelligence().preflight()

    message = str(failure.value)
    assert "did not start" in message
    assert "FileNotFoundError" in message
    assert "[claude]" in message
