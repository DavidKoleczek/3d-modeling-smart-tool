"""The references a request or a steering message comes with: found, copied into the model's directory, and which of
them are shown to the agent."""

from pathlib import Path
import shutil

from modeling_3d.intelligence.schemas import IMAGE_MEDIA_TYPES
from modeling_3d.schemas import Modeling3dError

# Folders a folder reference leaves out, beside hidden ones.
SKIPPED_FOLDERS = ("node_modules", "__pycache__")


def resolve_references(paths: list[Path]) -> list[Path]:
    resolved = [path.resolve() for path in paths]
    for path in resolved:
        if not path.is_file() and not path.is_dir():
            raise Modeling3dError(
                f"The reference {path} is not a file or a folder. Name each reference image, model, or folder by its "
                "path, relative to the working directory or absolute.",
                "missing-reference",
            )
    return resolved


def copy_references(target: Path, sources: list[Path]) -> list[str]:
    """Copy each reference into the model's references/, keeping its name unless another holds it already.

    A file the same as the one there already is not copied again. A folder is copied whole, and recorded with a
    trailing slash.
    """
    if not sources:
        return []
    folder = target / "references"
    folder.mkdir(exist_ok=True)
    copied: list[str] = []
    for source in sources:
        destination = folder / source.name
        suffix = 2
        while destination.exists() and (
            source.is_dir() or destination.is_dir() or destination.read_bytes() != source.read_bytes()
        ):
            destination = folder / f"{source.stem}-{suffix}{source.suffix}"
            suffix += 1
        if source.is_dir():
            shutil.copytree(source, destination, ignore=_skipped)
            copied.append(f"{destination.relative_to(target).as_posix()}/")
            continue
        if not destination.exists():
            shutil.copy2(source, destination)
        copied.append(destination.relative_to(target).as_posix())
    return copied


def attached(reference: str) -> bool:
    """Whether a reference is an image shown to the agent with the prompt; a folder's images are left for it to open."""
    return not reference.endswith("/") and Path(reference).suffix.lower() in IMAGE_MEDIA_TYPES


def _skipped(folder: str, names: list[str]) -> list[str]:
    """What a folder reference leaves out: hidden folders and tool caches, which are rarely what was meant."""
    return [name for name in names if (name.startswith(".") or name in SKIPPED_FOLDERS) and Path(folder, name).is_dir()]
