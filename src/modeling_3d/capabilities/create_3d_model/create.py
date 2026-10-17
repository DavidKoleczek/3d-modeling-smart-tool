"""Create or change a 3D model: an agent writes a Blender script in the model's directory, runs it, and checks it."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import time
from typing import Any
import uuid

from pydantic import ValidationError

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
DEFAULT_DIRECTORY = Path(".modeling-3d")
RECORD = "model.json"
REQUIRED_FILES = ("model.py", "model.glb")
# Blender as a Python module from PyPI, so building a model needs only uv.
BPY_REQUIREMENT = "bpy==5.2.*"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# How often the process running a model looks for steering messages and a cancel from other processes.
POLL_SECONDS = 1.0
# The agent's own timeout outlasts the run's, so the run is what stops it and can say it timed out.
AGENT_TIMEOUT_GRACE_SECONDS = 60
# Windows refuses to replace a file another process has open, such as a UX reading model.json; such a read is brief.
REPLACE_ATTEMPTS = 20
REPLACE_WAIT_SECONDS = 0.05


class ModelRun:
    """A model being created or changed: its events, a way to talk to its agent, and how it ended."""

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
        self._emit("started", f"Model {self.name} is being worked on in {directory}.", {"directory": str(directory)})
        self._task = asyncio.create_task(self._drive())

    @property
    def session_id(self) -> str | None:
        return self._agent.session_id

    def events(self) -> AsyncIterator[ModelEvent]:
        """Every event from the start, then live ones until the run ends with `finished` or `failed`."""
        return self._replay()

    async def steer(self, message: str) -> None:
        """Send a message to the agent while it works; a `steered` event shows when it is delivered."""
        if self._task.done():
            raise _not_running(self.name, self._run.status, self._next)
        await self._agent.steer(message)
        self._emit("steered", message, {"steering": self._intelligence.steering})

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
            error = f"The agent failed: {outcome.error} Its events are in {self._run_directory / 'events.jsonl'}."
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
            files=_files(self.directory),
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
            for path in sorted(steer.glob("*.md")):
                message = path.read_text(encoding="utf-8")
                path.unlink()
                if self._cancelling is not None:
                    continue
                try:
                    await self.steer(message)
                except Modeling3dError as error:
                    self._emit("steered", message, {"error": str(error)})
            await asyncio.sleep(POLL_SECONDS)

    def _request_cancel(self) -> None:
        if self._cancelling is None:
            self._cancelling = asyncio.create_task(self._agent.cancel())

    def _note_session(self) -> None:
        """Keep the session in model.json as soon as it is known, so a killed process leaves it resumable."""
        session_id = self._agent.session_id
        if session_id is not None and session_id != self._run.session_id:
            self._run.session_id = session_id
            _write_record(self.directory, self._record)

    def _end(self, status: ModelRunStatus, session_id: str | None) -> None:
        self._run.status = status
        self._run.finished = datetime.now(UTC)
        self._run.session_id = session_id or self._run.session_id
        _write_record(self.directory, self._record)

    def _emit(
        self, kind: ModelEventKind, text: str = "", data: dict[str, Any] | None = None, time: datetime | None = None
    ) -> None:
        event = ModelEvent(run_id=self.run_id, kind=kind, text=text, data=data or {})
        if time is not None:
            event.time = time
        with (self._run_directory / "events.jsonl").open("a", encoding="utf-8") as events:
            events.write(json.dumps(event.model_dump(mode="json")) + "\n")
        self._run.last_event = event.time
        _write_record(self.directory, self._record)
        self._events.append(event)
        self._appended.set()
        self._appended = asyncio.Event()


async def create_3d_model(
    prompt: str,
    name: str,
    directory: Path | None = None,
    references: list[Path] | None = None,
    edit: bool = False,
    resume: bool = False,
    agent_provider: AgentProvider | None = None,
    model: str | None = None,
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT,
    timeout_seconds: int = 3600,
    intelligence: Intelligence | None = None,
) -> ModelRun:
    """Start creating a new model, or changing an existing one, and return its handle once the agent runs."""
    root = (directory or DEFAULT_DIRECTORY).resolve()
    target, existing = _model_directory(root, name, edit=edit or resume)
    sources = _references(references or [])
    previous = existing.runs[-1] if existing is not None and existing.runs else None
    if previous is not None and previous.status == "running" and _alive(previous.pid):
        raise Modeling3dError(
            f"Model {target.name} is already being worked on by process {previous.pid}. Steer that run with "
            f"`modeling-3d steer-3d-model --name {target.name} --message <text>`, stop it with "
            f"`modeling-3d cancel-3d-model --name {target.name}`, or wait for it to end."
        )
    resumed = _resumable(target.name, existing) if resume and existing is not None else None
    if resumed is not None and agent_provider is None:
        agent_provider = resumed.agent_provider
    if resumed is not None and agent_provider != resumed.agent_provider:
        raise Modeling3dError(
            f"Model {target.name}'s session ran on {resumed.agent_provider}, and {agent_provider} was asked for. "
            f"Resume it on {resumed.agent_provider} by leaving the agent provider out, or leave out --resume for a "
            "fresh session that reads its model.py."
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
            pid=os.getpid(),
            started=now,
        )
    )
    _write_record(target, record)
    next_command = _next_command(target.name, directory)
    request = AgentRequest(
        prompt=_prompt(prompt, target, copied, resumed=resumed is not None, created=created),
        model=model,
        images=[target / path for path in copied if Path(path).suffix.lower() in IMAGE_MEDIA_TYPES],
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
            _write_record(target, record)
        raise
    return ModelRun(target, record, agent, intelligence, timeout_seconds, next_command)


def steer_3d_model(name: str, message: str, directory: Path | None = None) -> None:
    """Write a steering message for the process running the model's run to deliver."""
    steer = _running_run(name, directory) / "steer"
    stamp = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}-{secrets.token_hex(3)}"
    # Written aside and renamed, so the running run never reads half a message.
    partial = steer / f"{stamp}.tmp"
    partial.write_text(message, encoding="utf-8")
    partial.replace(steer / f"{stamp}.md")


