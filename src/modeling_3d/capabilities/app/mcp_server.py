"""The app's MCP server: the tool that opens the app, the tools its view calls, and the view as an MCP App resource."""

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable
import concurrent.futures
import contextlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import threading
import time
from typing import Any, Protocol
from urllib.parse import unquote
import uuid

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID, client_supports_apps
from mcp.types import (
    INVALID_PARAMS,
    BlobResourceContents,
    CallToolRequestParams,
    CallToolResult,
    ElicitRequest,
    ElicitRequestURLParams,
    ElicitResult,
    InputRequiredResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    TextContent,
    TextResourceContents,
    Tool,
)

from modeling_3d.capabilities.app.pins import (
    APP_STATE,
    keep,
    list_folder,
    pins_path,
    read_app_pins,
    remember,
    save_app_pins,
    used_here,
)
from modeling_3d.capabilities.app.server import App, serve_app, view
from modeling_3d.capabilities.app.settings import read_app_settings, save_app_settings, write_atomically
from modeling_3d.capabilities.app.tools import (
    APP_ONLY,
    CANCEL_MODEL,
    CHECK_MODEL,
    CHOOSE_FILES,
    CHOOSE_FOLDER,
    CHOOSE_INTELLIGENCE,
    COLOR_MODEL,
    DETAIL_MODEL,
    CREATE_MODEL,
    DELETE_MODEL,
    KEEP_UPLOAD,
    LIST_FOLDER,
    LIST_INTELLIGENCE,
    LIST_MODELS,
    MODEL_FILE,
    MODEL_FILE_PREFIX,
    OPEN_APP,
    OPEN_FOLDER,
    READ_ACTIVITY,
    READ_FOLDERS,
    READ_LIBRARY,
    READ_SETTINGS,
    READ_TOOL_CALL,
    REFERENCE_FILE,
    REFERENCE_FILE_PREFIX,
    RENAME_MODEL,
    RIG_MODEL,
    SAVE_PINS,
    SAVE_SETTINGS,
    STAGE_FILES,
    STEER_MODEL,
    UPLOAD_REFERENCE,
    VIEW,
    VIEW_META,
    VIEW_MODEL,
    VIEW_TOOLS,
    VIEW_URI,
)
from modeling_3d.schemas import (
    AGENT_PROVIDERS,
    DEFAULT_REASONING_EFFORT,
    NOT_GIVEN,
    REASONING_EFFORTS,
    AppFolders,
    AppIntelligence,
    AppLibrary,
    AppState,
    IntelligenceChoice,
    IntelligenceModels,
    Modeling3dError,
    ModelActivity,
    ModelCheck,
    ModelListing,
    ModelMode,
    ModelSummary,
    ReferenceEntry,
    StagedReference,
    ToolCall,
)

