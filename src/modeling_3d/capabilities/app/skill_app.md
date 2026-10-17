`app` serves the Modeling 3D app in a browser page on this machine, prints its URL, and keeps
serving until interrupted. Only this machine can reach it.

The app shows the models in one directory: each with its first render, its state, and when it was
last updated. It opens on the model viewed last and renders it in 3D, and reloads it each time a
run rebuilds its GLB. `view-3d-model` from another shell brings a model up in it. Beside the model
is its activity: each request and steering message with who sent it, what the agent said and did,
and how each run ended.

The person works there without an agent session. New model starts one from a prompt, files, and
models in the directory. With a model in view, what they write asks for a change, continuing the
model's session unless they switch that off, or steers the run working on it, which Stop ends.
Runs started there go on after the app stops. Nothing done in the app is sent to an agent
session; a session sees it with `read-3d-model-activity`.

The app's view is an MCP App. The page hosts it the way Claude or VS Code would inline, for
agents that cannot. `mcp`'s `open_app` tool serves the same app from inside a session.

```bash
# the models in .modeling-3d here, on a free port; prints the URL, then blocks until Ctrl+C
modeling-3d app

# another models directory, on a fixed port so a bookmark keeps working
modeling-3d app --directory models --port 8788
```

```python
from pathlib import Path

from modeling_3d.lib import app_server, app_view

app = app_server(Path("models"))
app.open().url  # the browser host page, which reaches app.server at its own /mcp
app.close()
app_view()  # the view's HTML, the MCP App resource
```

`open` returns once the page is listening, so the URL answers at once, and serves from daemon
threads until `close` or the process exits.

## Arguments

- `--port N`: the port to bind on `127.0.0.1`. A free one is chosen when omitted.
- `--directory DIR`: where the models to show are kept; `.modeling-3d` in the working directory
  when omitted.

## Result

The URL on stdout, `http://127.0.0.1:<port>`, then nothing more while it serves. Uvicorn writes
only warnings and errors to stderr.