def cancel_3d_model(name: str, directory: Path | None = None) -> None:
    """Write the cancel the process running the model's run acts on."""
    (_running_run(name, directory) / "cancel").touch()


def _running_run(name: str, directory: Path | None) -> Path:
    root = (directory or DEFAULT_DIRECTORY).resolve()
    target = root / name
    if not target.is_dir():
        known = ", ".join(_models(root)) or "none"
        raise Modeling3dError(
            f"There is no model named {name!r} in {root}. The models there: {known}. Name one of them, or pass the "
            "--directory the model was created in."
        )
    record = _load_record(target)
    run = record.runs[-1] if record.runs else None
    if run is None or run.status != "running" or not _alive(run.pid):
        raise _not_running(name, run.status if run is not None else "never run", _next_command(name, directory))
    return target / "runs" / run.id


def _not_running(name: str, status: str, next_command: str) -> Modeling3dError:
    ending = "its process is gone" if status == "running" else f"its last run ended {status}"
    return Modeling3dError(
        f"Model {name} is not being worked on; {ending}. Send the message as a new request instead: {next_command}"
    )


def _model_directory(root: Path, name: str, edit: bool) -> tuple[Path, ModelRecord | None]:
    """The model's directory, and its record when an existing model is to be changed."""
    if not NAME_PATTERN.match(name):
        raise Modeling3dError(
            f"{name!r} cannot name a model. Use letters, digits, '.', '_', and '-', starting with a letter or "
            "digit, such as 'bear' or 'bear-2'."
        )
    # Listed rather than probed, since Windows and macOS find `Bear` when only `bear` exists.
    taken = {path.name.lower(): path for path in root.iterdir()} if root.is_dir() else {}
    found = taken.get(name.lower())
    if edit:
        if found is None or found.name != name:
            known = ", ".join(_models(root)) or "none"
            raise Modeling3dError(
                f"There is no model named {name!r} in {root}, so there is nothing to edit. The models there: "
                f"{known}. Name one of them, or leave out --edit and --resume to create {name!r}."
            )
        return found, _load_record(found)
    if found is not None:
        if (found / RECORD).is_file():
            raise Modeling3dError(
                f"A model named {found.name!r} already exists in {root}. Pass --edit to change it, or choose "
                "another name."
            )
        raise Modeling3dError(f"{found} already exists and is not a model. Choose another name.")
    return root / name, None


