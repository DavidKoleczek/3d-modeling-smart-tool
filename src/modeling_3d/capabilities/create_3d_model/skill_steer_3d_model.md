`steer-3d-model` sends a message to the agent working on a model, from any process: another
shell, an app, or the agent that started the run. The process running the model picks it up
within a second, and the agent reads it when it next takes input, usually after the command it is
running. A `steered` event in the run's output shows when it was delivered.

```bash
modeling-3d steer-3d-model --name bear --message "Make the ears rounder."
```

```python
from modeling_3d.lib import steer_3d_model

steer_3d_model("bear", "Make the ears rounder.")
```

When nothing is working on the model, it fails and names the command that sends the message as a
new request instead. Run from Claude Code, the message is recorded as from
`claude-code:<session id>`, so the model's activity shows which session sent it.

## Arguments

- `--name NAME`: the model being worked on.
- `--message TEXT`: what to tell its agent.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.

## Result

Nothing on stdout; exit 0 once the message is handed over.
