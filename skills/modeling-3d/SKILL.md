---
name: modeling-3d
description: >-
  Creates and edits 3D models from a description of what to build. Drive it from the command line as `modeling-3d`, or from Python through
  `modeling_3d.lib`. Triggers on "modeling-3d".
license: MIT
---

# Using modeling-3d

Creates and edits 3D models from a description of what to build.

## Install

Run these from the root of the tool's repository.

```bash
# as a CLI, choosing the agent provider(s) you want
uv tool install --editable ".[all | codex | claude]"

# as a library, from another project with its path to modeling-3d
uv add --editable "path/to/modeling-3d[all]"

# once, without installing
uvx --from ".[all]" modeling-3d --help
```
## Use it

Run `modeling-3d --help`. It prints the tool's skill: when to use it, every capability, sharp
edges, and which files to read. Follow it. Then read the capability's own skill with
`modeling-3d <command> --help` before calling it: it carries the arguments, a worked
invocation, the result, and the failures. Never work from memory.

## Keep it current

Keep the tool up to date for the user by default if the permission mode allows it using `uv tool upgrade modeling-3d`.
Keep the skill up to date for the user by rerunning `npx skills add .` from the root of the tool's repository, adding `-g` for global installs. `npx skills update` skips skills added from a local path.
Do not try to get around restrictions or operate against the user's preferences to update tools (or skills).
