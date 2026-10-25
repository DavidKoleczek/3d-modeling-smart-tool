"""Runs a model in a process of its own, with its agent faked by a script there, as `detach=True` does."""

import asyncio
from collections.abc import Callable
import json
import os
from pathlib import Path
import time

import detached_agent
from fakes import SESSION, record_of, run_to_end
import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model import create
from modeling_3d.capabilities.create_3d_model.record import PROCESS_LOG, alive
from modeling_3d.cli import app
from modeling_3d.schemas import ModelEvent, Modeling3dError, ModelRunRecord

# A detached run starts a Python process of its own, which takes a while to import the library.
DETACHED_TIMEOUT_SECONDS = 30

runner = CliRunner()
pytestmark = [pytest.mark.detached, pytest.mark.usefixtures("working_directory", "quick_polls")]


@pytest.fixture
def detached(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Have detached runs fake their agent with the named script from fakes.py."""

    def use(script: str) -> None:
        monkeypatch.setattr(create, "BACKGROUND_COMMAND", detached_agent.command(script))

    return use


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
    assert (run.directory / "runs" / run.run_id / PROCESS_LOG).is_file()


async def test_a_detached_request_that_cannot_run_raises_what_stopped_it(detached: Callable[[str], None]) -> None:
    await run_to_end(name="bear")
    detached("builds")

    with pytest.raises(Modeling3dError) as taken:
        await lib.create_3d_model("Another bear", name="bear", resume_session="gone", detach=True)

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
