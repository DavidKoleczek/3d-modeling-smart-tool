from pathlib import Path
import sys

import pytest

from modeling_3d.capabilities.app import folders, mcp_server


@pytest.fixture(autouse=True)
def config_directory(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The per-user config location every test sees, so none reads or writes the app settings of whoever runs it."""
    config = tmp_path_factory.mktemp("config")
    monkeypatch.setenv("APPDATA", str(config))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    if sys.platform == "darwin":
        monkeypatch.setenv("HOME", str(config))
    return config


@pytest.fixture(autouse=True)
def uploads_directory(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Where the app keeps the references the view sends, so no test touches those of an app running on this machine."""
    uploads = tmp_path_factory.mktemp("uploads")
    monkeypatch.setattr(mcp_server, "UPLOADS", uploads)
    return uploads


@pytest.fixture(autouse=True)
def opened_folders(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """The folders the app was asked to show, which no test opens in a real file manager."""
    opened: list[Path] = []
    monkeypatch.setattr(folders, "open_folder", opened.append)
    return opened
