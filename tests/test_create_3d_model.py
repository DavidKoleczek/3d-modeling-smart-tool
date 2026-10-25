"""Drives create-3d-model with the agent faked by a script, so neither credentials nor a model are needed."""

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

from fakes import (
    SESSION,
    FakeIntelligence,
    FakeRun,
    Refusing,
    Script,
    builds,
    builds_nothing,
    fails,
    record_of,
    run_to_end,
    waits_for_steering,
    works_forever,
)
from glbs import Glb, box
import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model import constants, create
from modeling_3d.capabilities.create_3d_model.check import check
from modeling_3d.capabilities.create_3d_model.prompting import template
from modeling_3d.capabilities.create_3d_model.record import GITIGNORE, write_record
from modeling_3d.cli import app
from modeling_3d.intelligence import interface
from modeling_3d.intelligence.schemas import AgentResult
from modeling_3d.schemas import (
    BPY_REQUIREMENT,
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_MAX_DRAW_CALLS,
    DEFAULT_MAX_TRIANGLES,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_SCREEN_SIZE,
    PROVIDER_REASONING_EFFORTS,
    ModelEvent,
    Modeling3dError,
)

TIMEOUT_SECONDS = 5

runner = CliRunner()
pytestmark = pytest.mark.usefixtures("working_directory", "quick_polls")


