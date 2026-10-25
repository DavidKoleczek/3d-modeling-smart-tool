"""Run an agent on a 3D model in one of its modes: it writes a Blender script in the model's directory, runs it, and
checks it. Shaping creates or changes the model, rigging readies it to move, and coloring colors it by role."""

import asyncio
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
from typing import IO, Any
import uuid

from pydantic import BaseModel

from modeling_3d.capabilities.create_3d_model import prompting
from modeling_3d.capabilities.create_3d_model.budgets import require_budgets, resolved
from modeling_3d.capabilities.create_3d_model.check import check
from modeling_3d.capabilities.create_3d_model.constants import KEPT, MODE_CAPABILITIES
from modeling_3d.capabilities.create_3d_model.intelligence_models import require_reasoning_effort
from modeling_3d.capabilities.create_3d_model.record import (
    DEFAULT_DIRECTORY,
    GLB,
    RECORD,
    alive,
    last_session,
    load_record,
    make_models_directory,
    missing_model,
    write_record,
    write_runs,
)
from modeling_3d.capabilities.create_3d_model.references import attached, copy_references, resolve_references
from modeling_3d.capabilities.create_3d_model.runs import (
    Checking,
    DetachedRun,
    InProcessRun,
    ModelRun,
    not_running,
    write_steering,
)
from modeling_3d.intelligence.interface import Intelligence, can_resume, resolve_agent_provider, select_intelligence
from modeling_3d.intelligence.schemas import AgentRequest, HostWorkspace
from modeling_3d.schemas import (
    AGENT_PROVIDERS,
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_MAX_DRAW_CALLS,
    DEFAULT_MAX_TRIANGLES,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_SCREEN_SIZE,
    NOT_GIVEN,
    AgentProvider,
    Modeling3dError,
    ModelMode,
    ModelRecord,
    ModelRunRecord,
    NotGiven,
    ReasoningEffort,
)

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# The agent's own timeout outlasts the run's, so the run is what stops it and can say it timed out.
AGENT_TIMEOUT_GRACE_SECONDS = 60
# What starts a detached run, given its request on stdin. Tests swap it for a command that fakes the agent.
BACKGROUND_COMMAND = [sys.executable, "-m", "modeling_3d.capabilities.create_3d_model.background"]


class DetachedRequest(BaseModel):
    """What `start_run` hands the process a detached run runs in."""

    mode: ModelMode
    prompt: str
    name: str
    directory: Path | None
    references: list[Path]
    max_triangles: int | NotGiven | None
    max_draw_calls: int | NotGiven | None
    screen_size: tuple[int, int] | NotGiven | None
    resume_session: bool | str
    agent_provider: AgentProvider | None
    model: str | None
    reasoning_effort: ReasoningEffort
    timeout_seconds: int
    origin: str | None


