"""The AI models and reasoning efforts to pick from to run a model's agent."""

from modeling_3d.intelligence.interface import installed
from modeling_3d.schemas import (
    AGENT_PROVIDERS,
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_REASONING_EFFORT,
    INTELLIGENCE_MODELS,
    REASONING_EFFORTS,
    IntelligenceChoice,
    IntelligenceModels,
    Modeling3dError,
)


def list_intelligence_models() -> IntelligenceModels:
    """The models of the installed agent providers, every reasoning effort, and what runs when given neither."""
    # The one `create_3d_model` picks when given no agent provider.
    provider = next((candidate for candidate in AGENT_PROVIDERS if installed(candidate)), AGENT_PROVIDERS[0])
    return IntelligenceModels(
        models=[model for model in INTELLIGENCE_MODELS if installed(model.agent_provider)],
        reasoning_efforts=list(REASONING_EFFORTS),
        default=IntelligenceChoice(
            agent_provider=provider,
            model=DEFAULT_INTELLIGENCE_MODELS[provider],
            reasoning_effort=DEFAULT_REASONING_EFFORT,
        ),
    )


def require_reasoning_effort(reasoning_effort: str) -> None:
    """Raise unless `reasoning_effort` is one, since a caller outside Python can pass any string."""
    if reasoning_effort not in REASONING_EFFORTS:
        raise Modeling3dError(
            f"{reasoning_effort!r} is not a reasoning effort. Pass one of: {', '.join(REASONING_EFFORTS)}.",
            "bad-reasoning-effort",
        )
