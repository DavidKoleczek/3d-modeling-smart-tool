"""Drives create-3d-model with the agent faked by a script, so neither credentials nor a model are needed."""

import asyncio
from collections.abc import Callable
import json
import os
from pathlib import Path
import time
from typing import Any

import detached_agent
from fakes import (
    SESSION,
    FakeIntelligence,
    Refusing,
    Script,
    builds,
    builds_nothing,
    fails,
    waits_for_steering,
    works_forever,
)
import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model import create
from modeling_3d.capabilities.create_3d_model.record import alive, read_atomically
from modeling_3d.cli import app
from modeling_3d.intelligence import interface
from modeling_3d.schemas import ModelEvent, Modeling3dError, ModelRecord, ModelRunRecord

TIMEOUT_SECONDS = 5
# A detached run starts a Python process of its own, which takes a while to import the library.
DETACHED_TIMEOUT_SECONDS = 30

runner = CliRunner()


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


@pytest.fixture
def detached(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Have detached runs fake their agent with the named script from fakes.py."""

    def use(script: str) -> None:
        monkeypatch.setattr(create, "BACKGROUND_COMMAND", detached_agent.command(script))

    return use


def record_of(directory: Path) -> ModelRecord:
    # A detached run writes it from another process, which Windows refuses a read of in the moment of replacing it.
    return ModelRecord.model_validate_json(read_atomically(directory / "model.json"))


def ended(directory: Path) -> ModelRunRecord:
    """The model's last run once its process has finished it."""
    deadline = time.monotonic() + DETACHED_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        run = record_of(directory).runs[-1]
        if run.status != "running" and not alive(run.pid):
            return run
        time.sleep(0.05)
    raise AssertionError(f"The run in {directory} did not end.")


def events_of(directory: Path, run_id: str) -> list[ModelEvent]:
    lines = (directory / "runs" / run_id / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [ModelEvent.model_validate_json(line) for line in lines]


async def test_a_new_model_is_built_and_recorded_in_its_own_directory(working_directory: Path) -> None:
    last, run, intelligence, events = await run_to_end(name="bear")
    result = await run.result()

    directory = working_directory / ".modeling-3d" / "bear"
    assert result.status == "done"
    assert result.directory == directory == run.directory
    assert result.text == "A bear."
    assert result.session_id == SESSION
    assert result.files == ["model.py", "model.glb", "renders/front.png"]
    assert result.next == 'modeling-3d create-3d-model "<what to change>" --name bear --resume-session true'
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
    ("arguments", "message", "reason"),
    [
        ({"name": "notes"}, "already exists and is not a model", "name-in-use"),
        ({"name": "NOTES"}, "already exists and is not a model", "name-in-use"),
        ({"name": "../escape"}, "cannot name a model", "invalid-name"),
        ({"name": "a b"}, "cannot name a model", "invalid-name"),
        ({"name": ""}, "cannot name a model", "invalid-name"),
        ({"name": "fox", "references": [Path("nope.png")]}, "nope.png is not a file", "missing-reference"),
        (
            {"name": "elsewhere", "agent_provider": "claude", "resume_session": True},
            "ran on codex, and claude was asked for",
            "provider-mismatch",
        ),
        ({"name": "bear", "resume_session": "gone"}, "has no session 'gone'. Its sessions", "no-such-session"),
        ({"name": "fox", "resume_session": "gone"}, "Model fox has no session 'gone'", "no-such-session"),
    ],
)
async def test_a_request_that_cannot_run_is_refused_before_anything_starts(
    working_directory: Path, arguments: dict[str, Any], message: str, reason: str | None
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
    assert failure.value.reason == reason
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
    await run_to_end(name="bear", references=[image, image])

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


async def test_another_model_s_files_are_references_like_any_other() -> None:
    _, bear, _, _ = await run_to_end(name="bear")
    files = [bear.directory / "model.py", bear.directory / "model.glb", bear.directory / "renders" / "front.png"]

    _, cub, intelligence, _ = await run_to_end(prompt="A cub like the bear", name="cub", references=files)

    copied = cub.directory / "references"
    assert record_of(cub.directory).runs[0].references == [
        "references/model.py",
        "references/model.glb",
        "references/front.png",
    ]
    assert (copied / "model.py").read_text(encoding="utf-8") == "# the bear"
    assert intelligence.runs[0].request.images == [copied / "front.png"]


async def test_who_asked_is_kept_with_the_run_and_its_started_event() -> None:
    _, run, _, events = await run_to_end(name="bear", origin="claude-code:abc")

    assert record_of(run.directory).runs[0].origin == "claude-code:abc"
    started = events[0].data
    assert (started["prompt"], started["origin"], started["resumed"]) == ("A low poly bear", "claude-code:abc", False)
    assert (started["agent_provider"], started["references"]) == ("claude", [])


async def test_a_name_a_model_has_changes_it_in_a_fresh_session_unless_told_to_resume_one() -> None:
    _, first, creating, _ = await run_to_end(name="bear")

    _, changed, refreshing, _ = await run_to_end(prompt="Make the snout longer", name="Bear")
    _, _, resuming, _ = await run_to_end(prompt="And the ears rounder", name="bear", resume_session=True)

    fresh = refreshing.runs[0].request
    resume = resuming.runs[0].request
    assert "already holds" not in creating.runs[0].request.prompt
    assert changed.directory == first.directory
    assert changed.name == "bear"
    assert fresh.resume is None
    assert "Make the snout longer" in fresh.prompt
    assert "Read model.py first" in fresh.prompt
    assert resume.resume == SESSION
    assert resume.prompt.strip() == "And the ears rounder"
    assert [entry.resumed for entry in record_of(first.directory).runs] == [False, False, True]


async def test_a_session_named_by_its_id_is_the_one_continued() -> None:
    _, first, _, _ = await run_to_end(name="bear")
    await run_to_end(prompt="Make the snout longer", name="bear", resume_session=False)
    record = record_of(first.directory)
    record.runs[0].session_id, record.runs[1].session_id = "first-session", "second-session"
    (first.directory / "model.json").write_text(record.model_dump_json(), encoding="utf-8")

    _, _, named, _ = await run_to_end(prompt="Back to how it was", name="bear", resume_session="first-session")
    _, _, latest, _ = await run_to_end(prompt="And then", name="bear", resume_session=True)

    assert named.runs[0].request.resume == "first-session"
    assert latest.runs[0].request.resume == "first-session"


async def test_a_model_without_a_session_changes_in_a_fresh_one() -> None:
    _, first, _, _ = await run_to_end(name="bear")
    record = record_of(first.directory)
    record.runs[0].session_id = None
    (first.directory / "model.json").write_text(record.model_dump_json(), encoding="utf-8")

    _, _, intelligence, _ = await run_to_end(prompt="Make the snout longer", name="bear", resume_session=True)

    assert intelligence.runs[0].request.resume is None
    assert "Read model.py first" in intelligence.runs[0].request.prompt
    assert record_of(first.directory).runs[-1].resumed is False


async def test_a_model_already_being_worked_on_is_not_started_twice() -> None:
    run = await lib.create_3d_model("A bear", name="bear", intelligence=FakeIntelligence(works_forever))

    with pytest.raises(Modeling3dError) as failure:
        await lib.create_3d_model("Another", name="bear", intelligence=FakeIntelligence(builds))

    assert "cancel-3d-model --name bear" in str(failure.value)
    await run.cancel()


async def test_a_crashed_run_is_marked_failed_and_its_session_resumed() -> None:
    _, run, _, _ = await run_to_end(name="bear")
    record = record_of(run.directory)
    record.runs[0].status = "running"
    record.runs[0].pid = 2**22 + 7
    (run.directory / "model.json").write_text(record.model_dump_json(), encoding="utf-8")

    _, resumed, intelligence, _ = await run_to_end(prompt="Go on", name="bear", resume_session=True)

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


@pytest.mark.parametrize(("sender", "origin"), [("handle", "claude-code:abc"), ("another-process", "app")])
async def test_steering_reaches_the_agent_and_shows_as_an_event_from_its_sender(sender: str, origin: str) -> None:
    run = await lib.create_3d_model(
        "A bear", name="bear", origin="claude-code:abc", intelligence=FakeIntelligence(waits_for_steering)
    )

    if sender == "handle":
        await run.steer("Rounder ears.")
    else:
        await asyncio.to_thread(lib.steer_3d_model, "bear", "Rounder ears.", None, "app")
    result = await asyncio.wait_for(run.result(), TIMEOUT_SECONDS)

    assert result.text == "Did: Rounder ears."
    steered = [(event.kind, event.text, event.data.get("origin")) async for event in run.events()]
    assert ("steered", "Rounder ears.", origin) in steered
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
    assert 'create-3d-model "<what to change>" --name bear' in str(steering.value)
    assert (steering.value.reason, steering.value.model) == ("not-running", "bear")
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


async def test_a_detached_run_goes_on_in_its_own_process_and_its_handle_follows_it(
    detached: Callable[[str], None],
) -> None:
    detached("waits_for_steering")

    run = await lib.create_3d_model("A bear", name="bear", origin="app", detach=True)
    entry = record_of(run.directory).runs[0]
    await run.steer("Rounder ears.")
    result = await asyncio.wait_for(run.result(), DETACHED_TIMEOUT_SECONDS)
    events = [event async for event in run.events()]

    assert entry.pid != os.getpid()
    assert entry.origin == "app"
    assert (result.status, result.text, result.session_id) == ("done", "Did: Rounder ears.", SESSION)
    assert [event.kind for event in events] == ["started", "steered", "finished"]
    assert events[1].data["origin"] == "app"
    assert run.session_id == SESSION
    assert (run.directory / "runs" / run.run_id / create.PROCESS_LOG).is_file()


async def test_a_detached_run_outlives_its_handle_and_stops_when_its_handle_cancels(
    detached: Callable[[str], None],
) -> None:
    detached("waits_for_steering")
    run = await lib.create_3d_model("A bear", name="bear", detach=True)
    directory = run.directory
    del run

    await asyncio.to_thread(lib.steer_3d_model, "bear", "Rounder ears.")
    finished = await asyncio.to_thread(ended, directory)
    detached("works_forever")
    again = await lib.create_3d_model("Go on", name="bear", resume_session=True, detach=True)
    await asyncio.wait_for(again.cancel(), DETACHED_TIMEOUT_SECONDS)

    assert finished.status == "done"
    assert (await again.result()).status == "cancelled"
    assert record_of(directory).runs[-1].resumed


async def test_a_detached_request_that_cannot_run_raises_what_stopped_it(detached: Callable[[str], None]) -> None:
    await run_to_end(name="bear")
    detached("builds")

    with pytest.raises(Modeling3dError, match="has no session 'gone'") as taken:
        await lib.create_3d_model("Another bear", name="bear", resume_session="gone", detach=True)
    with pytest.raises(Modeling3dError, match="cannot reach"):
        await lib.create_3d_model("A fox", name="fox", detach=True, intelligence=FakeIntelligence(builds))

    assert (taken.value.reason, taken.value.model) == ("no-such-session", "bear")


def test_the_cli_detached_prints_the_started_event_and_exits_0_with_the_session_as_origin(
    monkeypatch: pytest.MonkeyPatch, detached: Callable[[str], None], working_directory: Path
) -> None:
    detached("waits_for_steering")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc")

    started = runner.invoke(app, ["create-3d-model", "A low poly bear", "--name", "bear", "--detach"])
    steered = runner.invoke(app, ["steer-3d-model", "--name", "bear", "--message", "Rounder ears."])
    directory = working_directory / ".modeling-3d" / "bear"
    run = ended(directory)

    assert started.exit_code == steered.exit_code == 0, started.output + steered.output
    [line] = [json.loads(line) for line in started.stdout.splitlines()]
    assert (line["kind"], line["data"]["origin"]) == ("started", "claude-code:abc")
    assert run.status == "done"
    steerings = [event.data["origin"] for event in events_of(directory, run.id) if event.kind == "steered"]
    assert steerings == ["claude-code:abc"]


def test_the_cli_starts_a_fresh_session_unless_given_true_or_a_session_id(
    monkeypatch: pytest.MonkeyPatch, working_directory: Path
) -> None:
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(builds))
    runner.invoke(app, ["create-3d-model", "A bear", "--name", "bear"])

    fresh = runner.invoke(app, ["create-3d-model", "Taller", "--name", "bear"])
    named = runner.invoke(app, ["create-3d-model", "Wider", "--name", "bear", "--resume-session", SESSION])
    last = runner.invoke(app, ["create-3d-model", "Rounder", "--name", "bear", "--resume-session", "true"])

    assert fresh.exit_code == named.exit_code == last.exit_code == 0, fresh.output + named.output + last.output
    runs = record_of(working_directory / ".modeling-3d" / "bear").runs
    assert [run.resumed for run in runs] == [False, False, True, True]
