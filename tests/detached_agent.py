"""The process a detached run runs in, with its agent faked by the script in fakes.py named as its one argument."""

from pathlib import Path
import sys

import fakes

from modeling_3d.capabilities.create_3d_model import background, runs


def command(script: str) -> list[str]:
    """What runs a detached run with its agent faked by `script`, in place of `create.BACKGROUND_COMMAND`."""
    return [sys.executable, str(Path(__file__)), script]


if __name__ == "__main__":
    runs.POLL_SECONDS = 0.01
    raise SystemExit(background.main(fakes.FakeIntelligence(getattr(fakes, sys.argv[1]))))
