"""Drives detail-3d-model with the agent faked by a script, so neither credentials nor a model are needed."""

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


async def test_a_detailing_works_on_the_colored_model_to_its_budgets_with_the_detail_instructions() -> None:
    await run_to_end(name="bear", max_draw_calls=2, screen_size=(40, 240))
    await (await lib.color_3d_model("bear", intelligence=FakeIntelligence(builds))).result()
    intelligence = FakeIntelligence(builds)

    run = await lib.detail_3d_model("bear", intelligence=intelligence)
    events = [event async for event in run.events()]
    result = await run.result()

    prompt = intelligence.runs[0].request.prompt
    assert f"through {constants.MODE_CAPABILITIES['detail']}." in prompt
    assert constants.UNASKED["detail"] in prompt
    assert template("detail.md").strip() in prompt
    assert f"{constants.EXISTING} {constants.KEEP.format(kept='its colors')}" in prompt
    assert "\n".join((*constants.DETAIL_DRAW_CALL_ADVICE, *constants.DETAIL_SCREEN_ADVICE)) in prompt
    assert events[0].data["mode"] == "detail"
    assert result.next == 'modeling-3d detail-3d-model "<what to change>" --name bear --resume-session true'


async def test_a_reshape_or_a_coloring_of_a_detailed_model_is_told_to_keep_what_the_other_modes_added() -> None:
    await run_to_end(name="bear")
    await (await lib.rig_3d_model("bear", intelligence=FakeIntelligence(builds))).result()
    await (await lib.color_3d_model("bear", intelligence=FakeIntelligence(builds))).result()
    await (await lib.detail_3d_model("bear", "Add wear", intelligence=FakeIntelligence(builds))).result()

    _, _, shaping, _ = await run_to_end(prompt="Taller", name="bear")
    coloring = FakeIntelligence(builds)
    await (await lib.color_3d_model("bear", intelligence=coloring)).result()

    kept = "its rig, its colors, and its surface detail"
    assert constants.KEEP.format(kept=kept) in shaping.runs[0].request.prompt
    assert constants.KEEP.format(kept="its rig and its surface detail") in coloring.runs[0].request.prompt


def test_the_cli_details_a_built_model_and_refuses_one_not_built_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    agents = iter([builds_nothing, builds, builds])
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(next(agents)))
    runner.invoke(app, ["create-3d-model", "A fox", "--name", "fox"])
    runner.invoke(app, ["create-3d-model", "A bear", "--name", "bear"])

    refused = runner.invoke(app, ["detail-3d-model", "--name", "fox"])
    detailed = runner.invoke(app, ["detail-3d-model", "--name", "bear"])

    assert isinstance(refused.exception, Modeling3dError)
    assert (refused.exception.reason, refused.exception.model) == ("not-built", "fox")
    assert "nothing to detail" in str(refused.exception)
    assert detailed.exit_code == 0, detailed.output
    started = json.loads(detailed.stdout.splitlines()[0])
    assert (started["kind"], started["data"]["mode"], started["data"]["prompt"]) == ("started", "detail", "")
