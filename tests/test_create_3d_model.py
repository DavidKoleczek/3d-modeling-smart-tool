"""Drives create-3d-model with the agent faked by a script, so neither credentials nor a model are needed."""

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model import create
from modeling_3d.cli import app
from modeling_3d.intelligence import interface
from modeling_3d.intelligence.schemas import AgentEvent, AgentRequest, AgentResult, Steering
from modeling_3d.schemas import ModelEvent, Modeling3dError, ModelRecord

SESSION = "fake-session"
TIMEOUT_SECONDS = 5

runner = CliRunner()


class FakeRun:
    """An agent run whose work is a script, which a cancel stops at once."""

    def __init__(self, request: AgentRequest, script: "Script") -> None:
        self.request = request
        self.session_id: str | None = request.resume or SESSION
        self.steered: list[str] = []
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

    async def steer(self, message: str) -> None:
        self.steered.append(message)
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
        self.emit("terminal", result.model_dump(mode="json"))
        return result


Script = Callable[[FakeRun], Coroutine[Any, Any, AgentResult]]


class FakeIntelligence:
    def __init__(self, script: Script) -> None:
        self.implementation = "fake"
        self.steering: Steering = "queued"
        self.script = script
        self.runs: list[FakeRun] = []

    def preflight(self) -> None:
        pass

    async def start(self, request: AgentRequest) -> FakeRun:
        run = FakeRun(request, self.script)
        self.runs.append(run)
        return run


class Refusing(FakeIntelligence):
    async def start(self, request: AgentRequest) -> FakeRun:
        raise Modeling3dError("This agent provider cannot run agents.")


def build(run: FakeRun) -> None:
    assert run.request.workspace is not None
    model = run.request.workspace.path
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


@pytest.fixture(autouse=True)
def working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(create, "POLL_SECONDS", 0.01)
    return tmp_path


async def run_to_end(
    script: Script = builds, prompt: str = "A low poly bear", **arguments: Any
) -> tuple[ModelEvent, lib.ModelRun, FakeIntelligence, list[ModelEvent]]:
    intelligence = FakeIntelligence(script)
    run = await lib.create_3d_model(prompt, intelligence=intelligence, **arguments)
    events = [event async for event in run.events()]
    return events[-1], run, intelligence, events


def record_of(directory: Path) -> ModelRecord:
    return ModelRecord.model_validate_json((directory / "model.json").read_text(encoding="utf-8"))


async def test_a_new_model_is_built_and_recorded_in_its_own_directory(working_directory: Path) -> None:
    last, run, intelligence, events = await run_to_end(name="bear")
    result = await run.result()

    directory = working_directory / ".modeling-3d" / "bear"
    assert result.status == "done"
    assert result.directory == directory == run.directory
    assert result.text == "A bear."
    assert result.session_id == SESSION
    assert result.files == ["model.py", "model.glb", "renders/front.png"]
    assert result.next == 'modeling-3d create-3d-model "<what to change>" --name bear --resume'
    assert [event.kind for event in events] == ["started", "agent", "finished"]
    assert events[1].text == "AssistantMessage"
    assert last.data["status"] == "done"
    request = intelligence.runs[0].request
    assert request.workspace is not None
    assert request.workspace.path == directory
    assert request.writable
    assert request.session_directory == directory / "sessions"
    assert request.resume is None
    assert request.model == "claude-sonnet-5-5"
    assert request.reasoning_effort == "medium"
    assert request.timeout_seconds == 3600 + create.AGENT_TIMEOUT_GRACE_SECONDS
    assert "A low poly bear" in request.prompt
    assert create.BPY_REQUIREMENT in request.prompt
    assert str(directory) in request.prompt
    assert "already holds" not in request.prompt
    record = record_of(directory)
    assert (record.tool, record.name) == ("modeling-3d", "bear")
    [entry] = record.runs
    assert (entry.id, entry.status, entry.session_id, entry.pid) == (run.run_id, "done", SESSION, os.getpid())
    assert entry.agent_provider == "claude"
    assert entry.finished is not None
    assert entry.last_event == events[-1].time
    lines = (directory / "runs" / run.run_id / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [ModelEvent.model_validate_json(line) for line in lines] == events


async def test_another_directory_holds_the_models_when_named(working_directory: Path) -> None:
    _, run, _, _ = await run_to_end(name="bear", directory=Path("models"))

    assert run.directory == working_directory / "models" / "bear"
    assert (await run.result()).next.endswith(f"--directory {working_directory / 'models'}")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"name": "bear"}, "A model named 'bear' already exists"),
        ({"name": "BEAR"}, "A model named 'bear' already exists"),
        ({"name": "notes"}, "already exists and is not a model"),
        ({"name": "notes", "edit": True}, "is not a model made by modeling-3d"),
        ({"name": "Bear", "edit": True}, "There is no model named 'Bear'"),
        ({"name": "fox", "resume": True}, "There is no model named 'fox'"),
        ({"name": "../escape"}, "cannot name a model"),
        ({"name": "a b"}, "cannot name a model"),
        ({"name": ""}, "cannot name a model"),
        ({"name": "fox", "references": [Path("nope.png")]}, "nope.png is not a file"),
        ({"name": "quiet", "resume": True}, "no session to resume"),
        ({"name": "elsewhere", "resume": True, "agent_provider": "claude"}, "ran on codex, and claude was asked for"),
    ],
)
async def test_a_request_that_cannot_run_is_refused_before_anything_starts(
    working_directory: Path, arguments: dict[str, Any], message: str
) -> None:
    for name, change in [("bear", None), ("quiet", {"session_id": None}), ("elsewhere", {"agent_provider": "codex"})]:
        _, built, _, _ = await run_to_end(name=name)
        if change is not None:
            record = record_of(built.directory)
            record.runs[0] = record.runs[0].model_copy(update=change)
            (built.directory / "model.json").write_text(record.model_dump_json(), encoding="utf-8")
    (working_directory / ".modeling-3d" / "notes").mkdir()
    intelligence = FakeIntelligence(builds)

    with pytest.raises(Modeling3dError) as failure:
        await lib.create_3d_model("Another bear", intelligence=intelligence, **arguments)

    assert message in str(failure.value)
    assert intelligence.runs == []
    assert not (working_directory / ".modeling-3d" / "fox").exists()
    assert len(record_of(working_directory / ".modeling-3d" / "bear").runs) == 1


