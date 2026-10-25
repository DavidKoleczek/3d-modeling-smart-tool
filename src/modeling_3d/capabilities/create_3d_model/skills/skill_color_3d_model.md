`color-3d-model` has an agent color a model that `create-3d-model` has built, by role. The agent
changes the model's `model.py`, keeping its shape, rig, and surface detail:

- Every mesh gets one material, whose base color texture is a palette: a column for each role and
  a row for each color scheme, embedded in `model.glb`.
- Each face's UVs land on the center of its role's swatch in the default scheme's row, so another
  scheme is another row.
- The roles that glow go in an emission palette of the same layout.
- The material declares the roles and schemes, as `check-3d-model` describes, so the check and
  the app name them.

The agent uses the project's roles and schemes where its guidance names them, may move a part to
another role, and finishes by listing each role's color in each scheme it set or changed. It works
to the model's own budgets, has `check-3d-model` as a skill, and is checked as it finishes, as for
`create-3d-model`. The run ends once the model is colored.

A coloring is a run of the model like any other: steer it with `steer-3d-model`, stop it with
`cancel-3d-model`, follow it with `read-3d-model-activity`, and leave it going with `--detach`.
A shape change, a rig, or a detailing of a colored model keeps its colors working.

```bash
# the agent works out the roles and colors
modeling-3d color-3d-model --name truck

# colors taken from concept art
modeling-3d color-3d-model "Take the colors from the concept's lit faces" --name truck --reference concept.png

# another scheme, continuing the session that colored it
modeling-3d color-3d-model "Add a postal scheme in reds and whites" --name truck --resume-session true
```

```python
from modeling_3d.lib import color_3d_model

run = await color_3d_model("truck", "Make the bumpers dark metal")
result = await run.result()
result.status, result.files
```

## Sessions

A coloring starts a fresh session by default, which reads `model.py`. `--resume-session`
continues one as for `create-3d-model`. Continuing a session that last worked in another mode
works too: the agent is told the coloring's instructions, which that session has not had.

## Arguments

- `PROMPT`: optional. The roles, schemes, or colors wanted, or what to change in them.
- `--name NAME`: required. A model in the directory that has been built.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.
- `--reference PATH`: a file or folder to work from, repeatable, as for `create-3d-model`.
- `--resume-session S`: `false` (the default) for a fresh session, `true` to continue the model's
  last one, or the id of one of its sessions.
- `--agent-provider P`, `--model M`, `--reasoning-effort E`, `--timeout-seconds N`, `--detach`: as
  for `create-3d-model`.

## Result

One JSON line per event on stdout, as for `create-3d-model`. The `started` event's `data` has
`mode` `color`, and the last line is `finished` or `failed`, whose `next` is the `color-3d-model`
command that goes on in the same session. Exits 0 when `status` is `done`, otherwise 1. A model
that is not built yet is refused, naming the command that builds it.
