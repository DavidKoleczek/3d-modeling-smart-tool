"""Lists the agent providers with their runtimes faked, so it needs no sign-in and starts no runtime."""

from importlib.machinery import ModuleSpec
from pathlib import Path

from mcp import Client
import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.capabilities.agent_providers import agent_providers
from modeling_3d.cli import app
from modeling_3d.intelligence import interface
from modeling_3d.schemas import AGENT_PROVIDERS, AgentProvider, AgentProviders, AgentProviderStatus, Modeling3dError

runner = CliRunner()


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> dict[AgentProvider, str | None]:
    """How each agent provider's runtime is signed in, None for not, which a test sets."""
    how: dict[AgentProvider, str | None] = dict.fromkeys(AGENT_PROVIDERS)

    def signed_in_with(agent_provider: AgentProvider) -> str:
        if how[agent_provider] is None:
            raise Modeling3dError(f"{agent_provider} has no credentials. Set them up.", "agent-unavailable")
        return str(how[agent_provider])

    monkeypatch.setattr(agent_providers, "agent_signed_in_with", signed_in_with)
    installed(monkeypatch, *AGENT_PROVIDERS)
    return how


def installed(monkeypatch: pytest.MonkeyPatch, *names: AgentProvider) -> None:
    modules = {interface.SDK_MODULES[name] for name in names}

    def find_spec(name: str) -> ModuleSpec | None:
        return ModuleSpec(name, None) if name in modules else None

    monkeypatch.setattr(interface, "find_spec", find_spec)


def test_each_agent_provider_says_whether_it_is_installed_and_how_it_is_signed_in(
    signed_in: dict[AgentProvider, str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    installed(monkeypatch, "claude")
    signed_in["claude"] = "Claude Max"

    claude, codex = lib.list_agent_providers().agent_providers

    assert claude == AgentProviderStatus(
        agent_provider="claude", installed=True, signed_in=True, signed_in_with="Claude Max", problem=None
    )
    assert (codex.agent_provider, codex.installed, codex.signed_in, codex.signed_in_with) == (
        "codex",
        False,
        False,
        None,
    )
    assert codex.problem is not None
    assert "uv tool install" in codex.problem
    assert "[codex]" in codex.problem


def test_one_not_signed_in_says_what_to_configure(signed_in: dict[AgentProvider, str | None]) -> None:
    claude, _ = lib.list_agent_providers().agent_providers

    assert (claude.installed, claude.signed_in, claude.signed_in_with) == (True, False, None)
    assert claude.problem == "claude has no credentials. Set them up."


def test_the_cli_prints_the_list_as_json(signed_in: dict[AgentProvider, str | None]) -> None:
    signed_in["codex"] = "ChatGPT"

    listed = runner.invoke(app, ["list-agent-providers"])

    assert listed.exit_code == 0
    providers = AgentProviders.model_validate_json(listed.stdout).agent_providers
    assert [(status.agent_provider, status.signed_in) for status in providers] == [("claude", False), ("codex", True)]


async def test_the_app_lists_them_for_its_settings(signed_in: dict[AgentProvider, str | None], tmp_path: Path) -> None:
    app_server = lib.app_server(tmp_path)
    try:
        async with Client(f"{app_server.open().url}/mcp") as client:
            before = await client.call_tool("list_agent_providers", {})
            signed_in["claude"] = "Anthropic Console account"
            after = await client.call_tool("list_agent_providers", {})
    finally:
        app_server.close()

    listed = [AgentProviders.model_validate(result.structured_content).agent_providers for result in (before, after)]
    assert [[(status.agent_provider, status.signed_in_with) for status in each] for each in listed] == [
        [("claude", None), ("codex", None)],
        [("claude", "Anthropic Console account"), ("codex", None)],
    ]
