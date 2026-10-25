`rig-3d-model` has an agent rig a model that `create-3d-model` has built, so it can move. The
agent changes the model's `model.py`, keeping its shape and the role of each face:

- Each part that moves on its own, is swapped for another, or is hidden on its own becomes its
  own named object, with its origin at its pivot and its motion declared as `check-3d-model`
  describes, so the check sweeps and poses it and whatever loads it can read its range.
- What bends gets a skeleton it is weighted to, in a neutral rest pose.
- Every other part is joined into one object.
- Named empties mark the points other code uses.

A model with nothing that moves comes out with its parts joined and its points marked. The agent
works to the model's own budgets, has `check-3d-model` as a skill, and is checked as it finishes,
as for `create-3d-model`. The run ends once the model is rigged.

A rig is a run of the model like any other: steer it with `steer-3d-model`, stop it with
`cancel-3d-model`, follow it with `read-3d-model-activity`, and leave it going with `--detach`.
A shape change on a rigged model with `create-3d-model` keeps the rig working, and a rig keeps the
colors `color-3d-model` gave the model and the detail `detail-3d-model` painted.

```bash
# the agent works out what moves
modeling-3d rig-3d-model --name truck

# what moves, and how
modeling-3d rig-3d-model "The tailgate swings down 90 degrees, and the wheels spin" --name truck

# a change to the rig, continuing the session that made it
modeling-3d rig-3d-model "Let the tailgate swing further" --name truck --resume-session true
```

```python
from modeling_3d.lib import rig_3d_model

run = await rig_3d_model("truck", "The tailgate swings down 90 degrees")
result = await run.result()
result.status, result.files
```

## Sessions

A rig starts a fresh session by default, which reads `model.py`. `--resume-session` continues one
as for `create-3d-model`. Continuing a session that last shaped the model works too: the agent is
told the rig's instructions, which that session has not had.

## Arguments

- `PROMPT`: optional. What moves and how, or what to change in the rig.
- `--name NAME`: required. A model in the directory that has been built.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.
- `--reference PATH`: a file or folder to work from, repeatable, as for `create-3d-model`.
- `--resume-session S`: `false` (the default) for a fresh session, `true` to continue the model's
  last one, or the id of one of its sessions.
- `--agent-provider P`, `--model M`, `--reasoning-effort E`, `--timeout-seconds N`, `--detach`: as
  for `create-3d-model`.

## Result

One JSON line per event on stdout, as for `create-3d-model`. The `started` event's `data` has
`mode` `rig`, and the last line is `finished` or `failed`, whose `next` is the `rig-3d-model`
command that goes on in the same session. Exits 0 when `status` is `done`, otherwise 1. A model
that is not built yet is refused, naming the command that builds it.
