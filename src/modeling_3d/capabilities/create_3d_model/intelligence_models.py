"""The AI models and reasoning efforts to pick from to run a model's agent."""

from modeling_3d.intelligence.interface import installed
from modeling_3d.schemas import (
    AGENT_PROVIDERS,
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_REASONING_EFFORT,
    INTELLIGENCE_MODELS,
    PROVIDER_REASONING_EFFORTS,
    REASONING_EFFORTS,
    AgentProvider,
    IntelligenceChoice,
    IntelligenceModels,
    Modeling3dError,
    ReasoningEffort,
)


def list_intelligence_models() -> IntelligenceModels:
    """The models of the installed agent providers, each with its reasoning efforts, and what runs when given neither."""
    # The one `create_3d_model` picks when given no agent provider.
    provider = next((candidate for candidate in AGENT_PROVIDERS if installed(candidate)), AGENT_PROVIDERS[0])
    return IntelligenceModels(
        models=[model for model in INTELLIGENCE_MODELS if installed(model.agent_provider)],
        default=IntelligenceChoice(
            agent_provider=provider,
            model=DEFAULT_INTELLIGENCE_MODELS[provider],
            reasoning_effort=DEFAULT_REASONING_EFFORT,
        ),
    )


def reasoning_efforts(agent_provider: AgentProvider, model: str) -> tuple[ReasoningEffort, ...]:
    """What `model` takes: its own efforts when the tool lists it, else every one its agent provider has."""
    listed = next((candidate for candidate in INTELLIGENCE_MODELS if candidate.id == model), None)
    if listed is not None and listed.agent_provider == agent_provider:
        return tuple(listed.reasoning_efforts)
    return PROVIDER_REASONING_EFFORTS[agent_provider]


def require_reasoning_effort(
    reasoning_effort: str, agent_provider: AgentProvider | None = None, model: str | None = None
) -> None:
    """Raise unless `reasoning_effort` is one `model` takes, or any model when none is named yet, since a caller outside
    Python can pass any string."""
    if agent_provider is None or model is None:
        efforts, what = REASONING_EFFORTS, "a reasoning effort"
    else:
        efforts, what = reasoning_efforts(agent_provider, model), f"a reasoning effort {model} takes"
    if reasoning_effort not in efforts:
        raise Modeling3dError(
            f"{reasoning_effort!r} is not {what}. Pass one of: {', '.join(efforts)}.", "bad-reasoning-effort"
        )
