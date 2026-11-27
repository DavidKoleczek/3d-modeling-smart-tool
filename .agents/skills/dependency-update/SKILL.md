---
name: dependency-update
description: Run this to update the Python and app dependencies, pnpm, and the reference clones to the newest versions the cooldown allows.
disable-model-invocation: true
metadata:
  internal: true
---

# Dependency update

All dependencies have a cooldown time. `exclude-newer = "5 days"` under `[tool.uv]` in `pyproject.toml`, and `minimumReleaseAge: 7200` (minutes) in `app/pnpm-workspace.yaml`.
Report every major version upgrade, such as `1.x` to `2.x` or `2.x` to `3.x`, and check whether dependency and peer ranges allow it. Keep the dependency on its current major unless the user approves the upgrade.

## Python

1. Runtime dependencies and extras usually carry a cap at the next major, for example `"mcp>=2.3.0,<3.0.0"`. Some `0.x` dependencies have a cap at the next minor, as FastAPI does. Dev dependencies have no cap.
1. For each dependency in `[project.dependencies]`, `[project.optional-dependencies]`, and `[dependency-groups]`, find the latest version. Read `https://pypi.org/pypi/<name>/json` and take the newest non-prerelease, non-yanked release whose earliest file upload is at least 5 days old. Do not trust the top of the PyPI history page; it ignores the cooldown.
1. Keep Python dependency ranges in `pyproject.toml` broad enough for downstream library users. Record routine upgrades in `uv.lock`. Raise a minimum only when the library or its development checks require a newer version, for example when the code uses a newly introduced API. Keep the existing version format.
1. When the latest eligible `0.x` release crosses a minor cap, review the intervening release notes against the APIs the project uses and check dependency constraints. If the release is compatible, move the cap to the next minor after that release, keep the existing minimum, and verify the update with the affected tests. If the upgrade requires breaking changes or the dependency constraints prevent it, keep the cap and report the blocker.
1. Update `uv_build` under `[build-system]` to the latest eligible version within its current major, moving its cap with it.
1. `[tool.uv.exclude-newer-package]`, when present, exempts packages from the cooldown, with a comment naming the version each was added for. Remove each exception once that version is at least 5 days old.
1. Refresh `uv.lock` even when `pyproject.toml` did not change. Preview `uv lock --upgrade --dry-run` and check the proposed direct and transitive changes for major upgrades, including uncapped development dependencies. If there are no major upgrades, run `uv lock --upgrade`. Otherwise use targeted `uv lock --upgrade-package '<name>==<version>'` updates to keep packages within their current major. Check the resulting lock changes before syncing.
1. Run `uv sync --frozen --all-extras --all-groups`. On Windows this fails with `failed to remove file ... modeling-3d.exe` while an agent session has the `modeling-3d` MCP server running. Either stop that session, or verify in a throwaway environment and tell the user to sync afterwards:

   ```bash
   UV_PROJECT_ENVIRONMENT=temp/.venv-verify uv sync --frozen --all-extras --all-groups
   ```

   Then prefix the checks below with the same variable and delete `temp/.venv-verify` when done.
1. A minimum is only worth keeping low if it works. After changing one, or the code that uses a dependency, check the minimums in a throwaway environment. Name each range from `[project.dependencies]` and `[project.optional-dependencies]` beside the wheel with its `all` extra, since `lowest-direct` only lowers what the command names:

   ```bash
   uv build --wheel -o temp/dist
   uv venv temp/.venv-floor
   uv pip install --python temp/.venv-floor --resolution lowest-direct "<each range>" "$(ls temp/dist/*.whl)[all]"
   ```

   Then check that `modeling-3d --version`, `modeling-3d -h`, and `modeling-3d app` work from `temp/.venv-floor`, with the app opened in a browser. Delete `temp/.venv-floor` after.
1. Run `uv build --wheel -o temp/dist` and confirm the wheel still holds `SMART_TOOL.md` and `capabilities/app/static/`. Delete `temp/dist` after.
1. `.pre-commit-config.yaml` only has local hooks that run through `uv run` and `build-app.py`, so it has no hook versions to bump. If a remote hook repository is ever added, bump its `rev` to its latest release the same way.

## App

1. `packageManager` in `app/package.json` pins pnpm, which pnpm switches to inside `app/`. Find its newest release that is at least 5 days old with `npm view pnpm time --json`, and read the release notes since the pinned one. A new major is a major upgrade like any other. Set that version, then run `pnpm --dir app install`, which pins the same pnpm at the top of `app/pnpm-lock.yaml`.
1. Run `pnpm --dir app outdated`. Its Latest column already respects the cooldown.
1. Note every row whose Latest is a new major (for example `typescript` 6 to 7). For each, check its peers with `pnpm view <package>@<version> peerDependencies`, and the peer ranges of the packages that depend on it, so the report can say whether it is possible today. A common blocker is `typescript-eslint` capping `typescript`.
1. Update everything else, excluding each major by name:

   ```bash
   pnpm --dir app update --latest '!<major-1>' '!<major-2>'
   ```

   Read the output for peer dependency warnings, especially across the React, Vite, and ESLint packages. pnpm runs no dependency's build scripts unless `allowBuilds` in `app/pnpm-workspace.yaml` names it, and fails the install when one has them. Allow a package only if the app needs what its script builds, and deny it otherwise.
1. Run `pnpm --dir app update <package>` for each excluded major, so it still moves to the newest release within its current range.
1. pnpm reads its settings, such as `overrides`, only from `app/pnpm-workspace.yaml`, never from a `pnpm` field in `app/package.json`. If it has `overrides`, make sure each still matches the updated versions, then run `pnpm --dir app install`.
1. Run `uv run build-app.py`. It installs, lints, formats, type checks, and compiles both the host page and the view into `src/modeling_3d/capabilities/app/static/`. Those compiled files are committed, so they are part of the change.

## Finish

1. Run `uv run setup-for-dev.py`. It moves each clone in `reference/` to the latest commit of its branch, so what is read matches the versions just taken.
1. Run `prek run --all-files` and `uv run pytest`; both must pass.
1. Report what moved on each side, any caps widened, every upgrade held back and why, and whether the user still needs to run `uv sync`.
