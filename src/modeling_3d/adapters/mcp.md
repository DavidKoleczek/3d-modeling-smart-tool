`mcp` runs the tool's MCP server over stdio, as a Claude Code
[channel](https://code.claude.com/docs/en/channels-reference): two tools that open the app and
reply in it, and the messages a person types in the app pushed into the session. It reads and
writes MCP messages on stdin and stdout until the client disconnects, then stops the app.

Configure the client to launch the command `modeling-3d` with the single argument `mcp`; the
client owns the process. Do not run it yourself in a terminal: it waits for an MCP client on
stdin. Nothing is served until `open_app` is called, so each session gets its own app on its
own free port, and a session that never opens it binds nothing.

```json
{ "mcpServers": { "modeling-3d": { "command": "modeling-3d", "args": ["mcp"] } } }
```

```bash
# custom channels are not on the research preview allowlist, so they load through the development flag
claude --dangerously-load-development-channels server:modeling-3d
```

The library has no `mcp` function. The command calls `run_stdio()` in
`modeling_3d.adapters.mcp`, which wraps `serve_app` from the library.

## Tools

- `open_app`: serves the app, the same page `modeling-3d app` serves, and returns its URL.
  Calling it again returns the same URL.
- `reply` with `text`: shows `text` on every open page of the app. Answers `sent`, or says no
  page is open.

The server declares the `claude/channel` capability. Each message typed in the app is sent as a
`notifications/claude/channel` notification with the message as `content`, which Claude Code
shows the model as a `<channel>` event.

## Failures

`reply` before `open_app` fails as a tool error naming the fix. A session started without the
server in `--channels` or `--dangerously-load-development-channels` still gets both tools, but
Claude Code drops the messages from the app without an error. Channels also need Claude Code's
feature flags, so a session with `DISABLE_TELEMETRY` or
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` set reports that channels are not available.

The server stays on MCP SDK 1.x: Claude Code does not register a channel that negotiates
protocol revision 2026-07-28, which SDK 2.x speaks.
