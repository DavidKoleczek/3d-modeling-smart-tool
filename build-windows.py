"""
Check and build the Windows app, when the tools to do so are present.

The exe under `windows/target/` is not committed; a release builds it. Rust is needed only to change the Windows app,
and it only builds on Windows; without cargo, or anywhere else, this script says so and exits 0, so
`prek run --all-files` passes for everyone who doesn't work on it.

Arguments name the steps to run, so each precommit hook runs one step; with none it runs all.
"""

from pathlib import Path
import shutil
import subprocess
import sys

WINDOWS = Path(__file__).parent / "windows"
STEPS = {
    "format": "fmt",
    "lint": "clippy --all-targets --locked -- -D warnings",
    "test": "test --locked",
    "build": "build --release --locked",
}


def main() -> None:
    if sys.platform != "win32":
        print("Not on Windows; skipping the Windows app, which only builds there.")
        return
    cargo = shutil.which("cargo")
    if cargo is None:
        print("cargo not found; skipping the Windows app. Install Rust only to change it (see CONTRIBUTING.md).")
        return
    for step in sys.argv[1:] or STEPS:
        # Run from the crate's folder, which is where rustup looks for the toolchain it pins.
        subprocess.run([cargo, *STEPS[step].split()], cwd=WINDOWS, check=True)


if __name__ == "__main__":
    main()
