`app` serves the Modeling 3D app in a browser page on this machine, prints its URL, and keeps
serving until interrupted. Only this machine can reach it.

The app shows the models in one directory: each with its first render, its state, and when it was
last updated. It opens on the model viewed last and renders it in 3D, and reloads it each time a
run rebuilds its GLB. `view-3d-model` from another shell brings a model up in it.

The app's view is an MCP App. The page hosts it the way Claude or VS Code would inline, for
agents that cannot. Run on its own like this, the app is not connected to an agent session, so
each message sent from the page is printed instead. To steer an agent through it, use `mcp`,
whose `open_app` tool serves the same app from inside the session.

```bash
# the models in .modeling-3d here, on a free port; prints the URL, then blocks until Ctrl+C
modeling-3d app

# another models directory, on a fixed port so a bookmark keeps working
modeling-3d app --directory models --port 8788
```

```python
from pathlib import Path

from modeling_3d.lib import app_server, app_view

app = app_server(deliver=print, directory=Path("models"))
app.open().url  # the browser host page, which reaches app.server at its own /mcp
app.say("hello from the agent")  # every open view shows it on its next poll
app.updates(after=0)  # ["hello from the agent"]
app.close()
app_view()  # the view's HTML, the MCP App resource
```

`open` returns once the page is listening, so the URL answers at once, and serves from daemon
threads until `close` or the process exits. `deliver` is called on a worker thread with each
message the user sends from the page.

## Arguments

- `--port N`: the port to bind on `127.0.0.1`. A free one is chosen when omitted.
- `--directory DIR`: where the models to show are kept; `.modeling-3d` in the working directory
  when omitted.

## Result

The URL on stdout, `http://127.0.0.1:<port>`, then nothing more while it serves. Uvicorn writes
only warnings and errors to stderr.
