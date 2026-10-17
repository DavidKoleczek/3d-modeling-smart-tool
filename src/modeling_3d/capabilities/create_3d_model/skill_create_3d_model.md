`create-3d-model` has an agent create a 3D model, or change one, as a Blender script. The agent
writes `model.py`, builds `model.glb` with it, renders the result, looks at the renders, and fixes
what does not match, until it is done. Every model has a name, unique in its directory. The same
command changes an existing model with `--edit`.

Blender comes from PyPI through uv, so no Blender install is needed. The first build downloads it,
about 340 MB, into uv's cache. Building runs on Windows, Linux x64, and macOS on Apple silicon.

A run takes minutes. Start it in the background, follow its output, and steer it from another
shell with `steer-3d-model`. Stop it with `cancel-3d-model`, or Ctrl+C in its own terminal.

```bash
# a new model, from a description and a reference image
modeling-3d create-3d-model "A low poly brown bear like the image" --name bear --reference bear.png > bear.jsonl &

# a follow-up right after, in the session that built it
modeling-3d create-3d-model "Make the snout longer" --name bear --resume

# coming back to it later, in a fresh session that reads its model.py
modeling-3d create-3d-model "Make it a polar bear" --name bear --edit
```

```python
from pathlib import Path

from modeling_3d.lib import create_3d_model

run = await create_3d_model("A low poly brown bear like the image", name="bear", references=[Path("bear.png")])
async for event in run.events():
    print(event.kind, event.text)
await run.steer("Make the ears rounder.")  # while it runs
result = await run.result()
result.status, result.directory, result.files
```

To open a model in Blender, run its `model.py` with `--blend <path>`, or import `model.glb`.
`modeling-3d add-blender-to-path` makes an installed Blender a `blender` command.

## Changing a model

A new model's name must not be taken in the directory, ignoring case; a taken name is refused,
and the caller chooses another name or edits the model that has it. To change a model, name it
with `--name`, then choose whether to resume the session that last worked on it:

- Resume with `--resume`, which implies `--edit`, for a follow-up soon after the last run, while that session's context is
  still cached and cheap to continue. Also resume when the last run was cut short, being
  cancelled, timing out, or failing, or when the request refers back to the conversation, such as
  "put the ears back how they were".
- Pass `--edit` alone when coming back to the model later, or once its session has grown long. A fresh
  session reads `model.py`, which holds the whole model as named parts, so it loses only the
  conversation, and starts from a small context instead of one full of earlier renders.

`model.json` records when each run finished. A resumed model runs on the agent provider that made
its session; a fresh session can use any.

## Arguments

- `PROMPT`: what to build, or what to change.
- `--name NAME`: required. The new model's name and directory, not yet taken in the directory, or
  with `--edit` or `--resume` the existing model to change. Letters, digits, `.`, `_`, and `-`.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.
- `--reference PATH`: an image or model to work from, repeatable. Each is copied into the model's
  `references/`, and images are also shown to the agent with the prompt.
- `--edit`: change the existing model named by `--name`, in a fresh session that reads its
  `model.py` first.
- `--resume`: edit, continuing the session that last worked on the model, for a follow-up soon
  after it. See Changing a model.
- `--agent-provider claude`: only `claude` runs agents for now.
- `--model M`: the agent provider's default when omitted.
- `--reasoning-effort E`: `low`, `medium` (the default), `high`, `xhigh`, or `max`.
- `--timeout-seconds N`: how long the run may take before it is stopped; 3600 by default. A
  stopped run's session can still be resumed.

## Result

One JSON line per event on stdout. `kind` is one of:

- `started`
- `agent`: one message from the agent, as its provider gave it, with the provider's name for it in
  `text`
- `steered`
- `finished`
- `failed`

The last line is `finished` or `failed`. Its `data` is the result: `status` (`done`, `failed`,
`cancelled`, or `timed-out`), `directory`, `files`, the agent's final message in `text`, `error`,
`session_id`, and in `next` the command that goes on changing the model. Exits 0 when `status` is
`done`, otherwise 1.

The model's directory, `<directory>/<name>/`:

```
model.json        marks it as a model made by modeling-3d; every run, its status, process, and session
model.py          the Blender script, with inline dependencies; `uv run --script model.py` rebuilds everything
model.py.lock     the locked dependencies
model.glb         the model
renders/          the renders the agent looked at
references/       the references given
sessions/         a copy of each agent session, which a resume can also start from
runs/<run id>/    events.jsonl, the same events as stdout
```
