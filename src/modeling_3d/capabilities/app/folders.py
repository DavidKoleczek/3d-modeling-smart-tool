"""Showing a folder to the person in their platform's file manager, and asking them for files from one."""

import json
import os
from pathlib import Path
import subprocess
import sys

from modeling_3d.schemas import Modeling3dError


def open_folder(path: Path) -> None:
    """Open `path` in Explorer, Finder, or whatever `xdg-open` picks, creating it first if it is not there yet."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)
        else:
            command = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen(
                [command, str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except OSError as error:
        raise Modeling3dError(
            f"Could not open {path} in a file manager: {error}. Open it from a terminal or file manager instead."
        ) from None


# Python's own Tk, run apart from the server: it shows the platform's native dialog on Windows and macOS, and a process
# of its own gives Tk the main thread macOS requires. The hidden window it hangs from stays on top, so the dialog shows
# above the browser that asked for it.
CHOOSE_SCRIPT = """
import json
import sys
import tkinter
from tkinter import filedialog

directory, title, kind = sys.argv[1:4]
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()
if kind == "folder":
    chosen = filedialog.askdirectory(parent=root, initialdir=directory, title=title, mustexist=True)
    print(json.dumps([chosen] if chosen else []))
else:
    print(json.dumps(list(filedialog.askopenfilenames(parent=root, initialdir=directory, title=title))))
"""


def choose_files(directory: Path, title: str) -> list[Path]:
    """Ask the person for files in their platform's file dialog, opened at `directory`; none when they cancel."""
    if not directory.is_dir():
        raise Modeling3dError(f"{directory} is not a folder on this machine. Unpin it and pin the folder again.")
    return _ask(directory, title, "files")


def choose_folder(directory: Path, title: str) -> Path | None:
    """Ask the person for a folder in their platform's folder dialog, opened at `directory`; None when they cancel."""
    chosen = _ask(directory, title, "folder")
    return chosen[0] if chosen else None


def _ask(directory: Path, title: str, kind: str) -> list[Path]:
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-c", CHOOSE_SCRIPT, str(directory), title, kind],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as error:
        raise Modeling3dError(
            f"Could not show a file dialog: {error}. Drop or paste the files onto the app instead."
        ) from None
    if done.returncode != 0:
        reason = done.stderr.strip().splitlines()[-1] if done.stderr.strip() else f"exit code {done.returncode}"
        raise Modeling3dError(
            f"Could not show a file dialog: {reason}. It needs Tk in the Python running the app; drop or paste the "
            "files onto the app instead."
        )
    return [Path(path) for path in json.loads(done.stdout or "[]")]
