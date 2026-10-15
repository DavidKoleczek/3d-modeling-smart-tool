"""Picks the agent provider and the model with the installed SDKs faked, so it runs on a bare install."""

from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest

from modeling_3d.intelligence import interface
from modeling_3d.intelligence.interface import resolve_agent_provider, select_intelligence
from modeling_3d.intelligence.schemas import AgentRequest, AgentResult
from modeling_3d.schemas import AGENT_PROVIDERS, DEFAULT_INTELLIGENCE_MODELS, AgentProvider, Modeling3dError


class FakeIntelligence:
    def __init__(self) -> None:
        self.implementation = "fake"

    def preflight(self) -> None:
        pass

    def run(self, request: AgentRequest) -> AgentResult:
        return AgentResult()


def only_installed(monkeypatch: pytest.MonkeyPatch, *agent_providers: AgentProvider) -> None:
    modules = {interface.SDK_MODULES[agent_provider] for agent_provider in agent_providers}

    def find_spec(name: str) -> ModuleSpec | None:
        return ModuleSpec(name, None) if name in modules else None

    monkeypatch.setattr(interface, "find_spec", find_spec)


@pytest.mark.parametrize("first", range(len(AGENT_PROVIDERS)))
def test_without_a_name_the_first_installed_in_order_is_picked(monkeypatch: pytest.MonkeyPatch, first: int) -> None:
    only_installed(monkeypatch, *AGENT_PROVIDERS[first:])

    assert resolve_agent_provider() == AGENT_PROVIDERS[first]


@pytest.mark.parametrize("named", AGENT_PROVIDERS)
def test_a_named_agent_provider_wins_over_the_order(monkeypatch: pytest.MonkeyPatch, named: AgentProvider) -> None:
    only_installed(monkeypatch, *AGENT_PROVIDERS)

    assert resolve_agent_provider(named) == named


@pytest.mark.parametrize(
    ("named", "extras"),
    [
        (None, ["all", "codex", "claude"]),
        ("codex", ["codex"]),
        ("claude", ["claude"]),
    ],
)
def test_a_missing_agent_provider_names_the_install_command(
    monkeypatch: pytest.MonkeyPatch, named: AgentProvider | None, extras: list[str]
) -> None:
    only_installed(monkeypatch)

    with pytest.raises(Modeling3dError) as failure:
        resolve_agent_provider(named)

    message = str(failure.value)
    assert f'uv tool install --editable ".[{extras[0]}]"' in message
    for extra in extras:
        assert f"[{extra}]" in message


def test_an_injected_intelligence_wins_and_needs_no_agent_provider_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    only_installed(monkeypatch)
    fake = FakeIntelligence()

    assert select_intelligence(fake, None, None, DEFAULT_INTELLIGENCE_MODELS) == (
        fake,
        DEFAULT_INTELLIGENCE_MODELS[AGENT_PROVIDERS[0]],
    )
    assert select_intelligence(fake, AGENT_PROVIDERS[-1], None, DEFAULT_INTELLIGENCE_MODELS) == (
        fake,
        DEFAULT_INTELLIGENCE_MODELS[AGENT_PROVIDERS[-1]],
    )
    assert select_intelligence(fake, None, "some-model", DEFAULT_INTELLIGENCE_MODELS) == (fake, "some-model")


@pytest.mark.parametrize("agent_provider", AGENT_PROVIDERS)
def test_without_an_injected_intelligence_the_agent_providers_default_model_is_asked_for(
    monkeypatch: pytest.MonkeyPatch, agent_provider: AgentProvider
) -> None:
    only_installed(monkeypatch, *AGENT_PROVIDERS)
    fake = FakeIntelligence()
    resolved: list[tuple[AgentProvider | None, str | None]] = []

    def resolve(named: AgentProvider | None, model: str | None) -> FakeIntelligence:
        resolved.append((named, model))
        return fake

    monkeypatch.setattr(interface, "resolve_intelligence", resolve)

    selected = select_intelligence(None, agent_provider, None, DEFAULT_INTELLIGENCE_MODELS)

    assert selected == (fake, DEFAULT_INTELLIGENCE_MODELS[agent_provider])
    assert resolved == [(agent_provider, DEFAULT_INTELLIGENCE_MODELS[agent_provider])]


@pytest.mark.parametrize("agent_provider", AGENT_PROVIDERS)
def test_every_installed_agent_provider_resolves_to_its_implementation(agent_provider: AgentProvider) -> None:
    pytest.importorskip(interface.SDK_MODULES[agent_provider])

    intelligence = interface.resolve_intelligence(agent_provider, DEFAULT_INTELLIGENCE_MODELS[agent_provider])

    assert intelligence.implementation


@pytest.mark.parametrize("agent_provider", ["claude"])
def test_state_lives_in_the_platform_state_directory_under_the_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, agent_provider: AgentProvider
) -> None:
    monkeypatch.setattr(interface.sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    assert interface.state_directory(agent_provider) == tmp_path / "modeling-3d" / agent_provider
