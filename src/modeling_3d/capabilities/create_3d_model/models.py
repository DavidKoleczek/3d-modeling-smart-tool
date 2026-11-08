"""List the models in a directory, remember the one viewed last, and rename and delete them."""

from collections.abc import Callable
from datetime import UTC, datetime
import os
from pathlib import Path
import secrets
import shutil
import stat
import time
from typing import Any

from modeling_3d.capabilities.create_3d_model.record import (
    DEFAULT_DIRECTORY,
    GLB,
    RECORD,
    REPORT,
    STATE,
    alive,
    last_session,
    load_record,
    missing_model,
    model_files,
    model_names,
    move_directory,
    read_atomically,
    require_name,
    write_atomically,
    write_record,
)
from modeling_3d.intelligence.interface import can_resume
from modeling_3d.schemas import (
    ModelCheck,
    Modeling3dError,
    ModelListing,
    ModelRecord,
    ModelRunRecord,
    ModelsState,
    ModelStatus,
    ModelSummary,
)

# How long deleting a model waits for the run it stopped to end. A run ends within a few seconds of a cancel, and the
# app's call stays under what a host waits for, as its check does.
STOP_WAIT_SECONDS = 15
STOP_POLL_SECONDS = 0.1
# The models directory's own, whose lines opt a model's sources in to being committed by the model's name.
IGNORES = ".gitignore"


def list_3d_models(directory: Path | None = None) -> ModelListing:
    """Every model in the directory, newest first, and the one viewed last. Reads only."""
    root = (directory or DEFAULT_DIRECTORY).resolve()
    if root.exists() and not root.is_dir():
        raise Modeling3dError(
            f"{root} is a file, not a directory of models. Pass the --directory the models are kept in."
        )
    models: list[ModelSummary] = []
    unreadable: list[str] = []
    for name in model_names(root):
        try:
            models.append(model_summary(root / name, load_record(root / name)))
        except Modeling3dError as error:
            unreadable.append(str(error))
    # Stable, so models updated at the same time stay in name order.
    models.sort(key=lambda summary: summary.updated, reverse=True)
    last_viewed = _state(root).last_viewed
    return ModelListing(
        directory=root,
        models=models,
        last_viewed=last_viewed if any(summary.name == last_viewed for summary in models) else None,
        unreadable=unreadable,
    )


def view_3d_model(name: str, directory: Path | None = None) -> ModelSummary:
    """Record the model as the one viewed last in its directory, and return its summary."""
    root = (directory or DEFAULT_DIRECTORY).resolve()
    target = _model(root, name)
    summary = model_summary(target, load_record(target))
    state = _state(root).model_copy(update={"last_viewed": name})
    write_atomically(root / STATE, state.model_dump_json(indent=2))
    return summary


def rename_3d_model(name: str, new_name: str, directory: Path | None = None) -> ModelSummary:
    """Move the model's directory to `new_name`, with the records that name it, and return its summary there."""
    root = (directory or DEFAULT_DIRECTORY).resolve()
    target = _model(root, name)
    require_name(new_name)
    record = load_record(target)
    if new_name == name:
        return model_summary(target, record)
    # Listed rather than probed, since Windows and macOS find `Bear` when only `bear` exists, which is this model when
    # only the case changes.
    taken = next((path for path in root.iterdir() if path.name.lower() == new_name.lower() and path.name != name), None)
    if taken is not None:
        held = "another model" if (taken / RECORD).is_file() else "something that is not a model"
        raise Modeling3dError(
            f"{taken} is already {held}, so model {name} cannot take its name. Choose another name.",
            "name-in-use",
            taken.name,
        )
    working = _working(record)
    if working is not None:
        raise Modeling3dError(
            f"Model {name} is being worked on by process {working.pid}, so it cannot be renamed now. Stop it with "
            f"`modeling-3d cancel-3d-model --name {name}`, or wait for it to end, then rename it.",
            "model-busy",
            name,
        )
    renamed = root / new_name
    _move(target, renamed, f"rename model {name}")
    record.name = new_name
    for run in record.runs:
        # Where each session that worked on it before runs kept their directory knows it to be, so it is told it moved.
        run.directory = run.directory or target
    try:
        write_record(renamed, record)
        _rename_report(renamed)
        _follow(root, name, new_name)
    except OSError as error:
        raise Modeling3dError(
            f"Model {name} is renamed to {new_name}, in {renamed}, but not every record of it could be updated: "
            f"{error}. Check that {root} can be written."
        ) from None
    return model_summary(renamed, record)


def delete_3d_model(name: str, directory: Path | None = None) -> Path:
    """Remove the model's directory and all in it, stopping a run working on it first, and return where it was."""
    root = (directory or DEFAULT_DIRECTORY).resolve()
    target = _model(root, name)
    try:
        working = _working(load_record(target))
    except Modeling3dError:
        # A model whose records cannot be read has no run to stop, and deleting it is one way to fix it.
        working = None
    if working is not None and working.pid == os.getpid():
        # Its handle is here, and waiting for it to end could hold up the very loop that ends it.
        raise Modeling3dError(
            f"Model {name} is being worked on by a run in this process. Stop it with `await run.cancel()` on its "
            "handle, then delete the model.",
            "model-busy",
            name,
        )
    if working is not None:
        _stop(target, working, name)
    # Moved aside in one step first, so the model is either gone whole or there whole, however far removing it gets.
    aside = root / f".deleting-{name}-{secrets.token_hex(3)}"
    _move(target, aside, f"delete model {name}")
    try:
        _follow(root, name, None)
        shutil.rmtree(aside, onexc=_remove_read_only)
    except OSError as error:
        raise Modeling3dError(
            f"Model {name} is gone from {root}, but cleaning up after it failed: {error}. If {aside} is still there, "
            "remove it once nothing has a file in it open."
        ) from None
    return target