async def test_references_are_copied_shown_with_the_prompt_and_never_overwrite_another(
    working_directory: Path,
) -> None:
    image = working_directory / "bear.png"
    image.write_bytes(b"first")
    mesh = working_directory / "old.glb"
    mesh.write_bytes(b"glTF")

    _, run, intelligence, _ = await run_to_end(name="bear", references=[image, mesh])
    image.write_bytes(b"second")
    await run_to_end(name="bear", edit=True, references=[image, image])

    request = intelligence.runs[0].request
    references = run.directory / "references"
    assert request.images == [references / "bear.png"]
    assert "references/bear.png (also attached)" in request.prompt
    assert "references/old.glb\n" in request.prompt
    assert (references / "old.glb").read_bytes() == b"glTF"
    assert (references / "bear.png").read_bytes() == b"first"
    assert (references / "bear-2.png").read_bytes() == b"second"
    assert [entry.references for entry in record_of(run.directory).runs] == [
        ["references/bear.png", "references/old.glb"],
        ["references/bear-2.png", "references/bear-2.png"],
    ]


async def test_an_edit_reads_model_py_in_a_fresh_session_and_a_resume_continues_the_last_one() -> None:
    _, first, _, _ = await run_to_end(name="bear")

    _, edited, editing, _ = await run_to_end(prompt="Make the snout longer", name="bear", edit=True)
    _, _, resuming, _ = await run_to_end(prompt="And the ears rounder", name="bear", resume=True)

    edit = editing.runs[0].request
    resume = resuming.runs[0].request
    assert edited.directory == first.directory
    assert edit.resume is None
    assert "Make the snout longer" in edit.prompt
    assert "Read model.py first" in edit.prompt
    assert resume.resume == SESSION
    assert resume.prompt.strip() == "And the ears rounder"
    assert [entry.resumed for entry in record_of(first.directory).runs] == [False, False, True]


async def test_a_model_already_being_worked_on_is_not_started_twice() -> None:
    run = await lib.create_3d_model("A bear", name="bear", intelligence=FakeIntelligence(works_forever))

    with pytest.raises(Modeling3dError) as failure:
        await lib.create_3d_model("Another", name="bear", edit=True, intelligence=FakeIntelligence(builds))

    assert "cancel-3d-model --name bear" in str(failure.value)
    await run.cancel()


async def test_a_crashed_run_is_marked_failed_and_its_session_resumed() -> None:
    _, run, _, _ = await run_to_end(name="bear")
    record = record_of(run.directory)
    record.runs[0].status = "running"
    record.runs[0].pid = 2**22 + 7
    (run.directory / "model.json").write_text(record.model_dump_json(), encoding="utf-8")

    _, resumed, intelligence, _ = await run_to_end(prompt="Go on", name="bear", resume=True)

    assert intelligence.runs[0].request.resume == SESSION
    assert [entry.status for entry in record_of(resumed.directory).runs] == ["failed", "done"]