# region: The model files the view reads
# What the view reads of a model: its GLB, its renders, and its reference images. The rest, such as model.py and its
# sessions, stays put.
MODEL_FILE_TYPES = {
    ".glb": "model/gltf-binary",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
# And its latest check: the report, and the renders beside it.
CHECK_FILE = re.compile(r"checks/(report\.json|[A-Za-z0-9._-]+\.png)")
# endregion

# region: Checks
# How long a call to check a model waits for it. Blender can take longer than a host waits for a call, the first time
# above all, when uv downloads it, so a call returns before then and the view calls again for the same check.
CHECK_WAIT_SECONDS = 20
# endregion

# region: Uploads
# Where references the view sends wait for the request that takes them, shared by every app on this machine. Each upload
# has a folder of its own there, under the view's id for it.
UPLOADS = Path(tempfile.gettempdir()) / "modeling-3d-uploads"
UPLOAD_ID = re.compile(r"[0-9a-f]{16,64}")
# An upload never taken, such as one whose app was killed, is cleared by the next app to start after this long.
UPLOAD_LIFETIME_SECONDS = 24 * 60 * 60
# A model's own files that stand for it as a reference, beside its first render: its script and its GLB.
REFERENCE_TYPES = (".py", ".glb")
# A file chosen in the file dialog comes back with a preview when it is an image the view shows, up to this size, as
# the view previews one it sends.
PREVIEW_TYPES = {**{suffix: kind for suffix, kind in MODEL_FILE_TYPES.items() if kind.startswith("image/")}, ".gif": "image/gif"}
PREVIEW_BYTES = 8 * 1024 * 1024
CHOOSE_TITLE = "Choose references"
CHOOSE_FOLDER_TITLE = "Choose a folder to pin"
# What a folder staged from this machine leaves out: what a folder reference leaves out when it is copied in, hidden
# folders and tool caches, along with hidden files.
STAGE_SKIPPED = shutil.ignore_patterns(".*", "node_modules", "__pycache__")
# endregion

# region: What the app keeps and who it acts as
# The key `open_app` files its request to open the browser under, when the client answers by retrying the call.
OPEN_REQUEST = "open"
# Who the model's activity shows as asking, for everything done in the app.
ORIGIN = "app"
# endregion

# region: The host agent's instructions
SEES_THE_APP = (
    "Nothing they do there is sent to you: see the models and their state with `modeling-3d list-3d-models`, and what "
    "was asked of one and what its agent did with `modeling-3d read-3d-model-activity --name <name>`."
)
INSTRUCTIONS = f"""\
3D Modeling has an app where the user watches the models in one directory being made, and creates, changes, steers, \
and stops them. Call `open_app` when they ask for it. `modeling-3d view-3d-model --name <name>` brings a model up in it.

{SEES_THE_APP} Read a model's activity before acting on it, since they may have changed or steered it in the app."""
# endregion


class Started(Protocol):
    """What the view needs of a run `create_model`, `rig_model`, `color_model`, or `detail_model` started: the model
    it works on."""

    name: str


class AppServer:
    """The app's MCP server, and the browser host page once it is open.

    Serve `server` over any MCP transport. Several at once share this state, so the browser host page reaches the
    same server the agent's session does. The capabilities the view calls are passed in, so this stays a surface.
    """

    def __init__(
        self,
        server_name: str,
        version: str,
        directory: Path,
        list_models: Callable[[Path], ModelListing],
        view_model: Callable[[str, Path], ModelSummary],
        rename_model: Callable[[str, str, Path], ModelSummary],
        delete_model: Callable[[str, Path], None],
        create_model: Callable[..., Awaitable[Started]],
        rig_model: Callable[..., Awaitable[Started]],
        color_model: Callable[..., Awaitable[Started]],
        detail_model: Callable[..., Awaitable[Started]],
        check_model: Callable[[str, Path], ModelCheck],
        steer_model: Callable[[str, str, Path, str, list[Path]], None],
        cancel_model: Callable[[str, Path], None],
        read_activity: Callable[[str, Path, str | None], ModelActivity],
        read_tool_call: Callable[[str, str, str, Path], ToolCall],
        list_intelligence: Callable[[], IntelligenceModels],
        settings_path: Path,
        open_folder: Callable[[Path], None],
        choose_files: Callable[[Path, str], list[Path]],
        choose_folder: Callable[[Path, str], Path | None],
    ) -> None:
        self.directory = directory
        self.settings_path = settings_path
        self.pins_path = pins_path(settings_path)
        self._open_folder = open_folder
        self._choose_files = choose_files
        self._choose_folder = choose_folder
        # Whether a file or folder dialog is showing, so a second click doesn't show another.
        self._choosing = False
        self._list_models = list_models
        self._view_model = view_model
        self._rename_model = rename_model
        self._delete_model = delete_model
        # What starts a run in each mode.
        self._starts: dict[ModelMode, Callable[..., Awaitable[Started]]] = {
            "shape": create_model,
            "rig": rig_model,
            "color": color_model,
            "detail": detail_model,
        }
        self._check_model = check_model
        # By model directory, the check under way, or ended and not yet given to a call.
        self._checks: dict[Path, concurrent.futures.Future[ModelCheck]] = {}
        self._steer_model = steer_model
        self._cancel_model = cancel_model
        self._read_activity = read_activity
        self._read_tool_call = read_tool_call
        self._list_intelligence = list_intelligence
        self._lock = threading.Lock()
        self._uploads: set[str] = set()
        self._app: App | None = None
        clear_old_uploads(time.time())
        self._offered = False
        self.server = Server(
            server_name,
            version=version,
            instructions=INSTRUCTIONS,
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool_or_explain,
            on_list_resources=self._list_resources,
            on_list_resource_templates=self._list_resource_templates,
            on_read_resource=self._read_resource,
        )
        self.server.extensions[EXTENSION_ID] = {}

    def open(self, port: int | None = None) -> App:
        """Serve the browser host page, unless it already is, and return it."""
        with self._lock:
            if self._app is None:
                self._app = serve_app(self.server, port)
            return self._app

    def close(self) -> None:
        """Stop serving the browser host page, if it was opened, and clear the uploads no request took."""
        with self._lock:
            if self._app is not None:
                self._app.stop()
                self._app = None
            for upload in self._uploads:
                shutil.rmtree(UPLOADS / upload, ignore_errors=True)
            self._uploads.clear()

    async def _list_tools(
        self, ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        # Tools only the view calls stay hidden from clients that would show them to the model.
        return ListToolsResult(tools=[OPEN_APP, *VIEW_TOOLS] if client_supports_apps(ctx) else [OPEN_APP])

    async def _list_resources(
        self, ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(resources=[VIEW] if client_supports_apps(ctx) else [])

    async def _list_resource_templates(
        self, ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        templates = [MODEL_FILE, REFERENCE_FILE] if client_supports_apps(ctx) else []
        return ListResourceTemplatesResult(resource_templates=templates)

    async def _read_resource(
        self, ctx: ServerRequestContext[Any], params: ReadResourceRequestParams
    ) -> ReadResourceResult:
        if params.uri == VIEW_URI:
            contents = TextResourceContents(uri=VIEW_URI, mime_type=APP_MIME_TYPE, text=view(), _meta=VIEW_META)
            return ReadResourceResult(contents=[contents])
        for prefix, read in ((MODEL_FILE_PREFIX, self._model_file), (REFERENCE_FILE_PREFIX, self._reference_file)):
            if params.uri.startswith(prefix):
                try:
                    return await asyncio.to_thread(read, params.uri)
                except Modeling3dError as error:
                    raise MCPError(INVALID_PARAMS, str(error)) from None
        raise MCPError(
            INVALID_PARAMS,
            f"'{params.uri}' is not a resource of this server. It has {VIEW_URI}, each model's GLB, renders, and "
            f"reference images at {MODEL_FILE.uri_template}, and the images the app offers to work from at "
            f"{REFERENCE_FILE.uri_template}.",
        )

    def _model_file(self, uri: str) -> ReadResourceResult:
        name, _, path = (unquote(part) for part in uri.removeprefix(MODEL_FILE_PREFIX).partition("/"))
        summary = self._summary(name)
        # Only what the model's summary lists, and what is in the folders it was given, so no other path in the
        # directory can be read through this.
        listed = [*summary.files, *summary.references]
        readable = [file for file in listed if PurePosixPath(file).suffix.lower() in MODEL_FILE_TYPES]
        checked = CHECK_FILE.fullmatch(path) is not None and (summary.directory / path).is_file()
        if path not in readable and not _in_reference_folder(summary, path) and not checked:
            raise Modeling3dError(
                f"{path!r} is not a file the app reads from model {name}. It has: {', '.join(readable) or 'none yet'}."
            )
        data = base64.b64encode((summary.directory / path).read_bytes()).decode("ascii")
        mime_type = MODEL_FILE_TYPES.get(PurePosixPath(path).suffix.lower(), "application/json")
        return ReadResourceResult(contents=[BlobResourceContents(uri=uri, mime_type=mime_type, blob=data)])

    def _reference_file(self, uri: str) -> ReadResourceResult:
        path = Path(unquote(uri.removeprefix(REFERENCE_FILE_PREFIX)))
        kind = PREVIEW_TYPES.get(path.suffix.lower())
        if kind is None or not self._in_library(path):
            raise Modeling3dError(
                f"{path} is not an image the app offers to work from. Pin it, pin the folder it is in, or choose it."
            )
        try:
            if path.stat().st_size > PREVIEW_BYTES:
                raise Modeling3dError(f"{path} is too large to preview; it can still be worked from.")
            data = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as error:
            raise Modeling3dError(
                f"Could not read {path}: {error}. If it moved, add it again from where it is now.", "missing-reference"
            ) from None
        return ReadResourceResult(contents=[BlobResourceContents(uri=uri, mime_type=kind, blob=data)])

    def _in_library(self, path: Path) -> bool:
        """Whether the app's library offers `path`: pinned, in a folder pinned to show its files, used here, or given
        to a model here, in its references/."""
        pins = read_app_pins(self.pins_path)
        if any(reference.path == path for reference in pins.references):
            return True
        if any(folder.shows == "files" and folder.path == path.parent for folder in pins.folders):
            return True
        if path in self._app_state().used:
            return True
        if not path.is_relative_to(self.directory):
            return False
        parts = path.relative_to(self.directory).parts
        return len(parts) > 2 and parts[1] == "references"

    async def _call_tool_or_explain(
        self, ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        # A low-level handler's exception is a protocol error the model never reads, so a named failure is a result.
        try:
            return await self._call_tool(ctx, params)
        except Modeling3dError as error:
            # Which failure it was rides along, so the view words it for the person rather than showing the message,
            # which names commands and arguments for an agent.
            return CallToolResult(
                content=[TextContent(type="text", text=str(error))],
                structured_content={"reason": error.reason, "model": error.model},
                is_error=True,
            )

    async def _call_tool(
        self, ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        arguments = params.arguments or {}
        if params.name == OPEN_APP.name:
            return await self._open_app(ctx, params)
        if params.name == LIST_MODELS.name:
            listing = await asyncio.to_thread(self._list_models, self.directory)
            return _structured(listing.model_dump(mode="json"))
        if params.name == VIEW_MODEL.name:
            summary = await asyncio.to_thread(self._view_model, arguments["name"], self.directory)
            return _structured(summary.model_dump(mode="json"))
        if params.name == CREATE_MODEL.name:
            return await self._start(arguments, "shape")
        if params.name == RIG_MODEL.name:
            return await self._start(arguments, "rig")
        if params.name == COLOR_MODEL.name:
            return await self._start(arguments, "color")
        if params.name == DETAIL_MODEL.name:
            return await self._start(arguments, "detail")
        if params.name == CHECK_MODEL.name:
            return await self._check(arguments["name"])
        if params.name == UPLOAD_REFERENCE.name:
            received = await asyncio.to_thread(
                self._receive, arguments["upload"], arguments["path"], arguments["offset"], arguments["data"]
            )
            return _structured({"received": received})
        if params.name == STEER_MODEL.name:
            return await self._steer(arguments)
        if params.name == RENAME_MODEL.name:
            summary = await asyncio.to_thread(self._rename, arguments["name"], arguments["new_name"])
            return _structured(summary.model_dump(mode="json"))
        if params.name == DELETE_MODEL.name:
            await asyncio.to_thread(self._delete, arguments["name"])
            return _text(f"Deleted {arguments['name']}.")
        if params.name == CANCEL_MODEL.name:
            await asyncio.to_thread(self._cancel_model, arguments["name"], self.directory)
            return _text("Stopping; the model's activity shows the run end.")
        if params.name == READ_ACTIVITY.name:
            activity = await asyncio.to_thread(
                self._read_activity, arguments["name"], self.directory, arguments.get("after")
            )
            return _structured(activity.model_dump(mode="json"))
        if params.name == READ_TOOL_CALL.name:
            call = await asyncio.to_thread(
                self._read_tool_call, arguments["name"], arguments["run_id"], arguments["call_id"], self.directory
            )
            return _structured(call.model_dump(mode="json"))
        if params.name == LIST_INTELLIGENCE.name:
            options = await asyncio.to_thread(self._intelligence)
            return _structured(options.model_dump(mode="json"))
        if params.name == CHOOSE_INTELLIGENCE.name:
            options = await asyncio.to_thread(
                self._choose, arguments["mode"], arguments["model"], arguments["reasoning_effort"]
            )
            return _structured(options.model_dump(mode="json"))
        if params.name == READ_SETTINGS.name:
            settings = await asyncio.to_thread(read_app_settings, self.settings_path)
            return _structured(settings.model_dump(mode="json"))
        if params.name == SAVE_SETTINGS.name:
            settings = await asyncio.to_thread(save_app_settings, arguments["settings"], self.settings_path)
            return _structured(settings.model_dump(mode="json"))
        if params.name == READ_FOLDERS.name:
            folders = AppFolders(settings=self.settings_path.parent, models=self.directory)
            return _structured(folders.model_dump(mode="json"))
        if params.name == OPEN_FOLDER.name:
            folder = await asyncio.to_thread(self._folder, arguments["folder"], arguments.get("name"))
            await asyncio.to_thread(self._open_folder, folder)
            return _structured({"opened": str(folder)})
        if params.name == CHOOSE_FILES.name:
            directory = arguments.get("directory")
            opened = Path(directory).expanduser() if directory else await asyncio.to_thread(self._last_folder)
            chosen = await self._in_dialog(self._choose_files, opened, CHOOSE_TITLE)
            staged = await self._staged_references(chosen)
            if chosen:
                await asyncio.to_thread(self._remember, chosen, chosen[0].parent)
            return staged
        if params.name == STAGE_FILES.name:
            paths = [Path(path) for path in arguments["paths"]]
            staged = await self._staged_references(paths)
            if arguments.get("remember"):
                await asyncio.to_thread(self._remember, paths)
            return staged
        if params.name == CHOOSE_FOLDER.name:
            opened = await asyncio.to_thread(self._last_folder)
            folder = await self._in_dialog(self._choose_folder, opened, CHOOSE_FOLDER_TITLE)
            return _structured({"path": str(folder.resolve()) if folder else None})
        if params.name == READ_LIBRARY.name:
            library = await asyncio.to_thread(self._library)
            return _structured(library.model_dump(mode="json"))
        if params.name == SAVE_PINS.name:
            pins = await asyncio.to_thread(save_app_pins, arguments["pins"], self.pins_path)
            return _structured(pins.model_dump(mode="json"))
        if params.name == LIST_FOLDER.name:
            entries = await asyncio.to_thread(self._pinned_folder, Path(arguments["path"]))
            return _structured({"entries": [entry.model_dump(mode="json") for entry in entries]})
        if params.name == KEEP_UPLOAD.name:
            kept = await asyncio.to_thread(self._keep, arguments["upload"])
            return _structured({"path": str(kept)})
        known = ", ".join(tool.name for tool in [OPEN_APP, *VIEW_TOOLS])
        raise Modeling3dError(f"'{params.name}' is not a tool of this server. The tools are: {known}.")

    async def _start(self, arguments: dict[str, Any], mode: ModelMode) -> CallToolResult:
        """Start a run that shapes, rigs, or colors the model, with what the view sent."""
        uploads: list[str] = arguments.get("uploads") or []
        references = [await asyncio.to_thread(_staged, upload) for upload in uploads]
        references += await asyncio.to_thread(self._model_references, arguments.get("reference_models") or [])
        start = self._starts[mode]
        created = mode == "shape" and not (self.directory / arguments["name"]).exists()
        # Only shaping takes budgets; the other modes work to the model's own.
        budgets: dict[str, Any] = {}
        if mode == "shape":
            screen_size = arguments.get("screen_size", NOT_GIVEN)
            budgets = {
                "max_triangles": arguments.get("max_triangles", NOT_GIVEN),
                "max_draw_calls": arguments.get("max_draw_calls", NOT_GIVEN),
                "screen_size": (screen_size[0], screen_size[1]) if isinstance(screen_size, list) else screen_size,
            }
        run = await start(
            prompt=arguments.get("prompt"),
            name=arguments["name"],
            directory=self.directory,
            references=references,
            resume_session=arguments.get("resume_session", False),
            agent_provider=arguments.get("agent_provider"),
            model=arguments.get("model"),
            reasoning_effort=arguments.get("reasoning_effort", DEFAULT_REASONING_EFFORT),
            origin=ORIGIN,
            detach=True,
            **budgets,
        )
        # Cleared only once the run has started, having copied them into the model: a request that is refused is
        # usually sent again, with the same references.
        await self._clear(uploads)
        if created:
            await asyncio.to_thread(self._update_state, lambda _: {"last_prompt": arguments["prompt"]})
        # Not recorded as viewed: the run starts long after it is asked for, by when the person may be viewing another.
        summary = await asyncio.to_thread(self._summary, run.name)
        return _structured(summary.model_dump(mode="json"))

    async def _check(self, name: str) -> CallToolResult:
        """The report of the model's check under way, or of a new one, once it ends or the call has waited long enough.

        Each check runs to its end in a thread of its own, so one a call stopped waiting on is there for the next call.
        """
        target = self.directory / name
        with self._lock:
            future = self._checks.get(target)
            if future is None:
                future = self._checks[target] = concurrent.futures.Future()
                threading.Thread(target=self._run_check, args=(name, self.directory, future), daemon=True).start()
        done, _ = await asyncio.to_thread(concurrent.futures.wait, [future], CHECK_WAIT_SECONDS)
        if not done:
            return _structured({"checking": True})
        with self._lock:
            if self._checks.get(target) is future:
                del self._checks[target]
        return _structured({"report": future.result().model_dump(mode="json")})

    def _rename(self, name: str, new_name: str) -> ModelSummary:
        self._not_checking(name, "renamed")
        return self._rename_model(name, new_name, self.directory)

    def _delete(self, name: str) -> None:
        self._not_checking(name, "deleted")
        self._delete_model(name, self.directory)

    def _not_checking(self, name: str, done: str) -> None:
        """Refuse while the model's check runs, since it writes into the model's directory and cannot be stopped."""
        target = self.directory / name
        with self._lock:
            future = self._checks.get(target)
            if future is not None and not future.done():
                raise Modeling3dError(
                    f"Model {name} is being checked in the app, so it cannot be {done} now. Try again once the "
                    "check ends.",
                    "model-busy",
                    name,
                )
            # One that ended unread is of the model as it was, and must not answer for another by its name.
            self._checks.pop(target, None)

    def _run_check(self, name: str, directory: Path, future: concurrent.futures.Future[ModelCheck]) -> None:
        try:
            future.set_result(self._check_model(name, directory))
        except Exception as error:
            future.set_exception(error)

    async def _steer(self, arguments: dict[str, Any]) -> CallToolResult:
        uploads: list[str] = arguments.get("uploads") or []
        references = [await asyncio.to_thread(_staged, upload) for upload in uploads]
        await asyncio.to_thread(
            self._steer_model, arguments["name"], arguments["message"], self.directory, ORIGIN, references
        )
        # As for a request: kept until the message has them, since one that is refused is usually sent again.
        await self._clear(uploads)
        return _text("Sent; the model's activity shows it once its agent has it.")

    async def _in_dialog[Chosen](self, ask: Callable[[Path, str], Chosen], directory: Path, title: str) -> Chosen:
        """What the person chose in the dialog `ask` shows, one dialog at a time."""
        with self._lock:
            if self._choosing:
                raise Modeling3dError("A file dialog is already showing. Choose there or cancel it, then try again.")
            self._choosing = True
        try:
            return await asyncio.to_thread(ask, directory, title)
        finally:
            with self._lock:
                self._choosing = False

    async def _staged_references(self, paths: list[Path]) -> CallToolResult:
        files = [await asyncio.to_thread(self._stage, path) for path in paths]
        return _structured({"files": [file.model_dump(mode="json") for file in files]})

    def _library(self) -> AppLibrary:
        state = self._app_state()
        return AppLibrary(
            **dict(read_app_pins(self.pins_path)),
            used=used_here(state.used, self._list_models(self.directory).models),
            last_prompt=state.last_prompt,
        )

    def _pinned_folder(self, path: Path) -> list[ReferenceEntry]:
        pinned = [folder.path for folder in read_app_pins(self.pins_path).folders if folder.shows == "files"]
        if path not in pinned:
            raise Modeling3dError(
                f"{path} is not a folder pinned to show its files. Those pinned so are: "
                f"{', '.join(str(folder) for folder in pinned) or 'none'}."
            )
        return list_folder(path)

    def _keep(self, upload: str) -> Path:
        return keep(_staged(upload), self.settings_path)

    def _last_folder(self) -> Path:
        """Where the file dialogs open: where files were last chosen from, while it is there, else the home folder."""
        folder = self._app_state().last_folder
        return folder if folder is not None and folder.is_dir() else Path.home()

    def _remember(self, chosen: list[Path], folder: Path | None = None) -> None:
        """Remember `chosen` as used in the app's directory, and `folder` as where files were last chosen from."""
        resolved = [path.expanduser().resolve() for path in chosen]
        self._update_state(
            lambda state: {
                "used": remember(state.used, resolved),
                **({"last_folder": folder.resolve()} if folder is not None else {}),
            }
        )

    def _update_state(self, change: Callable[[AppState], dict[str, Any]]) -> None:
        """Change what the app remembers in its directory, one change at a time."""
        path = self.directory / APP_STATE
        with self._lock:
            state = self._app_state()
            try:
                write_atomically(path, state.model_copy(update=change(state)).model_dump_json(indent=2))
            except OSError as error:
                raise Modeling3dError(
                    f"Could not save what the app remembers to {path}: {error}. Check that the folder can be written."
                ) from None

    def _stage(self, path: Path) -> StagedReference:
        """Stage a file or folder on this machine as an upload of its own, with a preview when it is an image."""
        source = path.expanduser().resolve()
        if not source.is_file() and not source.is_dir():
            raise Modeling3dError(
                f"{path} is not a file or a folder on this machine. If it moved, add it again from where it is now.",
                "missing-reference",
            )
        upload = uuid.uuid4().hex
        target = _upload_folder(upload) / source.name
        try:
            target.parent.mkdir(parents=True)
            with self._lock:
                self._uploads.add(upload)
            if source.is_dir():
                shutil.copytree(source, target, ignore=STAGE_SKIPPED)
                held = [file for file in target.rglob("*") if file.is_file()]
                size, files, preview = sum(file.stat().st_size for file in held), len(held), None
            else:
                shutil.copy2(source, target)
                size, files = target.stat().st_size, 1
                kind = PREVIEW_TYPES.get(source.suffix.lower())
                preview = (
                    f"data:{kind};base64,{base64.b64encode(target.read_bytes()).decode('ascii')}"
                    if kind and size <= PREVIEW_BYTES
                    else None
                )
        except OSError as error:
            raise Modeling3dError(f"Could not take {path}: {error}. Add it again, or drop it onto the app.") from None
        return StagedReference(
            upload=upload,
            name=source.name,
            path=source,
            kind="folder" if source.is_dir() else "file",
            size=size,
            files=files,
            preview=preview,
        )

    async def _clear(self, uploads: list[str]) -> None:
        for upload in uploads:
            await asyncio.to_thread(shutil.rmtree, UPLOADS / upload, True)
            with self._lock:
                self._uploads.discard(upload)

    def _receive(self, upload: str, path: str, offset: int, data: str) -> int:
        """Write a piece of an upload's file at `offset`, and return how much of the file has arrived."""
        folder = _upload_folder(upload)
        parts = re.split(r"[\\/]", path)
        if any(part in ("", ".", "..") or ":" in part or "\0" in part for part in parts):
            raise Modeling3dError(
                f"The reference {path!r} is not a file's name or its path in a folder. Add it again.", "bad-upload"
            )
        try:
            piece = base64.b64decode(data, validate=True)
        except binascii.Error:
            raise Modeling3dError(
                f"The reference {path} did not arrive as base64. Add it again.", "bad-upload"
            ) from None
        target = folder.joinpath(*parts)
        try:
            arrived = target.stat().st_size if target.is_file() else 0
            if offset > arrived:
                raise Modeling3dError(
                    f"A piece of {path} arrived at byte {offset}, but only {arrived} bytes had. Send it from byte "
                    f"{arrived}.",
                    "bad-upload",
                )
            with self._lock:
                self._uploads.add(upload)
            target.parent.mkdir(parents=True, exist_ok=True)
            # A piece sent again, after a reply that never came back, lands where it did the first time.
            with target.open("r+b" if offset > 0 else "wb") as file:
                file.seek(offset)
                file.write(piece)
                file.truncate()
                return file.tell()
        except OSError as error:
            raise Modeling3dError(
                f"Could not keep the reference {path}: {error}. Add it again.", "bad-upload"
            ) from None

    def _intelligence(self) -> AppIntelligence:
        options = self._list_intelligence()
        offered = {
            mode: choice
            for mode, choice in self._app_state().last_intelligence.items()
            if any(
                model.id == choice.model and choice.reasoning_effort in model.reasoning_efforts
                for model in options.models
            )
        }
        return AppIntelligence(models=options.models, defaults=options.defaults, chosen=offered)

    def _choose(self, mode: ModelMode, model: str, reasoning_effort: str) -> AppIntelligence:
        options = self._list_intelligence()
        picked = next((candidate for candidate in options.models if candidate.id == model), None)
        if picked is None:
            known = ", ".join(candidate.id for candidate in options.models) or "none"
            raise Modeling3dError(
                f"{model!r} is not a model the app offers. It offers: {known}.", "no-such-intelligence-model"
            )
        effort = next((candidate for candidate in picked.reasoning_efforts if candidate == reasoning_effort), None)
        if effort is None:
            raise Modeling3dError(
                f"{reasoning_effort!r} is not a reasoning effort {picked.id} takes. Pass one of: "
                f"{', '.join(picked.reasoning_efforts)}.",
                "bad-reasoning-effort",
            )
        choice = IntelligenceChoice(agent_provider=picked.agent_provider, model=picked.id, reasoning_effort=effort)
        self._update_state(lambda state: {"last_intelligence": {**state.last_intelligence, mode: choice}})
        return self._intelligence()

    def _app_state(self) -> AppState:
        """What the person picked in the app; nothing when it was never written or cannot be read."""
        try:
            return AppState.model_validate_json((self.directory / APP_STATE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return AppState()

    def _folder(self, folder: str, name: str | None) -> Path:
        if folder == "settings":
            return self.settings_path.parent
        if folder == "models":
            return self.directory
        if folder != "model" or name is None:
            raise Modeling3dError(
                f"There is no app folder {folder!r}{'' if name is None else f' named {name!r}'}. Pass `settings`, "
                "`models`, or `model` with the model's `name`."
            )
        return self._summary(name).directory

    def _summary(self, name: str) -> ModelSummary:
        listing = self._list_models(self.directory)
        summary = next((model for model in listing.models if model.name == name), None)
        if summary is None:
            known = ", ".join(model.name for model in listing.models) or "none"
            raise Modeling3dError(
                f"There is no model named {name!r} in {listing.directory}. The models there: {known}.",
                "no-such-model",
                name,
            )
        return summary

    def _model_references(self, names: list[str]) -> list[Path]:
        """The files that stand for each named model as a reference: its script, its GLB, and its first render."""
        models = {model.name: model for model in self._list_models(self.directory).models}
        paths: list[Path] = []
        for name in names:
            files = models[name].files if name in models else []
            own = [file for file in files if PurePosixPath(file).suffix in REFERENCE_TYPES]
            if not own:
                raise Modeling3dError(
                    f"There is no built model named {name!r} in {self.directory} to work from.",
                    "no-reference-model",
                    name,
                )
            renders = [file for file in files if file.startswith("renders/") and _image(file)]
            paths += [models[name].directory / file for file in [*own, *renders[:1]]]
        return paths

    async def _open_app(
        self, ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        directory = (params.arguments or {}).get("directory")
        if directory is not None:
            resolved = Path(directory).resolve()
            # Listed first, so a path the app cannot show is refused before the app switches to it.
            await asyncio.to_thread(self._list_models, resolved)
            self.directory = resolved
        app = await asyncio.to_thread(self.open)
        embedded = client_supports_apps(ctx)
        answer = (params.input_responses or {}).get(OPEN_REQUEST)
        opened = isinstance(answer, ElicitResult) and answer.action == "accept"
        if not embedded and not self._offered and _takes_url_elicitation(ctx):
            self._offered = True
            message = "Open the 3D Modeling Smart Tool app to watch the work and steer it."
            elicitation_id = str(uuid.uuid4())
            # Before 2026-07-28 the server asks mid-call; from it on, the server returns the question and the client
            # retries the call with the answer.
            if not ctx.session.can_send_request:
                request = ElicitRequestURLParams(message=message, url=app.url, elicitation_id=elicitation_id)
                return InputRequiredResult(input_requests={OPEN_REQUEST: ElicitRequest(params=request)})
            try:
                response = await ctx.session.elicit_url(message, app.url, elicitation_id)
            except MCPError:
                response = None
            opened = response is not None and response.action == "accept"
        if embedded:
            where = f"The app is shown to the user inline, and at {app.url} for a browser."
        elif opened:
            where = f"The user opened the app at {app.url}."
        else:
            where = f"Give the user this URL to open the app: {app.url}"
        return _text(
            f"{where} It shows the models in {self.directory}. There the user creates models, asks for changes, and "
            f"steers and stops runs themselves. {SEES_THE_APP}"
        )


def _upload_folder(upload: str) -> Path:
    if not UPLOAD_ID.fullmatch(upload):
        raise Modeling3dError(
            f"{upload!r} is not an upload id: name each upload with 16 to 64 lowercase hex digits.", "bad-upload"
        )
    return UPLOADS / upload


def _staged(upload: str) -> Path:
    """The file or folder an upload holds, as a reference to work from."""
    folder = _upload_folder(upload)
    held = list(folder.iterdir()) if folder.is_dir() else []
    if len(held) != 1:
        raise Modeling3dError(
            f"The upload {upload} holds {'more than one file or folder' if held else 'nothing'}; uploads are cleared "
            "when the app closes. Add the reference again.",
            "bad-upload",
        )
    return held[0]


def clear_old_uploads(now: float) -> None:
    """Clear the uploads apps left behind, such as one that was killed, once they are past their lifetime at `now`."""
    if not UPLOADS.is_dir():
        return
    for folder in UPLOADS.iterdir():
        with contextlib.suppress(OSError):
            if now - folder.stat().st_mtime > UPLOAD_LIFETIME_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)


def _in_reference_folder(summary: ModelSummary, path: str) -> bool:
    """Whether `path` is a file the view reads inside one of the folders the model was given, which it lists alone."""
    if PurePosixPath(path).suffix.lower() not in MODEL_FILE_TYPES:
        return False
    target = (summary.directory / path).resolve()
    return target.is_file() and any(
        target.is_relative_to((summary.directory / folder).resolve())
        for folder in summary.references
        if folder.endswith("/")
    )


def _image(path: str) -> bool:
    return MODEL_FILE_TYPES.get(PurePosixPath(path).suffix.lower(), "").startswith("image/")


def _text(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)])


def _structured(structured: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(structured))], structured_content=structured
    )


def _takes_url_elicitation(ctx: ServerRequestContext[Any]) -> bool:
    capabilities = ctx.session.client_capabilities
    return (
        capabilities is not None and capabilities.elicitation is not None and capabilities.elicitation.url is not None
    )
