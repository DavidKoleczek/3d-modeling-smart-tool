"""What the person pins in the app, kept once for them so it follows them to every directory, and what they used in
one directory, kept beside its models."""

from pathlib import Path
import shutil
from typing import Any
import uuid

from pydantic import ValidationError

from modeling_3d.capabilities.app.settings import write_atomically
from modeling_3d.schemas import AppPins, Modeling3dError, ModelSummary, ReferenceEntry

PINS = "app-pins.json"
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


def _clear_unpinned(kept: Path, pins: AppPins) -> None:
    if not kept.is_dir():
        return
    pinned = [reference.path for reference in pins.references]
    for folder in kept.iterdir():
        if not any(path.is_relative_to(folder) for path in pinned):
            shutil.rmtree(folder, ignore_errors=True)
