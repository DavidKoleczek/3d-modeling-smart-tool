"""Create or change a 3D model: an agent writes a Blender script in the model's directory, runs it, and checks it."""

import asyncio
from collections.abc import AsyncIterator
import contextlib
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
from typing import IO, Any, Protocol
import uuid

from pydantic import BaseModel

from modeling_3d.capabilities.create_3d_model.intelligence_models import require_reasoning_effort
from modeling_3d.capabilities.create_3d_model.record import (
    DEFAULT_DIRECTORY,
    EVENTS,
    RECORD,
    REQUIRED_FILES,
    alive,
    load_record,
    missing_model,
    model_files,
    read_events,
    write_record,
)
from modeling_3d.intelligence.interface import AgentRun, Intelligence, resolve_agent_provider, select_intelligence
from modeling_3d.intelligence.schemas import IMAGE_MEDIA_TYPES, AgentEvent, AgentRequest, HostWorkspace
from modeling_3d.schemas import (
    AGENT_PROVIDERS,
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_REASONING_EFFORT,
    AgentProvider,
    ModelEvent,
    ModelEventKind,
    Modeling3dError,
    ModelRecord,
    ModelResult,
    ModelRunRecord,
    ModelRunStatus,
    ReasoningEffort,
)

HERE = Path(__file__).parent
# Blender as a Python module from PyPI, so building a model needs only uv.
BPY_REQUIREMENT = "bpy==5.2.*"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Folders a folder reference leaves out, beside hidden ones.
SKIPPED_FOLDERS = ("node_modules", "__pycache__")
# How often the process running a model looks for steering messages and a cancel from other processes.
POLL_SECONDS = 1.0
# The agent's own timeout outlasts the run's, so the run is what stops it and can say it timed out.
AGENT_TIMEOUT_GRACE_SECONDS = 60
# What starts a detached run, given its request on stdin. Tests swap it for a command that fakes the agent.
BACKGROUND_COMMAND = [sys.executable, "-m", "modeling_3d.capabilities.create_3d_model.background"]
# Where a detached run's process writes once its agent runs, beside the run's events.
PROCESS_LOG = "process.log"


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

    async def steer(self, message: str) -> None:
        """Send a message to the agent while it works; a `steered` event shows when it is delivered."""
        ...

    async def cancel(self) -> None:
        """Stop the run at once and wait for it to end; its session can still be resumed."""
        ...

    async def result(self) -> ModelResult:
        """Wait for the run to end."""
        ...


class DetachedRequest(BaseModel):
    """What `create_3d_model` hands the process a detached run runs in."""

    prompt: str
    name: str
    directory: Path | None
    references: list[Path]
    resume_session: bool | str
    agent_provider: AgentProvider | None
    model: str | None
    reasoning_effort: ReasoningEffort
    timeout_seconds: int
    origin: str | None


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
            include={"prompt", "references", "resumed", "agent_provider", "model", "reasoning_effort", "origin"},
        )
        self._emit(
            "started", f"Model {self.name} is being worked on in {directory}.", {"directory": str(directory), **request}
        )
        self._task = asyncio.create_task(self._drive())

    @property
    def session_id(self) -> str | None:
        return self._agent.session_id

    def events(self) -> AsyncIterator[ModelEvent]:
        """Every event from the start, then live ones until the run ends with `finished` or `failed`."""
        return self._replay()

    async def steer(self, message: str) -> None:
        """Send a message to the agent while it works, as from whoever asked for the run."""
        await self._deliver(message, self._run.origin)

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

    async def _deliver(self, message: str, origin: str | None) -> None:
        if self._task.done():
            raise _not_running(self.name, self._run.status, self._next)
        await self._agent.steer(message)
        self._emit("steered", message, {"steering": self._intelligence.steering, "origin": origin})

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
        finally:
            watcher.cancel()
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
                try:
                    await self._deliver(note["message"], note.get("origin"))
                except Modeling3dError as error:
                    self._emit("steered", note["message"], {"error": str(error), "origin": note.get("origin")})
            await asyncio.sleep(POLL_SECONDS)

    def _request_cancel(self) -> None:
        if self._cancelling is None:
            self._cancelling = asyncio.create_task(self._agent.cancel())

    def _note_session(self) -> None:
        """Keep the session in model.json as soon as it is known, so a killed process leaves it resumable."""
        session_id = self._agent.session_id
        if session_id is not None and session_id != self._run.session_id:
            self._run.session_id = session_id
            write_record(self.directory, self._record)

    def _end(self, status: ModelRunStatus, session_id: str | None) -> None:
        self._run.status = status
        self._run.finished = datetime.now(UTC)
        self._run.session_id = session_id or self._run.session_id
        write_record(self.directory, self._record)

    def _emit(
        self, kind: ModelEventKind, text: str = "", data: dict[str, Any] | None = None, time: datetime | None = None
    ) -> None:
        event = ModelEvent(run_id=self.run_id, kind=kind, text=text, data=data or {})
        if time is not None:
            event.time = time
        with (self._run_directory / EVENTS).open("a", encoding="utf-8") as events:
            events.write(json.dumps(event.model_dump(mode="json")) + "\n")
        self._run.last_event = event.time
        write_record(self.directory, self._record)
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

    async def steer(self, message: str) -> None:
        """Send a message to the agent while it works, as from whoever asked for the run."""
        _write_steering(await asyncio.to_thread(self._running), message, self._origin)

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
            raise _not_running(self.name, run.status, self._next)
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


