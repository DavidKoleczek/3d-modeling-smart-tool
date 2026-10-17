"""The contract every model-backed capability runs through, so the implementation is swappable."""

from collections.abc import AsyncIterator, Callable
from importlib.util import find_spec
import os
from pathlib import Path
import sys
from typing import Protocol

from modeling_3d.core.skill import DISTRIBUTION, repository_url
from modeling_3d.intelligence import claude_steps
from modeling_3d.intelligence.schemas import AgentEvent, AgentRequest, AgentResult, AgentStep, Steering
from modeling_3d.schemas import AGENT_PROVIDERS, AgentProvider, Modeling3dError

# The import each agent provider's SDK answers to; its extra is named after the agent provider.
SDK_MODULES: dict[AgentProvider, str] = {
    "codex": "openai_codex",
    "claude": "claude_agent_sdk",
}


class AgentRun(Protocol):
    """One running agent: what it does as it happens, a way to talk to it, and how it ended."""

    @property
    def session_id(self) -> str | None:
        """The session a later run resumes, once the agent provider has made it; None before."""
        ...

    def events(self) -> AsyncIterator[AgentEvent]:
        """Every event from the start, then live ones until the run ends with `terminal`."""
        ...

    async def steer(self, message: str) -> None:
        """Send a message to the agent while it works; the implementation's `steering` says how it lands."""
        ...

    async def cancel(self) -> None:
        """Stop the run at once, and everything it started; its session can still be resumed."""
        ...

    async def result(self) -> AgentResult:
        """Wait for the run to end."""
        ...


class Intelligence(Protocol):
    """Runs agents against models; the library depends on this contract, never on an SDK."""

    implementation: str
    steering: Steering

    def preflight(self) -> None:
        """Raise Modeling3dError naming exactly what to configure when the implementation cannot run."""
        ...

    async def start(self, request: AgentRequest) -> AgentRun:
        """Start one agent and return once it runs; failures after that end the run with `AgentResult.error`."""
        ...


def installed(agent_provider: AgentProvider) -> bool:
    """Whether the agent provider's SDK is importable, without importing it."""
    return find_spec(SDK_MODULES[agent_provider]) is not None


def resolve_agent_provider(agent_provider: AgentProvider | None = None) -> AgentProvider:
    """The named agent provider when it is installed, else the first installed one in `AGENT_PROVIDERS` order."""
    if agent_provider is not None:
        if not installed(agent_provider):
            raise Modeling3dError(
                f"The {agent_provider} agent provider is not installed. Install modeling-3d with it: "
                f"`uv tool install {_install_source(agent_provider)}`. A project that uses the library runs `uv add` "
                "with the same requirement.",
                "agent-unavailable",
            )
        return agent_provider
    for candidate in AGENT_PROVIDERS:
        if installed(candidate):
            return candidate
    raise Modeling3dError(
        "Model-backed capabilities need an agent provider and none is installed. Install modeling-3d with every "
        f"one: `uv tool install {_install_source('all')}`, or put "
        + " or ".join(f"[{candidate}]" for candidate in AGENT_PROVIDERS)
        + " in place of [all] for just one. Use `uv add` instead of `uv tool install` in a project that uses the "
        "library.",
        "agent-unavailable",
    )


def resolve_intelligence(agent_provider: AgentProvider | None = None, model: str | None = None) -> Intelligence:
    """The shipped implementation for the agent provider `resolve_agent_provider` picks.

    `model` is what its preflight checks, when the implementation can check one before a run.
    """
    match resolve_agent_provider(agent_provider):
        case "codex":
            from modeling_3d.intelligence.codex import CodexIntelligence

            return CodexIntelligence()
        case "claude":
            from modeling_3d.intelligence.claude import ClaudeIntelligence

            return ClaudeIntelligence()


def select_intelligence(
    intelligence: Intelligence | None,
    agent_provider: AgentProvider | None,
    model: str | None,
    default_models: dict[AgentProvider, str],
) -> tuple[Intelligence, str]:
    """The intelligence a capability runs through and the model it asks for.

    An injected intelligence wins over `agent_provider`, which then only picks the default model; with neither
    named, that default is the first agent provider's, since nothing about an injected implementation says which
    agent provider it speaks for.
    """
    if intelligence is None:
        agent_provider = resolve_agent_provider(agent_provider)
        model = default_models[agent_provider] if model is None else model
        return resolve_intelligence(agent_provider, model), model
    return intelligence, default_models[agent_provider or AGENT_PROVIDERS[0]] if model is None else model


def agent_steps(agent_provider: AgentProvider) -> Callable[[AgentEvent, Path], list[AgentStep]]:
    """The agent provider's reader of its events, as kept, into what they show of a run; given the run's workspace.

    An agent provider without one yet shows nothing of what its agent did.
    """
    match agent_provider:
        case "claude":
            return claude_steps.steps
        case "codex":
            return lambda event, workspace: []


def state_directory(agent_provider: AgentProvider) -> Path:
    """The platform's per-user state location for the agent provider, where what a later run resumes lives."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / DISTRIBUTION / agent_provider


# The tool is not published to a package index, so it installs from its repository, or from a clone without one.
def _install_source(extra: str) -> str:
    repository = repository_url()
    if repository is None:
        return f'--editable ".[{extra}]"'
    return f'"{DISTRIBUTION}[{extra}] @ git+{repository}"'