async def test_a_new_model_is_built_and_recorded_in_its_own_directory(working_directory: Path) -> None:
    last, run, intelligence, events = await run_to_end(name="bear", origin="claude-code:abc")
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
    assert request.workspace.path == working_directory
    assert request.writable
    assert request.session_directory == directory / "sessions"
    assert request.resume is None
    assert request.model == DEFAULT_INTELLIGENCE_MODELS["claude"]
    assert request.reasoning_effort == DEFAULT_REASONING_EFFORT
    assert request.timeout_seconds == 3600 + create.AGENT_TIMEOUT_GRACE_SECONDS
    assert "A low poly bear" in request.prompt
    assert BPY_REQUIREMENT in request.prompt
    assert str(directory) in request.prompt
    assert f"through {constants.MODE_CAPABILITIES['shape']}." in request.prompt
    assert template("shape.md").strip() in request.prompt
    assert template("rig.md").strip() not in request.prompt
    assert constants.EXISTING not in request.prompt
    assert f"- At most {DEFAULT_MAX_TRIANGLES} triangles." in request.prompt
    record = record_of(directory)
    assert (record.tool, record.name) == ("modeling-3d", "bear")
    assert "runs" not in json.loads((directory / "model.json").read_text(encoding="utf-8"))
    [entry] = record.runs
    assert (entry.id, entry.status, entry.session_id, entry.pid) == (run.run_id, "done", SESSION, os.getpid())
    assert (entry.mode, events[0].data["mode"]) == ("shape", "shape")
    assert (entry.agent_provider, entry.origin) == ("claude", "claude-code:abc")
    started = events[0].data
    assert (started["prompt"], started["origin"], started["resumed"]) == ("A low poly bear", "claude-code:abc", False)
    assert (started["agent_provider"], started["references"]) == ("claude", [])
    assert (entry.max_triangles, entry.max_draw_calls, entry.screen_size) == (
        DEFAULT_MAX_TRIANGLES,
        DEFAULT_MAX_DRAW_CALLS,
        DEFAULT_SCREEN_SIZE,
    )
    assert entry.finished is not None
    assert entry.last_event == events[-1].time
    lines = (directory / "runs" / run.run_id / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [ModelEvent.model_validate_json(line) for line in lines] == events


async def test_the_models_directory_named_holds_the_models_and_gets_a_gitignore_when_new_to_the_tool(
    working_directory: Path,
) -> None:
    (working_directory / "picked").mkdir()
    (working_directory / "picked" / ".app.json").write_text("{}", encoding="utf-8")
    (working_directory / "kept" / "notes").mkdir(parents=True)

    _, made, _, _ = await run_to_end(name="bear")
    gitignore = made.directory.parent / ".gitignore"
    first = gitignore.read_text(encoding="utf-8")
    gitignore.write_text("/*\n", encoding="utf-8")
    await run_to_end(name="cub")
    _, fox, _, _ = await run_to_end(name="fox", directory=Path("picked"))
    await run_to_end(name="owl", directory=Path("kept"))

    written = GITIGNORE.read_text(encoding="utf-8")
    assert first == written
    assert "!/AGENTS.md" in written
    assert gitignore.read_text(encoding="utf-8") == "/*\n"
    assert (working_directory / "picked" / ".gitignore").read_text(encoding="utf-8") == written
    assert not (working_directory / "kept" / ".gitignore").exists()
    assert fox.directory == working_directory / "picked" / "fox"
    assert (await fox.result()).next.endswith(f"--directory {working_directory / 'picked'}")


@pytest.mark.parametrize(
    ("arguments", "message", "reason"),
    [
        ({"name": "notes"}, "already exists and is not a model", "name-in-use"),
        ({"name": "NOTES"}, "already exists and is not a model", "name-in-use"),
        ({"name": "../escape"}, "cannot name a model", "invalid-name"),
        ({"name": "fox", "references": [Path("nope.png")]}, "nope.png is not a file", "missing-reference"),
        (
            {"name": "elsewhere", "agent_provider": "claude", "resume_session": True},
            "ran on codex, and claude was asked for",
            "provider-mismatch",
        ),
        (
            {"name": "fox", "agent_provider": "claude", "model": "claude-opus-5-5", "reasoning_effort": "ultra"},
            ", ".join(PROVIDER_REASONING_EFFORTS["claude"]),
            "bad-reasoning-effort",
        ),
        ({"name": "bear", "resume_session": "gone"}, "has no session 'gone'. Its sessions", "no-such-session"),
        ({"name": "fox", "resume_session": "gone"}, "Model fox has no session 'gone'", "no-such-session"),
        ({"name": "fox", "max_triangles": 0}, "max_triangles is 0, and a budget is 1 or more", "bad-budget"),
        ({"name": "fox", "screen_size": (240, 40)}, "Give the smallest and then the largest", "bad-budget"),
        ({"name": "fox", "detach": True}, "cannot reach", None),
    ],
)
async def test_a_request_that_cannot_run_is_refused_before_anything_starts(
    working_directory: Path, arguments: dict[str, Any], message: str, reason: str | None
) -> None:
    for name, change in [("bear", None), ("elsewhere", {"agent_provider": "codex"})]:
        _, built, _, _ = await run_to_end(name=name)
        if change is not None:
            record = record_of(built.directory)
            record.runs[0] = record.runs[0].model_copy(update=change)
            write_record(built.directory, record)
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
    assert f"references/bear.png{constants.ATTACHED}" in request.prompt
    assert "references/old.glb\n" in request.prompt
    assert (references / "old.glb").read_bytes() == b"glTF"
    assert (references / "bear.png").read_bytes() == b"first"
    assert (references / "bear-2.png").read_bytes() == b"second"
    assert [entry.references for entry in record_of(run.directory).runs] == [
        ["references/bear.png", "references/old.glb"],
        ["references/bear-2.png", "references/bear-2.png"],
    ]


async def test_a_folder_is_copied_whole_but_for_hidden_folders_and_caches_and_never_overwrites_another(
    working_directory: Path,
) -> None:
    kit = working_directory / "kit"
    for path in ("parts/wheel.png", ".git/HEAD", "node_modules/a.js", "__pycache__/a.pyc", ".notes.txt"):
        (kit / path).parent.mkdir(parents=True, exist_ok=True)
        (kit / path).write_bytes(b"bytes")

    _, run, intelligence, _ = await run_to_end(name="bear", references=[kit])
    await run_to_end(name="bear", references=[kit])

    copied = run.directory / "references" / "kit"
    assert sorted(path.relative_to(copied).as_posix() for path in copied.rglob("*")) == [
        ".notes.txt",
        "parts",
        "parts/wheel.png",
    ]
    assert (run.directory / "references" / "kit-2" / "parts" / "wheel.png").is_file()
    assert f"references/kit/{constants.FOLDER}" in intelligence.runs[0].request.prompt
    assert intelligence.runs[0].request.images == []
    assert [entry.references for entry in record_of(run.directory).runs] == [["references/kit/"], ["references/kit-2/"]]


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


async def test_a_name_a_model_has_changes_it_in_a_fresh_session_unless_told_to_resume_one() -> None:
    _, first, creating, _ = await run_to_end(name="bear")

    _, changed, refreshing, _ = await run_to_end(prompt="Make the snout longer", name="Bear")
    _, _, resuming, _ = await run_to_end(prompt="And the ears rounder", name="bear", resume_session=True)

    fresh = refreshing.runs[0].request
    resume = resuming.runs[0].request
    assert constants.EXISTING not in creating.runs[0].request.prompt
    assert changed.directory == first.directory
    assert changed.name == "bear"
    assert fresh.resume is None
    assert "Make the snout longer" in fresh.prompt
    assert constants.EXISTING in fresh.prompt
    assert resume.resume == SESSION
    assert resume.prompt.strip() == "And the ears rounder"
    assert [entry.resumed for entry in record_of(first.directory).runs] == [False, False, True]


async def test_budgets_are_given_to_the_agent_kept_by_a_change_and_sent_to_a_session_only_when_set() -> None:
    _, run, creating, events = await run_to_end(
        name="bear", max_triangles=2000, max_draw_calls=2, screen_size=(40, 240)
    )
    _, _, refreshing, _ = await run_to_end(prompt="Make the snout longer", name="bear", max_triangles=3000)
    _, _, resuming, _ = await run_to_end(prompt="And the ears rounder", name="bear", resume_session=True)
    _, _, changing, _ = await run_to_end(
        prompt="Rounder still", name="bear", resume_session=True, max_draw_calls=1, screen_size=None
    )

    at_most, triangles, draw_calls = constants.AT_MOST.format, constants.TRIANGLE, constants.DRAW_CALL
    on_screen = constants.ON_SCREEN.format(smallest=40, largest=240)
    created = creating.runs[0].request.prompt
    assert f"{at_most(count=2000, noun=triangles[1])}\n{at_most(count=2, noun=draw_calls[1])}\n{on_screen}" in created
    assert "\n".join(constants.SHAPE_SCREEN_ADVICE) in created
    # Joining parts into objects is rigging's, so shaping lists the draw call budget without saying how to keep to it.
    assert constants.RIG_DRAW_CALL_ADVICE[0] not in created
    assert at_most(count=3000, noun=triangles[1]) in refreshing.runs[0].request.prompt
    assert resuming.runs[0].request.prompt.strip() == "And the ears rounder"
    told = changing.runs[0].request.prompt
    assert told.startswith("Rounder still\n")
    removed = constants.NO_BUDGET.format(name=constants.SCREEN_SIZE)
    assert f"{at_most(count=1, noun=draw_calls[0])}\n{removed}\n" in told
    assert at_most(count=3000, noun=triangles[1]) not in told
    assert constants.SHAPE_SCREEN_ADVICE[1] not in told
    assert [
        (entry.max_triangles, entry.max_draw_calls, entry.screen_size) for entry in record_of(run.directory).runs
    ] == [
        (2000, 2, (40, 240)),
        (3000, 2, (40, 240)),
        (3000, 2, (40, 240)),
        (3000, 1, None),
    ]
    assert (events[0].data["max_triangles"], events[0].data["screen_size"]) == (2000, [40, 240])


async def test_a_model_without_budgets_gets_no_budget_instructions() -> None:
    _, run, intelligence, _ = await run_to_end(name="bear", max_triangles=None, max_draw_calls=None, screen_size=None)
    _, _, refreshing, _ = await run_to_end(prompt="Make the snout longer", name="bear")

    for prompt in (intelligence.runs[0].request.prompt, refreshing.runs[0].request.prompt):
        assert "<budgets>" not in prompt
    assert record_of(run.directory).runs[-1].max_triangles is None


async def test_a_fresh_session_is_told_to_read_the_project_s_guidance_beside_its_models(
    working_directory: Path,
) -> None:
    _, bear, without, _ = await run_to_end(name="bear")
    (bear.directory.parent / "AGENTS.md").write_text("Models face -Z.\n", encoding="utf-8")
    (working_directory / "models").mkdir()
    (working_directory / "models" / "AGENTS.md").write_text("Keep them small.", encoding="utf-8")

    _, _, fresh, _ = await run_to_end(prompt="Make the snout longer", name="bear")
    _, _, resuming, _ = await run_to_end(prompt="And the ears rounder", name="bear", resume_session=True)
    _, _, elsewhere, _ = await run_to_end(name="fox", directory=Path("models"))

    guidance = bear.directory.parent / "AGENTS.md"
    assert str(guidance) not in without.runs[0].request.prompt
    assert constants.READ_GUIDANCE.format(path=guidance) in fresh.runs[0].request.prompt
    assert "Models face -Z." not in fresh.runs[0].request.prompt
    assert str(guidance) not in resuming.runs[0].request.prompt
    assert str(working_directory / "models" / "AGENTS.md") in elsewhere.runs[0].request.prompt


async def test_a_session_goes_on_with_another_model_of_its_agent_provider() -> None:
    await run_to_end(name="bear", agent_provider="codex", model="gpt-6.1-sol")

    _, _, resuming, _ = await run_to_end(
        prompt="Rounder ears", name="bear", resume_session=True, model="gpt-6-astra", reasoning_effort="ultra"
    )

    request = resuming.runs[0].request
    assert (request.resume, request.model, request.reasoning_effort) == (SESSION, "gpt-6-astra", "ultra")
    assert record_of(Path(".modeling-3d/bear")).runs[-1].agent_provider == "codex"


async def test_a_session_named_by_its_id_is_the_one_continued() -> None:
    _, first, _, _ = await run_to_end(name="bear")
    await run_to_end(prompt="Make the snout longer", name="bear", resume_session=False)
    record = record_of(first.directory)
    record.runs[0].session_id, record.runs[1].session_id = "first-session", "second-session"
    write_record(first.directory, record)

    _, _, named, _ = await run_to_end(prompt="Back to how it was", name="bear", resume_session="first-session")
    _, _, latest, _ = await run_to_end(prompt="And then", name="bear", resume_session=True)

    assert named.runs[0].request.resume == "first-session"
    assert latest.runs[0].request.resume == "first-session"


async def test_a_model_without_a_session_changes_in_a_fresh_one() -> None:
    _, first, _, _ = await run_to_end(name="bear")
    record = record_of(first.directory)
    record.runs[0].session_id = None
    write_record(first.directory, record)

    _, _, intelligence, _ = await run_to_end(prompt="Make the snout longer", name="bear", resume_session=True)

    assert intelligence.runs[0].request.resume is None
    assert constants.EXISTING in intelligence.runs[0].request.prompt
    assert record_of(first.directory).runs[-1].resumed is False


async def test_a_session_goes_on_only_where_its_agent_provider_still_keeps_it(
    monkeypatch: pytest.MonkeyPatch, codex_home: Path
) -> None:
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(builds))
    _, first, _, _ = await run_to_end(name="bear", agent_provider="codex", model="gpt-6.1-sol")

    with pytest.raises(Modeling3dError) as elsewhere:
        await lib.create_3d_model("Rounder ears", name="bear", resume_session=True)
    sessions = codex_home / "sessions" / "2026" / "10" / "21"
    sessions.mkdir(parents=True)
    (sessions / f"rollout-2026-10-21T10-00-00-{SESSION}.jsonl").write_text("", encoding="utf-8")
    await (await lib.create_3d_model("Rounder ears", name="bear", resume_session=True)).result()

    assert "not among the sessions codex keeps on this machine" in str(elsewhere.value)
    assert "--resume-session false" in str(elsewhere.value)
    assert (elsewhere.value.reason, elsewhere.value.model) == ("session-unavailable", "bear")
    assert [run.resumed for run in record_of(first.directory).runs] == [False, True]


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
    write_record(run.directory, record)

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
async def test_steering_reaches_the_agent_with_its_references_and_shows_as_an_event_from_its_sender(
    working_directory: Path, sender: str, origin: str
) -> None:
    (working_directory / "ears.png").write_bytes(b"png")
    intelligence = FakeIntelligence(waits_for_steering)
    run = await lib.create_3d_model("A bear", name="bear", origin="claude-code:abc", intelligence=intelligence)

    if sender == "handle":
        await run.steer("Rounder ears.", [Path("ears.png")])
    else:
        await asyncio.to_thread(lib.steer_3d_model, "bear", "Rounder ears.", None, "app", [Path("ears.png")])
    result = await asyncio.wait_for(run.result(), TIMEOUT_SECONDS)

    agent = intelligence.runs[0]
    listed = f"{constants.ADDED_REFERENCES}\n- references/ears.png{constants.ATTACHED}\n"
    assert agent.steered == [f"Rounder ears.\n{listed}"]
    assert result.text == f"Did: {agent.steered[0]}"
    assert agent.steered_images == [[run.directory / "references" / "ears.png"]]
    assert (run.directory / "references" / "ears.png").read_bytes() == b"png"
    steered = [event async for event in run.events() if event.kind == "steered"]
    assert [(event.text, event.data["origin"], event.data["references"]) for event in steered] == [
        ("Rounder ears.", origin, ["references/ears.png"])
    ]
    assert not list((run.directory / "runs" / run.run_id / "steer").iterdir())


