"""Reads a model's activity from runs written directly, their events trimmed from a real run's, so no agent is needed."""

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.cli import app
from modeling_3d.schemas import ModelActivity, Modeling3dError, ModelRecord, ModelRunRecord, ToolCall

START = datetime(2026, 10, 17, 10, tzinfo=UTC)
# What Claude Code sends back for a render the agent reads: the image, as base64.
RENDER = "iVBORw0KGgo" * 20_000

runner = CliRunner()


@pytest.fixture(autouse=True)
def working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def bear(working_directory: Path) -> Path:
    """A model with a run from before requests were kept in the started event, and one with Claude's events."""
    target = (working_directory / ".modeling-3d" / "bear").resolve()
    target.mkdir(parents=True)
    (target / "model.py").write_text("# the bear", encoding="utf-8")
    (target / "model.glb").write_bytes(b"glTF")
    write_run(target, run_record("old", "A low poly bear", references=["references/bear.png"]), old_run())
    write_run(
        target,
        run_record("new", "Make it a polar bear.", resumed=True, origin="app"),
        new_run(target),
    )
    return target


def run_record(
    run_id: str, prompt: str, references: list[str] | None = None, resumed: bool = False, origin: str | None = None
) -> ModelRunRecord:
    return ModelRunRecord(
        id=run_id,
        prompt=prompt,
        references=references or [],
        resumed=resumed,
        agent_provider="claude",
        model="claude-sonnet-5-5",
        reasoning_effort="medium",
        session_id="session",
        origin=origin,
        status="done",
        pid=1,
        started=START,
    )


def write_run(target: Path, run: ModelRunRecord, events: list[dict[str, Any]]) -> Path:
    record_path = target / "model.json"
    created = ModelRecord(id="id-bear", name="bear", created=START)
    record = (
        ModelRecord.model_validate_json(record_path.read_text(encoding="utf-8")) if record_path.is_file() else created
    )
    record.runs.append(run)
    record_path.write_text(record.model_dump_json(), encoding="utf-8")
    path = target / "runs" / run.id / "events.jsonl"
    path.parent.mkdir(parents=True)
    lines = [
        json.dumps({"time": (START + timedelta(seconds=index)).isoformat(), "run_id": run.id, **event})
        for index, event in enumerate(events)
    ]
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def agent(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "agent", "text": kind, "data": data}


def assistant(*content: dict[str, Any], parent: str | None = None) -> dict[str, Any]:
    return agent(
        "AssistantMessage",
        {"content": list(content), "model": "claude-sonnet-5-5", "parent_tool_use_id": parent, "error": None},
    )


def user(content: str | list[dict[str, Any]]) -> dict[str, Any]:
    return agent("UserMessage", {"content": content, "uuid": "u", "parent_tool_use_id": None, "tool_use_result": None})


def ending(kind: str, status: str, text: str, error: str | None) -> dict[str, Any]:
    result = {"status": status, "text": text, "error": error, "files": ["model.py", "model.glb"] if text else []}
    return {"kind": kind, "text": error or "", "data": result}


def old_run() -> list[dict[str, Any]]:
    return [
        {"kind": "started", "text": "Model bear is being worked on.", "data": {"directory": "bear"}},
        assistant({"text": "Building."}),
        ending("failed", "failed", "", "The API refused."),
    ]


