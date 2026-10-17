"""List the models in a directory, and remember the one viewed last."""

from pathlib import Path

from modeling_3d.capabilities.create_3d_model.record import (
    DEFAULT_DIRECTORY,
    alive,
    load_record,
    missing_model,
    model_files,
    model_names,
    write_atomically,
)
from modeling_3d.schemas import Modeling3dError, ModelListing, ModelRecord, ModelsState, ModelStatus, ModelSummary

# A model's name starts with a letter or digit, so this can never be a model's directory.
STATE = ".state.json"


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
            models.append(_summary(root / name, load_record(root / name)))
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
    summary = _summary(root / name, load_record(root / name))
    state = _state(root).model_copy(update={"last_viewed": name})
    write_atomically(root / STATE, state.model_dump_json(indent=2))
    return summary


def _summary(target: Path, record: ModelRecord) -> ModelSummary:
    run = record.runs[-1] if record.runs else None
    status: ModelStatus | None = None
    if run is not None:
        # Left as it is on disk: the next run on the model marks it failed, and a listing never races a writer.
        status = "crashed" if run.status == "running" and not alive(run.pid) else run.status
    times = [record.created] if run is None else [run.started, run.last_event, run.finished]
    return ModelSummary(
        name=target.name,
        id=record.id,
        directory=target,
        created=record.created,
        updated=max(time for time in times if time is not None),
        status=status,
        last_run=run,
        files=model_files(target),
    )


def _state(root: Path) -> ModelsState:
    """What the person last did in the directory; nothing when it was never written or cannot be read."""
    try:
        return ModelsState.model_validate_json((root / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ModelsState()
