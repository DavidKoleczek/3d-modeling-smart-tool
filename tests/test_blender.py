"""Puts a fake Blender on PATH, with the platform faked and the user's registry and home left alone."""

from pathlib import Path

import pytest

from modeling_3d import lib
from modeling_3d.capabilities.blender import blender
from modeling_3d.schemas import Modeling3dError


def executable(folder: Path, name: str = "blender.exe") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"")
    return path


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Path]:
    """Windows, with Program Files in tmp_path; what would be added to the user PATH is recorded instead."""
    monkeypatch.setattr(blender.sys, "platform", "win32")
    monkeypatch.setattr(blender.shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.delenv("ProgramW6432", raising=False)
    added: list[Path] = []

    def append(directory: Path) -> bool:
        if directory in added:
            return False
        added.append(directory)
        return True

    monkeypatch.setattr(blender, "_append_to_user_path", append)
    return added


@pytest.fixture
def links(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Linux, with ~/.local/bin in tmp_path; skipped where this machine cannot make a symlink."""
    probe = tmp_path / "probe"
    try:
        probe.symlink_to(tmp_path)
    except OSError:
        pytest.skip("This machine cannot make symlinks.")
    monkeypatch.setattr(blender.sys, "platform", "linux")
    monkeypatch.setattr(blender.shutil, "which", lambda name: None)
    monkeypatch.setattr(blender, "LINK_DIRECTORY", tmp_path / "bin")
    return tmp_path / "bin"


def test_a_blender_already_on_path_is_left_as_it_is(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(blender.shutil, "which", lambda name: "/usr/bin/blender")

    result = lib.add_blender_to_path()

    assert not result.changed
    assert result.executable == Path("/usr/bin/blender")
    assert "already runs" in result.message


def test_on_windows_the_newest_installed_blender_goes_on_the_user_path(windows: list[Path], tmp_path: Path) -> None:
    foundation = tmp_path / "Program Files" / "Blender Foundation"
    (foundation / "Blender 4.5").mkdir(parents=True)
    executable(foundation / "Blender 5.2")
    newest = executable(foundation / "Blender 5.10")

    first = lib.add_blender_to_path()
    again = lib.add_blender_to_path()

    assert first.changed
    assert first.executable == newest
    assert windows == [newest.parent]
    assert "Open a new terminal" in first.message
    assert not again.changed
    assert "already on your user PATH" in again.message


def test_a_named_folder_or_executable_is_the_blender_used(windows: list[Path], tmp_path: Path) -> None:
    portable = executable(tmp_path / "portable")

    by_folder = lib.add_blender_to_path(tmp_path / "portable")
    by_file = lib.add_blender_to_path(portable)

    assert by_folder.executable == by_file.executable == portable


@pytest.mark.parametrize(
    ("named", "message"),
    [(True, "no Blender executable"), (False, blender.DOWNLOAD)],
    ids=["named-path", "none-installed"],
)
def test_without_a_blender_it_names_what_to_do(windows: list[Path], tmp_path: Path, named: bool, message: str) -> None:
    with pytest.raises(Modeling3dError) as failure:
        lib.add_blender_to_path(tmp_path if named else None)

    assert message in str(failure.value)
    assert windows == []


def test_elsewhere_a_link_in_local_bin_runs_blender(links: Path, tmp_path: Path) -> None:
    installed = executable(tmp_path / "blender-5.2", "blender")

    first = lib.add_blender_to_path(installed)
    again = lib.add_blender_to_path(installed)

    assert first.changed
    assert (links / "blender").resolve() == installed.resolve()
    assert not again.changed


def test_a_link_that_runs_something_else_is_not_replaced(links: Path, tmp_path: Path) -> None:
    executable(links, "blender")

    with pytest.raises(Modeling3dError) as failure:
        lib.add_blender_to_path(executable(tmp_path / "blender-5.2", "blender"))

    assert "Remove it" in str(failure.value)