def model_summary(target: Path, record: ModelRecord) -> ModelSummary:
    """The model as a listing shows it, from its directory and its record."""
    run = record.runs[-1] if record.runs else None
    status: ModelStatus | None = None
    if run is not None:
        # Left as it is on disk: the next run on the model marks it failed, and a listing never races a writer.
        status = "crashed" if run.status == "running" and not alive(run.pid) else run.status
    times = [record.created] if run is None else [run.started, run.last_event, run.finished]
    session = last_session(record)
    return ModelSummary(
        name=target.name,
        id=record.id,
        directory=target,
        created=record.created,
        updated=max(time for time in times if time is not None),
        built=_written(target / GLB),
        checked=_written(target / REPORT),
        status=status,
        last_run=run,
        last_session=session,
        resumable=session is not None and can_resume(session.agent_provider, session.session_id),
        files=model_files(target),
        references=list(dict.fromkeys(path for entry in record.runs for path in entry.references)),
    )


def _written(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except FileNotFoundError:
        return None


def _state(root: Path) -> ModelsState:
    """What the person last did in the directory; nothing when it was never written or cannot be read."""
    try:
        return ModelsState.model_validate_json(read_atomically(root / STATE))
    except (OSError, ValueError):
        return ModelsState()


def _model(root: Path, name: str) -> Path:
    """The directory of the model named exactly `name`, so nothing else in the models directory can be reached."""
    # Compared against the names on disk, since Windows and macOS find `Bear` when only `bear` exists.
    if name not in model_names(root):
        raise missing_model(root, name)
    return root / name


def _working(record: ModelRecord) -> ModelRunRecord | None:
    """The run working on the model: its last, while it is running and its process is alive."""
    run = record.runs[-1] if record.runs else None
    return run if run is not None and run.status == "running" and alive(run.pid) else None


def _stop(target: Path, run: ModelRunRecord, name: str) -> None:
    """Stop the run as `cancel_3d_model` does, and wait for it to end and for its process to exit."""
    cancel = target / "runs" / run.id / "cancel"
    cancel.parent.mkdir(parents=True, exist_ok=True)
    cancel.touch()
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while True:
        # Its process may keep the run's log open until it exits, and Windows refuses to move a directory until then.
        if not alive(run.pid):
            return
        if time.monotonic() >= deadline:
            current = next((entry for entry in load_record(target).runs if entry.id == run.id), run)
            # A process that goes on past the run it ran, as a caller of the library may, is not waited on further.
            if current.status != "running":
                return
            raise Modeling3dError(
                f"Model {name}'s run was asked to stop, but process {current.pid} had not ended it after "
                f"{STOP_WAIT_SECONDS} seconds, so the model was left as it is. Delete it again once the run has ended.",
                "model-busy",
                name,
            )
        time.sleep(STOP_POLL_SECONDS)


def _move(source: Path, target: Path, doing: str) -> None:
    try:
        move_directory(source, target)
    except OSError as error:
        raise Modeling3dError(
            f"Could not {doing}: {error}. Close whatever has a file in {source} open, such as Blender, a file "
            "manager, or a terminal there, and try again."
        ) from None


def _rename_report(target: Path) -> None:
    """Name the model's latest check as the model is named now; the rest of it, such as its renders, is relative."""
    path = target / REPORT
    try:
        report = ModelCheck.model_validate_json(read_atomically(path))
    except (OSError, ValueError):
        return
    renamed = report.model_copy(update={"name": target.name, "directory": target})
    write_atomically(path, renamed.model_dump_json(indent=2))


def _follow(root: Path, name: str, new_name: str | None) -> None:
    """Point what the models directory keeps of the model at its new name, or forget it when `new_name` is None."""
    state = _state(root)
    if state.last_viewed == name:
        write_atomically(root / STATE, state.model_copy(update={"last_viewed": new_name}).model_dump_json(indent=2))
    try:
        lines = read_atomically(root / IGNORES).splitlines(keepends=True)
    except FileNotFoundError:
        return
    kept: list[str] = []
    for line in lines:
        path = line.strip().removeprefix("!")
        if path == f"/{name}" or path.startswith(f"/{name}/"):
            # A model deleted is never opted in again by accident, by a new one of the same name.
            if new_name is None:
                continue
            line = line.replace(f"/{name}", f"/{new_name}", 1)
        kept.append(line)
    if kept != lines:
        write_atomically(root / IGNORES, "".join(kept))


def _remove_read_only(function: Callable[..., Any], path: str, error: BaseException) -> None:
    """Clear the read-only flag that stops Windows removing a file, such as a git object in a reference, and retry."""
    if not isinstance(error, PermissionError):
        raise error
    Path(path).chmod(stat.S_IWRITE)
    function(path)
