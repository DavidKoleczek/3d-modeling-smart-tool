"""The workspaces opened in the app: kept once for the person, beside the app's settings, so any app offers them."""

from pathlib import Path

from modeling_3d.capabilities.app.settings import read_atomically, settings_path, write_atomically
from modeling_3d.schemas import AppWorkspaces, Modeling3dError, OpenedWorkspaces, RecentWorkspace

WORKSPACES = "app-workspaces.json"
# What the app offers to switch to, at most.
RECENT = 20


def workspaces_path() -> Path:
    """Where the workspaces opened in the app are kept: beside its settings."""
    return settings_path().with_name(WORKSPACES)


def last_workspace(path: Path) -> Path | None:
    """The workspace opened last, kept at `path`, that is still a folder; None when there is none."""
    return next((workspace for workspace in _opened_or_none(path) if workspace.is_dir()), None)


def read_app_workspaces(current: Path | None, path: Path) -> AppWorkspaces:
    """The workspace `current` while it is still a folder, and those kept at `path`, each with whether it is."""
    opened = _opened_or_none(path)
    recent = [RecentWorkspace(path=workspace, missing=not workspace.is_dir()) for workspace in opened]
    return AppWorkspaces(
        current=current if current is not None and current.is_dir() else None,
        recent=recent,
        new_in=_beside(current, opened),
    )


def default_folder(current: Path | None, path: Path) -> Path:
    """Where a new workspace is made, and the folder dialog opens, unless the person picks another folder."""
    return _beside(current, _opened_or_none(path))


def make_workspace(name: str, parent: Path) -> Path:
    """Make the folder `name` in `parent` for a new workspace, and return it."""
    name = name.strip()
    if name in ("", ".", "..") or any(separator in name for separator in "/\\"):
        raise Modeling3dError(f"{name!r} is not a folder's name. Name the new folder, without slashes.")
    if not parent.is_dir():
        raise Modeling3dError(f"{parent} is not a folder, so no workspace can be made in it. Choose another folder.")
    target = parent / name
    try:
        target.mkdir()
    except FileExistsError:
        raise Modeling3dError(
            f"{target} already exists. Open it with Open Workspace, or choose another name."
        ) from None
    except OSError as error:
        raise Modeling3dError(f"Could not make {target}: {error}. Choose another name or folder.") from None
    return target.resolve()


def _beside(current: Path | None, opened: list[Path]) -> Path:
    """Beside the workspace shown, else the one opened last, where another project of the person's is likeliest to be,
    while that folder is there; else the home folder."""
    nearby = [workspace.parent for workspace in [*([current] if current else []), *opened]]
    return next((folder for folder in nearby if folder.is_dir()), Path.home())


def record_workspace(workspace: Path, path: Path) -> None:
    """Keep `workspace` at `path` as the one opened last.

    Read again just before the write, so what other apps kept is kept too, but for one writing in the same instant.
    """
    opened = _opened(path)
    # Paths compare as the platform does, so on Windows one folder under two spellings of case is kept once.
    _write([workspace, *(other for other in opened if other != workspace)][:RECENT], path)


def forget_workspace(workspace: Path, path: Path) -> None:
    """Drop `workspace` from those kept at `path`, leaving its folder as it is."""
    opened = _opened(path)
    if workspace in opened:
        _write([other for other in opened if other != workspace], path)


def _opened_or_none(path: Path) -> list[Path]:
    try:
        return _opened(path)
    except OSError:
        return []


def _opened(path: Path) -> list[Path]:
    """Those kept at `path`, newest first; none when nothing was kept, or it was not written as this tool writes it.

    A file that is there but cannot be read raises, so a change never writes over what it could not read.
    """
    try:
        text = read_atomically(path)
    except FileNotFoundError:
        return []
    try:
        return OpenedWorkspaces.model_validate_json(text).workspaces
    except ValueError:
        return []


def _write(workspaces: list[Path], path: Path) -> None:
    write_atomically(path, OpenedWorkspaces(workspaces=workspaces).model_dump_json(indent=2))
