# Contributing to Modeling 3D

## Development Setup

### Prerequisites

Install:

- [Git](https://git-scm.com/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/): Manages Python environments
- [prek](https://github.com/j178/prek): Used for precommit hooks. Recommended to install through PyPI/uv with `uv tool install prek`. Use `uv tool upgrade prek` to update it.
- [Node.js](https://nodejs.org/) 22+ and [pnpm](https://pnpm.io/installation), optional: only to change the app's frontend. The compiled app is committed, so running it needs neither.
- [Codex CLI](https://github.com/openai/codex) [signed in](https://developers.openai.com/codex/auth) with ChatGPT or an API key, for intelligent features through the `codex` agent provider.
- [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/quickstart), for intelligent features through the `claude` agent provider.

### Initial Setup

1. Clone this repository and change into it.

1. Run the development installation script (sets up the uv env, precommit hooks, and the `reference/` clones):

   ```bash
   uv run setup-for-dev.py
   ```

### Essential Development Commands

*Commands should be run from the repository root, unless otherwise specified.*

#### Precommit hooks

Setup precommit hooks:

```bash
prek install
```

Run precommit hooks manually:

```bash
prek run --all-files
```

#### Python Library Development

Create uv virtual environment and install dependencies:

```bash
uv sync --frozen --all-extras --all-groups
```

To update dependencies and the lock file:

```bash
uv sync -U --all-extras --all-groups
```

Lint code:

```bash
uv run ruff check --fix --config pyproject.toml
```

Format code (also formats code blocks in .md files):

```bash
uv run ruff format --config pyproject.toml
```

Type check:

```bash
uv run ty check .
```

Run tests:

```bash
uv run pytest
```

#### App Development

`app/` holds the app's frontend, Vite, TypeScript, React, Tailwind, and Base UI, in two builds:

- The MCP App view, entry `mcp_app.html`, compiled to the single file `src/modeling_3d/capabilities/app/static/view/mcp_app.html`, which hosts load as one resource.
- The browser host page and its sandbox proxy, plain TS in `app/host/`, compiled to `src/modeling_3d/capabilities/app/static/host/`. They render the view the way any MCP Apps host does, for agents that can't embed it.

Both are vendored, so the tool installs and runs with no Node present.
The design tokens, light and dark, live in `app/src/theme.css`, and `app/src/index.css` maps them into Tailwind, so classes name only tokens.
The `app-lint`, `app-format`, `app-typecheck`, and `app-build` precommit hooks each run one step through `uv run build-app.py` whenever `app/` changes: with pnpm present it installs and runs that step; without pnpm it says so and passes.

Install dependencies (also done by `setup-for-dev.py` when pnpm is present):

```bash
pnpm --dir app install --frozen-lockfile
```

Serve the app on its own, then rebuild whichever side changed and reload the browser, since the server reads both on every request:

```bash
uv run modeling-3d app --port 5199

# Host page or sandbox
pnpm --dir app build

# View
pnpm --dir app build:view
```

Lint, format, and type check:

```bash
pnpm --dir app check
```

Check and compile both into the package, then commit them:

```bash
uv run build-app.py
```

#### References

`reference/` holds gitignored clones of the repositories worth reading while developing this tool. `uv run setup-for-dev.py` clones any that are missing.

#### Conformance

Run the spec's [conformance kit](https://github.com/microsoft/amplifier-smart-tools/tree/main/conformance) against this repository.
The outer `uv run` puts this project's `modeling-3d` on `PATH` for the kit to invoke; the inner one runs the kit with its own inline dependencies:

```bash
uv run -- uv run --no-project https://raw.githubusercontent.com/microsoft/amplifier-smart-tools/main/conformance/run.py .
```
