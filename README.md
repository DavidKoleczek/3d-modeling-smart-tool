<h1 align="center">3D Modeling Smart Tool</h1>

<p align="center">Describe a 3D model. Watch it get built. Point at what to change.</p>

<p align="center">
  <img src="docs/screenshots/tour.svg" alt="A tour of the app: a model being built, the 3D viewer, renders beside the activity, and a new model" width="800">
</p>

3D Modeling is a [Smart Tool](https://github.com/microsoft/amplifier-smart-tools) that creates and edits 3D models.
Drive it from an agent like Codex or Claude Code and steer and monitor the work from the app.

## Quickstart

Prerequisites:
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- At least one agent provider for building models:
  - `claude`: `ANTHROPIC_API_KEY`, or any of its other supported modes of [authentication](https://code.claude.com/docs/en/agent-sdk/quickstart).
  - `codex`: the [Codex CLI](https://github.com/openai/codex) signed in with ChatGPT or an API key, see [authentication](https://developers.openai.com/codex/auth).

### With an agent

1. Install the tool and the skill that teaches your agent to use it:

   ```bash
   # Choose the provider(s) you want: [all], [claude], or [codex]
   uv tool install "modeling-3d[all] @ git+https://github.com/DavidKoleczek/3d-modeling-smart-tool"
   npx skills add DavidKoleczek/3d-modeling-smart-tool
   ```

1. Start your agent in the directory where the models should live and ask for one:

   > Open the 3D modeling app and make a brown bear like bear.png

The agent opens the app, in your browser or inline in hosts that render [MCP Apps](https://github.com/modelcontextprotocol/ext-apps) and builds the model in `.modeling-3d/bear`.
Keep going from either side:

> Make the snout longer, and give it a cub that works from the bear

> What did I change in the app? Pick up from there.

### Without an agent

```bash
modeling-3d app
```

This serves the app at the printed URL for the models in `.modeling-3d`. Everything an agent can do, you can do from there.

## Command line

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

See the [CLI reference](docs/02-cli.md) for every flag and the [library reference](docs/01-library.md) for the Python surface.

## Installation

(Optional) Install the Smart Tools skill so your agent knows about Smart Tools: `npx skills add microsoft/amplifier-smart-tools`

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
claude mcp remove modeling-3d   # or: codex mcp remove modeling-3d
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to set up your development environment.
