"""
Cross-platform script to set up a development environment for the project.
It assumes that you have installed all the prerequisites listed in CONTRIBUTING.md.
"""

from pathlib import Path
import shlex
import shutil
import subprocess
import tomllib

REFERENCE_ROOT = Path(__file__).parent / "reference"
REFERENCES = [
    "https://github.com/microsoft/amplifier-smart-tools",
    "https://github.com/openai/codex",
    "https://github.com/anthropics/claude-agent-sdk-python",
    "https://github.com/agentskills/agentskills",
    "https://github.com/anthropics/claude-plugins-official",
    "https://github.com/modelcontextprotocol/python-sdk",
    "https://github.com/modelcontextprotocol/ext-apps",
    "https://github.com/microsoft/amplifier-smart-tool-creator",
    "https://github.com/microsoft/amplifier-smart-tool-reality-check",
    "https://github.com/astral-sh/uv",
    "https://github.com/DavidKoleczek/reference-store",
    "https://github.com/vercel-labs/skills",
]
WINDOWS_LOCK = Path(__file__).parent / "windows" / "Cargo.lock"
# Crates the Windows app is built on. Each is cloned at the version `windows/Cargo.lock` has
CRATE_REFERENCES = {
    "tao": "https://github.com/tauri-apps/tao",
    "tray-icon": "https://github.com/tauri-apps/tray-icon",
    "wry": "https://github.com/tauri-apps/wry",
}
# How these repositories tag a release.
CRATE_TAG = "{crate}-v{version}"
# A tag is checked out with no branch, which git otherwise explains at length.
QUIET_GIT = ["git", "-c", "advice.detachedHead=false"]


def run(command: str) -> None:
    """Run a command, forwarding its output to this process's stdout and stderr."""
    subprocess.run(shlex.split(command), check=True)


def clone_or_update_references() -> None:
    """Clone every reference repository that is absent, and move each present one to its branch's latest commit."""
    for repository in REFERENCES:
        destination = REFERENCE_ROOT / repository.rsplit("/", 1)[-1]
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--depth", "1", "--single-branch", repository, str(destination)], check=True
            )
            continue
        subprocess.run(["git", "-C", str(destination), "fetch", "--depth", "1"], check=True)
        # A shallow fetch leaves nothing to fast-forward from, so the clone is moved instead. `--keep` keeps any
        # local edits, and stops rather than overwrite one.
        subprocess.run(["git", "-C", str(destination), "reset", "--keep", "FETCH_HEAD"], check=True)


def clone_crate_references() -> None:
    """Clone each crate reference at its locked version, and move a clone left at another version to it."""
    lock = tomllib.loads(WINDOWS_LOCK.read_text(encoding="utf-8"))
    versions = {package["name"]: package["version"] for package in lock["package"]}
    for crate, repository in CRATE_REFERENCES.items():
        version = versions.get(crate)
        if version is None:
            print(f"{crate} is not in {WINDOWS_LOCK.name}; skipping its reference.")
            continue
        destination = REFERENCE_ROOT / crate
        tag = CRATE_TAG.format(crate=crate, version=version)
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [*QUIET_GIT, "clone", "--depth", "1", "--single-branch", "--branch", tag, repository, str(destination)],
                check=True,
            )
            continue
        git = [*QUIET_GIT, "-C", str(destination)]
        # The tag is missing from a clone of the default branch, or of another release.
        tagged = subprocess.run([*git, "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}"], capture_output=True)
        head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, check=True)
        if tagged.returncode != 0 or tagged.stdout != head.stdout:
            subprocess.run([*git, "fetch", "--depth", "1", "origin", "tag", tag], check=True)
            subprocess.run([*git, "checkout", tag], check=True)


def install_app_dependencies() -> None:
    """Only when pnpm is present; the compiled app is committed, so Node is needed only to change it."""
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        print("pnpm not found; skipping the app's dependencies. Install Node 22+ and pnpm to change the frontend.")
        return
    subprocess.run([pnpm, "--dir", "app", "install", "--frozen-lockfile"], check=True)


def fetch_windows_crates() -> None:
    """Only when cargo is present; Rust is needed only to change the Windows app."""
    cargo = shutil.which("cargo")
    if cargo is None:
        print("cargo not found; skipping the Windows app's crates. Install Rust to change the Windows app.")
        return
    subprocess.run([cargo, "fetch", "--locked"], cwd=WINDOWS_LOCK.parent, check=True)


def main() -> None:
    run("uv --version")
    run("prek --version")
    run("uv sync --frozen --all-extras --all-groups")
    run("prek install")
    clone_or_update_references()
    clone_crate_references()
    install_app_dependencies()
    fetch_windows_crates()


if __name__ == "__main__":
    main()
