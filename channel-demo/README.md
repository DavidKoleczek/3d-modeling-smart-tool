# Channel Demo

A minimal two-way [channel](https://code.claude.com/docs/en/channels-reference): a chat page at http://localhost:8788 that talks to a running Claude Code session.
Messages typed on the page arrive in the session, and Claude answers through the `reply` tool, which shows the answer on the page.

The MCP SDK is pinned to 1.x because Claude Code does not register a channel that negotiates MCP protocol revision 2026-07-28, which SDK 2.0 adds.

Prerequisites: [Bun](https://bun.sh), and Claude Code signed in with a claude.ai account or a Console API key.

1. From this directory, install the dependencies: `bun install`
1. From this directory, start Claude Code with the channel. Custom channels are not on the research preview allowlist, so they load through the development flag:
   ```bash
   claude --dangerously-load-development-channels server:channel-demo
   ```
1. Choose "I am using this for local development", then "Use this MCP server" for `channel-demo` from `.mcp.json`.
1. Open http://localhost:8788 and send a message.

The first `reply` may ask for permission in the terminal. Approve it there, since the page cannot answer permission prompts.
If nothing arrives, run `/mcp` in the session to check the server, or restart with `--debug` and read the log in `~/.claude/debug/`.
