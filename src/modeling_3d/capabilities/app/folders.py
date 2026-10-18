"""Showing a folder to the person, in their platform's file manager."""

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
