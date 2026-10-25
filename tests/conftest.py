from pathlib import Path
import sys

import pytest

from modeling_3d.capabilities.app import folders, mcp_server
from modeling_3d.capabilities.create_3d_model import runs
from modeling_3d.capabilities.create_3d_model.check import check


@pytest.fixture
def working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A working directory of the test's own, where `.modeling-3d` is its models directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def quick_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Steering and cancels from other processes reach a run at once."""
    monkeypatch.setattr(runs, "POLL_SECONDS", 0.01)


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
def state_directory(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The per-user state location every test sees, so none writes skills or scratch files for whoever runs it."""
    state = tmp_path_factory.mktemp("state")
    monkeypatch.setenv("LOCALAPPDATA", str(state))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    return state


@pytest.fixture(autouse=True)
def codex_home(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Where Codex keeps its sessions, so whether one can be continued never turns on those of whoever runs the tests."""
    home = tmp_path_factory.mktemp("codex")
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


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


@pytest.fixture(autouse=True)
def blender(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blender's half of the check, faked, since bpy is a large download and Blender is slow to start."""
    monkeypatch.setattr(check, "BLENDER_COMMAND", [sys.executable, str(Path(__file__).parent / "fake_blender.py")])
