# Modeling 3D Smart Tool

Creates and edits 3D models from a description of what to build.

## Installation

Prerequisites:
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- For the model-backed capabilities:
  - The `claude` agent provider: `ANTHROPIC_API_KEY`, or any of its other supported modes of [authentication](https://code.claude.com/docs/en/agent-sdk/quickstart). 
  - The `codex` agent provider: the [Codex CLI](https://github.com/openai/codex) signed in with ChatGPT or an API key, see [authentication](https://developers.openai.com/codex/auth).
- (Optional) Install the Smart Tools skill so your agent knows about Smart Tools: `npx skills add microsoft/amplifier-smart-tools`

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
# Run the app in background at http://127.0.0.1:8788 (runs even if the shell closes)
# bash
nohup modeling-3d app --port 8788 > /dev/null 2>&1 &
# Stop it on bash
pkill -f "modeling-3d app --port 8788"
# PowerShell
Start-Process modeling-3d -ArgumentList "app", "--port", "8788" -WindowStyle Hidden
# Stop it on PowerShell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8788 -State Listen).OwningProcess

# Create a 3D model in .modeling-3d/bear
modeling-3d create-3d-model "A low poly brown bear like the image" --name bear --reference bear.png

# Change it, in a fresh session that reads its model.py
modeling-3d create-3d-model "Make it a polar bear" --name bear

# Or continuing the session that last worked on it
modeling-3d create-3d-model "Make the snout longer" --name bear --resume-session true

# A cub that works from the bear, left running on its own
modeling-3d create-3d-model "A cub like the bear" --name cub --detach \
    --reference .modeling-3d/bear/model.py --reference .modeling-3d/bear/renders/front.png

# Steer or stop it from another shell while it works
modeling-3d steer-3d-model --name bear --message "Make the ears rounder"
modeling-3d cancel-3d-model --name bear

# What was asked of a model, by whom, and what its agent did, in the app or anywhere else
modeling-3d read-3d-model-activity --name bear

# One of its agent's tool calls in full, by the run_id and id of its entry in the activity
modeling-3d read-3d-model-tool-call --name bear --run 20261017-100000-ab12cd --id toolu_01

# List the models in .modeling-3d, newest first, with their state, and record one as viewed last
modeling-3d list-3d-models
modeling-3d view-3d-model --name bear

# Optionally, make `blender` run your installed Blender, for opening models in it
modeling-3d add-blender-to-path

# Serve the app in the browser
modeling-3d app
modeling-3d app --directory path/to/models

# Serve the app as an MCP App; an MCP client launches this
modeling-3d mcp
```

The app is called 3D Modeling Smart Tool. To use it beside Claude Code, start `claude` from this directory, where `.mcp.json` loads the server, and ask it to open the app.
Hosts that render MCP Apps, such as VS Code, show it inline instead.
What you do in the app is not sent to the session. Any session in the directory sees it by reading a model's activity, and what a session does shows in the app.

See the [CLI reference](docs/02-cli.md) for every flag and the [library reference](docs/01-library.md) for the Python surface.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to set up your development environment.