async def test_cancel_from_another_process_stops_the_run_and_keeps_the_session() -> None:
    run = await lib.create_3d_model("A bear", name="bear", intelligence=FakeIntelligence(works_forever))

    await asyncio.to_thread(lib.cancel_3d_model, "bear")
    result = await asyncio.wait_for(run.result(), TIMEOUT_SECONDS)

    assert result.status == "cancelled"
    assert result.session_id == SESSION
    assert record_of(run.directory).runs[0].status == "cancelled"
    assert [event.kind async for event in run.events()][-1] == "finished"


@pytest.mark.real_timeout
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

    assert (steering.value.reason, steering.value.model) == ("not-running", "bear")
    assert 'create-3d-model "<what to change>" --name bear' in str(steering.value)
    assert cancelling.value.reason == "not-running"
    assert missing.value.reason == "no-such-model"
    assert "bear" in str(missing.value)


def test_the_cli_prints_each_event_as_a_json_line_and_exits_0_only_when_done(
    monkeypatch: pytest.MonkeyPatch, working_directory: Path
) -> None:
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(builds))
    image = working_directory / "bear.png"
    image.write_bytes(b"png")

    result = runner.invoke(app, ["create-3d-model", "A low poly bear", "--name", "bear", "--reference", "bear.png"])
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(builds_nothing))
    unfinished = runner.invoke(app, ["create-3d-model", "A fox", "--name", "fox"])

    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in result.stdout.splitlines()]
    assert [line["kind"] for line in lines] == ["started", "agent", "finished"]
    assert lines[-1]["data"]["status"] == "done"
    assert (working_directory / ".modeling-3d" / "bear" / "references" / "bear.png").is_file()
    assert unfinished.exit_code == 1
    assert json.loads(unfinished.stdout.splitlines()[-1])["kind"] == "failed"


