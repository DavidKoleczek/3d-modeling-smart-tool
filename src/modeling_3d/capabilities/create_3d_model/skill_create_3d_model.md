`create-3d-model` has an agent create a 3D model, or change one, as a Blender script. The agent
writes `model.py`, builds `model.glb` with it, renders the result, looks at the renders, and fixes
what does not match, until it is done. Every model has a name, unique in its directory. Naming a
model that exists changes it; any other name creates a new model.

Blender comes from PyPI through uv, so no Blender install is needed. The first build downloads it,
about 340 MB, into uv's cache. Building runs on Windows, Linux x64, and macOS on Apple silicon.

A run takes minutes. Start it in the background, follow its output, and steer it from another
shell with `steer-3d-model`. Stop it with `cancel-3d-model`, or Ctrl+C in its own terminal.
For a run that should go on by itself, such as one the person follows in the app, pass
`--detach`: it prints the `started` event and returns once the agent runs, and the run goes on in
a process of its own. Follow it with `read-3d-model-activity`.

The person may have changed or steered a model in the app. Read its activity with
`read-3d-model-activity --name <name>` before changing it.

```bash
# a new model, from a description and a reference image
modeling-3d create-3d-model "A low poly brown bear like the image" --name bear --reference bear.png > bear.jsonl &

# a change, in a fresh session that reads its model.py
modeling-3d create-3d-model "Make it a polar bear" --name bear

# a change that continues the session that built it
modeling-3d create-3d-model "Make the snout longer" --name bear --resume-session true

# a change that goes back to an earlier session, by its id
modeling-3d create-3d-model "Put the ears back how they were" --name bear --resume-session 5f0e...

# a cub from the bear's files, left running on its own
modeling-3d create-3d-model "A cub like this bear" --name cub --detach \
    --reference .modeling-3d/bear/model.py --reference .modeling-3d/bear/renders/front.png
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

Name a model that exists, ignoring case, to change it. To make a new model instead, choose a
name no model has; `list-3d-models` lists the names taken.

A change starts a fresh agent session. It reads `model.py`, which holds the whole model as named
parts, so it loses only the conversation, and starts from a small context instead of one full of
earlier renders.

`--resume-session` continues a session instead, so the agent keeps the conversation:

- `true`: the last one. Use it for a follow-up soon after the last run, when the request refers
  back to the conversation ("put the ears back how they were"), or when the last run was cut short.
  A model without a session changes in a fresh one.
- A session id: an earlier session of the model, to go back to what it knew then. Each run's
  session is its `session_id` in the model's `model.json`; `read-3d-model-activity --name <name>`
  gives it on each request, beside that request's prompt, and `list-3d-models` gives the last
  run's.

A continued session runs on the agent provider that made it; a fresh one can use any.

## Arguments

- `PROMPT`: what to build, or what to change.
- `--name NAME`: required. The model's name and directory. A model by that name in the directory
  is changed; any other name creates one. Letters, digits, `.`, `_`, and `-`.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.
- `--reference PATH`: a file to work from, repeatable: an image, a model, or another model's
  `model.py`, `model.glb`, or render. Each is copied into the model's `references/`, and images are
  also shown to the agent with the prompt.
- `--resume-session S`: for a model that exists, `false` (the default) for a fresh session, `true`
  to continue its last one, or the id of one of its sessions. See Changing a model.
- `--agent-provider claude`: only `claude` runs agents for now.
- `--model M`: the agent provider's default when omitted. `list-intelligence-models` lists the
  ones to pick from.
- `--reasoning-effort E`: `low`, `medium` (the default), `high`, `xhigh`, or `max`.
- `--timeout-seconds N`: how long the run may take before it is stopped; 3600 by default. A
  stopped run's session can still be resumed.
- `--detach`: run in a process of its own, which outlives this command, and exit once the agent
  runs.

Run from Claude Code, the request is recorded as from `claude-code:<session id>`, from
`CLAUDE_CODE_SESSION_ID`, so the model's activity shows which session asked.

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
`done`, otherwise 1. With `--detach`, the one line is `started`, whose `data` holds the request,
and it exits 0.

The model's directory, `<directory>/<name>/`:

```
model.json        marks it as a model made by modeling-3d; every run, its status, process, and session
model.py          the Blender script, with inline dependencies; `uv run --script model.py` rebuilds everything
model.py.lock     the locked dependencies
model.glb         the model
renders/          the renders the agent looked at
references/       the references given
sessions/         a copy of each agent session, which a resume can also start from
runs/<run id>/    events.jsonl, the same events as stdout; process.log, what a detached run's process printed
```
