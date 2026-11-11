"""What the person pins and uses in the app in a models directory, kept beside its models so each directory has its
own."""

from pathlib import Path
import shutil
from typing import Any
import uuid

from pydantic import ValidationError

from modeling_3d.capabilities.app.settings import write_atomically
from modeling_3d.schemas import APP_STATE_FOLDER, AppPins, AppState, Modeling3dError, ModelSummary, ReferenceEntry

# What the person pinned, picked, and used in the app in a models directory, in its `APP_STATE_FOLDER`.
APP_STATE = "app.json"
# Where versions before 0.4.0 kept `APP_STATE`, beside the models. It is read until the state is next written, which
# moves it.
EARLIER_APP_STATE = ".app.json"
# Where, in `APP_STATE_FOLDER`, a file or folder the person dropped or pasted is kept once they pin it, since it has no
# path of its own.
KEPT = "pins"
# What the app offers as used before, at most.
USED = 50
# What a pinned folder lists, at most, so a folder of thousands still shows at once.
FOLDER_ENTRIES = 500


def app_state_path(directory: Path) -> Path:
    """Where what the person pinned, picked, and used in the app in the models `directory` is kept."""
    return directory / APP_STATE_FOLDER / APP_STATE


def read_app_state(directory: Path) -> AppState | None:
    """What the person pinned, picked, and used in the app in the models `directory`; None when nothing was kept
    there, or it cannot be read."""
    for path in (app_state_path(directory), directory / EARLIER_APP_STATE):
        if path.is_file():
            try:
                return AppState.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
    return None


def write_app_state(directory: Path, state: AppState) -> None:
    """Keep `state` for the models `directory`, replacing what was there, and remove where an earlier version kept
    it."""
    write_atomically(app_state_path(directory), state.model_dump_json(indent=2))
    (directory / EARLIER_APP_STATE).unlink(missing_ok=True)


def check_pins(pins: dict[str, Any]) -> AppPins:
    """`pins` as the app keeps them, or the first reason they cannot be."""
    try:
        return AppPins.model_validate(pins)
    except ValidationError as error:
        problem = error.errors()[0]
        field = ".".join(str(part) for part in problem["loc"]) or "pins"
        raise Modeling3dError(
            f"The app pin {field} is not valid: {problem['msg']}. Send what `read_app_library` returns, changed only "
            "where the person pinned or unpinned something.",
            "bad-pins",
        ) from None


def keep(source: Path, directory: Path) -> Path:
    """Copy a file or folder the person sent into a folder of its own in the models `directory`, to pin; return
    where."""
    target = directory / APP_STATE_FOLDER / KEPT / uuid.uuid4().hex / source.name
    try:
        target.parent.mkdir(parents=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    except OSError as error:
        raise Modeling3dError(
            f"Could not keep {source.name} to pin it: {error}. Check that {target.parents[1]} can be written."
        ) from None
    return target


def entry(path: Path) -> ReferenceEntry | None:
    """`path` as the app offers it to work from, or None when it is no longer a file or a folder."""
    if path.is_dir():
        return ReferenceEntry(name=path.name, path=path, kind="folder")
    if path.is_file():
        return ReferenceEntry(name=path.name, path=path, kind="file")
    return None


def used_here(chosen: list[Path], models: list[ModelSummary]) -> list[ReferenceEntry]:
    """What was chosen to work from in a directory, then what its models were given, newest first, each once, at most
    `USED`, of what is still there."""
    given = [
        model.directory / reference.rstrip("/") for model in models for reference in reversed(model.references)
    ]
    entries: list[ReferenceEntry] = []
    copies: set[tuple[str, int]] = set()
    for path in dict.fromkeys([*chosen, *given]):
        found = entry(path)
        if found is None:
            continue
        # A file given to several models is copied into each, so it is offered once, by its name and size.
        if found.kind == "file":
            copy = (found.name.lower(), path.stat().st_size)
            if copy in copies:
                continue
            copies.add(copy)
        entries.append(found)
        if len(entries) == USED:
            break
    return entries


def remember(used: list[Path], chosen: list[Path]) -> list[Path]:
    """What was used, with `chosen` first, each once, at most `USED`."""
    return list(dict.fromkeys([*chosen, *used]))[:USED]


def list_folder(folder: Path) -> list[ReferenceEntry]:
    """What is in a pinned folder to work from: its folders, then its files, each by name, leaving out hidden ones."""
    try:
        children = [child for child in folder.iterdir() if not child.name.startswith(".")]
    except OSError as error:
        raise Modeling3dError(
            f"Could not read the pinned folder {folder}: {error}. If it moved, unpin it and pin it from where it is now.",
            "missing-reference",
        ) from None
    children.sort(key=lambda child: (not child.is_dir(), child.name.lower()))
    entries = (entry(child) for child in children[:FOLDER_ENTRIES])
    return [found for found in entries if found is not None]


def clear_unpinned(directory: Path, pins: AppPins) -> None:
    """Clear what was kept in the models `directory` for pins no longer among `pins`."""
    kept = directory / APP_STATE_FOLDER / KEPT
    if not kept.is_dir():
        return
    pinned = [reference.path for reference in pins.references]
    for folder in kept.iterdir():
        if not any(path.is_relative_to(folder) for path in pinned):
            shutil.rmtree(folder, ignore_errors=True)


def moved(old: Path, new: Path | None, directory: Path) -> None:
    """Point what the person pinned and used in the models `directory` at the same place under `new` wherever it was
    at or under `old`, or forget it when `new` is None.

    For a model renamed or deleted, whose directory is `old`. A file that cannot be read is left as it is, since the app
    reads it as empty.
    """
    before = read_app_state(directory)
    if before is None:
        return
    references = [
        reference.model_copy(update={"path": path})
        for reference in before.pins.references
        if (path := _relocated(reference.path, old, new)) is not None
    ]
    folders = [
        folder.model_copy(update={"path": path})
        for folder in before.pins.folders
        if (path := _relocated(folder.path, old, new)) is not None
    ]
    used = [path for path in (_relocated(path, old, new) for path in before.used) if path is not None]
    last_folder = None if before.last_folder is None else _relocated(before.last_folder, old, new)
    after = before.model_copy(
        update={
            "pins": before.pins.model_copy(update={"references": references, "folders": folders}),
            "used": list(dict.fromkeys(used)),
            "last_folder": last_folder,
        }
    )
    if after == before:
        return
    try:
        write_app_state(directory, after)
    except OSError as error:
        raise Modeling3dError(
            f"Could not update {app_state_path(directory)} for the model that was in {old}: {error}. Check that the "
            "folder can be written."
        ) from None


def _relocated(path: Path, old: Path, new: Path | None) -> Path | None:
    """Where `path` is once `old` has moved to `new`: itself when it is not under `old`, and None when `new` is None."""
    if not path.is_relative_to(old):
        return path
    return None if new is None else new / path.relative_to(old)


