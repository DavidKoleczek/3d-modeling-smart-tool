"""The app's settings: kept once for the person rather than in each directory, so the app looks the same everywhere."""

import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from pydantic import ValidationError

from modeling_3d.core.skill import DISTRIBUTION
from modeling_3d.schemas import AppSettings, Modeling3dError

SETTINGS = "app-settings.json"


def settings_path() -> Path:
    """The platform's per-user config location for the app's settings, where tools like VS Code and uv keep theirs."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / DISTRIBUTION / SETTINGS


def read_app_settings(path: Path) -> AppSettings:
    """The settings kept at `path`; the defaults when there are none yet, or they cannot be read."""
    try:
        return AppSettings.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppSettings()


def save_app_settings(settings: dict[str, Any], path: Path) -> AppSettings:
    """Check `settings` and keep them at `path`, replacing what was there; the last of several apps to save wins."""
    try:
        checked = AppSettings.model_validate(settings)
    except ValidationError as error:
        problem = error.errors()[0]
        field = ".".join(str(part) for part in problem["loc"]) or "settings"
        raise Modeling3dError(
            f"The app setting {field} is not valid: {problem['msg']}. Send what `read_app_settings` returns, changed "
            "only where the person changed it.",
            "bad-settings",
        ) from None
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside it and moved into place, so an app reading it at the same moment never sees half a file.
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(checked.model_dump_json(indent=2))
        temporary.replace(path)
    except OSError as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise Modeling3dError(
            f"Could not save the app's settings to {path}: {error}. Check that the folder can be written."
        ) from None
    return checked
