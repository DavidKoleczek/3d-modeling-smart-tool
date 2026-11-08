"""What the person pins in the app, kept once for them so it follows them to every directory, and what they used in
one directory, kept beside its models."""

from pathlib import Path
import shutil
from typing import Any
import uuid

from pydantic import BaseModel, ValidationError

from modeling_3d.capabilities.app.settings import write_atomically
from modeling_3d.schemas import AppPins, AppState, Modeling3dError, ModelSummary, ReferenceEntry

PINS = "app-pins.json"
# What the person picked and used in the app in a models directory, kept beside its models. Starting with a dot, it is
# never a model.
APP_STATE = ".app.json"
# Where a file or folder the person dropped or pasted is kept once they pin it, since it has no path of its own.
KEPT = "kept"
# What the app offers as used before, at most.
USED = 50
# What a pinned folder lists, at most, so a folder of thousands still shows at once.
FOLDER_ENTRIES = 500


def pins_path(settings: Path) -> Path:
    """Where the person's pins are kept: beside their settings at `settings`."""
    return settings.with_name(PINS)


def read_app_pins(path: Path) -> AppPins:
    """The pins kept at `path`; none when there are none yet, or they cannot be read."""
    try:
        return AppPins.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppPins()


def save_app_pins(pins: dict[str, Any], path: Path) -> AppPins:
    """Check `pins` and keep them at `path`, replacing what was there, and clear what was kept for pins now gone."""
    try:
        checked = AppPins.model_validate(pins)
    except ValidationError as error:
        problem = error.errors()[0]
        field = ".".join(str(part) for part in problem["loc"]) or "pins"
        raise Modeling3dError(
            f"The app pin {field} is not valid: {problem['msg']}. Send what `read_app_library` returns, changed only "
            "where the person pinned or unpinned something.",
            "bad-pins",
        ) from None
    try:
        write_atomically(path, checked.model_dump_json(indent=2))
    except OSError as error:
        raise Modeling3dError(
            f"Could not save the app's pins to {path}: {error}. Check that the folder can be written."
        ) from None
    _clear_unpinned(path.parent / KEPT, checked)
    return checked


def keep(source: Path, settings: Path) -> Path:
    """Copy a file or folder the person sent into a folder of its own beside their settings, to pin; return where."""
    target = settings.parent / KEPT / uuid.uuid4().hex / source.name
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


def moved(old: Path, new: Path | None, pins: Path, state: Path) -> None:
    """Point what the person pinned at `pins`, and what they used in the models directory whose `.app.json` is `state`,
    at the same place under `new` wherever it was at or under `old`, or forget it when `new` is None.

    For a model renamed or deleted, whose directory is `old`. A file that cannot be read is left as it is, since the app
    reads it as empty.
    """
    pinned = _read(AppPins, pins)
    if pinned is not None:
        references = [
            reference.model_copy(update={"path": path})
            for reference in pinned.references
            if (path := _relocated(reference.path, old, new)) is not None
        ]
        folders = [
            folder.model_copy(update={"path": path})
            for folder in pinned.folders
            if (path := _relocated(folder.path, old, new)) is not None
        ]
        _write_changed(pins, pinned, pinned.model_copy(update={"references": references, "folders": folders}), old)
    used = _read(AppState, state)
    if used is not None:
        kept = [path for path in (_relocated(path, old, new) for path in used.used) if path is not None]
        last_folder = None if used.last_folder is None else _relocated(used.last_folder, old, new)
        changed = used.model_copy(update={"used": list(dict.fromkeys(kept)), "last_folder": last_folder})
        _write_changed(state, used, changed, old)


def _relocated(path: Path, old: Path, new: Path | None) -> Path | None:
    """Where `path` is once `old` has moved to `new`: itself when it is not under `old`, and None when `new` is None."""
    if not path.is_relative_to(old):
        return path
    return None if new is None else new / path.relative_to(old)


def _read[Kept: BaseModel](kind: type[Kept], path: Path) -> Kept | None:
    try:
        return kind.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_changed(path: Path, before: BaseModel, after: BaseModel, old: Path) -> None:
    if after == before:
        return
    try:
        write_atomically(path, after.model_dump_json(indent=2))
    except OSError as error:
        raise Modeling3dError(
            f"Could not update {path} for the model that was in {old}: {error}. Check that the folder can be written."
        ) from None


def _clear_unpinned(kept: Path, pins: AppPins) -> None:
    if not kept.is_dir():
        return
    pinned = [reference.path for reference in pins.references]
    for folder in kept.iterdir():
        if not any(path.is_relative_to(folder) for path in pinned):
            shutil.rmtree(folder, ignore_errors=True)
