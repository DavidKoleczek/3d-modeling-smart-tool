"""List the models in a directory, and remember the one viewed last."""

from datetime import UTC, datetime
from pathlib import Path

from modeling_3d.capabilities.create_3d_model.record import (
    DEFAULT_DIRECTORY,
    GLB,
    REPORT,
    STATE,
    alive,
    last_session,
    load_record,
    missing_model,
    model_files,
    model_names,
    read_atomically,
    write_atomically,
)
from modeling_3d.intelligence.interface import can_resume
from modeling_3d.schemas import Modeling3dError, ModelListing, ModelRecord, ModelsState, ModelStatus, ModelSummary


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
    # Compared against the names on disk, since Windows and macOS find `Bear` when only `bear` exists.
    if name not in model_names(root):
        raise missing_model(root, name)
    summary = model_summary(root / name, load_record(root / name))
    state = _state(root).model_copy(update={"last_viewed": name})
    write_atomically(root / STATE, state.model_dump_json(indent=2))
    return summary


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
