"""Drives rig-3d-model with the agent faked by a script, so neither credentials nor a model are needed."""

import json
from pathlib import Path

from fakes import SESSION, FakeIntelligence, builds, builds_nothing, record_of, run_to_end
import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model import constants
from modeling_3d.capabilities.create_3d_model.prompting import template
from modeling_3d.cli import app
from modeling_3d.intelligence import interface
from modeling_3d.schemas import Modeling3dError

runner = CliRunner()
pytestmark = pytest.mark.usefixtures("working_directory")


async def test_a_rig_works_on_the_built_model_to_its_budgets_with_the_rig_s_instructions() -> None:
    _, created, _, _ = await run_to_end(name="bear", max_triangles=2000, max_draw_calls=2, screen_size=(40, 240))
    intelligence = FakeIntelligence(builds)

    run = await lib.rig_3d_model("Bear", intelligence=intelligence)
    events = [event async for event in run.events()]
    result = await run.result()
    told = await lib.rig_3d_model("bear", "The jaw opens", intelligence=FakeIntelligence(builds))
    await told.result()
    activity = lib.read_3d_model_activity("bear")

    prompt = intelligence.runs[0].request.prompt
    assert f"through {constants.MODE_CAPABILITIES['rig']}." in prompt
    assert constants.UNASKED["rig"] in prompt
    assert template("rig.md").strip() in prompt
    assert template("shape.md").strip() not in prompt
    assert constants.EXISTING in prompt
    assert constants.AT_MOST.format(count=2, noun=constants.DRAW_CALL[1]) in prompt
    assert "\n".join(constants.RIG_DRAW_CALL_ADVICE) in prompt
    assert constants.SHAPE_SCREEN_ADVICE[1] not in prompt
    assert result.status == "done"
    assert result.next == 'modeling-3d rig-3d-model "<what to change>" --name bear --resume-session true'
    assert events[0].data["mode"] == "rig"
    runs = record_of(created.directory).runs
    assert [(entry.mode, entry.prompt) for entry in runs] == [
        ("shape", "A low poly bear"),
        ("rig", ""),
        ("rig", "The jaw opens"),
    ]
    assert {(entry.max_triangles, entry.max_draw_calls, entry.screen_size) for entry in runs} == {(2000, 2, (40, 240))}
    requests = [(entry.text, entry.data["mode"]) for entry in activity.entries if entry.kind == "request"]
    assert requests == [("A low poly bear", "shape"), ("", "rig"), ("The jaw opens", "rig")]


async def test_a_rig_is_refused_for_a_model_that_does_not_exist_or_is_not_built() -> None:
    await run_to_end(builds_nothing, name="bear")

    with pytest.raises(Modeling3dError, match="no model named 'fox'") as missing:
        await lib.rig_3d_model("fox", intelligence=FakeIntelligence(builds))
    with pytest.raises(Modeling3dError, match=r"no model\.glb yet") as unbuilt:
        await lib.rig_3d_model("bear", intelligence=FakeIntelligence(builds))

    assert missing.value.reason == "no-such-model"
    assert (unbuilt.value.reason, unbuilt.value.model) == ("not-built", "bear")
    assert 'create-3d-model "<what to build>" --name bear' in str(unbuilt.value)


async def test_a_session_going_on_in_another_mode_is_told_that_mode_s_instructions_and_budgets() -> None:
    _, created, _, _ = await run_to_end(name="bear", max_draw_calls=2, screen_size=(40, 240))

    rigging = FakeIntelligence(builds)
    await (await lib.rig_3d_model("bear", "The jaw opens", resume_session=True, intelligence=rigging)).result()
    again = FakeIntelligence(builds)
    await (await lib.rig_3d_model("bear", "Wider", resume_session=True, intelligence=again)).result()
    _, _, shaping, _ = await run_to_end(prompt="Taller", name="bear", resume_session=True)
    _, _, fresh, _ = await run_to_end(prompt="Longer", name="bear")

    rig = rigging.runs[0].request
    assert rig.resume == SESSION
    assert rig.prompt.startswith(f"The jaw opens\n\n{constants.CHANGED_MODE}\n\n{template('rig.md').strip()}\n")
    assert constants.AT_MOST.format(count=2, noun=constants.DRAW_CALL[1]) in rig.prompt
    assert constants.RIG_DRAW_CALL_ADVICE[1] in rig.prompt
    assert again.runs[0].request.prompt.strip() == "Wider"
    shape = shaping.runs[0].request.prompt
    assert shape.startswith(f"Taller\n\n{constants.CHANGED_MODE}\n\n{template('shape.md').strip()}\n")
    assert constants.SHAPE_SCREEN_ADVICE[1] in shape
    assert f"{constants.EXISTING} {constants.KEEP.format(kept='its rig')}" in fresh.runs[0].request.prompt
    assert [entry.resumed for entry in record_of(created.directory).runs] == [False, True, True, True, False]


def test_the_cli_rigs_a_built_model_with_or_without_a_prompt(
    monkeypatch: pytest.MonkeyPatch, working_directory: Path
) -> None:
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(builds))
    runner.invoke(app, ["create-3d-model", "A bear", "--name", "bear"])

    rigged = runner.invoke(app, ["rig-3d-model", "--name", "bear"])
    told = runner.invoke(app, ["rig-3d-model", "The jaw opens", "--name", "bear"])
    directory = working_directory / ".modeling-3d" / "bear"

    assert rigged.exit_code == told.exit_code == 0, rigged.output + told.output
    assert json.loads(rigged.stdout.splitlines()[-1])["data"]["next"].startswith("modeling-3d rig-3d-model")
    started = json.loads(told.stdout.splitlines()[0])
    assert (started["kind"], started["data"]["mode"], started["data"]["prompt"]) == ("started", "rig", "The jaw opens")
    assert [(entry.mode, entry.prompt) for entry in record_of(directory).runs] == [
        ("shape", "A bear"),
        ("rig", ""),
        ("rig", "The jaw opens"),
    ]
