"""An agent faked by a script, so neither credentials nor a model are needed to run a model's request, and the runs a
model's record keeps, written directly."""

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model.record import load_record
from modeling_3d.intelligence.schemas import AgentEvent, AgentRequest, AgentResult, Steering
from modeling_3d.schemas import (
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_REASONING_EFFORT,
    ModelEvent,
    Modeling3dError,
    ModelRecord,
    ModelRunRecord,
)

SESSION = "fake-session"
FOLLOW_UPS = 5


class FakeRun:
    """An agent run whose work is a script, which a cancel stops at once."""

    def __init__(self, request: AgentRequest, script: "Script", follows_up: bool = False) -> None:
        self.request = request
        self.session_id: str | None = request.resume or SESSION
        self.follows_up = follows_up
        self.followed_up: list[str] = []
        self.steered: list[str] = []
        self.steered_images: list[list[Path]] = []
        self.steer_arrived = asyncio.Event()
        self._events: list[AgentEvent] = []
        self._appended = asyncio.Event()
        self._cancelled = asyncio.Event()
        self._task = asyncio.create_task(self._drive(script))

    def emit(self, kind: str, data: dict[str, Any] | None = None) -> None:
        self._events.append(AgentEvent(type=kind, data=data or {}))
        self._appended.set()
        self._appended = asyncio.Event()

    def events(self) -> AsyncIterator[AgentEvent]:
        return self._replay()

    async def steer(self, message: str, images: list[Path] | None = None) -> None:
        self.steered.append(message)
        self.steered_images.append(images or [])
        self.steer_arrived.set()

    async def cancel(self) -> None:
        self._cancelled.set()
        await asyncio.wait([self._task])

    async def result(self) -> AgentResult:
        return await asyncio.shield(self._task)

    async def _replay(self) -> AsyncIterator[AgentEvent]:
        index = 0
        while True:
            appended = self._appended
            while index < len(self._events):
                event = self._events[index]
                index += 1
                yield event
                if event.type == "terminal":
                    return
            await appended.wait()

    async def _drive(self, script: "Script") -> AgentResult:
        work = asyncio.create_task(script(self))
        cancelled = asyncio.create_task(self._cancelled.wait())
        await asyncio.wait([work, cancelled], return_when=asyncio.FIRST_COMPLETED)
        if work.done():
            result = work.result()
        else:
            work.cancel()
            result = AgentResult(cancelled=True, session_id=self.session_id)
        cancelled.cancel()
        # As a provider does each time its agent ends a turn, up to a few, which only a follow up that never stops
        # would reach.
        follow_up = self.request.follow_up
        while self.follows_up and follow_up is not None and result.error is None and not result.cancelled:
            message = await follow_up()
            if message is None or len(self.followed_up) == FOLLOW_UPS:
                break
            self.followed_up.append(message)
        self.emit("terminal", result.model_dump(mode="json"))
        return result


Script = Callable[[FakeRun], Coroutine[Any, Any, AgentResult]]


class FakeIntelligence:
    def __init__(self, script: Script, follows_up: bool = False) -> None:
        self.implementation = "fake"
        self.steering: Steering = "queued"
        self.script = script
        self.follows_up = follows_up
        self.runs: list[FakeRun] = []

    def preflight(self) -> None:
        pass

    async def start(self, request: AgentRequest) -> FakeRun:
        run = FakeRun(request, self.script, self.follows_up)
        self.runs.append(run)
        return run


class Refusing(FakeIntelligence):
    async def start(self, request: AgentRequest) -> FakeRun:
        raise Modeling3dError("This agent provider cannot run agents.")


def build(run: FakeRun) -> None:
    assert run.request.session_directory is not None
    model = run.request.session_directory.parent
    (model / "model.py").write_text("# the bear", encoding="utf-8")
    (model / "model.glb").write_bytes(b"glTF")
    (model / "renders").mkdir(exist_ok=True)
    (model / "renders" / "front.png").write_bytes(b"png")


async def builds(run: FakeRun) -> AgentResult:
    run.emit("AssistantMessage", {"content": [{"text": "Building."}]})
    build(run)
    return AgentResult(text="A bear.", session_id=run.session_id)


async def builds_nothing(run: FakeRun) -> AgentResult:
    return AgentResult(text="I could not.", session_id=run.session_id)


async def fails(run: FakeRun) -> AgentResult:
    return AgentResult(error="The API refused.", session_id=run.session_id)


async def waits_for_steering(run: FakeRun) -> AgentResult:
    await run.steer_arrived.wait()
    build(run)
    return AgentResult(text=f"Did: {run.steered[0]}", session_id=run.session_id)


async def works_forever(run: FakeRun) -> AgentResult:
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


def run_record(**fields: Any) -> ModelRunRecord:
    """A run that ended done, as runs.json keeps it, with any of its fields given in place of these."""
    agent_provider = fields.get("agent_provider", "claude")
    defaults = {
        "id": "run",
        "prompt": "A bear",
        "resumed": False,
        "agent_provider": agent_provider,
        "model": DEFAULT_INTELLIGENCE_MODELS[agent_provider],
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
        "status": "done",
        "pid": 1,
        "started": datetime.now(UTC),
    }
    return ModelRunRecord.model_validate({**defaults, **fields})


async def collect(events: AsyncIterator[AgentEvent]) -> list[AgentEvent]:
    return [event async for event in events]


async def run_to_end(
    script: Script = builds, prompt: str = "A low poly bear", **arguments: Any
) -> tuple[ModelEvent, lib.ModelRun, FakeIntelligence, list[ModelEvent]]:
    intelligence = FakeIntelligence(script)
    run = await lib.create_3d_model(prompt, intelligence=intelligence, **arguments)
    events = [event async for event in run.events()]
    return events[-1], run, intelligence, events


def record_of(directory: Path) -> ModelRecord:
    return load_record(directory)
