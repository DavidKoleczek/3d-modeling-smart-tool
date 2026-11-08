`delete-3d-model` deletes a model for good: its directory and everything in it, its `model.py`,
`model.glb`, renders, references, checks, and agent sessions. It cannot be undone, so delete only a
model the person asked to delete.

```bash
modeling-3d delete-3d-model --name bear
```

```python
from modeling_3d.lib import delete_3d_model

delete_3d_model("bear")
```

A run working on the model is stopped first, as `cancel-3d-model` does, and the delete waits up to
15 seconds for it to end. A run that has not ended by then leaves the model whole. Its entry in
`.state.json`, the lines of the models directory's `.gitignore` that opt it in, and the person's
pins of it in the app go with it. Copies other models took of its files as references stay theirs.

The name must match the model's directory exactly. Naming a model that does not exist fails and
names the models there.

## Arguments

- `--name NAME`: the model to delete.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.

## Result

Nothing on stdout; exit 0 once the model is gone.
