`list-intelligence-models` lists the AI models to pick from for `create-3d-model`, each with the
reasoning efforts it takes, and the default it runs with when given neither. The app's picker offers the
same. Pass a pick to `create-3d-model` as `--agent-provider`, `--model`, and `--reasoning-effort`.

```bash
modeling-3d list-intelligence-models
```

```python
from modeling_3d.lib import list_intelligence_models

[model.id for model in list_intelligence_models().models]
```

The models are those of the installed agent providers. `create-3d-model` also takes any other
model the agent provider knows by name, with any reasoning effort that agent provider has.

## Result

JSON on stdout:

```json
{
  "models": [
    {"agent_provider": "claude", "id": "claude-sonnet-5-5", "label": "Sonnet 5.5",
     "reasoning_efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"agent_provider": "claude", "id": "claude-opus-5-5", "label": "Opus 5.5",
     "reasoning_efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"agent_provider": "codex", "id": "gpt-6.1-sol", "label": "Sol 6.1",
     "reasoning_efforts": ["low", "medium", "high", "xhigh", "max", "ultra"]},
    {"agent_provider": "codex", "id": "gpt-6-astra", "label": "Astra 6",
     "reasoning_efforts": ["low", "medium", "high", "xhigh", "max", "ultra"]}
  ],
  "default": {"agent_provider": "claude", "model": "claude-sonnet-5-5", "reasoning_effort": "medium"}
}
```
