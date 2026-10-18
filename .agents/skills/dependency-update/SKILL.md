---
name: dependency-update
description: Run this to update the Python and app dependencies to the newest versions the cooldown allows.
disable-model-invocation: true
metadata:
  internal: true
---

# Dependency update

All dependencies have a cooldown time. `exclude-newer = "5 days"` under `[tool.uv]` in `pyproject.toml`, and `minimumReleaseAge: 7200` (minutes) in `app/pnpm-workspace.yaml`.
Never apply a major version upgrade yourself. Collect each one, check whether its peers allow it, and report it at the end for the user to decide.

## Python

1. Notice how we version. Runtime dependencies and extras carry a cap at the next major, for example `"mcp>=2.3.0,<3.0.0"`, so we never auto upgrade to a new major. A 0.x package treats its minor as the major, so its cap is the next minor, for example `"fastapi>=0.143.0,<0.144.0"`. Dev dependencies have no cap.
1. For each dependency in `[project.dependencies]`, `[project.optional-dependencies]`, and `[dependency-groups]`, find the latest version. Read `https://pypi.org/pypi/<name>/json` and take the newest non-prerelease, non-yanked release whose earliest file upload is at least 5 days old. Do not trust the top of the PyPI history page; it ignores the cooldown.
1. Raise each floor that is behind to that version, keeping the form the entry already uses (`>=2.14,<3.0` stays two-part, `>=0.27.3,<0.28.0` stays three-part). Never raise a cap: a latest version at or past the cap is a major upgrade to report.
1. Update `uv_build` under `[build-system]` to the latest version, moving its cap with it. It is the one exception to the cap rule.
1. Run `uv lock --upgrade`. It respects the cooldown and the caps, and moves transitive dependencies too. Do this even when `pyproject.toml` did not change.
1. Run `uv sync --frozen --all-extras --all-groups`. On Windows this fails with `failed to remove file ... modeling-3d.exe` while an agent session has the `modeling-3d` MCP server running. Either stop that session, or verify in a throwaway environment and tell the user to sync afterwards:

   ```bash
   UV_PROJECT_ENVIRONMENT=temp/.venv-verify uv sync --frozen --all-extras --all-groups
   ```

   Then prefix the checks below with the same variable and delete `temp/.venv-verify` when done.
1. Run `uv build --wheel -o temp/dist` and confirm the wheel still holds `SMART_TOOL.md` and `capabilities/app/static/`. Delete `temp/dist` after.
1. `.pre-commit-config.yaml` only has local hooks that run through `uv run` and `build-app.py`, so it has no hook versions to bump. If a remote hook repository is ever added, bump its `rev` to its latest release the same way.

## App

1. Run `pnpm --dir app outdated`. Its Latest column already respects the cooldown.
1. Note every row whose Latest is a new major (for example `typescript` 6 to 7). For each, check its peers with `pnpm view <package>@<version> peerDependencies`, and the peer ranges of the packages that depend on it, so the report can say whether it is possible today. A common blocker is `typescript-eslint` capping `typescript`.
1. Update everything else, excluding each major by name:

   ```bash
   pnpm --dir app update --latest '!<major-1>' '!<major-2>'
   ```

   Read the output for peer dependency warnings, especially across the React, Vite, and ESLint packages.
1. Run `pnpm --dir app update <package>` for each excluded major, so it still moves to the newest release within its current range.
1. If `app/package.json` has a `pnpm.overrides` section, make sure each override still matches the updated versions, then run `pnpm --dir app install`.
1. Run `uv run build-app.py`. It installs, lints, formats, type checks, and compiles both the host page and the view into `src/modeling_3d/capabilities/app/static/`. Those compiled files are committed, so they are part of the change.

## Finish

1. Run `prek run --all-files` and `uv run pytest`; both must pass. Because `app/` may be untracked, also run the app hooks on its files: `prek run --files $(git ls-files -co --exclude-standard app)`.
1. Report what moved on each side, every major upgrade you held back with whether its peers allow it, and whether the user still needs to run `uv sync`.
