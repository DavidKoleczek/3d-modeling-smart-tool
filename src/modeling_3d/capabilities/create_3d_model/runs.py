"""A run on a model: its agent driven by this process, or a detached run followed through the files its process writes."""

import asyncio
from collections.abc import AsyncIterator, Callable, Generator
import contextlib
from datetime import UTC, datetime
import json
from pathlib import Path
import secrets
import signal
from types import FrameType
from typing import Any, Protocol

from modeling_3d.capabilities.create_3d_model.check import check
from modeling_3d.capabilities.create_3d_model.constants import CHECK_FAILED
from modeling_3d.capabilities.create_3d_model.prompting import steering, template
from modeling_3d.capabilities.create_3d_model.record import (
    EVENTS,
    GLB,
    PROCESS_LOG,
    REPORT,
    REQUIRED_FILES,
    alive,
    load_record,
    model_files,
    read_events,
    write_runs,
)
from modeling_3d.capabilities.create_3d_model.references import attached, copy_references, resolve_references
from modeling_3d.intelligence.interface import AgentRun, Intelligence
from modeling_3d.intelligence.schemas import AgentEvent
from modeling_3d.schemas import (
    ModelEvent,
    ModelEventKind,
    Modeling3dError,
    ModelRecord,
    ModelResult,
    ModelRunRecord,
    ModelRunStatus,
)

# How often the process running a model looks for steering messages and a cancel from other processes.
POLL_SECONDS = 1.0
# Every signal that ends the process stops a run first, so its session stays resumable and nothing it started
# outlives it. SIGHUP is the console closing on Linux and macOS, and SIGBREAK is Windows' Ctrl+Break and console
# closing, which reaches a process group of its own.
STOPPING_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK")


class ModelRun(Protocol):
    """A model being created or changed: its events, a way to talk to its agent, and how it ended."""

    name: str
    directory: Path
    run_id: str

    @property
    def session_id(self) -> str | None:
        """The session a later run resumes, once the agent provider has made it; None before."""
        ...

    def events(self) -> AsyncIterator[ModelEvent]:
        """Every event from the start, then live ones until the run ends with `finished` or `failed`."""
        ...

    async def steer(self, message: str, references: list[Path] | None = None) -> None:
        """Send a message, and any references with it, to the agent while it works; a `steered` event shows when it is
        delivered."""
        ...

    async def cancel(self) -> None:
        """Stop the run at once and wait for it to end; its session can still be resumed."""
        ...

    async def result(self) -> ModelResult:
        """Wait for the run to end."""
        ...


class Checking:
    """The check a run's agent gets as it is about to finish: once a run, and not when it has just run the check."""

    def __init__(self, target: Path, run: ModelRunRecord) -> None:
        self._target = target
        self._run = run
        self._sent = False
        self._emit: Callable[[str, dict[str, Any]], None] | None = None
        # What was checked before the run could record it, as for an agent that finishes at once.
        self._unrecorded: list[tuple[str, dict[str, Any]]] = []

    def record(self, emit: Callable[[str, dict[str, Any]], None]) -> None:
        """Record each report sent as an event of the run, those sent already first."""
        self._emit = emit
        for text, data in self._unrecorded:
            emit(text, data)
        self._unrecorded.clear()

    async def __call__(self) -> str | None:
        if self._sent or not (self._target / GLB).is_file() or await asyncio.to_thread(check.covers, self._target):
            return None
        self._sent = True
        try:
            report = await check.check_model(
                self._target.name,
                self._target.parent,
                self._run.max_triangles,
                self._run.max_draw_calls,
                self._run.screen_size,
            )
        except Modeling3dError as error:
            found, data = CHECK_FAILED.format(error=error), {"error": str(error)}
        else:
            found, data = check.describe(report), {"report": REPORT.as_posix()}
        if self._emit is None:
            self._unrecorded.append((found, data))
        else:
            self._emit(found, data)
        return template("checked.md").format(report=found)