def new_run(target: Path) -> list[dict[str, Any]]:
    return [
        {"kind": "started", "text": "Model bear is being worked on.", "data": {"prompt": "Make it a polar bear."}},
        agent("SystemMessage", {"subtype": "init", "data": {"session_id": "session"}}),
        user("Make it a polar bear.\n\n"),
        assistant({"thinking": "", "signature": "CAQS"}),
        assistant({"text": "I'll read model.py first."}),
        assistant({"id": "toolu_read", "name": "Read", "input": {"file_path": str(target / "model.py")}}),
        user([{"tool_use_id": "toolu_read", "content": [{"type": "image", "data": RENDER}], "is_error": None}]),
        assistant(
            {
                "id": "toolu_bash",
                "name": "Bash",
                "input": {"command": f'cd "{target.as_posix()}" && uv run --script model.py\necho built'},
            }
        ),
        assistant({"text": "A subagent's words."}, parent="toolu_task"),
        user([{"tool_use_id": "toolu_bash", "content": "<tool_use_error>Exit code 1\nTraceback", "is_error": True}]),
        {"kind": "steered", "text": "Whiter fur.", "data": {"steering": "queued", "origin": "claude-code:abc"}},
        user("Whiter fur."),
        assistant({"text": "Done: a polar bear."}),
        agent("ResultMessage", {"subtype": "success", "result": "Done: a polar bear.", "is_error": False}),
        ending("finished", "done", "Done: a polar bear.", None),
    ]


def test_the_activity_reads_every_run_in_order_beside_the_model_s_summary(bear: Path) -> None:
    activity = lib.read_3d_model_activity("bear")

    assert [(entry.run_id, entry.kind, entry.origin, entry.text) for entry in activity.entries] == [
        ("old", "request", None, "A low poly bear"),
        ("old", "said", None, "Building."),
        ("old", "ended", None, ""),
        ("new", "request", "app", "Make it a polar bear."),
        ("new", "said", None, "I'll read model.py first."),
        ("new", "tool", None, "model.py"),
        ("new", "tool-result", None, ""),
        ("new", "tool", None, "uv run --script model.py"),
        ("new", "tool-result", None, "Exit code 1"),
        ("new", "steered", "claude-code:abc", "Whiter fur."),
        ("new", "said", None, "Done: a polar bear."),
        ("new", "ended", None, "Done: a polar bear."),
    ]
    old, _, failed, new, _, read, read_result, bash, bash_result, steered, _, done = activity.entries
    assert old.data == {
        "references": ["references/bear.png"],
        "resumed": False,
        "agent_provider": "claude",
        "model": "claude-sonnet-5-5",
        "reasoning_effort": "medium",
        "session_id": "session",
    }
    assert new.data["resumed"]
    assert read.data == {"id": "toolu_read", "name": "Read", "target": "model.py"}
    assert (read_result.data, bash.data["name"], bash_result.data) == (
        {"id": "toolu_read", "failed": False},
        "Bash",
        {"id": "toolu_bash", "failed": True},
    )
    assert steered.data == {"steering": "queued"}
    assert failed.data == {"status": "failed", "error": "The API refused.", "files": []}
    assert done.data == {"status": "done", "error": None, "files": ["model.py", "model.glb"]}
    assert done.time == START + timedelta(seconds=14)
    assert activity.model == lib.list_3d_models().models[0]
    assert activity.model.references == ["references/bear.png"]


def test_a_cursor_reads_only_what_came_since_never_half_a_line_and_moves_on_to_a_new_run(bear: Path) -> None:
    events = bear / "runs" / "new" / "events.jsonl"
    line = json.dumps({"time": START.isoformat(), "run_id": "new", "kind": "steered", "text": "Bigger paws."})

    first = lib.read_3d_model_activity("bear")
    with events.open("a", encoding="utf-8") as appending:
        appending.write(line[:30])
    partial = lib.read_3d_model_activity("bear", after=first.cursor)
    with events.open("a", encoding="utf-8") as appending:
        appending.write(line[30:] + "\n")
    whole = lib.read_3d_model_activity("bear", after=partial.cursor)
    write_run(bear, run_record("next", "Add a cub.", origin="claude-code:abc"), [old_run()[0]])
    moved = lib.read_3d_model_activity("bear", after=whole.cursor)

    assert (partial.entries, partial.cursor) == ([], first.cursor)
    assert [(entry.kind, entry.text) for entry in whole.entries] == [("steered", "Bigger paws.")]
    assert [(entry.run_id, entry.kind, entry.origin) for entry in moved.entries] == [
        ("next", "request", "claude-code:abc")
    ]
    assert moved.cursor.startswith("next:")
    assert lib.read_3d_model_activity("bear", after=moved.cursor).entries == []


