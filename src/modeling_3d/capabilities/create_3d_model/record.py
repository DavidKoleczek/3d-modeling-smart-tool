"""A models directory on disk: each model's records and files, and whether the process running it is alive."""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

from pydantic import ValidationError

from modeling_3d.schemas import ModelEvent, Modeling3dError, ModelRecord, ModelRunRecord, ModelRuns

# region: A models directory
DEFAULT_DIRECTORY = Path(".modeling-3d")
# Written into a models directory the tool makes. Its patterns start with / so they reach only that directory, and
# being the deepest .gitignore, it decides over the project's own for the files in it.
GITIGNORE = Path(__file__).parent / "models.gitignore"
# The project's guidance for every model in a directory, beside them. Neither agent provider loads it by itself, since
# each looks for its instructions only from the project's root to its working directory, the project's root.
GUIDANCE = "AGENTS.md"
# Which model was viewed last, kept beside the models. A model's name starts with a letter or digit, so this can never
# be a model's directory.
STATE = ".state.json"
# endregion

# region: A model's directory
RECORD = "model.json"
RUNS = "runs.json"
GLB = "model.glb"
REQUIRED_FILES = ("model.py", GLB)
# The model's surface detail, which its material declares, since glTF has no place for it.
DETAIL = "model-detail.png"
# The model's latest check, with its renders beside it.
REPORT = Path("checks") / "report.json"
# Each run's events, and where a detached run's process writes once its agent runs, in the run's directory.
EVENTS = "events.jsonl"
PROCESS_LOG = "process.log"
# endregion

# Windows refuses to replace a file another process has open, such as a UX reading runs.json, and to open one being
# replaced; both are brief.
REPLACE_ATTEMPTS = 20
REPLACE_WAIT_SECONDS = 0.05


def load_record(target: Path) -> ModelRecord:
    path = target / RECORD
    if not path.is_file():
        raise Modeling3dError(
            f"{target} is not a model made by modeling-3d: it has no {RECORD}. Choose another name, or another "
            "--directory."
        )
    try:
        record = ModelRecord.model_validate_json(read_atomically(path))
    except ValidationError as error:
        raise Modeling3dError(
            f"{path} is not a modeling-3d model record: {error.errors()[0]['msg']}. Fix or remove it."
        ) from None
    runs = target / RUNS
    if not runs.is_file():
        # A model whose runs were never kept here, as one cloned from where it was made, has none.
        record.runs = []
        return record
    try:
        record.runs = ModelRuns.model_validate_json(read_atomically(runs)).runs
    except ValidationError as error:
        raise Modeling3dError(
            f"{runs} is not a modeling-3d run record: {error.errors()[0]['msg']}. Fix it, or remove it to forget the "
            "model's runs and sessions."
        ) from None
    return record


def write_record(target: Path, record: ModelRecord) -> None:
    # The runs first, so a model found by its model.json has them.
    write_runs(target, record.runs)
    write_atomically(target / RECORD, record.model_dump_json(indent=2))


def write_runs(target: Path, runs: list[ModelRunRecord]) -> None:
    write_atomically(target / RUNS, ModelRuns(runs=runs).model_dump_json(indent=2))


def make_models_directory(root: Path) -> None:
    """Make the models directory, with a .gitignore of its own while it holds no models yet.

    Holding only hidden files, such as what the app remembers there, it is new to the tool. One holding anything else
    is left as it is, since its project has already set up what it commits.
    """
    root.mkdir(parents=True, exist_ok=True)
    target = root / ".gitignore"
    if target.exists() or any(entry.is_dir() or not entry.name.startswith(".") for entry in root.iterdir()):
        return
    shutil.copyfile(GITIGNORE, target)


def last_session(record: ModelRecord) -> ModelRunRecord | None:
    """The latest run with a session, which a request continues when it resumes without naming a session."""
    return next((run for run in reversed(record.runs) if run.session_id is not None), None)


def read_atomically(path: Path) -> str:
    # Windows refuses to open a file in the moment another process replaces it, as write_atomically does.
    for _ in range(REPLACE_ATTEMPTS - 1):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            time.sleep(REPLACE_WAIT_SECONDS)
    return path.read_text(encoding="utf-8")


def write_atomically(path: Path, text: str) -> None:
    # Written aside and renamed, because other processes read it while this one writes it. Each write has a file of its
    # own to rename, so two at once never take each other's.
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as file:
        partial = Path(file.name)
        file.write(text)
    try:
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                partial.replace(path)
                return
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_WAIT_SECONDS)
    finally:
        partial.unlink(missing_ok=True)


def read_events(path: Path, offset: int = 0) -> tuple[list[ModelEvent], int]:
    """The events in a run's events.jsonl past `offset`, and the offset to read on from.

    Only whole lines are read, so a line its run is still writing waits for the next read.
    """
    try:
        with path.open("rb") as events:
            events.seek(offset)
            data = events.read()
    except FileNotFoundError:
        return [], offset
    end = data.rfind(b"\n") + 1
    try:
        read = [ModelEvent.model_validate_json(line) for line in data[:end].splitlines() if line.strip()]
    except ValidationError as error:
        raise Modeling3dError(
            f"{path} holds a line that is not a modeling-3d event: {error.errors()[0]['msg']}. Remove that line."
        ) from None
    return read, offset + end


def model_files(target: Path) -> list[str]:
    """The model's own files: its script and what it builds, not the run's bookkeeping."""
    names = [name for name in (*REQUIRED_FILES, DETAIL, "model.py.lock", "model.blend") if (target / name).is_file()]
    renders = sorted(path.relative_to(target).as_posix() for path in (target / "renders").glob("*") if path.is_file())
    return names + renders


def model_names(root: Path) -> list[str]:
    return sorted(path.parent.name for path in root.glob(f"*/{RECORD}"))


def missing_model(root: Path, name: str) -> Modeling3dError:
    known = ", ".join(model_names(root)) or "none"
    return Modeling3dError(
        f"There is no model named {name!r} in {root}. The models there: {known}. Name one of them, or pass the "
        "--directory the model was created in.",
        "no-such-model",
        name,
    )


def alive(pid: int) -> bool:
    """Whether a process with this id is running."""
    if sys.platform == "win32":
        import ctypes

        # os.kill on Windows terminates the process rather than probing it, so ask the kernel instead.
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