@pytest.mark.parametrize(
    ("script", "message"),
    [(builds_nothing, "without leaving model.py or model.glb"), (fails, "The API refused.")],
    ids=["no-model", "agent-error"],
)
async def test_a_failed_run_says_why_and_how_to_go_on(script: Script, message: str) -> None:
    last, run, _, _ = await run_to_end(script, name="bear")
    result = await run.result()

    assert result.status == "failed"
    assert result.error is not None
    assert message in result.error
    assert ("events.jsonl" if script is fails else result.next) in result.error
    assert last.kind == "failed"
    assert record_of(run.directory).runs[0].status == "failed"


async def test_a_refused_start_leaves_no_new_model_behind(working_directory: Path) -> None:
    with pytest.raises(Modeling3dError):
        await lib.create_3d_model("A bear", name="bear", intelligence=Refusing(builds))

    assert not (working_directory / ".modeling-3d" / "bear").exists()


@pytest.mark.parametrize("sender", ["handle", "another-process"])
async def test_steering_reaches_the_agent_and_shows_as_an_event(sender: str) -> None:
    run = await lib.create_3d_model("A bear", name="bear", intelligence=FakeIntelligence(waits_for_steering))

    if sender == "handle":
        await run.steer("Rounder ears.")
    else:
        await asyncio.to_thread(lib.steer_3d_model, "bear", "Rounder ears.")
    result = await asyncio.wait_for(run.result(), TIMEOUT_SECONDS)

    assert result.text == "Did: Rounder ears."
    assert ("steered", "Rounder ears.") in [(event.kind, event.text) async for event in run.events()]
    assert not list((run.directory / "runs" / run.run_id / "steer").iterdir())


async def test_cancel_from_another_process_stops_the_run_and_keeps_the_session() -> None:
    run = await lib.create_3d_model("A bear", name="bear", intelligence=FakeIntelligence(works_forever))

    await asyncio.to_thread(lib.cancel_3d_model, "bear")
    result = await asyncio.wait_for(run.result(), TIMEOUT_SECONDS)

    assert result.status == "cancelled"
    assert result.session_id == SESSION
    assert record_of(run.directory).runs[0].status == "cancelled"
    assert [event.kind async for event in run.events()][-1] == "finished"


async def test_a_run_past_its_timeout_is_stopped_and_says_how_to_go_on() -> None:
    last, run, _, _ = await run_to_end(works_forever, name="bear", timeout_seconds=1)
    result = await run.result()

    assert result.status == "timed-out"
    assert result.error is not None
    assert result.next in result.error
    assert last.kind == "failed"


async def test_steering_or_cancelling_a_model_nothing_works_on_names_what_to_do_instead() -> None:
    await run_to_end(name="bear")

    with pytest.raises(Modeling3dError) as steering:
        lib.steer_3d_model("bear", "More.")
    with pytest.raises(Modeling3dError) as cancelling:
        lib.cancel_3d_model("bear")
    with pytest.raises(Modeling3dError) as missing:
        lib.cancel_3d_model("fox")

    assert "not being worked on" in str(steering.value)
    assert "--name bear --resume" in str(steering.value)
    assert "its last run ended done" in str(cancelling.value)
    assert "no model named 'fox'" in str(missing.value)
    assert "bear" in str(missing.value)


def test_the_cli_prints_each_event_as_a_json_line_and_exits_0_when_done(
    monkeypatch: pytest.MonkeyPatch, working_directory: Path
) -> None:
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(builds))
    image = working_directory / "bear.png"
    image.write_bytes(b"png")

    result = runner.invoke(app, ["create-3d-model", "A low poly bear", "--name", "bear", "--reference", "bear.png"])

    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in result.stdout.splitlines()]
    assert [line["kind"] for line in lines] == ["started", "agent", "finished"]
    assert lines[-1]["data"]["status"] == "done"
    assert (working_directory / ".modeling-3d" / "bear" / "references" / "bear.png").is_file()


def test_the_cli_exits_2_without_a_name_and_1_when_the_model_is_not_done(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(builds_nothing))

    nameless = runner.invoke(app, ["create-3d-model", "A low poly bear"])
    unfinished = runner.invoke(app, ["create-3d-model", "A low poly bear", "--name", "bear"])

    assert nameless.exit_code == 2
    assert "--name" in nameless.output
    assert unfinished.exit_code == 1
    assert json.loads(unfinished.stdout.splitlines()[-1])["kind"] == "failed"
