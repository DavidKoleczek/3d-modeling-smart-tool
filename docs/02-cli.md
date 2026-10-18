# CLI Reference

The CLI is a thin wrapper over the [library](01-library.md): one command per capability, taking the same arguments under the same names, and doing nothing the library does not. 
What each argument means and what a capability returns or raises is documented there. This page covers only what the CLI adds: the invocation shape, and what reaches stdout, stderr, and the exit code.

Results go to stdout and diagnostics to stderr. A failure the library can name prints its message to stderr and exits 1; a bad invocation exits 2.

`modeling-3d --version` (or `-V`) prints the distribution name and its installed version.

## Help

```
modeling-3d -h                 terse summary for a person: the commands, a line each
modeling-3d --help             the tool's skill, written for an agent driving it
modeling-3d <command> -h       terse summary of one command: its arguments and defaults
modeling-3d <command> --help   that command's skill, written for an agent about to call it
```

`--help` on the tool prints what `lib.skill()` returns and on a command what `lib.skill("<command>")` returns; the CLI adds nothing of its own.

## modeling-3d manifest

```bash
modeling-3d manifest
```

`lib.load_manifest()`, printed as JSON.

## modeling-3d app

```bash
modeling-3d app [--port <n>] [--directory <dir>]
```

`lib.app_server().open()`, with its URL printed. The command then keeps serving until Ctrl+C, which exits 0; runs started in the app go on after. Exits 1 when `--port` names a held port; without `--port` a free one is chosen.

## modeling-3d create-3d-model

```bash
modeling-3d create-3d-model PROMPT --name <name> [--directory <dir>] [--reference <path>]...
    [--resume-session true|false|<session id>] [--agent-provider claude] [--model <model>]
    [--reasoning-effort medium] [--timeout-seconds 3600] [--detach]
```

`lib.create_3d_model()`, run to its end. Each event is printed to stdout as one JSON line; the last is `finished` or `failed`, carrying the result in `data`. Exits 0 when the result's `status` is `done`, otherwise 1. A failure before the agent starts exits 1 with its message on stderr.
Ctrl+C, and every other signal that ends the process, stops the run at once, and its session can still be resumed.
`--resume-session` takes `true`, `false`, or a session id, the values of `resume_session`.
With `--detach`, it prints the `started` event and exits 0 once the agent runs, and the run goes on in a process of its own.
Run from Claude Code, the origin is `claude-code:` and the session's `CLAUDE_CODE_SESSION_ID`, so the model's activity shows which session asked.

A run takes minutes, so start it in the background with its output in a file, rather than waiting on it. Read the file to follow it, and steer or stop the run from the foreground meanwhile:

```bash
modeling-3d create-3d-model "A low poly bear" --name bear > bear.jsonl 2> bear.err &
tail -f bear.jsonl
modeling-3d steer-3d-model --name bear --message "Rounder ears"
```

An agent harness with its own way to run a command in the background can use that instead of `&`; the output still goes to the file. The model's `runs/<run id>/events.jsonl` holds the same events, so the run can be followed from there too.

## modeling-3d steer-3d-model

```bash
modeling-3d steer-3d-model --name <name> --message <text> [--directory <dir>]
```

`lib.steer_3d_model()`, with the origin from `CLAUDE_CODE_SESSION_ID` as for `create-3d-model`. Prints nothing; exits 1 when nothing is working on the model.

## modeling-3d cancel-3d-model

```bash
modeling-3d cancel-3d-model --name <name> [--directory <dir>]
```

`lib.cancel_3d_model()`. Prints nothing; exits 1 when nothing is working on the model.

## modeling-3d list-3d-models

```bash
modeling-3d list-3d-models [--directory <dir>]
```

`lib.list_3d_models()`, printed as JSON. Exits 1 when the directory is a file.

## modeling-3d read-3d-model-activity

```bash
modeling-3d read-3d-model-activity --name <name> [--after <cursor>] [--directory <dir>]
```

`lib.read_3d_model_activity()`, printed as JSON. Exits 1 when there is no model by that name, or `--after` is not a cursor into its activity.

## modeling-3d read-3d-model-tool-call

```bash
modeling-3d read-3d-model-tool-call --name <name> --run <run_id> --id <id> [--directory <dir>]
```

`lib.read_3d_model_tool_call()`, printed as JSON. Exits 1 when there is no model by that name, or its run has no call with that id.

## modeling-3d view-3d-model

```bash
modeling-3d view-3d-model --name <name> [--directory <dir>]
```

`lib.view_3d_model()`, the model's summary printed as JSON. Exits 1 when there is no model by that name.

## modeling-3d add-blender-to-path

```bash
modeling-3d add-blender-to-path [--blender-path <path>]
```

`lib.add_blender_to_path()`, its result printed as JSON. Exits 1 when no Blender is found.

## modeling-3d mcp

```bash
modeling-3d mcp [--directory <dir>]
```

`modeling_3d.adapters.mcp.run_stdio()`, the app as an MCP App, for MCP clients that launch the server themselves. stdin and stdout carry only MCP messages until the client disconnects.

## Adding a command

Each command gets a section here: the invocation shape with its options and defaults, which library function it calls, and what it prints and exits with. Argument meanings belong in the library reference, not here.
