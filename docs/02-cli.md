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
modeling-3d app [--port <n>]
```

`lib.serve_app()`, with its URL printed. The command then keeps serving until Ctrl+C, which exits 0. Exits 1 when `--port` names a held port; without `--port` a free one is chosen.

## modeling-3d mcp

```bash
modeling-3d mcp
```

`modeling_3d.adapters.mcp.run_stdio()`, for MCP clients that launch the server themselves. stdin and stdout carry only MCP messages until the client disconnects.

## Adding a command

Each command gets a section here: the invocation shape with its options and defaults, which library function it calls, and what it prints and exits with. Argument meanings belong in the library reference, not here.
