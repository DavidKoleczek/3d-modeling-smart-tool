"""Command line entry point for Modeling 3D"""

import asyncio
from collections.abc import Callable, Coroutine, Generator
import contextlib
import json
import os
from pathlib import Path
import signal
import time
from types import FrameType
from typing import Annotated, Any

import typer

# Typer 0.27 vendors Click, so a command that overrides Click's own hooks has to speak the vendored types.
from typer._click import Context, Parameter
from typer.core import TyperCommand, TyperOption
from typer.models import CommandFunctionType

from modeling_3d import lib
from modeling_3d.adapters import mcp as mcp_adapter
from modeling_3d.core.skill import DISTRIBUTION
from modeling_3d.schemas import DEFAULT_REASONING_EFFORT, AgentProvider, ModelEvent, Modeling3dError, ReasoningEffort

# Every signal that ends the process stops a run first, so its session stays resumable and nothing it started
# outlives it. SIGHUP is the console closing on Linux and macOS, SIGBREAK on Windows.
STOPPING_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK")
# Claude Code sets it for the commands its sessions run, so what a session asks for shows in the activity as its own.
SESSION_VARIABLE = "CLAUDE_CODE_SESSION_ID"


class CapabilityCommand(TyperCommand):
    """Every capability answers `-h` with the generated summary and `--help` with its skill from the library."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["add_help_option"] = False
        super().__init__(*args, **kwargs)

    def get_params(self, ctx: Context) -> list[Parameter]:
        def short(ctx: Context, param: Parameter, value: bool) -> None:
            if value and not ctx.resilient_parsing:
                typer.echo(ctx.get_help())
                ctx.exit()

        def capability_skill(ctx: Context, param: Parameter, value: bool) -> None:
            if value and not ctx.resilient_parsing:
                typer.echo(lib.skill(self.name))
                ctx.exit()

        return [
            *super().get_params(ctx),
            TyperOption(
                param_decls=["-h"],
                is_flag=True,
                is_eager=True,
                expose_value=False,
                callback=short,
                help="Terse summary of this capability.",
            ),
            TyperOption(
                param_decls=["--help"],
                is_flag=True,
                is_eager=True,
                expose_value=False,
                callback=capability_skill,
                help="This capability's skill, for an agent about to call it.",
            ),
        ]


class SmartToolTyper(typer.Typer):
    """A Typer whose commands are CapabilityCommand by default, so a capability added later inherits the help split."""

    def command(
        self, *args: Any, cls: type[TyperCommand] = CapabilityCommand, **kwargs: Any
    ) -> Callable[[CommandFunctionType], CommandFunctionType]:
        return super().command(*args, cls=cls, **kwargs)


app = SmartToolTyper(
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    # `-h` is the terse summary and `--help` is the skill, at both scopes. On the root, the callback's parameter
    # claims `--help` and Click drops a help option name a parameter already took, which leaves the generated
    # summary on `-h`; on a capability, CapabilityCommand splits the two itself.
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _print_skill(value: bool) -> None:
    """Answer the root `--help` with the skill the library composes, leaving `-h` to Typer."""
    if value:
        typer.echo(lib.skill())
        raise typer.Exit()


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"{DISTRIBUTION} {lib.version()}")
        raise typer.Exit()


@app.callback()
def cli(
    version: Annotated[
        bool,
        typer.Option("--version", "-V", is_eager=True, callback=_print_version, help="Print the version and exit."),
    ] = False,
    help: Annotated[
        bool,
        typer.Option(
            "--help", is_eager=True, callback=_print_skill, help="This tool's skill, for an agent driving it."
        ),
    ] = False,
) -> None:
    """Creates and edits 3D models from a description of what to build"""


@app.command()
def manifest() -> None:
    """Print the tool's manifest as JSON. Deterministic."""
    typer.echo(lib.load_manifest().model_dump_json(indent=2))


