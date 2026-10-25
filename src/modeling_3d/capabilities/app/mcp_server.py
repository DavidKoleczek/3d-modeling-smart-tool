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

from modeling_3d.capabilities.app.server import App, serve_app, view
from modeling_3d.capabilities.app.settings import read_app_settings, save_app_settings
from modeling_3d.capabilities.app.tools import (
    APP_ONLY,
    CANCEL_MODEL,
    CHECK_MODEL,
    CHOOSE_INTELLIGENCE,
    COLOR_MODEL,
    DETAIL_MODEL,
    CREATE_MODEL,
    LIST_INTELLIGENCE,
    LIST_MODELS,
    MODEL_FILE,
    MODEL_FILE_PREFIX,
    OPEN_APP,
    OPEN_FOLDER,
    READ_ACTIVITY,
    READ_FOLDERS,
    READ_SETTINGS,
    READ_TOOL_CALL,
    RIG_MODEL,
    SAVE_SETTINGS,
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
    AppState,
    IntelligenceChoice,
    IntelligenceModels,
    Modeling3dError,
    ModelActivity,
    ModelCheck,
    ModelListing,
    ModelMode,
    ModelSummary,
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
# endregion

# region: What the app keeps and who it acts as
# The key `open_app` files its request to open the browser under, when the client answers by retrying the call.
OPEN_REQUEST = "open"
# Who the model's activity shows as asking, for everything done in the app.
ORIGIN = "app"
# What the person picked in the app, kept beside the models it shows. Starting with a dot, it is never a model.
APP_STATE = ".app.json"
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
    ) -> None:
        self.directory = directory
        self.settings_path = settings_path
        self._open_folder = open_folder
        self._list_models = list_models
        self._view_model = view_model
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
        return ListResourceTemplatesResult(resource_templates=[MODEL_FILE] if client_supports_apps(ctx) else [])

    async def _read_resource(
        self, ctx: ServerRequestContext[Any], params: ReadResourceRequestParams
    ) -> ReadResourceResult:
        if params.uri == VIEW_URI:
            contents = TextResourceContents(uri=VIEW_URI, mime_type=APP_MIME_TYPE, text=view(), _meta=VIEW_META)
            return ReadResourceResult(contents=[contents])
        if params.uri.startswith(MODEL_FILE_PREFIX):
            try:
                return await asyncio.to_thread(self._model_file, params.uri)
            except Modeling3dError as error:
                raise MCPError(INVALID_PARAMS, str(error)) from None
        raise MCPError(
            INVALID_PARAMS,
            f"'{params.uri}' is not a resource of this server. It has {VIEW_URI}, and each model's GLB, renders, and "
            f"reference images at {MODEL_FILE.uri_template}.",
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
            options = await asyncio.to_thread(self._choose, arguments["model"], arguments["reasoning_effort"])
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
        known = ", ".join(tool.name for tool in [OPEN_APP, *VIEW_TOOLS])
        raise Modeling3dError(f"'{params.name}' is not a tool of this server. The tools are: {known}.")

    async def _start(self, arguments: dict[str, Any], mode: ModelMode) -> CallToolResult:
        """Start a run that shapes, rigs, or colors the model, with what the view sent."""
        uploads: list[str] = arguments.get("uploads") or []
        references = [await asyncio.to_thread(_staged, upload) for upload in uploads]
        references += await asyncio.to_thread(self._model_references, arguments.get("reference_models") or [])
        start = self._starts[mode]
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
        summary = await asyncio.to_thread(self._view_model, run.name, self.directory)
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
        chosen = self._app_state().intelligence
        offered = chosen is not None and any(
            model.id == chosen.model and chosen.reasoning_effort in model.reasoning_efforts for model in options.models
        )
        return AppIntelligence(
            models=options.models,
            default=options.default,
            chosen=chosen if offered else None,
        )

    def _choose(self, model: str, reasoning_effort: str) -> AppIntelligence:
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
        self.directory.mkdir(parents=True, exist_ok=True)
        state = self._app_state().model_copy(update={"intelligence": choice})
        (self.directory / APP_STATE).write_text(state.model_dump_json(indent=2), encoding="utf-8")
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
