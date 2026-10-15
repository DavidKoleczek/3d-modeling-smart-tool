`app` serves the Modeling 3d app, a chat page on this machine, prints its URL, and keeps
serving until interrupted. Only this machine can reach it.

Run on its own like this, the app is not connected to an agent session: messages typed on the
page show there and go nowhere else. To talk to Claude Code through it, use `mcp`, whose
`open_app` tool serves the same app from inside the session.

```bash
# on a free port; prints the URL, then blocks until Ctrl+C
modeling-3d app

# a fixed port, so a bookmark keeps working
modeling-3d app --port 8788
```

```python
from modeling_3d.lib import serve_app

app = serve_app(on_message=print)
app.url
app.send("hello from the agent")  # shown on every open page; returns how many are open
app.stop()
```

`serve_app` returns once the port is listening, so the URL answers at once. The server runs on
a daemon thread until `stop` or the process exits. `on_message` is called on that thread with
each message typed on the page, so keep it quick.

## Arguments

- `--port N`: the port to bind on `127.0.0.1`. A free one is chosen when omitted.

## Result

The URL on stdout, `http://127.0.0.1:<port>`, then nothing more while it serves. Uvicorn writes
only warnings and errors to stderr.

## Failures

Exits 0 when interrupted with Ctrl+C. Exits 2 on a bad invocation, such as a `--port` that is
not a number. Exits 1 before printing the URL when the port cannot be bound, most often because
`--port` is held by another process; omit `--port` to have a free one chosen.