@app.command("app")
def app_(
    port: Annotated[int | None, typer.Option(help="The port to bind; a free one is chosen when omitted.")] = None,
    directory: Annotated[
        Path | None,
        typer.Option("--directory", help="Where the models to show are kept; .modeling-3d here when omitted."),
    ] = None,
) -> None:
    """Serve the app in a browser page on this machine and print its URL. Deterministic.

    The person creates, changes, steers, and stops models in it without an agent session. Keeps serving until Ctrl+C;
    runs started in it go on after. Exits 1 with the cause and remedy when the port is held.
    """
    app_server = lib.app_server(directory=directory)
    typer.echo(app_server.open(port).url)
    with contextlib.suppress(KeyboardInterrupt):
        while True:
            time.sleep(1)
    app_server.close()


@app.command()
def create_3d_model(
    prompt: Annotated[str, typer.Argument(help="What to build, or what to change.", show_default=False)],
    name: Annotated[
        str, typer.Option("--name", help="The model's name; a model by that name in the directory is changed.")
    ],
    directory: Annotated[
        Path | None, typer.Option("--directory", help="Where models are kept; .modeling-3d here when omitted.")
    ] = None,
    references: Annotated[
        list[Path] | None,
        typer.Option("--reference", help="A file to work from, such as an image or a model; repeatable."),
    ] = None,
    resume_session: Annotated[
        str,
        typer.Option(
            "--resume-session",
            help="For a model that exists: true to continue its last session, false for a fresh one, or the id of "
            "one of its sessions.",
        ),
    ] = "false",
    agent_provider: Annotated[
        AgentProvider | None, typer.Option("--agent-provider", help="The first installed when omitted.")
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="The agent provider's default when omitted.")] = None,
    reasoning_effort: Annotated[ReasoningEffort, typer.Option("--reasoning-effort")] = DEFAULT_REASONING_EFFORT,
    timeout_seconds: Annotated[int, typer.Option("--timeout-seconds", min=1)] = 3600,
    detach: Annotated[
        bool, typer.Option("--detach", help="Leave the run going in a process of its own once its agent runs.")
    ] = False,
) -> None:
    """Create a 3D model, or change one, printing each event as a JSON line. Model-backed.

    The last line is the `finished` or `failed` event, carrying the result. Exits 0 when the model is done. With
    --detach, prints the `started` event and exits 0 once the agent runs, and the run goes on by itself.
    """
    code = asyncio.run(
        _run_model(
            lib.create_3d_model(
                prompt=prompt,
                name=name,
                directory=directory,
                references=references,
                resume_session={"true": True, "false": False}.get(resume_session.lower(), resume_session),
                agent_provider=agent_provider,
                model=model,
                reasoning_effort=reasoning_effort,
                timeout_seconds=timeout_seconds,
                origin=_origin(),
                detach=detach,
            ),
            detach,
        )
    )
    raise typer.Exit(code)


@app.command()
def steer_3d_model(
    name: Annotated[str, typer.Option("--name", help="The model being worked on.")],
    message: Annotated[str, typer.Option("--message", help="What to tell its agent.")],
    directory: Annotated[
        Path | None, typer.Option("--directory", help="Where models are kept; .modeling-3d here when omitted.")
    ] = None,
) -> None:
    """Send a message to the agent working on a model. Deterministic."""
    lib.steer_3d_model(name=name, message=message, directory=directory, origin=_origin())


@app.command()
def cancel_3d_model(
    name: Annotated[str, typer.Option("--name", help="The model being worked on.")],
    directory: Annotated[
        Path | None, typer.Option("--directory", help="Where models are kept; .modeling-3d here when omitted.")
    ] = None,
) -> None:
    """Stop the run working on a model at once; its session can still be resumed. Deterministic."""
    lib.cancel_3d_model(name=name, directory=directory)


@app.command()
def list_3d_models(
    directory: Annotated[
        Path | None, typer.Option("--directory", help="Where models are kept; .modeling-3d here when omitted.")
    ] = None,
) -> None:
    """List the models in a directory, newest first, with their state, printed as JSON. Deterministic."""
    typer.echo(lib.list_3d_models(directory=directory).model_dump_json(indent=2))