def test_the_cli_takes_the_budgets_and_starts_a_fresh_session_unless_given_true_or_a_session_id(
    monkeypatch: pytest.MonkeyPatch, working_directory: Path
) -> None:
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(builds))
    budgets = ["--max-triangles", "none", "--max-draw-calls", "2", "--screen-size", "40-240"]

    results = [
        runner.invoke(app, ["create-3d-model", "A bear", "--name", "bear", *budgets]),
        runner.invoke(app, ["create-3d-model", "Taller", "--name", "bear"]),
        runner.invoke(app, ["create-3d-model", "Wider", "--name", "bear", "--resume-session", SESSION]),
        runner.invoke(app, ["create-3d-model", "Rounder", "--name", "bear", "--resume-session", "true"]),
    ]
    misread = runner.invoke(app, ["create-3d-model", "A fox", "--name", "fox", "--screen-size", "40x240"])

    assert [result.exit_code for result in results] == [0, 0, 0, 0], "".join(result.output for result in results)
    runs = record_of(working_directory / ".modeling-3d" / "bear").runs
    assert [run.resumed for run in runs] == [False, False, True, True]
    assert (runs[0].max_triangles, runs[0].max_draw_calls, runs[0].screen_size) == (None, 2, (40, 240))
    assert misread.exit_code == 2
    assert "SMALLEST-LARGEST" in misread.output


