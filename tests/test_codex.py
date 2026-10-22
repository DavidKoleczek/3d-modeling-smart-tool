"""Drives the Codex adapter with the SDK's client faked, so neither a Codex sign-in nor a model is needed."""

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("openai_codex")

from openai_codex import ApprovalMode, InvalidRequestError, LocalImageInput, Sandbox, TextInput
from openai_codex.models import (
    ItemCompletedNotification,
    Notification,
    ThreadTokenUsageUpdatedNotification,
    UnknownNotification,
)
from openai_codex.types import GetAccountResponse, TurnCompletedNotification

from modeling_3d.intelligence import codex as adapter
from modeling_3d.intelligence import interface
from modeling_3d.intelligence.codex import CodexIntelligence, scratch_directory
from modeling_3d.intelligence.schemas import AgentEvent, AgentRequest, HostWorkspace
from modeling_3d.schemas import Modeling3dError

THREAD = "fake-thread"
TIMEOUT_SECONDS = 5


def said(text: str) -> Notification:
    item = {"id": f"message-{text}", "type": "agentMessage", "text": text, "phase": "final_answer"}
    payload = {"threadId": THREAD, "turnId": "turn", "completedAtMs": 0, "item": item}
    return Notification("item/completed", ItemCompletedNotification.model_validate(payload))


def used(tokens: int) -> Notification:
    breakdown = {
        "cachedInputTokens": 0,
        "inputTokens": tokens,
        "outputTokens": 0,
        "reasoningOutputTokens": 0,
        "totalTokens": tokens,
    }
    payload = {"threadId": THREAD, "turnId": "turn", "tokenUsage": {"last": breakdown, "total": breakdown}}
    return Notification("thread/tokenUsage/updated", ThreadTokenUsageUpdatedNotification.model_validate(payload))


def completed(status: str = "completed", error: str | None = None) -> Notification:
    turn: dict[str, Any] = {"id": "turn", "items": [], "itemsView": "summary", "status": status}
    if error is not None:
        turn["error"] = {"message": error}
    payload = TurnCompletedNotification.model_validate({"threadId": THREAD, "turn": turn})
    return Notification("turn/completed", payload)


class FakeTurn:
    """Stands in for AsyncTurnHandle: streams what its script puts, takes steering until it completes."""

    def __init__(self, world: "FakeWorld", input: Any, effort: Any, summary: Any) -> None:
        self.world = world
        self.input = input
        self.effort = effort
        self.summary = summary
        self.notifications: asyncio.Queue[Notification] = asyncio.Queue()
        self.steered: list[Any] = []
        self.done = False

    def put(self, notification: Notification) -> None:
        if notification.method == "turn/completed":
            self.done = True
        self.notifications.put_nowait(notification)

    async def stream(self) -> AsyncIterator[Notification]:
        while True:
            notification = await self.notifications.get()
            yield notification
            if notification.method == "turn/completed":
                return

    async def steer(self, input: Any) -> None:
        if self.done:
            raise InvalidRequestError(-32600, "no active turn to steer")
        self.steered.append(input)

    async def interrupt(self) -> None:
        self.world.interrupted += 1
        if not self.done:
            self.put(completed("interrupted"))


class FakeThread:
    def __init__(self, world: "FakeWorld") -> None:
        self.world = world
        self.id = THREAD

    async def turn(self, input: Any, effort: Any = None, summary: Any = None) -> FakeTurn:
        turn = FakeTurn(self.world, input, effort, summary)
        script = self.world.scripts[min(len(self.world.turns), len(self.world.scripts) - 1)]
        self.world.turns.append(turn)
        self.world.tasks.append(asyncio.create_task(script(turn)))
        return turn

    async def read(self) -> SimpleNamespace:
        return SimpleNamespace(thread=SimpleNamespace(path=self.world.rollout))


Script = Callable[[FakeTurn], Coroutine[Any, Any, None]]


def answers(text: str = "done", status: str = "completed", error: str | None = None) -> Script:
    async def script(turn: FakeTurn) -> None:
        turn.put(Notification("item/agentMessage/delta", UnknownNotification({"delta": text})))
        turn.put(used(10))
        turn.put(said(text))
        turn.put(used(20))
        turn.put(completed(status, error))

    return script


async def never_answers(turn: FakeTurn) -> None:
    pass


