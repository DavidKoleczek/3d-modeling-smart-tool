"""A model's activity: what was asked of it, what its agent said and did, steering, and how each run ended."""

from pathlib import Path

from modeling_3d.capabilities.create_3d_model.models import model_summary
from modeling_3d.capabilities.create_3d_model.record import (
    DEFAULT_DIRECTORY,
    EVENTS,
    load_record,
    missing_model,
    model_names,
    read_events,
)
from modeling_3d.intelligence.interface import agent_steps
from modeling_3d.intelligence.schemas import AgentEvent
from modeling_3d.schemas import ActivityEntry, ModelActivity, ModelEvent, Modeling3dError, ModelRunRecord


def read_3d_model_activity(name: str, directory: Path | None = None, after: str | None = None) -> ModelActivity:
    """The model's summary and its activity across every run, or only what came after the cursor `after`."""
    root = (directory or DEFAULT_DIRECTORY).resolve()
    # Compared against the names on disk, since Windows and macOS find `Bear` when only `bear` exists.
    if name not in model_names(root):
        raise missing_model(root, name)
    target = root / name
    record = load_record(target)
    first, offset = _position(name, record.runs, after)
    entries: list[ActivityEntry] = []
    cursor = after or ""
    for run in record.runs[first:]:
        events, end = read_events(target / "runs" / run.id / EVENTS, offset)
        offset = 0
        steps = agent_steps(run.agent_provider)
        for event in events:
            if event.kind == "agent":
                agent_event = AgentEvent(time=event.time, type=event.text, data=event.data)
                entries += [
                    ActivityEntry(time=event.time, run_id=run.id, kind=step.kind, text=step.text, data=step.data)
                    for step in steps(agent_event, target)
                ]
            else:
                entries.append(_entry(event, run))
        # Byte offsets, so a read takes only what was written since the last one.
        cursor = f"{run.id}:{end}"
    return ModelActivity(model=model_summary(target, record), entries=entries, cursor=cursor)


def _position(name: str, runs: list[ModelRunRecord], after: str | None) -> tuple[int, int]:
    """The run a cursor is in and how far into its events, or the very start for none."""
    if not after:
        return 0, 0
    run_id, _, offset = after.rpartition(":")
    index = next((index for index, run in enumerate(runs) if run.id == run_id), None)
    if index is None or not offset.isdigit():
        raise Modeling3dError(
            f"{after!r} is not a cursor into model {name}'s activity. Read it without after to start from the "
            "beginning, then pass the cursor that read returns.",
            "bad-cursor",
            name,
        )
    return index, int(offset)


def _entry(event: ModelEvent, run: ModelRunRecord) -> ActivityEntry:
    if event.kind == "started":
        # From model.json, which runs from before the started event carried the request also have.
        data = {
            "references": run.references,
            "resumed": run.resumed,
            "agent_provider": run.agent_provider,
            "model": run.model,
            "session_id": run.session_id,
        }
        return ActivityEntry(
            time=event.time, run_id=run.id, kind="request", text=run.prompt, origin=run.origin, data=data
        )
    if event.kind == "steered":
        data = {key: event.data[key] for key in ("steering", "error") if key in event.data}
        return ActivityEntry(
            time=event.time, run_id=run.id, kind="steered", text=event.text, origin=event.data.get("origin"), data=data
        )
    data = {key: event.data.get(key) for key in ("status", "error", "files")}
    return ActivityEntry(time=event.time, run_id=run.id, kind="ended", text=event.data.get("text", ""), data=data)
