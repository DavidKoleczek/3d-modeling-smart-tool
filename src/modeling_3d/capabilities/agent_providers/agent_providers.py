"""The agent providers on this machine: whether each is installed, and whether and how it is signed in."""

from concurrent.futures import ThreadPoolExecutor

from modeling_3d.intelligence.interface import agent_signed_in_with, installed, resolve_agent_provider
from modeling_3d.schemas import AGENT_PROVIDERS, AgentProvider, AgentProviders, AgentProviderStatus, Modeling3dError


def list_agent_providers() -> AgentProviders:
    """Each agent provider, whether it is installed, and whether and how it is signed in."""
    # Each one's runtime is started to ask, which takes a second or so, so they are asked at once.
    with ThreadPoolExecutor(len(AGENT_PROVIDERS)) as pool:
        return AgentProviders(agent_providers=list(pool.map(agent_provider_status, AGENT_PROVIDERS)))


def agent_provider_status(agent_provider: AgentProvider) -> AgentProviderStatus:
    """Whether the agent provider is installed, and whether and how its runtime is signed in."""
    try:
        resolve_agent_provider(agent_provider)
        how = agent_signed_in_with(agent_provider)
    except Modeling3dError as error:
        return AgentProviderStatus(
            agent_provider=agent_provider,
            installed=installed(agent_provider),
            signed_in=False,
            signed_in_with=None,
            problem=str(error),
        )
    return AgentProviderStatus(
        agent_provider=agent_provider, installed=True, signed_in=True, signed_in_with=how, problem=None
    )