class InProcessRun:
    """A model being created or changed by an agent this process runs."""

    def __init__(
        self,
        directory: Path,
        record: ModelRecord,
        agent: AgentRun,
        intelligence: Intelligence,
        timeout_seconds: int,
        next_command: str,
        checking: Checking,
    ) -> None:
        self.name = record.name
        self.directory = directory
        self.run_id = record.runs[-1].id
        self._record = record
        self._agent = agent
        self._intelligence = intelligence
        self._timeout_seconds = timeout_seconds
        self._next = next_command
        self._events: list[ModelEvent] = []
        # Replaced on every append, so a reader waits on the one current when it ran out of events.
        self._appended = asyncio.Event()
        self._cancelling: asyncio.Task[None] | None = None
        request = self._run.model_dump(
            mode="json",
            include={
                "mode",
                "prompt",
                "references",
                "max_triangles",
                "max_draw_calls",
                "screen_size",
                "resumed",
                "agent_provider",
                "model",
                "reasoning_effort",
                "origin",
            },
        )
        self._emit(
            "started", f"Model {self.name} is being worked on in {directory}.", {"directory": str(directory), **request}
        )
        checking.record(lambda text, data: self._emit("checked", text, data))
        self._task = asyncio.create_task(self._drive())

    @property
    def session_id(self) -> str | None:
        return self._agent.session_id

    def events(self) -> AsyncIterator[ModelEvent]:
        """Every event from the start, then live ones until the run ends with `finished` or `failed`."""
        return self._replay()

    async def steer(self, message: str, references: list[Path] | None = None) -> None:
        """Send a message, and any references with it, to the agent while it works, as from whoever asked for the run."""
        copied = await asyncio.to_thread(copy_references, self.directory, resolve_references(references or []))
        await self._deliver(message, copied, self._run.origin)

    async def cancel(self) -> None:
        """Stop the run at once and wait for it to end; its session can still be resumed."""
        self._request_cancel()
        await asyncio.wait([self._task])

    async def result(self) -> ModelResult:
        """Wait for the run to end."""
        return await asyncio.shield(self._task)

    @property
    def _run(self) -> ModelRunRecord:
        return self._record.runs[-1]

    @property
    def _run_directory(self) -> Path:
        return self.directory / "runs" / self.run_id

    async def _deliver(self, message: str, references: list[str], origin: str | None) -> None:
        if self._task.done():
            raise not_running(self.name, self._run.status, self._next)
        images = [self.directory / path for path in references if attached(path)]
        await self._agent.steer(steering(message, references), images)
        self._emit(
            "steered", message, {"steering": self._intelligence.steering, "origin": origin, **_given(references)}
        )

    async def _replay(self) -> AsyncIterator[ModelEvent]:
        index = 0
        while True:
            appended = self._appended
            while index < len(self._events):
                event = self._events[index]
                index += 1
                yield event
                if event.kind in ("finished", "failed"):
                    return
            if self._task.done():
                return
            await appended.wait()

    async def _drive(self) -> ModelResult:
        watcher = asyncio.create_task(self._watch())
        timed_out = False
        try:
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    async for event in self._agent.events():
                        self._forward(event)
            except TimeoutError:
                timed_out = True
                await self._agent.cancel()
            outcome = await self._agent.result()
            if self._cancelling is not None:
                await self._cancelling
            if not timed_out and not outcome.cancelled and outcome.error is None:
                await self._check_for_later()
        finally:
            watcher.cancel()
            # Set for good, so readers waiting on it see the run end; nothing after this may wait.
            self._appended.set()
        status: ModelRunStatus
        error: str | None = None
        if timed_out:
            status = "timed-out"
            error = (
                f"The run did not finish within {self._timeout_seconds} seconds and was stopped. Go on where it "
                f"stopped with `{self._next}`, or give it more time with --timeout-seconds."
            )
        elif outcome.cancelled:
            status = "cancelled"
        elif outcome.error is not None:
            status = "failed"
            error = f"The agent failed: {outcome.error} Its events are in {self._run_directory / EVENTS}."
        elif missing := [name for name in REQUIRED_FILES if not (self.directory / name).is_file()]:
            status = "failed"
            error = (
                f"The agent finished without leaving {' or '.join(missing)} in {self.directory}. Ask for it with "
                f"`{self._next}`."
            )
        else:
            status = "done"
        session_id = outcome.session_id or self.session_id
        self._end(status, session_id)
        result = ModelResult(
            name=self.name,
            directory=self.directory,
            run_id=self.run_id,
            status=status,
            text=outcome.text,
            error=error,
            session_id=session_id,
            agent_provider=self._run.agent_provider,
            files=model_files(self.directory),
            next=self._next,
        )
        if status in ("done", "cancelled"):
            self._emit("finished", f"Model {self.name} {status}, in {self.directory}.", result.model_dump(mode="json"))
        else:
            self._emit("failed", error or "", result.model_dump(mode="json"))
        return result

    async def _check_for_later(self) -> None:
        """Check a model.glb the agent left without a report, for whoever looks at the model next, such as the app.

        The agent has finished, so it is not told.
        """
        if not (self.directory / GLB).is_file() or await asyncio.to_thread(check.covers, self.directory):
            return
        run = self._run
        with contextlib.suppress(Modeling3dError):
            await check.check_model(
                self.name, self.directory.parent, run.max_triangles, run.max_draw_calls, run.screen_size
            )

    def _forward(self, event: AgentEvent) -> None:
        if event.type == "terminal":
            return
        self._note_session()
        self._emit("agent", event.type, event.data, event.time)

    async def _watch(self) -> None:
        """Act on what other processes wrote to the run's directory."""
        steer = self._run_directory / "steer"
        while True:
            self._note_session()
            if (self._run_directory / "cancel").exists():
                self._request_cancel()
            for path in sorted(steer.glob("*.json")):
                note = json.loads(path.read_text(encoding="utf-8"))
                path.unlink()
                if self._cancelling is not None:
                    continue
                references = note.get("references", [])
                try:
                    await self._deliver(note["message"], references, note.get("origin"))
                except Modeling3dError as error:
                    data = {"error": str(error), "origin": note.get("origin"), **_given(references)}
                    self._emit("steered", note["message"], data)
            await asyncio.sleep(POLL_SECONDS)

    def _request_cancel(self) -> None:
        if self._cancelling is None:
            self._cancelling = asyncio.create_task(self._agent.cancel())

    def _note_session(self) -> None:
        """Keep the session in runs.json as soon as it is known, so a killed process leaves it resumable."""
        session_id = self._agent.session_id
        if session_id is not None and session_id != self._run.session_id:
            self._run.session_id = session_id
            write_runs(self.directory, self._record.runs)

    def _end(self, status: ModelRunStatus, session_id: str | None) -> None:
        self._run.status = status
        self._run.finished = datetime.now(UTC)
        self._run.session_id = session_id or self._run.session_id
        write_runs(self.directory, self._record.runs)

    def _emit(
        self, kind: ModelEventKind, text: str = "", data: dict[str, Any] | None = None, time: datetime | None = None
    ) -> None:
        event = ModelEvent(run_id=self.run_id, kind=kind, text=text, data=data or {})
        if time is not None:
            event.time = time
        with (self._run_directory / EVENTS).open("a", encoding="utf-8") as events:
            events.write(json.dumps(event.model_dump(mode="json")) + "\n")
        self._run.last_event = event.time
        write_runs(self.directory, self._record.runs)
        self._events.append(event)
        self._appended.set()
        self._appended = asyncio.Event()


