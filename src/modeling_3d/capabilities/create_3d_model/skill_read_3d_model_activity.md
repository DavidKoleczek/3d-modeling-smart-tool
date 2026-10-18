`read-3d-model-activity` reads everything about how a model is being made: its summary, as
`list-3d-models` gives it, and its activity across every run. The activity is each request and
steering message with who sent it, what the agent said and reasoned, the tools it ran and which
failed, and how each run ended. It is what the app shows beside the model, so it includes what the
person asked for there. It only reads, so it is safe while runs are working.

Read a model's activity before acting on it, since the person may have changed or steered it in
the app. Pass a read's `cursor` as `--after` to the next read for only what came since.

```bash
modeling-3d read-3d-model-activity --name bear
modeling-3d read-3d-model-activity --name bear --after 20261017-100000-ab12cd:48213
```

```python
from modeling_3d.lib import read_3d_model_activity

activity = read_3d_model_activity("bear")
activity.model.status, [(entry.kind, entry.origin, entry.text) for entry in activity.entries]
since = read_3d_model_activity("bear", after=activity.cursor)
```

## Arguments

- `--name NAME`: the model to read, exactly as its directory is named.
- `--after CURSOR`: the `cursor` of an earlier read, for only the activity since.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.

## Result

JSON on stdout: `model`, the summary, the same as one entry of `list-3d-models`' `models`;
`entries`, oldest first; and `cursor`. Each entry has `time`, `run_id`, `kind`, `text`, `origin`,
and `data`:

```json
{"kind": "request", "text": "A low poly bear", "origin": "app", "data": {"references": ["references/bear.png"], "resumed": false, "agent_provider": "claude", "model": "claude-sonnet-5-5", "reasoning_effort": "medium"}}
{"kind": "said", "text": "I'll block out the body first.", "origin": null, "data": {}}
{"kind": "tool", "text": "model.py", "origin": null, "data": {"id": "toolu_01", "name": "Write", "target": "model.py"}}
{"kind": "tool-result", "text": "", "origin": null, "data": {"id": "toolu_01", "failed": false}}
{"kind": "steered", "text": "Make the ears rounder.", "origin": "claude-code:5f0e...", "data": {"steering": "queued"}}
{"kind": "ended", "text": "A low poly bear, with...", "origin": null, "data": {"status": "done", "error": null, "files": ["model.py", "model.glb"]}}
```

- `request`: what a run was asked, in `text`, with the references it was given, a folder's ending
  in `/`, and the model and reasoning effort it ran with.
- `said`: what the agent wrote for the person.
- `reasoning`: the agent started reasoning, as soon as it did. Whatever comes next ends it.
- `thought`: the summary of the reasoning just done, in `text`, when the agent gave one.
- `composing`: a tool call the agent is still writing out, such as a long file, about once a
  second: `id`, `name`, `target` once that much is written, and `characters` so far. The `tool`
  entry with the same `id` follows once it is called. Only claude reports these.
- `tool`: a tool call, with `target`, what it works on: a command's first line, or a file's path
  relative to the model. `read-3d-model-tool-call` gives the call in full.
- `tool-result`: the end of the call with the same `id`; `failed` says whether it failed, with the
  first line of why in `text`. A call with no result yet is still running.
- `usage`: at the end of each turn, what the agent's session has used in all so far, with its
  `session_id`: `cost_usd` on claude, `tokens` on codex, which reports no cost. A resumed
  session's total includes its earlier runs, so the latest of each session, summed across
  sessions, is what the model has used.
- `steered`: a steering message as delivered, or with `error` when it was not.
- `ended`: how a run ended, with the agent's final message in `text`.

`origin` is who sent a request or steering message: `app` for the person in the app,
`claude-code:<session id>` for a Claude Code session, or null when it is not known.
