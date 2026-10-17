"""Lists the AI models to pick from, which needs no agent to run."""

from typing import cast

import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model import intelligence_models
from modeling_3d.cli import app
from modeling_3d.schemas import (
    REASONING_EFFORTS,
    IntelligenceChoice,
    IntelligenceModels,
    Modeling3dError,
    ReasoningEffort,
)

runner = CliRunner()


@pytest.fixture
def only_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: agent_provider == "claude")


def test_it_offers_sonnet_and_opus_at_every_effort_with_the_default(only_claude: None) -> None:
    options = lib.list_intelligence_models()

    assert [(model.id, model.label) for model in options.models] == [
        ("claude-sonnet-5-5", "Sonnet 5.5"),
        ("claude-opus-5-5", "Opus 5.5"),
    ]
    assert options.reasoning_efforts == ["low", "medium", "high", "xhigh", "max"] == list(REASONING_EFFORTS)
    assert options.default == IntelligenceChoice(
        agent_provider="claude", model="claude-sonnet-5-5", reasoning_effort="medium"
    )


def test_without_an_agent_provider_it_offers_no_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: False)

    assert lib.list_intelligence_models().models == []


async def test_a_reasoning_effort_that_is_not_one_names_the_ones_that_are() -> None:
    with pytest.raises(Modeling3dError) as failure:
        await lib.create_3d_model("A bear", name="bear", reasoning_effort=cast(ReasoningEffort, "extreme"), detach=True)

    assert failure.value.reason == "bad-reasoning-effort"
    assert "Pass one of: low, medium, high, xhigh, max." in str(failure.value)


def test_the_cli_prints_the_options_as_json(only_claude: None) -> None:
    listed = runner.invoke(app, ["list-intelligence-models"])

    assert listed.exit_code == 0, listed.output
    assert IntelligenceModels.model_validate_json(listed.stdout) == lib.list_intelligence_models()