class FakeWorld:
    """Stands in for AsyncCodex: hands out one thread, and answers the account question."""

    def __init__(self, scripts: list[Script], account: GetAccountResponse | None, rollout: Path | None) -> None:
        self.scripts = scripts
        self.account = account
        self.rollout = None if rollout is None else str(rollout)
        self.started: list[dict[str, Any]] = []
        self.resumed: list[tuple[str, dict[str, Any]]] = []
        self.turns: list[FakeTurn] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.start_error: Exception | None = None
        self.interrupted = 0
        self.closed = 0

    def codex(self) -> Any:
        world = self

        class Codex:
            async def __aenter__(self) -> "Codex":
                return self

            async def __aexit__(self, *exc: object) -> None:
                pass

            async def account(self) -> GetAccountResponse | None:
                return world.account

            async def thread_start(self, **settings: Any) -> FakeThread:
                if world.start_error is not None:
                    raise world.start_error
                world.started.append(settings)
                return FakeThread(world)

            async def thread_resume(self, thread_id: str, **settings: Any) -> FakeThread:
                world.resumed.append((thread_id, settings))
                return FakeThread(world)

            async def close(self) -> None:
                world.closed += 1

        return Codex()


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[..., FakeWorld]:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(interface.sys, "platform", "linux")

    def install(*scripts: Script, account: GetAccountResponse | None = None, rollout: Path | None = None) -> FakeWorld:
        fake = FakeWorld(list(scripts) or [answers()], account, rollout)
        monkeypatch.setattr(adapter, "AsyncCodex", fake.codex)
        return fake

    return install


def request(workspace: Path | None = None, **fields: Any) -> AgentRequest:
    return AgentRequest(
        prompt="Do the work.",
        model=fields.pop("model", "gpt-6.1-sol"),
        workspace=HostWorkspace(path=workspace) if workspace is not None else None,
        reasoning_effort=fields.pop("reasoning_effort", "high"),
        timeout_seconds=fields.pop("timeout_seconds", TIMEOUT_SECONDS),
        **fields,
    )


async def collect(events: AsyncIterator[AgentEvent]) -> list[AgentEvent]:
    return [event async for event in events]


@pytest.mark.parametrize(
    ("writable", "sandbox"), [(False, Sandbox.read_only), (True, Sandbox.full_access)], ids=["read", "write"]
)
async def test_a_workspace_run_gets_the_access_it_asks_for_without_approval_prompts(
    world: Callable[..., FakeWorld], tmp_path: Path, writable: bool, sandbox: Sandbox
) -> None:
    fake = world()

    run = await CodexIntelligence().start(request(tmp_path, writable=writable, reasoning_effort="ultra"))
    result = await run.result()

    assert result.error is None
    assert result.text == "done"
    assert result.session_id == run.session_id == THREAD
    settings = fake.started[0]
    assert settings["cwd"] == str(tmp_path.resolve())
    assert settings["model"] == "gpt-6.1-sol"
    assert settings["sandbox"] == sandbox
    assert settings["approval_mode"] == ApprovalMode.deny_all
    assert settings["config"] == {"model_reasoning_summary": "detailed"}
    turn = fake.turns[0]
    assert turn.effort.value == "ultra"
    assert turn.summary.root.value == "detailed"
    assert fake.closed == 1


async def test_images_go_with_the_prompt(world: Callable[..., FakeWorld], tmp_path: Path) -> None:
    fake = world()
    image = tmp_path / "front.png"

    run = await CodexIntelligence().start(request(tmp_path, images=[image]))
    await run.result()

    assert fake.turns[0].input == [TextInput("Do the work."), LocalImageInput(str(image))]


async def test_a_plain_completion_runs_read_only_in_one_scratch_directory(world: Callable[..., FakeWorld]) -> None:
    fake = world()

    run = await CodexIntelligence().start(request())
    await run.result()

    assert fake.started[0]["cwd"] == str(scratch_directory())
    assert fake.started[0]["sandbox"] == Sandbox.read_only
    assert scratch_directory().is_dir()