async def create_3d_model(
    prompt: str,
    name: str,
    directory: Path | None = None,
    references: list[Path] | None = None,
    resume_session: bool | str = False,
    agent_provider: AgentProvider | None = None,
    model: str | None = None,
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT,
    timeout_seconds: int = 3600,
    origin: str | None = None,
    detach: bool = False,
    intelligence: Intelligence | None = None,
) -> ModelRun:
    """Start creating the model named `name`, or changing it when it exists, and return its handle once the agent runs."""
    require_reasoning_effort(reasoning_effort)
    if detach:
        if intelligence is not None:
            raise Modeling3dError(
                "A detached run's agent runs in a process of its own, which the intelligence passed cannot reach. "
                "Leave out detach to run the agent with it here, or leave out the intelligence."
            )
        request = DetachedRequest(
            prompt=prompt,
            name=name,
            directory=directory,
            references=references or [],
            resume_session=resume_session,
            agent_provider=agent_provider,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            origin=origin,
        )
        return await _detach(request)
    root = (directory or DEFAULT_DIRECTORY).resolve()
    target, existing = _model_directory(root, name)
    sources = _references(references or [])
    previous = existing.runs[-1] if existing is not None and existing.runs else None
    if previous is not None and previous.status == "running" and alive(previous.pid):
        raise Modeling3dError(
            f"Model {target.name} is already being worked on by process {previous.pid}. Steer that run with "
            f"`modeling-3d steer-3d-model --name {target.name} --message <text>`, stop it with "
            f"`modeling-3d cancel-3d-model --name {target.name}`, or wait for it to end.",
            "already-running",
            target.name,
        )
    resumed = _resumed(target.name, existing, resume_session)
    if resumed is not None and agent_provider is None:
        agent_provider = resumed.agent_provider
    if resumed is not None and agent_provider != resumed.agent_provider:
        raise Modeling3dError(
            f"Model {target.name}'s session ran on {resumed.agent_provider}, and {agent_provider} was asked for. "
            f"Continue it on {resumed.agent_provider} by leaving the agent provider out, or pass --resume-session "
            "false for a fresh session that reads its model.py.",
            "provider-mismatch",
            target.name,
        )
    if intelligence is None:
        agent_provider = resolve_agent_provider(agent_provider)
    provider: AgentProvider = agent_provider or AGENT_PROVIDERS[0]
    intelligence, model = select_intelligence(intelligence, provider, model, DEFAULT_INTELLIGENCE_MODELS)
    await asyncio.to_thread(intelligence.preflight)

    created = existing is None
    now = datetime.now(UTC)
    record = existing or ModelRecord(id=str(uuid.uuid4()), name=target.name, created=now)
    if previous is not None and previous.status == "running":
        # Its process is gone, so it crashed; its session, kept as soon as it was known, can still be resumed.
        previous.status = "failed"
    run_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    (target / "runs" / run_id / "steer").mkdir(parents=True)
    copied = _copy_references(target, sources)
    record.runs.append(
        ModelRunRecord(
            id=run_id,
            prompt=prompt,
            references=copied,
            resumed=resumed is not None,
            agent_provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            session_id=resumed.session_id if resumed is not None else None,
            origin=origin,
            pid=os.getpid(),
            started=now,
        )
    )
    write_record(target, record)
    next_command = _next_command(target.name, directory)
    request = AgentRequest(
        prompt=_prompt(prompt, target, copied, resumed=resumed is not None, created=created),
        model=model,
        images=[target / path for path in copied if _attached(path)],
        workspace=HostWorkspace(path=target),
        writable=True,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds + AGENT_TIMEOUT_GRACE_SECONDS,
        resume=resumed.session_id if resumed is not None else None,
        session_directory=target / "sessions",
    )
    try:
        agent = await intelligence.start(request)
    except BaseException:
        if created:
            shutil.rmtree(target, ignore_errors=True)
        else:
            record.runs[-1].status = "failed"
            record.runs[-1].finished = datetime.now(UTC)
            write_record(target, record)
        raise
    return InProcessRun(target, record, agent, intelligence, timeout_seconds, next_command)