class DetachedRun:
    """A model being created or changed in a process of its own, followed through the files that process writes."""

    def __init__(self, directory: Path, run_id: str, origin: str | None, next_command: str) -> None:
        self.name = directory.name
        self.directory = directory
        self.run_id = run_id
        self._origin = origin
        self._next = next_command

    @property
    def session_id(self) -> str | None:
        return self._record().session_id

    def events(self) -> AsyncIterator[ModelEvent]:
        """Every event from the start, then each as the run's process writes it, until the run ends."""
        return self._follow()

    async def steer(self, message: str, references: list[Path] | None = None) -> None:
        """Send a message, and any references with it, to the agent while it works, as from whoever asked for the run."""
        running = await asyncio.to_thread(self._running)
        await asyncio.to_thread(write_steering, running, message, references or [], self._origin)

    async def cancel(self) -> None:
        """Stop the run at once and wait for it to end; its session can still be resumed."""
        # A run that has ended already needs no stopping.
        with contextlib.suppress(Modeling3dError):
            (await asyncio.to_thread(self._running) / "cancel").touch()
        await self.result()

    async def result(self) -> ModelResult:
        """Wait for the run to end."""
        last: ModelEvent | None = None
        async for event in self._follow():
            last = event
        if last is not None and last.kind in ("finished", "failed"):
            return ModelResult.model_validate(last.data)
        run = self._record()
        log = self.directory / "runs" / self.run_id / PROCESS_LOG
        return ModelResult(
            name=self.name,
            directory=self.directory,
            run_id=self.run_id,
            status="failed",
            error=f"The process running the model, {run.pid}, ended before the run did. What it printed is in {log}. "
            f"Go on where it stopped with `{self._next}`.",
            session_id=run.session_id,
            agent_provider=run.agent_provider,
            files=model_files(self.directory),
            next=self._next,
        )

    def _record(self) -> ModelRunRecord:
        return next(run for run in load_record(self.directory).runs if run.id == self.run_id)

    def _running(self) -> Path:
        run = self._record()
        if run.status != "running" or not alive(run.pid):
            raise not_running(self.name, run.status, self._next)
        return self.directory / "runs" / self.run_id

    async def _follow(self) -> AsyncIterator[ModelEvent]:
        path = self.directory / "runs" / self.run_id / EVENTS
        offset = 0
        while True:
            # Looked at before reading, so every event of a run seen to have ended is read.
            run = await asyncio.to_thread(self._record)
            ended = run.status != "running" or not alive(run.pid)
            events, offset = await asyncio.to_thread(read_events, path, offset)
            for event in events:
                yield event
                if event.kind in ("finished", "failed"):
                    return
            if ended:
                return
            await asyncio.sleep(POLL_SECONDS)


def write_steering(run_directory: Path, message: str, references: list[Path], origin: str | None) -> None:
    """Write a steering message, with its references copied in, for the process running the run to deliver."""
    copied = copy_references(run_directory.parents[1], resolve_references(references))
    steer = run_directory / "steer"
    stamp = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}-{secrets.token_hex(3)}"
    # Written aside and renamed, so the running run never reads half a message.
    partial = steer / f"{stamp}.tmp"
    partial.write_text(json.dumps({"message": message, "references": copied, "origin": origin}), encoding="utf-8")
    partial.replace(steer / f"{stamp}.json")


def not_running(name: str, status: str, next_command: str) -> Modeling3dError:
    ending = "its process is gone" if status == "running" else f"its last run ended {status}"
    return Modeling3dError(
        f"Model {name} is not being worked on; {ending}. Send the message as a new request instead: {next_command}",
        "not-running",
        name,
    )


@contextlib.contextmanager
def stopped_by_signals(run: ModelRun) -> Generator[None]:
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


def _given(references: list[str]) -> dict[str, list[str]]:
    """What a `steered` event records of the references sent with it, which most steering has none of."""
    return {"references": references} if references else {}
