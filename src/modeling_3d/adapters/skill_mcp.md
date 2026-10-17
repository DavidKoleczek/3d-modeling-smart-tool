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
- `reply` with `text`: shows `text` in every open view, on the view's next poll.
- `app_updates` with `after`: the agent's messages past the first `after`, which the view polls.
- `app_message` with `text`: hands the agent a message from the browser host page.
- `list_3d_models` and `view_3d_model` with `name`: the library's, on the app's directory,
  which the view polls and calls when the person picks a model.

All but the first two are listed only to hosts that render MCP Apps, with
`visibility: ["app"]`, so no model sees them.

## Resources

- `ui://modeling-3d/app`: the view.
- `modeling-3d://models/{name}/{+path}`: a model's `model.glb` or one of its renders, as a
  base64 blob, which the view reads to show it. Nothing else in the directory can be read.

## Where the user's messages go

1. In a host that renders MCP Apps, such as VS Code, the view sends them as `ui/message`, and
   the host adds them to the conversation.
1. In Claude Code, which does not render MCP Apps, the user opens the URL. The page there is an
   MCP Apps host for the same view, connected to this server at the page's `/mcp`. It hands each
   message to `app_message`, and the server posts it into the inbox of the session that launched
   it, from `CLAUDE_CODE_MESSAGING_SOCKET` and `CLAUDE_CODE_MESSAGING_TOKEN`. An idle session
   starts a turn with it; a busy one reads it between tool calls. It arrives as a
   [message from another session](https://code.claude.com/docs/en/cross-session-messaging),
   so it cannot approve anything.
1. Anywhere else, they come back with the result of the agent's next `reply` or `open_app`.
