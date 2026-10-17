"""Put an installed Blender on PATH, so `blender` runs it from a new terminal."""

import os
from pathlib import Path
import re
import shutil
import sys

from modeling_3d.schemas import BlenderOnPath, Modeling3dError

DOWNLOAD = "https://www.blender.org/download/"
# Where a link makes Blender a command on macOS and Linux. uv installs its tools here too, so it is usually on PATH.
LINK_DIRECTORY = Path.home() / ".local" / "bin"
EXECUTABLE_NAMES = ("blender.exe", "blender", "Blender.app/Contents/MacOS/Blender")


def add_blender_to_path(blender_path: Path | None = None) -> BlenderOnPath:
    """Make `blender` run the given Blender, or the newest one installed in the platform's usual place."""
    if blender_path is None:
        found = shutil.which("blender")
        if found is not None:
            return BlenderOnPath(
                executable=Path(found), changed=False, message=f"`blender` already runs {found}; nothing changed."
            )
        executable = _installed()
    else:
        executable = _executable(blender_path)
    if sys.platform == "win32":
        directory = executable.parent
        if _append_to_user_path(directory):
            message = f"Added {directory} to your user PATH. Open a new terminal, and `blender` runs {executable}."
            return BlenderOnPath(executable=executable, changed=True, message=message)
        message = (
            f"{directory} is already on your user PATH. A terminal opened before it was added does not see it, so "
            "open a new one."
        )
        return BlenderOnPath(executable=executable, changed=False, message=message)
    return _link(executable)


def _installed() -> Path:
    for candidate in _candidates():
        if candidate.is_file():
            return candidate
    raise Modeling3dError(
        f"No installed Blender was found where {sys.platform} keeps it. Install Blender from {DOWNLOAD}, or pass "
        "--blender-path with the path to its executable or its folder."
    )


def _candidates() -> list[Path]:
    """Where Blender installs, the newest version first."""
    if sys.platform == "win32":
        roots = {Path(os.environ[name]) for name in ("ProgramFiles", "ProgramW6432") if os.environ.get(name)}
        # An uninstall can leave a version folder behind without blender.exe, which the glob passes over.
        found = [path for root in roots for path in root.glob("Blender Foundation/Blender*/blender.exe")]
        return sorted(found, key=_version, reverse=True)
    if sys.platform == "darwin":
        bundle = Path("Blender.app/Contents/MacOS/Blender")
        return [Path("/Applications") / bundle, Path.home() / "Applications" / bundle]
    return [
        Path("/snap/bin/blender"),
        Path("/usr/bin/blender"),
        Path("/usr/local/bin/blender"),
        *sorted(Path("/opt").glob("blender*/blender"), key=_version, reverse=True),
    ]


def _version(executable: Path) -> tuple[int, ...]:
    return tuple(int(number) for number in re.findall(r"\d+", executable.parent.name))


def _executable(blender: Path) -> Path:
    blender = blender.expanduser().resolve()
    if blender.is_file():
        return blender
    for name in EXECUTABLE_NAMES:
        if (blender / name).is_file():
            return blender / name
    raise Modeling3dError(
        f"There is no Blender executable at {blender}. Pass the path to blender.exe, blender, or Blender.app, or "
        "the folder that holds it."
    )


def _link(executable: Path) -> BlenderOnPath:
    link = LINK_DIRECTORY / "blender"
    LINK_DIRECTORY.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        if link.resolve() != executable.resolve():
            raise Modeling3dError(f"{link} already exists and does not run {executable}. Remove it, then run again.")
        changed = False
    else:
        link.symlink_to(executable)
        changed = True
    message = f"{link} runs {executable}."
    if str(LINK_DIRECTORY) not in os.environ.get("PATH", "").split(os.pathsep):
        message += f" {LINK_DIRECTORY} is not on PATH: add it, for example with `uv tool update-shell`."
    return BlenderOnPath(executable=executable, changed=changed, message=message + " Then open a new terminal.")


def _append_to_user_path(directory: Path) -> bool:
    """Add the directory to the user's PATH in the registry unless it is there; whether it was added."""
    if sys.platform != "win32":
        raise NotImplementedError("The user PATH lives in the registry only on Windows.")
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        entries = {os.path.normcase(os.path.expandvars(entry)).rstrip("\\") for entry in value.split(";") if entry}
        if os.path.normcase(str(directory)).rstrip("\\") in entries:
            return False
        # The same registry type is kept, so entries written with %VARIABLES% still expand.
        winreg.SetValueEx(key, "Path", 0, kind, f"{value.rstrip(';')};{directory}" if value else str(directory))
    hwnd_broadcast, wm_settingchange, smto_abortifhung = 0xFFFF, 0x001A, 0x0002
    # Tells Explorer the environment changed, so terminals opened from now on start with the new PATH.
    ctypes.windll.user32.SendMessageTimeoutW(
        hwnd_broadcast, wm_settingchange, 0, "Environment", smto_abortifhung, 5000, ctypes.byref(ctypes.c_ulong())
    )
    return True
