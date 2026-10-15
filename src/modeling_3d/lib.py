"""Top level entry point for the Modeling 3d library."""

from collections.abc import Callable
from pathlib import Path

from modeling_3d.capabilities.app import server as app_module
from modeling_3d.capabilities.app.server import App
from modeling_3d.core import manifest
from modeling_3d.core import skill as skill_module
from modeling_3d.schemas import Manifest


def load_manifest() -> Manifest:
    """The tool's manifest as structured data, read from the SMART_TOOL.md shipped inside the package."""
    return manifest.load_manifest()


def skill(capability: str | None = None) -> str:
    """The tool's skill, or the named capability's own skill, wrapped so a reader knows where the tool's files are."""
    return skill_module.skill(capability)


def skill_directory() -> Path:
    """The installed package root, where the files the skill names can be read."""
    return skill_module.skill_directory()


def skill_resources() -> list[str]:
    """The files the skill lists, as paths relative to the skill directory. Every one ships inside the package."""
    return skill_module.skill_resources()


def capability_skill_resources(capability: str) -> list[str]:
    """The files that capability's skill lists, as paths relative to the skill directory."""
    return skill_module.capability_skill_resources(capability)


def version() -> str:
    """The installed package's version, from its metadata."""
    return skill_module.version()


def repository_url() -> str | None:
    """The tool's canonical source, from the package metadata, or None when the package declares none."""
    return skill_module.repository_url()


def serve_app(on_message: Callable[[str], None] | None = None, port: int | None = None) -> App:
    """Serve the app, a chat page on this machine, from a daemon thread and return it once the port is listening.

    It lives until `App.stop` or the process exits, and only this machine can reach it.

    Args:
        on_message: Called with each message typed on the page, on the app's own thread.
        port: The port to bind; a free one is chosen when omitted.
    """
    return app_module.serve_app(on_message, port)
