---
smart_tool_format: 1
name: modeling-3d
version: 0.1.0
description: >-
  Creates and edits 3D models from a description of what to build
use_cases:
  - >-
    Creates and edits 3D models from a description of what to build
platforms:
  - linux
  - macos
  - windows
requires:
  - name: codex-sign-in
    purpose: >-
      The Codex CLI signed in with ChatGPT or an API key, for the codex agent provider.
      Without it, the model-backed capabilities cannot run through codex.
    optional: true
    install: https://developers.openai.com/codex/auth
  - name: claude-credentials
    purpose: >-
      ANTHROPIC_API_KEY, or a cloud provider's credentials, for the claude agent provider.
      Without them, the model-backed capabilities cannot run through claude.
    optional: true
    install: https://code.claude.com/docs/en/agent-sdk/quickstart

---

Creates and edits 3D models from a description of what to build.

**The library is the tool.** `modeling_3d.lib` holds every capability. The CLI is a thin
wrapper over it, so anything you can do from the shell you can also do from Python.

## When to reach for it

- Creates and edits 3D models from a description of what to build.

## Before writing code

Every capability has its own skill. Read `modeling-3d <command> --help` before calling it: it
carries the arguments, a worked invocation, the result, and the failures. Do not fill gaps
from memory. The library source beside this file, `lib.py`, carries the signatures. The
repository's `docs/01-library.md` and `docs/02-cli.md` carry the rest.

## Install

Run these from the root of the tool's repository.

```bash
# as a CLI
uv tool install --editable ".[all]"

# as a library, from another project with its path to modeling-3d
uv add --editable "path/to/modeling-3d[all]"

# once, without installing
uvx --from ".[all]" modeling-3d --help
```

`[all]` brings every agent provider the model-backed capabilities run through. Put
`[codex]` or `[claude]` in its place for just one, or drop it for the deterministic
capabilities only.

Verify with `modeling-3d manifest`, which needs no credentials. To upgrade, run
`uv tool upgrade modeling-3d`.

## Prerequisites

Deterministic capabilities need only `uv`. Model-backed capabilities run through an agent
provider, the first installed of `codex` and `claude`:

- `codex`: [OpenAI Codex](https://github.com/openai/codex), with the user's Codex configuration.
  The Codex CLI must be signed in with ChatGPT or an API key, see
  [authentication](https://developers.openai.com/codex/auth).
- `claude`: the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python), with the
  user's Claude Code settings. Needs `ANTHROPIC_API_KEY`, or Amazon Bedrock, Claude Platform on AWS,
  Google Cloud's Agent Platform, or Microsoft Foundry credentials, see
  [authentication](https://code.claude.com/docs/en/agent-sdk/quickstart).

Without one, a model-backed capability fails immediately and names what to configure; it
never falls back to a deterministic answer.

Runs on Linux, macOS, and Windows.

## Straight and smart paths

Deterministic capabilities run with no provider configured. Model-backed capabilities go
through Codex or Claude, and say so in their help text.

## Output and failure contract

Results go to stdout, diagnostics to stderr. A failure prints a message naming what went
wrong and how to fix it, and exits non-zero: 1 for a failure the tool can name, 2 for a
bad invocation. Never treat an empty result as success.

## Choosing a surface

Import the library from Python. Shell out to the CLI from anything that cannot import
Python in-process: a shell script, a CI job, or an agent that can run commands but not
load a Python object. Both reach the same capabilities.