def steer_3d_model(name: str, message: str, directory: Path | None = None, origin: str | None = None) -> None:
    """Write a steering message for the process running the model's run to deliver."""
    _write_steering(_running_run(name, directory), message, origin)


def cancel_3d_model(name: str, directory: Path | None = None) -> None:
    """Write the cancel the process running the model's run acts on."""
    (_running_run(name, directory) / "cancel").touch()


def _write_steering(run_directory: Path, message: str, origin: str | None) -> None:
    steer = run_directory / "steer"
    stamp = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}-{secrets.token_hex(3)}"
    # Written aside and renamed, so the running run never reads half a message.
    partial = steer / f"{stamp}.tmp"
    partial.write_text(json.dumps({"message": message, "origin": origin}), encoding="utf-8")
    partial.replace(steer / f"{stamp}.json")


async def _detach(request: DetachedRequest) -> DetachedRun:
    report = await asyncio.to_thread(_start_process, request)
    if report.get("error"):
        raise Modeling3dError(report["error"], report.get("reason"), report.get("model"))
    target = (request.directory or DEFAULT_DIRECTORY).resolve() / report["name"]
    return DetachedRun(target, report["run_id"], request.origin, _next_command(target.name, request.directory))


def _start_process(request: DetachedRequest) -> dict[str, Any]:
    """Start the process a detached run runs in, and return what it reports once its agent runs or cannot."""
    process = detached_process(BACKGROUND_COMMAND, subprocess.PIPE, subprocess.PIPE)
    # It only starts the run's own process and exits; waited on here so it leaves no zombie.
    threading.Thread(target=process.wait, daemon=True).start()
    assert process.stdin is not None
    assert process.stdout is not None
    with process.stdin:
        process.stdin.write(request.model_dump_json().encode("utf-8"))
    with process.stdout:
        line = process.stdout.readline()
    if not line:
        return {
            "error": "The process that runs the model ended before its agent ran, without saying why. Run the request "
            "without detach to see why.",
            "reason": "start-failed",
            "model": request.name,
        }
    return json.loads(line)


