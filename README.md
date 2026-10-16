# Modeling 3D Smart Tool

Creates and edits 3D models from a description of what to build.

This is a [Smart Tool](https://github.com/microsoft/amplifier-smart-tools) which is a library with a thin CLI over it and model-backed capabilities sit behind an interface so many providers can be used.
We support the [OpenAI Codex SDK](https://github.com/openai/codex/tree/main/sdk/python) and the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).

## Installation

Prerequisites:
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- For the model-backed capabilities, one of:
  - `codex` agent provider: the [Codex CLI](https://github.com/openai/codex) signed in with ChatGPT or an API key. See [authentication](https://developers.openai.com/codex/auth).
  - `claude` agent provider: `ANTHROPIC_API_KEY`, or any of its other supported modes of [authentication](https://code.claude.com/docs/en/agent-sdk/quickstart).
- (Optional) Install the Smart Tools skill so your agent knows about Smart Tools: `npx skills add microsoft/amplifier-smart-tools`

To get started, from the root of this repository:

```bash
# Install the Agent Skill so your agent knows about it.
npx skills add .
# Install the tool, choosing the provider(s) you want. Editable, so source changes apply without reinstalling.
uv tool install --editable ".[all | codex | claude]"
# Check the install; needs no credentials
modeling-3d manifest
```

To use it as a library, from another project with its path to this directory:

```bash
uv add --editable "path/to/modeling-3d[all]"
```

To update, from the root of this repository:

```bash
npx skills add .   # add -g for global installs
uv tool upgrade modeling-3d
```

To uninstall:

```bash
npx skills remove modeling-3d   # add -g for global installs
uv tool uninstall modeling-3d
```

## Interface

```bash
# Print the tool's manifest as JSON
modeling-3d manifest

# Serve the app in a browser page, without an agent session; messages sent from it are printed
modeling-3d app

# Serve the app as an MCP App; an MCP client launches this
modeling-3d mcp
```

To steer Claude Code through the app, start `claude` from this directory, where `.mcp.json` loads the server, and ask it to open the app.
Hosts that render MCP Apps, such as VS Code, show it inline instead.

See the [CLI reference](docs/02-cli.md) for every flag and the [library reference](docs/01-library.md) for the Python surface.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to set up your development environment.
