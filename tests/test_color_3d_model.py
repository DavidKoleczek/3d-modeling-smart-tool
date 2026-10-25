"""Drives color-3d-model with the agent faked by a script, so neither credentials nor a model are needed."""

import json

from fakes import FakeIntelligence, builds, builds_nothing, run_to_end
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


async def test_a_coloring_works_on_the_rigged_model_to_its_budgets_with_the_color_instructions() -> None:
    await run_to_end(name="bear", max_draw_calls=2, screen_size=(40, 240))
    await (await lib.rig_3d_model("bear", intelligence=FakeIntelligence(builds))).result()
    intelligence = FakeIntelligence(builds)

    run = await lib.color_3d_model("bear", intelligence=intelligence)
    events = [event async for event in run.events()]
    result = await run.result()

    prompt = intelligence.runs[0].request.prompt
    assert f"through {constants.MODE_CAPABILITIES['color']}." in prompt
    assert constants.UNASKED["color"] in prompt
    assert template("color.md").strip() in prompt
    assert f"{constants.EXISTING} {constants.KEEP.format(kept='its rig')}" in prompt
    assert "\n".join((*constants.COLOR_DRAW_CALL_ADVICE, *constants.COLOR_SCREEN_ADVICE)) in prompt
    assert events[0].data["mode"] == "color"
    assert result.next == 'modeling-3d color-3d-model "<what to change>" --name bear --resume-session true'


async def test_a_reshape_or_a_rig_of_a_colored_model_is_told_to_keep_what_the_other_modes_added() -> None:
    await run_to_end(name="bear")
    await (await lib.rig_3d_model("bear", intelligence=FakeIntelligence(builds))).result()
    await (await lib.color_3d_model("bear", "Make it brown", intelligence=FakeIntelligence(builds))).result()

    _, _, shaping, _ = await run_to_end(prompt="Taller", name="bear")
    rigging = FakeIntelligence(builds)
    await (await lib.rig_3d_model("bear", intelligence=rigging)).result()

    assert constants.KEEP.format(kept="its rig and its colors") in shaping.runs[0].request.prompt
    assert constants.KEEP.format(kept="its colors") in rigging.runs[0].request.prompt


def test_the_cli_colors_a_built_model_and_refuses_one_not_built_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    agents = iter([builds_nothing, builds, builds])
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(next(agents)))
    runner.invoke(app, ["create-3d-model", "A fox", "--name", "fox"])
    runner.invoke(app, ["create-3d-model", "A bear", "--name", "bear"])

    refused = runner.invoke(app, ["color-3d-model", "--name", "fox"])
    colored = runner.invoke(app, ["color-3d-model", "--name", "bear"])

    assert isinstance(refused.exception, Modeling3dError)
    assert (refused.exception.reason, refused.exception.model) == ("not-built", "fox")
    assert "nothing to color" in str(refused.exception)
    assert colored.exit_code == 0, colored.output
    started = json.loads(colored.stdout.splitlines()[0])
    assert (started["kind"], started["data"]["mode"], started["data"]["prompt"]) == ("started", "color", "")