async def test_resuming_continues_the_thread_with_the_model_asked_for(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world()

    run = await CodexIntelligence().start(request(tmp_path, resume=THREAD, model="gpt-6-astra"))
    result = await run.result()

    assert fake.started == []
    assert fake.resumed[0][0] == THREAD
    assert fake.resumed[0][1]["model"] == "gpt-6-astra"
    assert result.session_id == THREAD


async def test_events_keep_what_codex_said_without_its_deltas_and_one_token_count_a_turn(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    world()

    run = await CodexIntelligence().start(request(tmp_path))
    events = await collect(run.events())

    assert [event.type for event in events] == [
        "item/completed",
        "thread/tokenUsage/updated",
        "turn/completed",
        "terminal",
    ]
    assert events[0].data["item"]["text"] == "done"
    assert events[1].data["tokenUsage"]["total"]["totalTokens"] == 20
    assert events[-1].data["text"] == "done"


async def test_steering_lands_in_the_turn_under_way(world: Callable[..., FakeWorld], tmp_path: Path) -> None:
    fake = world(never_answers)

    image = tmp_path / "marked.png"

    run = await CodexIntelligence().start(request(tmp_path))
    await run.steer("Make the legs longer.")
    await run.steer("And this one.", [image])
    fake.turns[0].put(completed())
    await run.result()

    assert fake.turns[0].steered == [
        [TextInput("Make the legs longer.")],
        [TextInput("And this one."), LocalImageInput(str(image))],
    ]
    assert len(fake.turns) == 1


async def test_steering_that_arrives_as_the_turn_ends_goes_on_in_a_turn_of_its_own(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    release = asyncio.Event()

    async def ends_then_waits(turn: FakeTurn) -> None:
        turn.done = True
        await release.wait()
        turn.put(said("first"))
        turn.put(completed())

    fake = world(ends_then_waits, answers("second"))

    run = await CodexIntelligence().start(request(tmp_path))
    await run.steer("Also add a hat.")
    release.set()
    result = await run.result()

    assert fake.turns[0].steered == []
    assert fake.turns[1].input == [TextInput("Also add a hat.")]
    assert result.text == "second"


async def test_steering_after_the_run_ended_names_the_session_to_resume(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    world()

    run = await CodexIntelligence().start(request(tmp_path))
    await run.result()

    with pytest.raises(Modeling3dError) as failure:
        await run.steer("Too late.")

    assert THREAD in str(failure.value)


async def test_cancelling_interrupts_the_turn_and_closes_the_runtime(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(never_answers)

    run = await CodexIntelligence().start(request(tmp_path))
    await run.cancel()
    result = await run.result()

    assert result.cancelled
    assert result.session_id == THREAD
    assert fake.interrupted == 1
    assert fake.closed == 1


async def test_a_run_that_outlasts_its_timeout_ends_in_an_error(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(never_answers)

    run = await CodexIntelligence().start(request(tmp_path, timeout_seconds=1))
    result = await run.result()

    assert result.error == "The agent did not finish within 1 seconds."
    assert fake.interrupted == 1


async def test_a_failed_turn_ends_in_the_runtimes_own_words(world: Callable[..., FakeWorld], tmp_path: Path) -> None:
    world(answers(status="failed", error="The model is overloaded."))

    run = await CodexIntelligence().start(request(tmp_path))
    result = await run.result()

    assert result.error == "The model is overloaded."
    assert result.text == "done"


async def test_a_runtime_that_fails_to_start_a_thread_ends_the_run_in_an_error(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world()
    fake.start_error = RuntimeError("no runtime")

    run = await CodexIntelligence().start(request(tmp_path))
    result = await run.result()

    assert result.error == "RuntimeError: no runtime"
    assert [event.type for event in await collect(run.events())] == ["terminal"]


async def test_the_session_is_copied_where_the_request_keeps_it(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text('{"type":"session_meta"}\n', encoding="utf-8")
    world(rollout=rollout)
    sessions = tmp_path / "model" / "sessions"

    run = await CodexIntelligence().start(request(tmp_path, session_directory=sessions))
    await run.result()

    assert (sessions / f"{THREAD}.jsonl").read_text(encoding="utf-8") == '{"type":"session_meta"}\n'


@pytest.mark.parametrize(
    "account",
    [
        GetAccountResponse.model_validate(
            {
                "account": {"type": "chatgpt", "email": "user@example.com", "planType": "plus"},
                "requiresOpenaiAuth": True,
            }
        ),
        GetAccountResponse.model_validate({"account": None, "requiresOpenaiAuth": False}),
    ],
    ids=["signed-in", "custom-provider"],
)
def test_preflight_passes_when_signed_in_or_when_the_provider_needs_no_openai_sign_in(
    world: Callable[..., FakeWorld], account: GetAccountResponse
) -> None:
    world(account=account)

    CodexIntelligence().preflight()


def test_preflight_names_both_ways_to_sign_in_when_codex_is_not_signed_in(world: Callable[..., FakeWorld]) -> None:
    world(account=GetAccountResponse.model_validate({"account": None, "requiresOpenaiAuth": True}))

    with pytest.raises(Modeling3dError) as failure:
        CodexIntelligence().preflight()

    message = str(failure.value)
    assert "not signed in" in message
    assert "codex login" in message
    assert adapter.SIGN_IN_DOCUMENTATION in message


def test_preflight_names_the_runtime_when_it_cannot_start(monkeypatch: pytest.MonkeyPatch) -> None:
    class Unstartable:
        async def __aenter__(self) -> None:
            raise FileNotFoundError("codex")

        async def __aexit__(self, *exc: object) -> None:
            pass

    monkeypatch.setattr(adapter, "AsyncCodex", Unstartable)

    with pytest.raises(Modeling3dError) as failure:
        CodexIntelligence().preflight()

    message = str(failure.value)
    assert "did not start" in message
    assert "FileNotFoundError" in message
    assert "[codex]" in message
