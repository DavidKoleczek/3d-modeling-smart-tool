"""The process a detached run runs in: its request on stdin, one report on stdout once its agent runs, then the run.

`create_3d_model(detach=True)` starts it apart from the caller, so the run outlives the caller.
"""

import asyncio
from collections.abc import Generator
import contextlib
import json
import os
from pathlib import Path
import signal
import sys
from types import FrameType
from typing import Any, TextIO

from modeling_3d.capabilities.create_3d_model import create
from modeling_3d.intelligence.interface import Intelligence
from modeling_3d.schemas import Modeling3dError

# Set in the process that runs the request. The process the caller starts only starts that one, with the same pipes,
# and exits, so the run descends from nothing a caller's process tree takes down with it when it is ended.
RUNNING = "MODELING_3D_DETACHED_RUN"
# Every signal that ends the process stops the run first, so its session stays resumable and nothing it started
# outlives it. SIGBREAK is Windows' Ctrl+Break, which reaches a process group of its own.
STOPPING_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK")


def main(intelligence: Intelligence | None = None) -> int:
    """Run the request on stdin to its end; `intelligence` stands in for the agent provider's in tests."""
    if RUNNING not in os.environ:
        try:
            command = [sys.executable, *sys.orig_argv[1:]]
            create.detached_process(command, sys.stdin, sys.stdout, {**os.environ, RUNNING: "1"})
        except OSError as error:
            failure = {"error": f"The process that runs the model did not start: {error}", "reason": "start-failed"}
            print(json.dumps(failure), flush=True)
            return 1
        return 0
    # The report goes out on a copy of stdout, and stdout itself goes nowhere until the run starts, so nothing else
    # printed can garble the report.
    report = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    sys.stdout.flush()
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    request = create.DetachedRequest.model_validate_json(sys.stdin.buffer.read())
    return asyncio.run(_run(request, intelligence, report))


async def _run(request: create.DetachedRequest, intelligence: Intelligence | None, report: TextIO) -> int:
    with report:
        try:
            run = await create.create_3d_model(**request.model_dump(), intelligence=intelligence)
        except Modeling3dError as error:
            _report(report, {"error": str(error), "reason": error.reason, "model": error.model})
            return 1
        except Exception as error:  # whatever stopped it, the caller is waiting to hear
            failure = f"The run did not start: {type(error).__name__}: {error}"
            _report(report, {"error": failure, "reason": "start-failed", "model": request.name})
            return 1
        _log_to(run.directory / "runs" / run.run_id / create.PROCESS_LOG)
        _report(report, {"name": run.name, "run_id": run.run_id})
    with _stopped_by_signals(run):
        result = await run.result()
    return 0 if result.status == "done" else 1


def _report(report: TextIO, message: dict[str, str | None]) -> None:
    report.write(json.dumps(message) + "\n")
    report.flush()


def _log_to(path: Path) -> None:
    """Send what this process prints from now on to the run's log, beside its events."""
    sys.stdout.flush()
    sys.stderr.flush()
    log = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.dup2(log, sys.stdout.fileno())
    os.dup2(log, sys.stderr.fileno())
    os.close(log)


@contextlib.contextmanager
def _stopped_by_signals(run: create.ModelRun) -> Generator[None]:
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


if __name__ == "__main__":
    raise SystemExit(main())
