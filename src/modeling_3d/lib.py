"""Top level entry point for the Modeling 3D library."""

from collections.abc import Callable
from pathlib import Path

from modeling_3d.capabilities.app import mcp_server as app_server_module
from modeling_3d.capabilities.app import server as app_module
from modeling_3d.capabilities.app.mcp_server import AppServer
from modeling_3d.capabilities.blender import blender
from modeling_3d.capabilities.create_3d_model import create, models
from modeling_3d.capabilities.create_3d_model.create import ModelRun
from modeling_3d.core import manifest
from modeling_3d.core import skill as skill_module
from modeling_3d.intelligence.interface import Intelligence
from modeling_3d.schemas import (
    DEFAULT_REASONING_EFFORT,
    AgentProvider,
    BlenderOnPath,
    Manifest,
    ModelListing,
    ModelSummary,
    ReasoningEffort,
)


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


async def create_3d_model(
    prompt: str,
    name: str,
    directory: Path | None = None,
    references: list[Path] | None = None,
    edit: bool = False,
    resume: bool = False,
    agent_provider: AgentProvider | None = None,
    model: str | None = None,
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT,
    timeout_seconds: int = 3600,
    intelligence: Intelligence | None = None,
) -> ModelRun:
    """Create a 3D model, or change one with `edit`, returning its handle as soon as the agent runs. Model-backed.

    An agent writes the model as a Blender script, model.py, in the model's own directory, builds model.glb with it,
    and renders and looks at the result until it matches the request.

    Args:
        prompt: What to build, or what to change.
        name: The model's name and directory under `directory`. A new model's name must not be taken there, ignoring
            case; with `edit` or `resume`, it names the existing model to change.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
        references: Images and models to work from, copied into the model's directory. Images are also shown to the
            agent with the prompt.
        edit: Change the existing model named `name`, in a fresh session that reads its model.py first.
        resume: Implies `edit`. Continue the session that last worked on the model, for a follow-up soon after it while its context
            is still cached, or after a run that was cut short. Leave it out when coming back later: a fresh session
            reads model.py, which holds the whole model, and starts from a small context.
        agent_provider: The first installed when omitted; a resumed model's own when omitted.
        model: The agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS` when omitted.
        reasoning_effort: How hard the model thinks.
        timeout_seconds: How long the run may take before it is stopped; its session can still be resumed.
        intelligence: An implementation to run the agent with, in place of the agent provider's.
    """
    return await create.create_3d_model(
        prompt=prompt,
        name=name,
        directory=directory,
        references=references,
        edit=edit,
        resume=resume,
        agent_provider=agent_provider,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        intelligence=intelligence,
    )


def steer_3d_model(name: str, message: str, directory: Path | None = None) -> None:
    """Send a message to the agent working on the model, from any process; the run's events show when it lands."""
    create.steer_3d_model(name=name, message=message, directory=directory)


def cancel_3d_model(name: str, directory: Path | None = None) -> None:
    """Stop the run working on the model at once, from any process; its session can still be resumed."""
    create.cancel_3d_model(name=name, directory=directory)


def list_3d_models(directory: Path | None = None) -> ModelListing:
    """Every model in a directory, most recently updated first, with its state, and the one viewed last.

    Reads only, so it is safe while runs write. A directory that does not exist lists as empty.

    Args:
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
    """
    return models.list_3d_models(directory=directory)


def view_3d_model(name: str, directory: Path | None = None) -> ModelSummary:
    """Record the model as the one viewed last in its directory, and return its summary.

    Args:
        name: The model's name, exactly as its directory is named.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
    """
    return models.view_3d_model(name=name, directory=directory)


def add_blender_to_path(blender_path: Path | None = None) -> BlenderOnPath:
    """Make `blender` run an installed Blender from new terminals, for opening and running models outside the tool.

    Building models does not need it: model.py gets Blender from PyPI through uv.

    Args:
        blender_path: Blender's executable, or the folder that holds it; the newest found where the platform installs
            it when omitted.
    """
    return blender.add_blender_to_path(blender_path)
