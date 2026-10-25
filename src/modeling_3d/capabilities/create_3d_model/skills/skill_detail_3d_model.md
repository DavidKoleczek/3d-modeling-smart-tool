`detail-3d-model` has an agent paint the surface detail of a model that `create-3d-model` has
built. The agent changes the model's `model.py`, keeping its shape, rig, and colors:

- It paints one grayscale texture from the geometry, such as seams, fasteners, highlights along
  edges, and wear, so a later change to a part repaints it.
- It unwraps the faces the detail covers on the second set of texture coordinates, at a density
  set by the largest size on screen, and points every other face at a neutral patch.
- It saves the texture beside `model.glb` as `model-detail.png`, and the material declares it,
  as `check-3d-model` describes, since glTF has no place for it.

A renderer multiplies the base color by twice the detail, so mid gray leaves a color as it is and one
texture works in every color scheme. The agent follows the project's guidance on how much to
paint, and finishes by listing what it painted where. It works to the model's own budgets, has
`check-3d-model` as a skill, and is checked as it finishes, as for `create-3d-model`. The run
ends once the detail is painted.

A detailing is a run of the model like any other: steer it with `steer-3d-model`, stop it with
`cancel-3d-model`, follow it with `read-3d-model-activity`, and leave it going with `--detach`.
A shape change, a rig, or a coloring of a detailed model keeps its detail working.

```bash
# the agent works out what to paint
modeling-3d detail-3d-model --name truck

# wear taken from a photo
modeling-3d detail-3d-model "Chipped paint like this, mostly on the edges" --name truck --reference wear.jpg

# a change, continuing the session that painted it
modeling-3d detail-3d-model "Make the mud reach twice as far" --name truck --resume-session true
```

```python
from modeling_3d.lib import detail_3d_model

run = await detail_3d_model("truck", "Add a seam around the hood")
result = await run.result()
result.status, result.files
```

## Sessions

A detailing starts a fresh session by default, which reads `model.py`. `--resume-session`
continues one as for `create-3d-model`. Continuing a session that last worked in another mode
works too: the agent is told the detailing's instructions, which that session has not had.

## Arguments

- `PROMPT`: optional. The detail wanted, or what to change in it.
- `--name NAME`: required. A model in the directory that has been built.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.
- `--reference PATH`: a file or folder to work from, repeatable, as for `create-3d-model`.
- `--resume-session S`: `false` (the default) for a fresh session, `true` to continue the model's
  last one, or the id of one of its sessions.
- `--agent-provider P`, `--model M`, `--reasoning-effort E`, `--timeout-seconds N`, `--detach`: as
  for `create-3d-model`.

## Result

One JSON line per event on stdout, as for `create-3d-model`. The `started` event's `data` has
`mode` `detail`, and the last line is `finished` or `failed`, whose `next` is the
`detail-3d-model` command that goes on in the same session. Exits 0 when `status` is `done`,
otherwise 1. A model that is not built yet is refused, naming the command that builds it.
