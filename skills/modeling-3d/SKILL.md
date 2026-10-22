---
name: modeling-3d
description: >-
  Creates and edits 3D models from a description of what to build. Drive it from the command line as `modeling-3d`, or from Python through
  `modeling_3d.lib`. Triggers on "modeling-3d".
license: MIT
metadata:
  version: "0.2.0"
---

# Using modeling-3d

Creates and edits 3D models from a description of what to build.

## Install

The tool installs from its repository, https://github.com/DavidKoleczek/3d-modeling-smart-tool.

```bash
# as a CLI, choosing the agent provider(s) you want: [all], [claude], or [codex]
uv tool install "modeling-3d[all] @ git+https://github.com/DavidKoleczek/3d-modeling-smart-tool"

# as a library, from another project
uv add "modeling-3d[all] @ git+https://github.com/DavidKoleczek/3d-modeling-smart-tool"

# once, without installing
uvx --from "modeling-3d[all] @ git+https://github.com/DavidKoleczek/3d-modeling-smart-tool" modeling-3d --help
```

## Use it

Run `modeling-3d --help`. It prints the tool's skill: when to use it, every capability, sharp
edges, and which files to read. Follow it. Then read the capability's own skill with
`modeling-3d <command> --help` before calling it: it carries the arguments, a worked
invocation, the result, and the failures. Never work from memory.

## Keep it current

Keep the tool up to date for the user by default if the permission mode allows it using `uv tool upgrade modeling-3d`.
Keep the skill up to date for the user with `npx skills update`, adding `-g` for global installs. It was added with `npx skills add DavidKoleczek/3d-modeling-smart-tool`.
Do not try to get around restrictions or operate against the user's preferences to update tools (or skills).