def _load_record(target: Path) -> ModelRecord:
    path = target / RECORD
    if not path.is_file():
        raise Modeling3dError(
            f"{target} is not a model made by modeling-3d: it has no {RECORD}. Choose another name, or another "
            "--directory."
        )
    try:
        return ModelRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise Modeling3dError(
            f"{path} is not a modeling-3d model record: {error.errors()[0]['msg']}. Fix or remove it, or choose "
            "another name."
        ) from None


def _resumable(name: str, existing: ModelRecord) -> ModelRunRecord:
    """The latest run with a session, which a resumed run continues."""
    resumable = next((run for run in reversed(existing.runs) if run.session_id is not None), None)
    if resumable is None:
        raise Modeling3dError(
            f"Model {name} has no session to resume. Pass --edit without --resume to change it in a fresh session "
            "that reads its model.py."
        )
    return resumable


def _references(paths: list[Path]) -> list[Path]:
    resolved = [path.resolve() for path in paths]
    for path in resolved:
        if not path.is_file():
            raise Modeling3dError(
                f"The reference {path} is not a file. Name each reference image or model by its path, relative to "
                "the working directory or absolute."
            )
    return resolved


def _copy_references(target: Path, sources: list[Path]) -> list[str]:
    """Copy each reference into the model's references/, keeping its name unless another file holds it already."""
    if not sources:
        return []
    folder = target / "references"
    folder.mkdir(exist_ok=True)
    copied: list[str] = []
    for source in sources:
        destination = folder / source.name
        suffix = 2
        while destination.exists() and destination.read_bytes() != source.read_bytes():
            destination = folder / f"{source.stem}-{suffix}{source.suffix}"
            suffix += 1
        if not destination.exists():
            shutil.copy2(source, destination)
        copied.append(destination.relative_to(target).as_posix())
    return copied


def _prompt(request: str, target: Path, references: list[str], resumed: bool, created: bool) -> str:
    listed = ""
    if references:
        lines = [
            f"- {path}{' (also attached)' if Path(path).suffix.lower() in IMAGE_MEDIA_TYPES else ''}"
            for path in references
        ]
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


def _files(target: Path) -> list[str]:
    """The model's own files: its script and what it builds, not the run's bookkeeping."""
    names = [name for name in (*REQUIRED_FILES, "model.py.lock", "model.blend") if (target / name).is_file()]
    renders = sorted(path.relative_to(target).as_posix() for path in (target / "renders").glob("*") if path.is_file())
    return names + renders


def _models(root: Path) -> list[str]:
    return sorted(path.parent.name for path in root.glob(f"*/{RECORD}"))


def _next_command(name: str, directory: Path | None) -> str:
    command = f'modeling-3d create-3d-model "<what to change>" --name {name} --resume'
    if directory is not None and directory != DEFAULT_DIRECTORY:
        resolved = str(directory.resolve())
        command += f' --directory "{resolved}"' if re.search(r"\s", resolved) else f" --directory {resolved}"
    return command


def _write_record(target: Path, record: ModelRecord) -> None:
    # Written aside and renamed, because other processes read it while a run writes it.
    partial = target / f"{RECORD}.tmp"
    partial.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            partial.replace(target / RECORD)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_SECONDS)


def _alive(pid: int) -> bool:
    """Whether a process with this id is running."""
    if sys.platform == "win32":
        import ctypes

        # os.kill on Windows terminates the process rather than probing it, so ask the kernel instead.
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