@pytest.mark.parametrize("cursor", ["gone:12", "new:twelve", "nonsense"])
def test_a_cursor_into_no_run_of_the_model_names_the_fix(bear: Path, cursor: str) -> None:
    with pytest.raises(Modeling3dError) as failure:
        lib.read_3d_model_activity("bear", after=cursor)

    assert f"{cursor!r} is not a cursor into model bear's activity" in str(failure.value)
    assert "Read it without after" in str(failure.value)


def test_a_model_that_never_ran_has_no_activity_and_an_unknown_one_names_the_models(working_directory: Path) -> None:
    target = working_directory / ".modeling-3d" / "owl"
    target.mkdir(parents=True)
    (target / "model.json").write_text(
        ModelRecord(id="id-owl", name="owl", created=START).model_dump_json(), encoding="utf-8"
    )

    activity = lib.read_3d_model_activity("owl")
    with pytest.raises(Modeling3dError) as failure:
        lib.read_3d_model_activity("fox")

    assert (activity.entries, activity.cursor) == ([], "")
    assert "There is no model named 'fox'" in str(failure.value)
    assert "The models there: owl." in str(failure.value)


def test_the_cli_prints_the_activity_as_json_and_reads_on_from_a_cursor(bear: Path) -> None:
    printed = runner.invoke(app, ["read-3d-model-activity", "--name", "bear"])
    activity = ModelActivity.model_validate_json(printed.stdout)
    since = runner.invoke(app, ["read-3d-model-activity", "--name", "bear", "--after", activity.cursor])

    assert printed.exit_code == since.exit_code == 0, printed.output + since.output
    assert activity == lib.read_3d_model_activity("bear")
    assert ModelActivity.model_validate_json(since.stdout).entries == []


def test_a_tool_call_reads_in_full_with_its_output_as_text_and_none_while_it_runs(bear: Path) -> None:
    events = bear / "runs" / "new" / "events.jsonl"
    edit = {"file_path": str(bear / "model.py"), "old_string": "# the bear", "new_string": "# the polar bear"}
    with events.open("a", encoding="utf-8") as appending:
        for event in (
            assistant({"id": "toolu_edit", "name": "Edit", "input": edit}),
            user([{"tool_use_id": "toolu_edit", "content": [{"type": "text", "text": "Edited."}], "is_error": False}]),
            assistant({"id": "toolu_glob", "name": "Glob", "input": {"pattern": "renders/*.png"}}),
        ):
            appending.write(json.dumps({"time": START.isoformat(), "run_id": "new", **event}) + "\n")

    calls = {call_id: lib.read_3d_model_tool_call("bear", "new", call_id) for call_id in ("toolu_read", "toolu_bash")}
    edited = lib.read_3d_model_tool_call("bear", "new", "toolu_edit")
    running = lib.read_3d_model_tool_call("bear", "new", "toolu_glob")

    assert calls["toolu_read"] == ToolCall(
        name="Read", input={"file_path": str(bear / "model.py")}, output="", failed=False
    )
    assert calls["toolu_bash"].input["command"].endswith("uv run --script model.py\necho built")
    assert (calls["toolu_bash"].output, calls["toolu_bash"].failed) == ("Exit code 1\nTraceback", True)
    assert (edited.input, edited.output, edited.failed) == (edit, "Edited.", False)
    assert (running.name, running.output) == ("Glob", None)


@pytest.mark.parametrize(("run_id", "call_id"), [("new", "toolu_none"), ("gone", "toolu_read"), ("old", "toolu_read")])
def test_a_tool_call_the_model_s_runs_do_not_have_names_the_fix(bear: Path, run_id: str, call_id: str) -> None:
    with pytest.raises(Modeling3dError) as failure:
        lib.read_3d_model_tool_call("bear", run_id, call_id)

    assert f"Model bear has no tool call {call_id!r} in a run {run_id!r}" in str(failure.value)
    assert failure.value.reason == "no-such-tool-call"
    assert "read-3d-model-activity --name bear" in str(failure.value)


