`rename-3d-model` renames a model: its directory moves to the new name, and what names it follows,
so every command takes the new name from then on. An open app on that directory follows it.

```bash
modeling-3d rename-3d-model --name bear --new-name grizzly
```

```python
from modeling_3d.lib import rename_3d_model

rename_3d_model("bear", "grizzly").directory
```

Its `model.json`, its latest check's `checks/report.json`, `.state.json`, and the lines of the
models directory's `.gitignore` that opt it in follow the name, as do the person's pins of it in
the app. Its history, such as each run's prompt and events, and its agent's own sources, such as
`model.py`, are left as they are. A session continued with `--resume-session` after the rename is
told where the model is now. Anything outside the models directory that points at the old path,
such as a project's import of its `model.glb`, needs changing by hand.

The name must match the model's directory exactly. The new name uses letters, digits, `.`, `_`,
and `-`, starting with a letter or digit, and no other entry in the directory may hold it, ignoring
case. A run working on the model refuses the rename: stop it with `cancel-3d-model`, or wait for
it to end.

## Arguments

- `--name NAME`: the model to rename.
- `--new-name NEW_NAME`: its new name, which its directory takes.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.

## Result

The model's summary under its new name as JSON on stdout, the same as one entry of
`list-3d-models`' `models`, with the same `id`.
