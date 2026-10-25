`read-3d-model-tool-call` reads one tool call of a model's agent in full: the arguments it was
called with, such as the whole command, edit, or file it wrote, and what came back. The activity
gives each call only by what it works on, so read this when that is not enough, such as for why a
command failed. It only reads, so it is safe while runs are working.

```bash
modeling-3d read-3d-model-tool-call --name bear --run 20261017-100000-ab12cd --id toolu_01
```

```python
from modeling_3d.lib import read_3d_model_activity, read_3d_model_tool_call

tool = next(entry for entry in read_3d_model_activity("bear").entries if entry.kind == "tool")
call = read_3d_model_tool_call("bear", run_id=tool.run_id, call_id=tool.data["id"])
call.input, call.output
```

## Arguments

- `--name NAME`: the model whose agent made the call, exactly as its directory is named.
- `--run RUN_ID`: the `run_id` of the call's `tool` entry in `read-3d-model-activity`.
- `--id ID`: the `id` in that entry's `data`.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.

## Result

JSON on stdout:

```json
{"name": "Bash", "input": {"command": "uv run --script model.py", "description": "Build the model"}, "output": "Exported model.glb", "failed": false}
```

- `name`: the tool, as the agent provider names it.
- `input`: the arguments the agent called it with, as it gave them.
- `output`: what came back, as text with any images left out, or null while the call is still
  running.
- `failed`: whether the call failed, with why in `output`.