def detached_process(
    command: list[str], stdin: int | IO[Any], stdout: int | IO[Any], environment: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    """Start `command` apart from this process's console, session, and job, so ending them leaves it running."""
    if sys.platform != "win32":
        return _popen(command, stdin, stdout, environment, start_new_session=True)
    # A console of its own without a window, which the agent's processes share, so none of them opens one.
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        # Out of the caller's job as well, since a host may end everything in its job when it exits.
        return _popen(command, stdin, stdout, environment, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
    except PermissionError:
        # The job allows no breaking away. Hosts built on Node let the children of their children leave it anyway.
        return _popen(command, stdin, stdout, environment, creationflags=flags)


def _popen(
    command: list[str],
    stdin: int | IO[Any],
    stdout: int | IO[Any],
    environment: dict[str, str] | None,
    start_new_session: bool = False,
    creationflags: int = 0,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        command,
        stdin=stdin,
        stdout=stdout,
        stderr=subprocess.DEVNULL,
        env=environment,
        start_new_session=start_new_session,
        creationflags=creationflags,
    )


def _running_run(name: str, directory: Path | None) -> Path:
    root = (directory or DEFAULT_DIRECTORY).resolve()
    target = root / name
    if not target.is_dir():
        raise missing_model(root, name)
    record = load_record(target)
    run = record.runs[-1] if record.runs else None
    if run is None or run.status != "running" or not alive(run.pid):
        raise _not_running(name, run.status if run is not None else "never run", _next_command(name, directory))
    return target / "runs" / run.id


def _not_running(name: str, status: str, next_command: str) -> Modeling3dError:
    ending = "its process is gone" if status == "running" else f"its last run ended {status}"
    return Modeling3dError(
        f"Model {name} is not being worked on; {ending}. Send the message as a new request instead: {next_command}",
        "not-running",
        name,
    )


def _model_directory(root: Path, name: str) -> tuple[Path, ModelRecord | None]:
    """The model's directory, and its record when a model by that name exists already, ignoring case."""
    if not NAME_PATTERN.match(name):
        raise Modeling3dError(
            f"{name!r} cannot name a model. Use letters, digits, '.', '_', and '-', starting with a letter or "
            "digit, such as 'bear' or 'bear-2'.",
            "invalid-name",
            name,
        )
    # Listed rather than probed, since Windows and macOS find `Bear` when only `bear` exists.
    taken = {path.name.lower(): path for path in root.iterdir()} if root.is_dir() else {}
    found = taken.get(name.lower())
    if found is None:
        return root / name, None
    if not (found / RECORD).is_file():
        raise Modeling3dError(
            f"{found} already exists and is not a model. Choose another name.", "name-in-use", found.name
        )
    return found, load_record(found)


def _resumed(name: str, existing: ModelRecord | None, resume_session: bool | str) -> ModelRunRecord | None:
    """The run whose session this one continues: the latest with a session, or the one with the session named."""
    runs = list(reversed(existing.runs)) if existing is not None else []
    if not isinstance(resume_session, str):
        # A model without a session yet changes in a fresh one.
        return next((run for run in runs if run.session_id is not None), None) if resume_session else None
    resumed = next((run for run in runs if run.session_id == resume_session), None)
    if resumed is None:
        sessions = ", ".join(dict.fromkeys(run.session_id for run in runs if run.session_id is not None))
        raise Modeling3dError(
            f"Model {name} has no session {resume_session!r}. Its sessions, newest first: {sessions or 'none'}. "
            f"`modeling-3d read-3d-model-activity --name {name}` shows the session each request worked in.",
            "no-such-session",
            name,
        )
    return resumed


def _references(paths: list[Path]) -> list[Path]:
    resolved = [path.resolve() for path in paths]
    for path in resolved:
        if not path.is_file() and not path.is_dir():
            raise Modeling3dError(
                f"The reference {path} is not a file or a folder. Name each reference image, model, or folder by its "
                "path, relative to the working directory or absolute.",
                "missing-reference",
            )
    return resolved


def _skipped(folder: str, names: list[str]) -> list[str]:
    """What a folder reference leaves out: hidden folders and tool caches, which are rarely what was meant."""
    return [name for name in names if (name.startswith(".") or name in SKIPPED_FOLDERS) and Path(folder, name).is_dir()]


def _copy_references(target: Path, sources: list[Path]) -> list[str]:
    """Copy each reference into the model's references/, keeping its name unless another holds it already.

    A file the same as the one there already is not copied again. A folder is copied whole, and recorded with a
    trailing slash.
    """
    if not sources:
        return []
    folder = target / "references"
    folder.mkdir(exist_ok=True)
    copied: list[str] = []
    for source in sources:
        destination = folder / source.name
        suffix = 2
        while destination.exists() and (
            source.is_dir() or destination.is_dir() or destination.read_bytes() != source.read_bytes()
        ):
            destination = folder / f"{source.stem}-{suffix}{source.suffix}"
            suffix += 1
        if source.is_dir():
            shutil.copytree(source, destination, ignore=_skipped)
            copied.append(f"{destination.relative_to(target).as_posix()}/")
            continue
        if not destination.exists():
            shutil.copy2(source, destination)
        copied.append(destination.relative_to(target).as_posix())
    return copied


def _prompt(request: str, target: Path, references: list[str], resumed: bool, created: bool) -> str:
    listed = ""
    if references:
        lines = [f"- {path}{_noted(path)}" for path in references]
        listed = "\nReferences for this request, copied into the model's directory:\n" + "\n".join(lines) + "\n"
    if resumed:
        return (HERE / "resume_prompt.md").read_text(encoding="utf-8").format(request=request, references=listed)
    existing = (
        ""
        if created
        else "\nThe directory already holds the model, built by its model.py. Read model.py first and change it "
        "rather than starting over.\n"
    )
    return (
        (HERE / "prompt.md")
        .read_text(encoding="utf-8")
        .format(request=request, directory=target, bpy=BPY_REQUIREMENT, references=listed, existing=existing)
    )


def _attached(reference: str) -> bool:
    """Whether a reference is an image shown to the agent with the prompt; a folder's images are left for it to open."""
    return not reference.endswith("/") and Path(reference).suffix.lower() in IMAGE_MEDIA_TYPES


def _noted(reference: str) -> str:
    if reference.endswith("/"):
        return " (a folder)"
    return " (also attached)" if _attached(reference) else ""


def _next_command(name: str, directory: Path | None) -> str:
    command = f'modeling-3d create-3d-model "<what to change>" --name {name} --resume-session true'
    if directory is not None and directory != DEFAULT_DIRECTORY:
        resolved = str(directory.resolve())
        command += f' --directory "{resolved}"' if re.search(r"\s", resolved) else f" --directory {resolved}"
    return command