async def builds_a_box(run: FakeRun) -> AgentResult:
    """An agent that builds a model the check can read, and finishes without checking it."""
    assert run.request.session_directory is not None
    model = run.request.session_directory.parent
    (model / "model.py").write_text("# the box", encoding="utf-8")
    glb = Glb()
    glb.node("Box", mesh=glb.mesh(box()))
    glb.write(model / "model.glb")
    return AgentResult(text="A box.", session_id=run.session_id)


async def builds_a_box_and_checks_it(run: FakeRun) -> AgentResult:
    result = await builds_a_box(run)
    await asyncio.to_thread(lib.check_3d_model, "box")
    return result


async def checks_too_soon(run: FakeRun) -> AgentResult:
    """An agent that checks the model, then changes it."""
    result = await builds_a_box_and_checks_it(run)
    glb = Glb()
    glb.node("Box", mesh=glb.mesh(box(size=(2.0, 2.0, 2.0))))
    assert run.request.session_directory is not None
    glb.write(run.request.session_directory.parent / "model.glb")
    return result


async def test_every_run_gets_the_check_as_a_skill_and_is_told_to_run_it(state_directory: Path) -> None:
    _, run, intelligence, _ = await run_to_end(name="bear")

    request = intelligence.runs[0].request
    [skills] = request.skill_directories
    assert skills.is_relative_to(state_directory)
    skill = (skills / "check-3d-model" / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = f"---\nname: {constants.AGENT_SKILL}\ndescription: {constants.AGENT_SKILL_DESCRIPTION}\n"
    assert skill.startswith(frontmatter)
    assert sys.executable in skill
    assert " ".join(check.CHECK_COMMAND[1:]) in skill
    assert lib.skill(constants.AGENT_SKILL) in skill
    assert f"--name bear --directory {run.directory.parent}" in request.prompt


async def test_an_agent_that_did_not_check_the_model_gets_the_check_once_as_it_finishes() -> None:
    intelligence = FakeIntelligence(builds_a_box, follows_up=True)

    run = await lib.create_3d_model(
        "A box", name="box", max_triangles=100, max_draw_calls=None, screen_size=None, intelligence=intelligence
    )
    events = [event async for event in run.events()]

    [message] = intelligence.runs[0].followed_up
    assert [event.kind for event in events] == ["started", "checked", "finished"]
    assert message == template("checked.md").format(report=events[1].text)
    assert events[1].data == {"report": "checks/report.json"}
    entries = lib.read_3d_model_activity("box").entries
    assert [entry.kind for entry in entries] == ["request", "checked", "ended"]
    assert entries[1].data == {"report": "checks/report.json"}


async def test_an_agent_that_checked_the_model_as_it_is_gets_no_follow_up() -> None:
    intelligence = FakeIntelligence(builds_a_box_and_checks_it, follows_up=True)

    run = await lib.create_3d_model("A box", name="box", intelligence=intelligence)
    events = [event async for event in run.events()]

    assert intelligence.runs[0].followed_up == []
    assert [event.kind for event in events] == ["started", "finished"]


async def test_an_agent_that_changed_the_model_after_checking_it_gets_the_check_of_it_as_it_is() -> None:
    intelligence = FakeIntelligence(checks_too_soon, follows_up=True)

    run = await lib.create_3d_model("A box", name="box", intelligence=intelligence)
    events = [event async for event in run.events()]

    [message] = intelligence.runs[0].followed_up
    [checked] = [event for event in events if event.kind == "checked"]
    assert message == template("checked.md").format(report=checked.text)
    assert check.covers(run.directory)


async def test_a_check_that_cannot_run_tells_the_agent_why() -> None:
    intelligence = FakeIntelligence(builds, follows_up=True)

    run = await lib.create_3d_model("A bear", name="bear", intelligence=intelligence)
    events = [event async for event in run.events()]

    [message] = intelligence.runs[0].followed_up
    [checked] = [event for event in events if event.kind == "checked"]
    assert "is not a glTF binary" in checked.data["error"]
    failed = constants.CHECK_FAILED.format(error=checked.data["error"])
    assert message == template("checked.md").format(report=failed)


async def test_a_run_that_leaves_its_model_unchecked_is_checked_for_whoever_looks_next() -> None:
    _, run, _, events = await run_to_end(builds_a_box, name="box")

    assert check.covers(run.directory)
    assert "checked" not in [event.kind for event in events]
