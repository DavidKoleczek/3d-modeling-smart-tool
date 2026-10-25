"""Lists the AI models to pick from, which needs no agent to run."""

from typing import cast

import pytest

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model import intelligence_models
from modeling_3d.schemas import (
    AGENT_PROVIDERS,
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_REASONING_EFFORT,
    INTELLIGENCE_MODELS,
    PROVIDER_REASONING_EFFORTS,
    REASONING_EFFORTS,
    AgentProvider,
    IntelligenceChoice,
    Modeling3dError,
    ReasoningEffort,
)


@pytest.mark.parametrize(
    "providers", [("claude",), ("claude", "codex"), ("codex",), ()], ids=["claude", "both", "codex", "none"]
)
def test_it_offers_the_models_of_the_installed_agent_providers_and_defaults_to_the_first_s(
    monkeypatch: pytest.MonkeyPatch, providers: tuple[AgentProvider, ...]
) -> None:
    monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: agent_provider in providers)

    options = lib.list_intelligence_models()

    assert options.models == [model for model in INTELLIGENCE_MODELS if model.agent_provider in providers]
    first = providers[0] if providers else AGENT_PROVIDERS[0]
    assert options.default == IntelligenceChoice(
        agent_provider=first, model=DEFAULT_INTELLIGENCE_MODELS[first], reasoning_effort=DEFAULT_REASONING_EFFORT
    )


async def test_a_reasoning_effort_that_is_not_one_names_the_ones_that_are() -> None:
    with pytest.raises(Modeling3dError) as failure:
        await lib.create_3d_model("A bear", name="bear", reasoning_effort=cast(ReasoningEffort, "extreme"), detach=True)

    assert failure.value.reason == "bad-reasoning-effort"
    assert ", ".join(REASONING_EFFORTS) in str(failure.value)


@pytest.mark.parametrize("agent_provider", AGENT_PROVIDERS)
def test_a_model_not_listed_takes_its_agent_provider_s_efforts(agent_provider: AgentProvider) -> None:
    efforts = intelligence_models.reasoning_efforts(agent_provider, f"{agent_provider}-future")

    assert efforts == PROVIDER_REASONING_EFFORTS[agent_provider]
