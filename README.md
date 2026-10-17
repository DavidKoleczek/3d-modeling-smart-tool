# Modeling 3D Smart Tool

Creates and edits 3D models from a description of what to build.

This is a [Smart Tool](https://github.com/microsoft/amplifier-smart-tools) which is a library with a thin CLI over it and model-backed capabilities sit behind an interface so many providers can be used.
We support the [OpenAI Codex SDK](https://github.com/openai/codex/tree/main/sdk/python) and the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).

## Installation

Prerequisites:
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- For the model-backed capabilities:
  - The `claude` agent provider: `ANTHROPIC_API_KEY`, or any of its other supported modes of [authentication](https://code.claude.com/docs/en/agent-sdk/quickstart). 
  - The `codex` agent provider cannot run agents yet.
- (Optional) Install the Smart Tools skill so your agent knows about Smart Tools: `npx skills add microsoft/amplifier-smart-tools`

Install from [the repository](https://github.com/DavidKoleczek/3d-modeling-smart-tool).
While it is private, git needs access to it, for example through `gh auth login`.

```bash
# Install the Agent Skill so your agent knows about it.
npx skills add DavidKoleczek/3d-modeling-smart-tool
# Install the tool, choosing the provider(s) you want: [all], [claude], or [codex].
uv tool install "modeling-3d[all] @ git+https://github.com/DavidKoleczek/3d-modeling-smart-tool"
# Check the install; needs no credentials
modeling-3d manifest
```

To use it as a library, from another project:

```bash
uv add "modeling-3d[all] @ git+https://github.com/DavidKoleczek/3d-modeling-smart-tool"
```

To update:

```bash
npx skills update   # add -g for global installs
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

# Create a 3D model in .modeling-3d/bear
modeling-3d create-3d-model "A low poly brown bear like the image" --name bear --reference bear.png

# A follow-up right after, continuing the session that built it
modeling-3d create-3d-model "Make the snout longer" --name bear --resume

# Coming back to it later, in a fresh session that reads its model.py
modeling-3d create-3d-model "Make it a polar bear" --name bear --edit

# Steer or stop it from another shell while it works
modeling-3d steer-3d-model --name bear --message "Make the ears rounder"
modeling-3d cancel-3d-model --name bear

# Optionally, make `blender` run your installed Blender, for opening models in it
modeling-3d add-blender-to-path

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
