`mcp` runs the tool's MCP server over stdio, with the app as an [MCP App](https://github.com/modelcontextprotocol/ext-apps).

Configure the client to launch the command `modeling-3d` with the single argument `mcp`. 
The client owns the process. Do not run it yourself in a terminal: it waits for an MCP client on stdin. 
Nothing is served until `open_app` is called, so each session gets its own app on its own free port, and a session that never opens it binds nothing.

```json
{ "mcpServers": { "modeling-3d": { "command": "modeling-3d", "args": ["mcp"] } } }
```

The library has no `mcp` function. The command calls `run_stdio()` in `modeling_3d.adapters.mcp`, which serves `app_server().server` from the library over stdio.

## Arguments

- `--directory DIR`: where the models the app shows are kept; `.modeling-3d` in the working
  directory when omitted. `open_app` can switch it.

## Tools

- `open_app` with an optional `directory`: serves the app and returns its browser URL. Its
  `_meta.ui.resourceUri` names the view, so a host that renders MCP Apps shows it inline. A
  client that takes URL elicitation, such as Claude Code, is asked to open the URL in the
  browser. Calling it again returns the same URL. `directory` switches which models it shows.
- `list_3d_models`, `view_3d_model`, and `read_3d_model_activity`: the library's, on the app's
  directory, which the view polls and calls when the person picks a model.
- `create_3d_model`, `steer_3d_model`, and `cancel_3d_model`: the library's, on the app's
  directory with origin `app`, which the view calls for the person. `create_3d_model` always
  detaches, so its runs outlive the server, and takes the files to work from as `{name, data}`
  with `data` in base64, and the agent provider, model, and reasoning effort the person picked.
- `list_intelligence_models` and `choose_intelligence_model`: what the view's picker offers, from
  the library's `list_intelligence_models`, and the person's last pick, which the app keeps in
  `.app.json` in its directory.

All but `open_app` are listed only to hosts that render MCP Apps, with `visibility: ["app"]`, so
no model sees them.

## Resources

- `ui://modeling-3d/app`: the view.
- `modeling-3d://models/{name}/{+path}`: a model's `model.glb`, one of its renders, or a
  reference image it was given, as a base64 blob, which the view reads to show it. Nothing else
  in the directory can be read.

## What the person does in the app

The person creates models, asks for changes, and steers and stops runs in the app, and the view
calls the capabilities for each itself. Nothing is sent to the session, whether the app is inline
or in the browser. The session sees what they did by reading a model's activity with
`modeling-3d read-3d-model-activity --name <name>`, which shows each request and steering message
with who sent it, so it reads that before acting on a model. What the session does shows in the
app the same way, as from Claude Code.