def test_the_cli_prints_a_tool_call_as_json(bear: Path) -> None:
    printed = runner.invoke(app, ["read-3d-model-tool-call", "--name", "bear", "--run", "new", "--id", "toolu_bash"])

    assert printed.exit_code == 0, printed.output
    assert ToolCall.model_validate_json(printed.stdout) == lib.read_3d_model_tool_call("bear", "new", "toolu_bash")


def test_reasoning_shows_from_its_first_count_and_its_summary_once_done_with_left_out_reasoning_showing_nothing(
    bear: Path,
) -> None:
    def counted(total: int, delta: int) -> dict[str, Any]:
        count = {
            "type": "system",
            "subtype": "thinking_tokens",
            "estimated_tokens": total,
            "estimated_tokens_delta": delta,
        }
        return agent("SystemMessage", {"subtype": "thinking_tokens", "data": count})

    write_run(
        bear,
        run_record("next", "Rounder ears."),
        [
            old_run()[0],
            counted(50, 50),
            counted(209, 159),
            assistant({"thinking": "**Shaping the ears**\n\nI'll widen them.\n", "signature": "CAQS"}),
            assistant({"thinking": "", "signature": "CAQS"}),
            counted(40, 40),
            assistant({"text": "Rounder now."}),
        ],
    )

    entries = lib.read_3d_model_activity("bear").entries

    assert [(entry.kind, entry.text) for entry in entries if entry.run_id == "next"] == [
        ("request", "Rounder ears."),
        ("reasoning", ""),
        ("thought", "**Shaping the ears**\n\nI'll widen them."),
        ("reasoning", ""),
        ("said", "Rounder now."),
    ]


def test_a_tool_call_being_written_shows_what_it_works_on_once_that_much_is_written_and_how_far_it_has_got(
    bear: Path,
) -> None:
    whole = json.dumps({"file_path": str(bear / "model.py"), "content": "import bpy"})
    write_run(
        bear,
        run_record("next", "Rounder ears."),
        [
            old_run()[0],
            agent("composing", {"id": "toolu_w", "name": "Write", "head": whole[:20], "characters": 20}),
            agent("composing", {"id": "toolu_w", "name": "Write", "head": whole[:-3], "characters": 9000}),
        ],
    )

    composing = [entry for entry in lib.read_3d_model_activity("bear").entries if entry.kind == "composing"]

    assert [(entry.text, entry.data) for entry in composing] == [
        ("", {"id": "toolu_w", "name": "Write", "target": "", "characters": 20}),
        ("model.py", {"id": "toolu_w", "name": "Write", "target": "model.py", "characters": 9000}),
    ]


def test_each_turn_s_result_shows_what_its_session_has_cost_in_all(bear: Path) -> None:
    def result(cost: float, session: str) -> dict[str, Any]:
        return agent("ResultMessage", {"subtype": "success", "total_cost_usd": cost, "session_id": session})

    write_run(bear, run_record("next", "Rounder ears."), [old_run()[0], result(0.25, "s1"), result(0.5, "s1")])
    write_run(bear, run_record("last", "Again.", resumed=True), [old_run()[0], result(0.75, "s1"), result(0.1, "s2")])

    usage = [
        (entry.run_id, entry.data) for entry in lib.read_3d_model_activity("bear").entries if entry.kind == "usage"
    ]

    assert usage == [
        ("next", {"cost_usd": 0.25, "session_id": "s1"}),
        ("next", {"cost_usd": 0.5, "session_id": "s1"}),
        ("last", {"cost_usd": 0.75, "session_id": "s1"}),
        ("last", {"cost_usd": 0.1, "session_id": "s2"}),
    ]
