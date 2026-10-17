"""A models directory on disk: each model's model.json, its files, and whether the process running it is alive."""

import os
from pathlib import Path
import sys
import time

from pydantic import ValidationError

from modeling_3d.schemas import Modeling3dError, ModelRecord

DEFAULT_DIRECTORY = Path(".modeling-3d")
RECORD = "model.json"
REQUIRED_FILES = ("model.py", "model.glb")
# Windows refuses to replace a file another process has open, such as a UX reading model.json; such a read is brief.
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
        return ModelRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise Modeling3dError(
            f"{path} is not a modeling-3d model record: {error.errors()[0]['msg']}. Fix or remove it."
        ) from None


def write_record(target: Path, record: ModelRecord) -> None:
    write_atomically(target / RECORD, record.model_dump_json(indent=2))


def write_atomically(path: Path, text: str) -> None:
    # Written aside and renamed, because other processes read it while this one writes it.
    partial = path.with_name(f"{path.name}.tmp")
    partial.write_text(text, encoding="utf-8")
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            partial.replace(path)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_SECONDS)


def model_files(target: Path) -> list[str]:
    """The model's own files: its script and what it builds, not the run's bookkeeping."""
    names = [name for name in (*REQUIRED_FILES, "model.py.lock", "model.blend") if (target / name).is_file()]
    renders = sorted(path.relative_to(target).as_posix() for path in (target / "renders").glob("*") if path.is_file())
    return names + renders


def model_names(root: Path) -> list[str]:
    return sorted(path.parent.name for path in root.glob(f"*/{RECORD}"))


def missing_model(root: Path, name: str) -> Modeling3dError:
    known = ", ".join(model_names(root)) or "none"
    return Modeling3dError(
        f"There is no model named {name!r} in {root}. The models there: {known}. Name one of them, or pass the "
        "--directory the model was created in."
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
