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
- `list_3d_models`, `view_3d_model`, `read_3d_model_activity`, and `read_3d_model_tool_call`: the
  library's, on the app's directory, which the view polls and calls when the person picks a model
  or opens a step.
- `create_3d_model`, `rig_3d_model`, `color_3d_model`, `detail_3d_model`, `steer_3d_model`, and
  `cancel_3d_model`: the library's, on the app's directory with origin `app`, which the view calls
  for the person. `create_3d_model`, `rig_3d_model`, `color_3d_model`, and `detail_3d_model`, the
  request box's Shape, Rig, Color, and Detail modes, always detach, so their runs outlive the
  server, and take the agent provider, model, and reasoning effort the person picked, the models in
  the directory to work from, and the uploads to work from.
- `rename_3d_model` and `delete_3d_model`: the library's, on the app's directory, which the view
  calls once the person confirms. Delete stops a run working on the model first. Both refuse while
  the app's own check of the model runs.
- `check_3d_model`: the library's, against the model's own budgets. A check still going after a
  while returns `{"checking": true}`, and calling again waits on the same check, so a check that
  outlasts a host's time limit for a call still reaches the view. The view reads the report and
  its renders under the model's `checks/` through the model file resource.
- `upload_reference`: a piece of a file or folder the person added, in base64 at an offset in a
  path under an upload id of the view's, so a reference of any size arrives in requests the
  transport takes. Uploads no request took are cleared when the server closes, or a day on by the
  next server to start.
- `list_intelligence_models` and `choose_intelligence_model`: what the view's picker offers, from
  the library's `list_intelligence_models`, and the person's last pick, which the app keeps in
  `.app-state/app.json` in its directory.
- `read_app_settings` and `save_app_settings`: how the person set the app up, its theme, pane
  sizes, and viewport tools, kept for them in every directory in `app-settings.json` in their
  config directory. A setting that is not valid fails with reason `bad-settings`.
- `read_activity_steps` and `save_activity_step`: the groups of steps the person opened or closed
  in each model's activity, kept for the app's directory in `.app-state/steps.json`, which forgets
  those of models no longer there.
- `read_app_folders` and `open_app_folder`: where the app keeps the person's settings and the
  models it shows, and opening the folder of either, or of one model, in the person's file manager.
- `read_app_library` and `save_app_pins`: what the view offers to start a request from. The
  references, folders, and prompts the person pinned in the app's directory, the last 50 files and
  folders used there, chosen there or given to its models, and the last prompt a model was created
  from there are kept in `.app-state/app.json` in that directory; pins that are not valid fail with reason
  `bad-pins`.
- `choose_reference_files` and `choose_reference_folder`: the platform's file and folder dialogs,
  opened where files were last chosen from. Files chosen are staged as uploads and remembered as
  used.
- `stage_reference_files`, `list_reference_folder`, and `keep_upload`: staging files and folders
  on this machine by path as uploads, as `upload_reference` does for those the person sends; what
  is in a folder pinned to show its files; and keeping a copy of a dropped or pasted upload to pin,
  cleared once it is unpinned.

All but `open_app` are listed only to hosts that render MCP Apps, with `visibility: ["app"]`, so
no model sees them.

## Resources

- `ui://modeling-3d/app`: the view.
- `modeling-3d://models/{name}/{+path}`: a model's `model.glb`, one of its renders, a reference
  image it was given, or its latest check's report and renders, as a base64 blob, which the view
  reads to show it. Nothing else in the directory can be read.
- `modeling-3d://references/{+path}`: an image the view's library offers, by its absolute path, as
  a base64 blob: one pinned, in a folder pinned to show its files, used in the app's directory, or
  given to a model there. No other path can be read.

## What the person does in the app

The person creates models, asks for changes, and steers and stops runs in the app, and the view
calls the capabilities for each itself. Nothing is sent to the session, whether the app is inline
or in the browser. The session sees what they did by reading a model's activity with
`modeling-3d read-3d-model-activity --name <name>`, which shows each request and steering message
with who sent it, so it reads that before acting on a model. What the session does shows in the
app the same way, as from Claude Code.
