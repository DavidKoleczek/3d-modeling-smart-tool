`view-3d-model` records a model as the one viewed last in its directory, and prints its summary.
An open app on that directory switches to it within a second, so use it to show the person a
model. `list-3d-models` reports it as `last_viewed`, and the app opens on it next time. The
record is `.state.json` in the models directory.

```bash
modeling-3d view-3d-model --name bear
```

```python
from modeling_3d.lib import view_3d_model

view_3d_model("bear").files
```

The name must match the model's directory exactly. Naming a model that does not exist fails and
names the models there.

## Arguments

- `--name NAME`: the model to record as the one viewed last.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.

## Result

The model's summary as JSON on stdout, the same as one entry of `list-3d-models`' `models`:
`name`, `id`, `directory`, `created`, `updated`, `built`, `status`, `last_run`, `last_session`,
`resumable`, and `files`.