@app.command()
def read_3d_model_activity(
    name: Annotated[str, typer.Option("--name", help="The model to read.")],
    after: Annotated[
        str | None, typer.Option("--after", help="The cursor of an earlier read, for only what came since.")
    ] = None,
    directory: Annotated[
        Path | None, typer.Option("--directory", help="Where models are kept; .modeling-3d here when omitted.")
    ] = None,
) -> None:
    """Print a model's summary and its activity across every run as JSON. Deterministic."""
    typer.echo(lib.read_3d_model_activity(name=name, directory=directory, after=after).model_dump_json(indent=2))


@app.command()
def view_3d_model(
    name: Annotated[str, typer.Option("--name", help="The model to record as the one viewed last.")],
    directory: Annotated[
        Path | None, typer.Option("--directory", help="Where models are kept; .modeling-3d here when omitted.")
    ] = None,
) -> None:
    """Record a model as the one viewed last in its directory, printing its summary as JSON. Deterministic."""
    typer.echo(lib.view_3d_model(name=name, directory=directory).model_dump_json(indent=2))


@app.command()
def list_intelligence_models() -> None:
    """List the AI models and reasoning efforts to pick from, printed as JSON. Deterministic."""
    typer.echo(lib.list_intelligence_models().model_dump_json(indent=2))


@app.command()
def add_blender_to_path(
    blender_path: Annotated[
        Path | None,
        typer.Option("--blender-path", help="Blender's executable or folder; the newest installed when omitted."),
    ] = None,
) -> None:
    """Make `blender` run an installed Blender from new terminals, printing what changed as JSON. Deterministic."""
    typer.echo(lib.add_blender_to_path(blender_path=blender_path).model_dump_json(indent=2))


@app.command()
def mcp(
    directory: Annotated[
        Path | None,
        typer.Option("--directory", help="Where the models to show are kept; .modeling-3d here when omitted."),
    ] = None,
) -> None:
    """Serve the app's MCP server on stdio, with the app as an MCP App. Deterministic.

    For MCP clients that launch the server themselves. Reads and writes MCP messages on stdin and stdout until the
    client disconnects; prints nothing else to stdout.
    """
    mcp_adapter.run_stdio(directory)


async def _run_model(starting: Coroutine[Any, Any, lib.ModelRun], detach: bool) -> int:
    """Run a model's request to its end, one JSON line per event, and the exit code its end calls for."""
    run = await starting
    if detach:
        # The run goes on in its own process, so its start is all there is to print.
        _print_event(await anext(run.events()))
        return 0
    with _stopped_by_signals(run):
        async for event in run.events():
            _print_event(event)
        result = await run.result()
    return 0 if result.status == "done" else 1


def _origin() -> str | None:
    session = os.environ.get(SESSION_VARIABLE)
    return f"claude-code:{session}" if session else None


def _print_event(event: ModelEvent) -> None:
    # ASCII-escaped JSON is UTF-8 on any console encoding, and echo writes the line in one call and flushes it.
    typer.echo(json.dumps(event.model_dump(mode="json")))


@contextlib.contextmanager
def _stopped_by_signals(run: lib.ModelRun) -> Generator[None]:
    """Stop the run on every signal that ends the process."""
    loop = asyncio.get_running_loop()
    stopping: set[asyncio.Task[None]] = set()

    def stop() -> None:
        task = asyncio.ensure_future(run.cancel())
        stopping.add(task)
        task.add_done_callback(stopping.discard)

    def handler(signum: int, frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop)

    previous: dict[signal.Signals, Any] = {}
    for name in STOPPING_SIGNALS:
        number = getattr(signal, name, None)
        if isinstance(number, signal.Signals):
            previous[number] = signal.signal(number, handler)
    try:
        yield
    finally:
        for number, original in previous.items():
            signal.signal(number, original)


def main() -> int:
    try:
        app()
    except Modeling3dError as error:
        typer.echo(error, err=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
