"""Top level entry point for the Modeling 3D library."""

from collections.abc import Callable

from modeling_3d.capabilities.app import mcp_server as app_server_module
from modeling_3d.capabilities.app import server as app_module
from modeling_3d.capabilities.app.mcp_server import AppServer
from modeling_3d.core import manifest
from modeling_3d.core import skill as skill_module
from modeling_3d.schemas import Manifest


def load_manifest() -> Manifest:
    """The tool's manifest as structured data, read from the SMART_TOOL.md shipped inside the package."""
    return manifest.load_manifest()


def skill(capability: str | None = None) -> str:
    """The tool's skill, or the named capability's own skill, wrapped so a reader knows where the tool's files are.

    Args:
        capability: One of the names the tool's skill lists under its capabilities; an unknown name raises
            `Modeling3dError` listing the valid ones. Omit it for the tool's skill.
    """
    return skill_module.skill(capability)


def version() -> str:
    """The installed package's version, from its metadata."""
    return skill_module.version()


def app_server(deliver: Callable[[str], None] | None = None) -> AppServer:
    """The app's MCP server: tools that open the app and talk through it, and its view as an MCP App resource.

    Serve `AppServer.server` over any MCP transport. `AppServer.open` serves the browser host page, which renders
    the view for agents that cannot embed it and reaches the same server at its own `/mcp`.

    Args:
        deliver: Called with each message the user sends from the browser host page, on a worker thread; raises
            `OSError` when it cannot deliver. Without it, or when it raises, the message is handed to the agent with
            its next tool result instead.
    """
    return app_server_module.AppServer(skill_module.DISTRIBUTION, version(), deliver)


def app_view() -> str:
    """The app's view, an MCP App: the HTML a host renders inline, and the one the browser host page renders."""
    return app_module.view()
