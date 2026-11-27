# Contributing to 3D Modeling

## Development Setup

### Prerequisites

Install:

- [Git](https://git-scm.com/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/): Manages Python environments
- [prek](https://github.com/j178/prek): Used for precommit hooks. Recommended to install through PyPI/uv with `uv tool install prek`. Use `uv tool upgrade prek` to update it.
- [Node.js](https://nodejs.org/) 22+ and [pnpm](https://pnpm.io/installation), optional: only to change the app's frontend.
- [Rust](https://rustup.rs/), optional for the Windows app.
- [Codex CLI](https://github.com/openai/codex) [signed in](https://developers.openai.com/codex/auth) with ChatGPT or an API key, for intelligent features through the `codex` agent provider.
- [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/quickstart), for intelligent features through the `claude` agent provider.

### Initial Setup

1. Clone this repository and cd into it.

1. Run the development installation script (sets up the uv env, precommit hooks, the app's dependencies, the Windows app's crates, and the `reference/` clones):

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

They run in parallel, leaving out the slow tests, which start a process or wait out a real timeout. When a change touches the code a slow test covers, run its marker too:

- `mcp_process`: the MCP adapter, `adapters/mcp.py`, the `mcp` command, and `open_app` and which tools a client sees.
- `detached`: detached runs, in `background.py`, how `create.py` starts one, and `DetachedRun` in `runs.py`, and the app's tools that start, steer, and cancel runs.
- `real_timeout`: how a run, or either agent provider, times out.

```bash
uv run pytest -m detached              # one marker's tests
uv run pytest -m ""                    # every test
uv run pytest -n 0 tests/test_app.py   # in one process, as for a debugger
```

A new test that starts a process or waits out real time gets one of these markers, or a new one registered in `pyproject.toml` with the code it covers.

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

#### Windows App

`windows/` holds the Windows installer and app described in [docs/03-windows-app.md](docs/03-windows-app.md).

Format, lint, test, and build `windows/target/release/Modeling3DSetup.exe`:

```bash
uv run build-windows.py
```

To try the exe without installing anything for real, use `--sandbox` and everything will be installed into that folder instead. The registry entries go to `HKCU\Software\Modeling3DSandbox`, which Windows ignores. uv's cache and Pythons are shared with the machine, so the tool isn't downloaded again.

```powershell
# Open setup
windows\target\release\Modeling3DSetup.exe --sandbox temp\windows-sandbox
# Or install without the window. `| Out-Host` makes PowerShell wait for the exe and show what it prints
windows\target\release\Modeling3DSetup.exe --sandbox temp\windows-sandbox --install --workspace temp\windows-sandbox\workspace --desktop-shortcut | Out-Host
# Open the app, which stays in the tray until Quit
temp\windows-sandbox\install\Modeling3D.exe --sandbox temp\windows-sandbox
# Uninstall
windows\target\release\Modeling3DSetup.exe --sandbox temp\windows-sandbox --uninstall --quiet | Out-Host
```

Without `--sandbox`, the same commands install and uninstall for real.

The app looks for a newer version on GitHub. To try an update in the sandbox, set `MODELING_3D_SANDBOX_RELEASE` to an address that answers as GitHub's API does for a repository's latest release. It is read only in a sandbox.

In VS Code, the `Windows app (sandbox)` launch configuration debugs setup in the sandbox, and `Windows app tray (sandbox)` debugs the app once it is installed there.

#### Releases

A release is made when the version changes on main. Bump it, set the same version in `src/modeling_3d/SMART_TOOL.md` and in `metadata.version` of `skills/modeling-3d/SKILL.md`, commit those with `pyproject.toml` and `uv.lock`, and push:

```bash
uv version --bump patch
```

The Release workflow checks that `uv.lock` and the app's committed build are current, builds `Modeling3DSetup.exe`, and publishes it as the release `v<version>`. It doesn't run the tests or the other checks, so run those before pushing. Installed apps offer the update within a day.

#### References

`reference/` holds gitignored clones of the repositories that could be useful to reference. `uv run setup-for-dev.py` clones any that are missing and moves the rest to the latest commit of their branch, keeping local edits.

#### Dependencies

`.agents/skills/dependency-update/SKILL.md` updates the Python, app, and Windows app dependencies, pnpm, the release workflow's actions, and the `reference/` clones within their cooldown and caps.

#### Conformance

Run the spec's [conformance kit](https://github.com/microsoft/amplifier-smart-tools/tree/main/conformance) against this repository.
The outer `uv run` puts this project's `modeling-3d` on `PATH` for the kit to invoke; the inner one runs the kit with its own inline dependencies:

```bash
uv run -- uv run --no-project https://raw.githubusercontent.com/microsoft/amplifier-smart-tools/main/conformance/run.py .
```
