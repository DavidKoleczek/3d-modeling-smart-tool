`list-3d-models` lists the models made in a directory, most recently updated first, with what
state each is in, its files, and the model viewed last there. It only reads, so it is safe while
runs are working. Use it to find a model to change, or to check on runs started elsewhere.

```bash
modeling-3d list-3d-models
modeling-3d list-3d-models --directory models
```

```python
from modeling_3d.lib import list_3d_models

listing = list_3d_models()
[(model.name, model.status) for model in listing.models]
```

A directory that does not exist lists as empty. A model whose `model.json` cannot be read is left
out and named in `unreadable`, with what is wrong with it.

## Arguments

- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.

## Result

JSON on stdout:

```json
{
  "directory": "/work/.modeling-3d",
  "models": [
    {
      "name": "bear",
      "id": "8d3c41f0-...",
      "directory": "/work/.modeling-3d/bear",
      "created": "2026-10-17T10:00:00Z",
      "updated": "2026-10-17T10:28:41Z",
      "status": "done",
      "last_run": {
        "id": "20261017-100000-ab12cd",
        "prompt": "A low poly bear",
        "references": [],
        "resumed": false,
        "agent_provider": "claude",
        "model": "claude-sonnet-5-5",
        "reasoning_effort": "medium",
        "session_id": "5f0e...",
        "status": "done",
        "pid": 1234,
        "started": "2026-10-17T10:00:00Z",
        "last_event": "2026-10-17T10:28:41Z",
        "finished": "2026-10-17T10:28:40Z"
      },
      "files": ["model.py", "model.glb", "model.py.lock", "renders/front.png"]
    }
  ],
  "last_viewed": "bear",
  "unreadable": []
}
```

`last_run` is the last run's entry in the model's `model.json`, and null for a model that never
ran. `status` is the last run's: `running`, `done`, `failed`, `cancelled`, or `timed-out`, or
`crashed` when a run is recorded as running but its process is gone. A crashed model goes on
with `create-3d-model --name <name> --edit`, or `--resume` to continue its session.
`last_viewed` is set by `view-3d-model`, and is null when that model is gone.