async def create_3d_model(
    prompt: str,
    name: str,
    directory: Path | None = None,
    references: list[Path] | None = None,
    max_triangles: int | NotGiven | None = NOT_GIVEN,
    max_draw_calls: int | NotGiven | None = NOT_GIVEN,
    screen_size: tuple[int, int] | NotGiven | None = NOT_GIVEN,
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
    return await start_run(
        "shape",
        prompt,
        name,
        directory,
        references,
        max_triangles,
        max_draw_calls,
        screen_size,
        resume_session,
        agent_provider,
        model,
        reasoning_effort,
        timeout_seconds,
        origin,
        detach,
        intelligence,
    )


async def rig_3d_model(
    name: str,
    prompt: str | None = None,
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
    """Start rigging the built model named `name`, to its own budgets, and return its handle once the agent runs."""
    return await start_run(
        "rig",
        prompt or "",
        name,
        directory,
        references,
        NOT_GIVEN,
        NOT_GIVEN,
        NOT_GIVEN,
        resume_session,
        agent_provider,
        model,
        reasoning_effort,
        timeout_seconds,
        origin,
        detach,
        intelligence,
    )


async def color_3d_model(
    name: str,
    prompt: str | None = None,
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
    """Start coloring the built model named `name`, to its own budgets, and return its handle once the agent runs."""
    return await start_run(
        "color",
        prompt or "",
        name,
        directory,
        references,
        NOT_GIVEN,
        NOT_GIVEN,
        NOT_GIVEN,
        resume_session,
        agent_provider,
        model,
        reasoning_effort,
        timeout_seconds,
        origin,
        detach,
        intelligence,
    )


async def detail_3d_model(
    name: str,
    prompt: str | None = None,
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
    """Start painting the surface detail of the built model named `name`, to its own budgets, and return its handle once the agent runs."""
    return await start_run(
        "detail",
        prompt or "",
        name,
        directory,
        references,
        NOT_GIVEN,
        NOT_GIVEN,
        NOT_GIVEN,
        resume_session,
        agent_provider,
        model,
        reasoning_effort,
        timeout_seconds,
        origin,
        detach,
        intelligence,
    )


async def start_run(
    mode: ModelMode,
    prompt: str,
    name: str,
    directory: Path | None,
    references: list[Path] | None,
    max_triangles: int | NotGiven | None,
    max_draw_calls: int | NotGiven | None,
    screen_size: tuple[int, int] | NotGiven | None,
    resume_session: bool | str,
    agent_provider: AgentProvider | None,
    model: str | None,
    reasoning_effort: ReasoningEffort,
    timeout_seconds: int,
    origin: str | None,
    detach: bool,
    intelligence: Intelligence | None,
) -> ModelRun:
    """Start a run on the model named `name` in `mode`, and return its handle once the agent runs."""
    require_reasoning_effort(reasoning_effort)
    require_budgets(max_triangles, max_draw_calls, screen_size)
    if detach:
        if intelligence is not None:
            raise Modeling3dError(
                "A detached run's agent runs in a process of its own, which the intelligence passed cannot reach. "
                "Leave out detach to run the agent with it here, or leave out the intelligence."
            )
        request = DetachedRequest(
            mode=mode,
            prompt=prompt,
            name=name,
            directory=directory,
            references=references or [],
            max_triangles=max_triangles,
            max_draw_calls=max_draw_calls,
            screen_size=screen_size,
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
    # Only shaping builds a model; every other mode works on one built already.
    if mode != "shape" and existing is None:
        raise missing_model(root, name)
    if mode != "shape" and not (target / GLB).is_file():
        raise Modeling3dError(
            f"Model {target.name} has no {GLB} yet, so there is nothing to {mode}. Build it first with "
            f'`modeling-3d create-3d-model "<what to build>" --name {target.name}`.',
            "not-built",
            target.name,
        )
    sources = resolve_references(references or [])
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
        if resumed is not None and not can_resume(resumed.agent_provider, resumed.session_id):
            raise Modeling3dError(
                f"Model {target.name}'s session {resumed.session_id} is not among the sessions "
                f"{resumed.agent_provider} keeps on this machine, as when the model was made on another, so it cannot "
                "be continued here. Pass --resume-session false for a fresh session that reads its model.py.",
                "session-unavailable",
                target.name,
            )
    provider: AgentProvider = agent_provider or AGENT_PROVIDERS[0]
    intelligence, model = select_intelligence(intelligence, provider, model, DEFAULT_INTELLIGENCE_MODELS)
    require_reasoning_effort(reasoning_effort, provider, model)
    await asyncio.to_thread(intelligence.preflight)
    skills = await asyncio.to_thread(check.agent_skills)

    created = existing is None
    # A run keeps working what runs in the other modes after shaping added, such as a rig while the model is colored.
    kept = [
        other
        for other in KEPT
        if other != mode and existing is not None and any(run.mode == other for run in existing.runs)
    ]
    now = datetime.now(UTC)
    record = existing or ModelRecord(id=str(uuid.uuid4()), name=target.name, created=now)
    # A change that leaves a budget out keeps the one its model had, so a change from the app, a fresh session, or a rig
    # still works to it. A new model gets the default.
    triangles = resolved(max_triangles, previous.max_triangles if previous else DEFAULT_MAX_TRIANGLES)
    draw_calls = resolved(max_draw_calls, previous.max_draw_calls if previous else DEFAULT_MAX_DRAW_CALLS)
    on_screen = resolved(screen_size, previous.screen_size if previous else DEFAULT_SCREEN_SIZE)
    if previous is not None and previous.status == "running":
        # Its process is gone, so it crashed; its session, kept as soon as it was known, can still be resumed.
        previous.status = "failed"
    run_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    make_models_directory(root)
    (target / "runs" / run_id / "steer").mkdir(parents=True)
    copied = copy_references(target, sources)
    record.runs.append(
        ModelRunRecord(
            id=run_id,
            mode=mode,
            prompt=prompt,
            references=copied,
            resumed=resumed is not None,
            agent_provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            max_triangles=triangles,
            max_draw_calls=draw_calls,
            screen_size=on_screen,
            session_id=resumed.session_id if resumed is not None else None,
            origin=origin,
            pid=os.getpid(),
            started=now,
        )
    )
    write_record(target, record)
    next_command = _next_command(mode, target.name, directory)
    if resumed is not None and resumed.mode == mode:
        # The session has the model's budgets already, so it hears only those this request sets.
        budgets = prompting.changed_budgets_block(mode, max_triangles, max_draw_calls, screen_size)
    else:
        # A session going on in another mode has the budgets, but not how this mode keeps to them.
        budgets = prompting.budgets_block(mode, triangles, draw_calls, on_screen)
    checking = Checking(target, record.runs[-1])
    request = AgentRequest(
        prompt=prompting.prompt(record.runs[-1], target, root, budgets, resumed, created, kept),
        model=model,
        images=[target / path for path in copied if attached(path)],
        # Where the tool was launched, usually the project the model is for, so the agent finds its context and
        # instructions there; the prompt keeps what it writes in the model's directory.
        workspace=HostWorkspace(path=Path.cwd()),
        writable=True,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds + AGENT_TIMEOUT_GRACE_SECONDS,
        resume=resumed.session_id if resumed is not None else None,
        session_directory=target / "sessions",
        skill_directories=[skills],
        follow_up=checking,
    )
    try:
        agent = await intelligence.start(request)
    except BaseException:
        if created:
            shutil.rmtree(target, ignore_errors=True)
        else:
            record.runs[-1].status = "failed"
            record.runs[-1].finished = datetime.now(UTC)
            write_runs(target, record.runs)
        raise
    return InProcessRun(target, record, agent, intelligence, timeout_seconds, next_command, checking)


def steer_3d_model(
    name: str,
    message: str,
    directory: Path | None = None,
    origin: str | None = None,
    references: list[Path] | None = None,
) -> None:
    """Write a steering message for the process running the model's run to deliver, with its references copied in."""
    write_steering(_running_run(name, directory), message, references or [], origin)


def cancel_3d_model(name: str, directory: Path | None = None) -> None:
    """Write the cancel the process running the model's run acts on."""
    (_running_run(name, directory) / "cancel").touch()


async def _detach(request: DetachedRequest) -> DetachedRun:
    report = await asyncio.to_thread(_start_process, request)
    if report.get("error"):
        raise Modeling3dError(report["error"], report.get("reason"), report.get("model"))
    target = (request.directory or DEFAULT_DIRECTORY).resolve() / report["name"]
    next_command = _next_command(request.mode, target.name, request.directory)
    return DetachedRun(target, report["run_id"], request.origin, next_command)


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
        next_command = _next_command(run.mode if run is not None else "shape", name, directory)
        raise not_running(name, run.status if run is not None else "never run", next_command)
    return target / "runs" / run.id


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
    if not isinstance(resume_session, str):
        # A model without a session yet changes in a fresh one.
        return last_session(existing) if resume_session and existing is not None else None
    runs = list(reversed(existing.runs)) if existing is not None else []
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


def _next_command(mode: ModelMode, name: str, directory: Path | None) -> str:
    capability = MODE_CAPABILITIES[mode].replace("_", "-")
    command = f'modeling-3d {capability} "<what to change>" --name {name} --resume-session true'
    if directory is not None and directory != DEFAULT_DIRECTORY:
        resolved = str(directory.resolve())
        command += f' --directory "{resolved}"' if re.search(r"\s", resolved) else f" --directory {resolved}"
    return command
