"""Top level entry point for the Modeling 3D library."""

from pathlib import Path

from modeling_3d.capabilities.app import folders as app_folders
from modeling_3d.capabilities.app import mcp_server as app_server_module
from modeling_3d.capabilities.app import server as app_module
from modeling_3d.capabilities.app import settings as app_settings
from modeling_3d.capabilities.app.mcp_server import AppServer
from modeling_3d.capabilities.blender import blender
from modeling_3d.capabilities.create_3d_model import activity, create, intelligence_models, models
from modeling_3d.capabilities.create_3d_model.create import ModelRun
from modeling_3d.capabilities.create_3d_model.record import DEFAULT_DIRECTORY
from modeling_3d.core import manifest
from modeling_3d.core import skill as skill_module
from modeling_3d.intelligence.interface import Intelligence
from modeling_3d.schemas import (
    DEFAULT_REASONING_EFFORT,
    AgentProvider,
    BlenderOnPath,
    IntelligenceModels,
    Manifest,
    ModelActivity,
    ModelListing,
    ModelSummary,
    ReasoningEffort,
    ToolCall,
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


def app_server(directory: Path | None = None) -> AppServer:
    """The app's MCP server: the tool that opens the app, the tools its view calls, and the view as an MCP App.

    Serve `AppServer.server` over any MCP transport. `AppServer.open` serves the browser host page, which renders
    the view for agents that cannot embed it and reaches the same server at its own `/mcp`. The view shows the models
    in `AppServer.directory`, and creates, changes, steers, and stops them through this library's capabilities, as
    from `app`. Nothing done in it is sent to an agent session; a session sees it with `read_3d_model_activity`.
    How the person set up the app, such as its theme and pane sizes, is theirs in every directory, kept in
    `app-settings.json` in their config directory.

    Args:
        directory: Where the models the app shows are kept; `.modeling-3d` in the working directory when omitted.
    """
    return app_server_module.AppServer(
        skill_module.DISTRIBUTION,
        version(),
        (directory or DEFAULT_DIRECTORY).resolve(),
        list_models=models.list_3d_models,
        view_model=models.view_3d_model,
        create_model=create.create_3d_model,
        steer_model=create.steer_3d_model,
        cancel_model=create.cancel_3d_model,
        read_activity=activity.read_3d_model_activity,
        read_tool_call=activity.read_3d_model_tool_call,
        list_intelligence=intelligence_models.list_intelligence_models,
        settings_path=app_settings.settings_path(),
        open_folder=app_folders.open_folder,
    )


def app_view() -> str:
    """The app's view, an MCP App: the HTML a host renders inline, and the one the browser host page renders."""
    return app_module.view()


async def create_3d_model(
    prompt: str,
    name: str,
    directory: Path | None = None,
    references: list[Path] | None = None,
    resume_session: bool | str = False,
    agent_provider: AgentProvider | None = None,
    model: str | None = None,
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT,
    timeout_seconds: int = 3600,
    origin: str | None = None,
    detach: bool = False,
    intelligence: Intelligence | None = None,
) -> ModelRun:
    """Create a 3D model, or change it when it exists, returning its handle as soon as the agent runs. Model-backed.

    An agent writes the model as a Blender script, model.py, in the model's own directory, builds model.glb with it,
    and renders and looks at the result until it matches the request.

    Args:
        prompt: What to build, or what to change.
        name: The model's name and directory under `directory`. When a model by that name exists there, ignoring
            case, the request changes it; otherwise it creates a new model.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
        references: Files and folders to work from, such as images, models, or another model's model.py, model.glb,
            and renders. Each is copied into the model's references/, a folder whole but for its hidden folders,
            node_modules, and __pycache__, and images given as files are also shown to the agent with the prompt.
        resume_session: For a model that exists, which agent session to continue, so the agent keeps the
            conversation: True for its last session, or the id of one of its sessions. False, the default, starts a
            fresh session, which reads model.py, the whole model, and starts from a small context. A new model, or one
            without a session, starts a fresh one. A model's sessions are the `session_id` of each run in its
            model.json; `read_3d_model_activity` gives each request's, and `list_3d_models` gives the last run's.
        agent_provider: The first installed when omitted; the session's own when continuing one.
        model: The agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS` when omitted.
        reasoning_effort: How hard the model thinks.
        timeout_seconds: How long the run may take before it is stopped; its session can still be resumed.
        origin: Who is asking, shown with the request in the model's activity: `app`, `claude-code:<session id>`, or
            a name of the caller's own.
        detach: Run in a process of its own, which outlives this one. It still returns once the agent runs, and a
            request that cannot run still raises. The handle follows the run through the files it writes.
        intelligence: An implementation to run the agent with, in place of the agent provider's; not with `detach`.
    """
    return await create.create_3d_model(
        prompt=prompt,
        name=name,
        directory=directory,
        references=references,
        resume_session=resume_session,
        agent_provider=agent_provider,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        origin=origin,
        detach=detach,
        intelligence=intelligence,
    )


def steer_3d_model(name: str, message: str, directory: Path | None = None, origin: str | None = None) -> None:
    """Send a message to the agent working on the model, from any process; the run's events show when it lands.

    Args:
        name: The model being worked on.
        message: What to tell its agent.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
        origin: Who is sending it, shown with it in the model's activity, as for `create_3d_model`.
    """
    create.steer_3d_model(name=name, message=message, directory=directory, origin=origin)


def cancel_3d_model(name: str, directory: Path | None = None) -> None:
    """Stop the run working on the model at once, from any process; its session can still be resumed."""
    create.cancel_3d_model(name=name, directory=directory)


def read_3d_model_activity(name: str, directory: Path | None = None, after: str | None = None) -> ModelActivity:
    """Everything about how a model is being made: its summary, and its activity across every run.

    The activity is each request and steering message with who sent it, what the agent said, the tools it ran and
    which failed, and how each run ended. It is the one view of a run every agent provider shares; their own events
    stay in each run's events.jsonl as they gave them. Reads only, so it is safe while runs write.

    Args:
        name: The model's name, exactly as its directory is named.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
        after: The `cursor` of an earlier read, for only the activity since.
    """
    return activity.read_3d_model_activity(name=name, directory=directory, after=after)


def read_3d_model_tool_call(name: str, run_id: str, call_id: str, directory: Path | None = None) -> ToolCall:
    """One tool call of a model's agent in full: the arguments it was called with, and what came back as text.

    The activity gives each call only by what it works on; this gives the whole command, edit, or file, and its
    output. Reads only, so it is safe while runs write.

    Args:
        name: The model's name, exactly as its directory is named.
        run_id: The `run_id` of the call's `tool` entry in the model's activity.
        call_id: The `id` in that entry's `data`.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
    """
    return activity.read_3d_model_tool_call(name=name, run_id=run_id, call_id=call_id, directory=directory)


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


def list_intelligence_models() -> IntelligenceModels:
    """The AI models and reasoning efforts to pick from for `create_3d_model`, and what it runs with given neither.

    The models are those of the installed agent providers; `create_3d_model` also takes any other model by name.
    """
    return intelligence_models.list_intelligence_models()


def add_blender_to_path(blender_path: Path | None = None) -> BlenderOnPath:
    """Make `blender` run an installed Blender from new terminals, for opening and running models outside the tool.

    Building models does not need it: model.py gets Blender from PyPI through uv.

    Args:
        blender_path: Blender's executable, or the folder that holds it; the newest found where the platform installs
            it when omitted.
    """
    return blender.add_blender_to_path(blender_path)
