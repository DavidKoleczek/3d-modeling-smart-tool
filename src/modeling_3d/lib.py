"""Top level entry point for the 3D Modeling library."""

from contextlib import AbstractContextManager
from pathlib import Path

from modeling_3d.capabilities.app import folders as app_folders
from modeling_3d.capabilities.app import mcp_server as app_server_module
from modeling_3d.capabilities.app import server as app_module
from modeling_3d.capabilities.app import settings as app_settings
from modeling_3d.capabilities.app.mcp_server import AppServer
from modeling_3d.capabilities.blender import blender
from modeling_3d.capabilities.create_3d_model import activity, create, intelligence_models, models, runs
from modeling_3d.capabilities.create_3d_model.check import check
from modeling_3d.capabilities.create_3d_model.record import DEFAULT_DIRECTORY
from modeling_3d.capabilities.create_3d_model.runs import ModelRun
from modeling_3d.core import manifest
from modeling_3d.core import skill as skill_module
from modeling_3d.intelligence.interface import Intelligence
from modeling_3d.schemas import (
    DEFAULT_REASONING_EFFORT,
    NOT_GIVEN,
    AgentProvider,
    BlenderOnPath,
    IntelligenceModels,
    Manifest,
    ModelActivity,
    ModelCheck,
    ModelListing,
    ModelSummary,
    NotGiven,
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
    in `AppServer.directory`, and creates, changes, rigs, colors, details, checks, steers, and stops them through this library's
    capabilities, as from `app`. Nothing done in it is sent to an agent session; a session sees it with
    `read_3d_model_activity`.
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
        rig_model=create.rig_3d_model,
        color_model=create.color_3d_model,
        detail_model=create.detail_3d_model,
        check_model=check.check_3d_model,
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
    max_triangles: int | NotGiven | None = NOT_GIVEN,
    max_draw_calls: int | NotGiven | None = NOT_GIVEN,
    screen_size: tuple[int, int] | NotGiven | None = NOT_GIVEN,
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
    and renders and looks at the result until it matches the request. It builds the shape from named parts, without
    materials unless asked, which `rig_3d_model` splits and joins to ready it to move and `color_3d_model` colors by
    role; reshaping a rigged or colored model keeps its rig and colors. It runs in the working directory, usually the
    project the model is for, which it may explore; it writes only in the model's directory. An AGENTS.md in
    `directory` is the project's guidance for its models, and a fresh session is told to read it. The run ends with
    the shape, and never goes on to rig or color the model by itself.

    Args:
        prompt: What to build, or what to change.
        name: The model's name and directory under `directory`. When a model by that name exists there, ignoring
            case, the request changes it; otherwise it creates a new model.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
        references: Files and folders to work from, such as images, models, or another model's model.py, model.glb,
            and renders. Each is copied into the model's references/, a folder whole but for its hidden folders,
            node_modules, and __pycache__, and images given as files are also shown to the agent with the prompt.
        max_triangles: The most triangles the model may have; None for no budget. Each budget left out is the
            default for a new model, from `DEFAULT_MAX_TRIANGLES` and the others in schemas.py, and the model's own
            for a change. Set them for what the model is for rather than leaving the defaults, and leave them out
            when continuing a session unless they change.
        max_draw_calls: The most draw calls the model may take, one for each material on each mesh object.
        screen_size: The smallest and largest the model is on screen, in pixels along its longest side at 1080p, which
            sets how small its detail can be and how many sides its round parts need.
        resume_session: For a model that exists, which agent session to continue, so the agent keeps the
            conversation: True for its last session, or the id of one of its sessions. False, the default, starts a
            fresh session, which reads model.py, the whole model, and starts from a small context. A new model, or one
            without a session, starts a fresh one. A model's sessions are the `session_id` of each run in its
            runs.json; `read_3d_model_activity` gives each request's, and `list_3d_models` gives the last run's. A
            session that last worked in another mode, such as rigging, is told this one's instructions as it goes on.
        agent_provider: The first installed when omitted; the session's own when continuing one.
        model: The agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS` when omitted.
        reasoning_effort: How hard the model thinks; one the model takes, as `list_intelligence_models` lists.
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
        max_triangles=max_triangles,
        max_draw_calls=max_draw_calls,
        screen_size=screen_size,
        resume_session=resume_session,
        agent_provider=agent_provider,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        origin=origin,
        detach=detach,
        intelligence=intelligence,
    )


async def rig_3d_model(
    name: str,
    prompt: str | None = None,
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
    """Rig a built 3D model so it can move, returning its handle as soon as the agent runs. Model-backed.

    An agent changes the model's model.py, keeping its shape: each part that moves, is swapped, or is hidden on its
    own becomes its own object with its origin at its pivot and its motion declared as `check_3d_model` reads it;
    what bends gets a skeleton; every other part is joined into one object; and named empties mark the points
    other code uses. A model with nothing that moves comes out with its parts joined and its points marked. It works to the
    model's own budgets. A rig is a run of the model like any other, so it is steered, cancelled, followed, and
    continued the same ways, and it ends once the model is rigged.

    Args:
        name: A model in `directory` that has been built, ignoring case.
        prompt: What moves and how, or what to change in the rig; when omitted, the agent works it out from the model,
            its references, and the project's guidance.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
        references: Files and folders to work from, as for `create_3d_model`.
        resume_session: Which agent session to continue, as for `create_3d_model`. A session that last shaped the
            model is told the rig's instructions as it goes on.
        agent_provider: As for `create_3d_model`.
        model: As for `create_3d_model`.
        reasoning_effort: As for `create_3d_model`.
        timeout_seconds: How long the run may take before it is stopped; its session can still be resumed.
        origin: Who is asking, as for `create_3d_model`.
        detach: Run in a process of its own, as for `create_3d_model`.
        intelligence: An implementation to run the agent with, in place of the agent provider's; not with `detach`.
    """
    return await create.rig_3d_model(
        name=name,
        prompt=prompt,
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


async def color_3d_model(
    name: str,
    prompt: str | None = None,
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
    """Color a built 3D model by role, returning its handle as soon as the agent runs. Model-backed.

    An agent changes the model's model.py, keeping its shape and rig: every mesh gets one material whose base color
    texture is a palette, a column for each role and a row for each color scheme; each face's UVs land on its role's
    swatch in the default scheme; the roles that glow go in an emission palette of the same layout; and the material
    declares the roles and schemes as `check_3d_model` reads them. It uses the project's roles and schemes where its
    guidance names them, and may move a part to another role. It works to the model's own budgets. A coloring is a
    run of the model like any other, so it is steered, cancelled, followed, and continued the same ways, and it ends
    once the model is colored.

    Args:
        name: A model in `directory` that has been built, ignoring case.
        prompt: The roles, schemes, or colors wanted, or what to change in them; when omitted, the agent works them
            out from the model, its references, and the project's guidance.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
        references: Files and folders to work from, such as concept art to take colors from, as for
            `create_3d_model`.
        resume_session: Which agent session to continue, as for `create_3d_model`. A session that last worked in
            another mode is told the coloring's instructions as it goes on.
        agent_provider: As for `create_3d_model`.
        model: As for `create_3d_model`.
        reasoning_effort: As for `create_3d_model`.
        timeout_seconds: How long the run may take before it is stopped; its session can still be resumed.
        origin: Who is asking, as for `create_3d_model`.
        detach: Run in a process of its own, as for `create_3d_model`.
        intelligence: An implementation to run the agent with, in place of the agent provider's; not with `detach`.
    """
    return await create.color_3d_model(
        name=name,
        prompt=prompt,
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


async def detail_3d_model(
    name: str,
    prompt: str | None = None,
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
    """Paint the surface detail of a built 3D model, returning its handle as soon as the agent runs. Model-backed.

    An agent changes the model's model.py, keeping its shape, rig, and colors: it paints one grayscale texture from the
    geometry, such as seams, fasteners, highlights along edges, and wear, unwraps the faces it covers on the second
    set of texture coordinates at a density set by the largest size on screen, saves it beside model.glb as
    model-detail.png, and declares it on the material as `check_3d_model` reads it. A renderer multiplies the base color
    by twice the detail, so mid gray leaves a color as it is in every scheme. It follows the project's guidance on how
    much to paint, and works to the model's own budgets. A detailing is a run of the model like any other, so it is
    steered, cancelled, followed, and continued the same ways, and it ends once the detail is painted.

    Args:
        name: A model in `directory` that has been built, ignoring case.
        prompt: The detail wanted, or what to change in it; when omitted, the agent works out what the model would
            show from the model, its references, and the project's guidance.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
        references: Files and folders to work from, such as photos of the wear wanted, as for `create_3d_model`.
        resume_session: Which agent session to continue, as for `create_3d_model`. A session that last worked in
            another mode is told the detailing's instructions as it goes on.
        agent_provider: As for `create_3d_model`.
        model: As for `create_3d_model`.
        reasoning_effort: As for `create_3d_model`.
        timeout_seconds: How long the run may take before it is stopped; its session can still be resumed.
        origin: Who is asking, as for `create_3d_model`.
        detach: Run in a process of its own, as for `create_3d_model`.
        intelligence: An implementation to run the agent with, in place of the agent provider's; not with `detach`.
    """
    return await create.detail_3d_model(
        name=name,
        prompt=prompt,
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


def check_3d_model(
    name: str,
    directory: Path | None = None,
    checks: list[str] | None = None,
    max_triangles: int | NotGiven | None = NOT_GIVEN,
    max_draw_calls: int | NotGiven | None = NOT_GIVEN,
    screen_size: tuple[int, int] | NotGiven | None = NOT_GIVEN,
) -> ModelCheck:
    """Measure a model's model.glb against its budgets and the workflow, and keep the report in its checks/.

    Purely informational: each check reports what it measured, and nothing passes or fails, so whoever reads it
    decides what matters. A check is skipped, saying why, when what it measures is absent, such as a budget or a
    motion. The shape checks are the triangles, those under a pixel at the smallest size on screen, how far smooth
    curves stray from true ones at the largest, faces no ray from outside reaches, and renders at both sizes beside
    the model's image references. The rig checks are the draw calls, the mesh objects that neither move nor have a
    skin, each declared motion and what its part touches through its range, skeletons, markers, and renders of each
    motion's poses. The color checks read the palette, a column for each role and a row for each scheme, with the
    roles and schemes its material declares: its swatches, the role each triangle's UVs land on, what the emission
    palette lights, and flat renders in each scheme. Buried faces, sweeps, and renders run Blender through uv, which
    downloads bpy the first time. It never writes model.json or runs.json, so it can run while an agent works on the
    model.

    Args:
        name: The model's name, exactly as its directory is named.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
        checks: The checks to run, by name or by the groups `shape`, `rig`, and `color`, as `CHECK_NAMES` and
            `CHECK_GROUPS` in schemas.py list them; every check when omitted.
        max_triangles: The triangle budget to measure against; None for none. Each budget left out is the model's
            own, from its last run, and never the defaults a new model gets.
        max_draw_calls: The draw call budget to measure against.
        screen_size: The smallest and largest the model is on screen to measure at, in pixels along its longest side
            at 1080p.
    """
    return check.check_3d_model(
        name=name,
        directory=directory,
        checks=checks,
        max_triangles=max_triangles,
        max_draw_calls=max_draw_calls,
        screen_size=screen_size,
    )


def steer_3d_model(
    name: str,
    message: str,
    directory: Path | None = None,
    origin: str | None = None,
    references: list[Path] | None = None,
) -> None:
    """Send a message to the agent working on the model, from any process; the run's events show when it lands.

    Args:
        name: The model being worked on.
        message: What to tell its agent.
        directory: Where models are kept; `.modeling-3d` in the working directory when omitted.
        origin: Who is sending it, shown with it in the model's activity, as for `create_3d_model`.
        references: Files or folders to send with it, copied into the model's references/ as for `create_3d_model`;
            images are shown to the agent with the message.
    """
    create.steer_3d_model(name=name, message=message, directory=directory, origin=origin, references=references)


def cancel_3d_model(name: str, directory: Path | None = None) -> None:
    """Stop the run working on the model at once, from any process; its session can still be resumed."""
    create.cancel_3d_model(name=name, directory=directory)


def stopped_by_signals(run: ModelRun) -> AbstractContextManager[None]:
    """While in the block, stop the run on every signal that ends this process, such as Ctrl+C or its console closing.

    For a process that waits on a run it started, so the run's session stays resumable and nothing its agent started
    outlives it. Each signal's handler is put back after.
    """
    return runs.stopped_by_signals(run)


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
    """The AI models to pick from for `create_3d_model`, each with its reasoning efforts, and what it runs with given
    neither.

    The models are those of the installed agent providers; `create_3d_model` also takes any other model by name, with
    any reasoning effort its agent provider has.
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
