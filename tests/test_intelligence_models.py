"""Lists the AI models to pick from, which needs no agent to run."""

from typing import cast

import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model import intelligence_models
from modeling_3d.cli import app
from modeling_3d.schemas import AgentProvider, IntelligenceChoice, IntelligenceModels, Modeling3dError, ReasoningEffort

runner = CliRunner()


@pytest.fixture
def only_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: agent_provider == "claude")


def test_it_offers_sonnet_and_opus_up_to_max_with_the_default(only_claude: None) -> None:
    options = lib.list_intelligence_models()

    assert [(model.id, model.label, model.reasoning_efforts) for model in options.models] == [
        ("claude-sonnet-5-5", "Sonnet 5.5", ["low", "medium", "high", "xhigh", "max"]),
        ("claude-opus-5-5", "Opus 5.5", ["low", "medium", "high", "xhigh", "max"]),
    ]
    assert options.default == IntelligenceChoice(
        agent_provider="claude", model="claude-sonnet-5-5", reasoning_effort="medium"
    )


def test_with_codex_installed_it_also_offers_sol_and_astra_up_to_ultra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: True)

    options = lib.list_intelligence_models()

    assert [(model.agent_provider, model.id, model.label) for model in options.models] == [
        ("claude", "claude-sonnet-5-5", "Sonnet 5.5"),
        ("claude", "claude-opus-5-5", "Opus 5.5"),
        ("codex", "gpt-6.1-sol", "Sol 6.1"),
        ("codex", "gpt-6-astra", "Astra 6"),
    ]
    assert [model.reasoning_efforts for model in options.models[2:]] == [
        ["low", "medium", "high", "xhigh", "max", "ultra"]
    ] * 2


def test_only_codex_installed_makes_sol_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: agent_provider == "codex")

    options = lib.list_intelligence_models()

    assert [model.id for model in options.models] == ["gpt-6.1-sol", "gpt-6-astra"]
    assert options.default == IntelligenceChoice(agent_provider="codex", model="gpt-6.1-sol", reasoning_effort="medium")


def test_without_an_agent_provider_it_offers_no_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: False)

    assert lib.list_intelligence_models().models == []


async def test_a_reasoning_effort_that_is_not_one_names_the_ones_that_are() -> None:
    with pytest.raises(Modeling3dError) as failure:
        await lib.create_3d_model("A bear", name="bear", reasoning_effort=cast(ReasoningEffort, "extreme"), detach=True)

    assert failure.value.reason == "bad-reasoning-effort"
    assert "Pass one of: low, medium, high, xhigh, max, ultra." in str(failure.value)


@pytest.mark.parametrize(
    ("agent_provider", "model", "efforts"),
    [
        ("claude", "claude-opus-5-5", ("low", "medium", "high", "xhigh", "max")),
        ("claude", "claude-future", ("low", "medium", "high", "xhigh", "max")),
        ("codex", "gpt-6-astra", ("low", "medium", "high", "xhigh", "max", "ultra")),
        ("codex", "gpt-future", ("low", "medium", "high", "xhigh", "max", "ultra")),
    ],
)
def test_a_model_takes_its_own_efforts_or_its_agent_provider_s_when_not_listed(
    agent_provider: AgentProvider, model: str, efforts: tuple[ReasoningEffort, ...]
) -> None:
    assert intelligence_models.reasoning_efforts(agent_provider, model) == efforts


def test_the_cli_prints_the_options_as_json(only_claude: None) -> None:
    listed = runner.invoke(app, ["list-intelligence-models"])

    assert listed.exit_code == 0, listed.output
    assert IntelligenceModels.model_validate_json(listed.stdout) == lib.list_intelligence_models()
