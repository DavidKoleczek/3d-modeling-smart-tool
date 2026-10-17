`cancel-3d-model` stops the run working on a model, from any process. The process running it
stops its agent at once, along with every command the agent started, and ends with a `finished`
event whose status is `cancelled`. Its session can still be resumed, with `create-3d-model --name
<name> --resume`.

```bash
modeling-3d cancel-3d-model --name bear
```

```python
from modeling_3d.lib import cancel_3d_model

cancel_3d_model("bear")
```

## Arguments

- `--name NAME`: the model being worked on.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.

## Result

Nothing on stdout; exit 0 once the stop is asked for. The run ends within a few seconds.
