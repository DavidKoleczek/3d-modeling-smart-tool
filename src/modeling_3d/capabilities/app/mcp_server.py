"""The app's MCP server: the tool that opens the app, the tools its view calls, and the view as an MCP App resource."""

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import threading
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
from modeling_3d.schemas import Modeling3dError, ModelActivity, ModelListing, ModelSummary

VIEW_URI = "ui://modeling-3d/app"
MODEL_FILE_PREFIX = "modeling-3d://models/"
# What the view reads of a model: its GLB, its renders, and its reference images. The rest, such as model.py and its
# sessions, stays put.
MODEL_FILE_TYPES = {
    ".glb": "model/gltf-binary",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
# A model's own files that stand for it as a reference, beside its first render: its script and its GLB.
REFERENCE_TYPES = (".py", ".glb")
# The key `open_app` files its request to open the browser under, when the client answers by retrying the call.
OPEN_REQUEST = "open"
# Who the model's activity shows as asking, for everything done in the app.
ORIGIN = "app"
SEES_THE_APP = (
    "Nothing they do there is sent to you: see the models and their state with `modeling-3d list-3d-models`, and what "
    "was asked of one and what its agent did with `modeling-3d read-3d-model-activity --name <name>`."
)
INSTRUCTIONS = f"""\
Modeling 3D has an app where the user watches the models in one directory being made, and creates, changes, steers, \
and stops them. Call `open_app` when they ask for it. `modeling-3d view-3d-model --name <name>` brings a model up in it.

{SEES_THE_APP} Read a model's activity before acting on it, since they may have changed or steered it in the app."""

APP_ONLY = {"ui": {"resourceUri": VIEW_URI, "visibility": ["app"]}}
OPEN_APP = Tool(
    name="open_app",
    description="Show the Modeling 3D app, where the user watches the models in a directory being made, and creates, "
    "changes, and steers them, and return its browser URL. Hosts that render MCP Apps show it inline. Opening it "
    "again returns the same URL.",
    input_schema={
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Where the models to show are kept, absolute or relative to where this server started. "
                "Omit it to keep the current one, .modeling-3d in the working directory at first.",
            }
        },
    },
    _meta={"ui": {"resourceUri": VIEW_URI}},
)
LIST_MODELS = Tool(
    name="list_3d_models",
    description="The models in the app's directory, newest first, with their state, and the one viewed last. Called "
    "by the view.",
    input_schema={"type": "object", "properties": {}},
    _meta=APP_ONLY,
)
VIEW_MODEL = Tool(
    name="view_3d_model",
    description="Record a model in the app's directory as the one viewed last, and return its summary. Called by the "
    "view.",
    input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    _meta=APP_ONLY,
)
CREATE_MODEL = Tool(
    name="create_3d_model",
    description="Create a model in the app's directory, or change the one by that name, in a run of its own that "
    "outlives this server; return the model's summary once its agent runs, and record it as viewed last. Called by "
    "the view.",
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "name": {"type": "string"},
            "resume_session": {"type": ["boolean", "string"]},
            "reference_models": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Models in the app's directory, whose script, GLB, and first render are references",
            },
            "references": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "data": {"type": "string", "description": "Base64"}},
                    "required": ["name", "data"],
                },
            },
        },
        "required": ["prompt", "name"],
    },
    _meta=APP_ONLY,
)
STEER_MODEL = Tool(
    name="steer_3d_model",
    description="Send a message to the agent working on a model in the app's directory. Called by the view.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}, "message": {"type": "string"}},
        "required": ["name", "message"],
    },
    _meta=APP_ONLY,
)
CANCEL_MODEL = Tool(
    name="cancel_3d_model",
    description="Stop the run working on a model in the app's directory. Called by the view.",
    input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    _meta=APP_ONLY,
)
READ_ACTIVITY = Tool(
    name="read_3d_model_activity",
    description="A model's summary and its activity, or only what came after the cursor `after`. Called by the view.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}, "after": {"type": "string"}},
        "required": ["name"],
    },
    _meta=APP_ONLY,
)
VIEW_TOOLS = [LIST_MODELS, VIEW_MODEL, CREATE_MODEL, STEER_MODEL, CANCEL_MODEL, READ_ACTIVITY]
VIEW = Resource(uri=VIEW_URI, name="Modeling 3D app", mime_type=APP_MIME_TYPE)
MODEL_FILE = ResourceTemplate(
    name="Model file",
    uri_template=f"{MODEL_FILE_PREFIX}{{name}}/{{+path}}",
    description="A model's GLB, one of its renders, or a reference image it was given, as base64, for the app's view.",
)


class Started(Protocol):
    """What the view needs of a run `create_model` started: the model it works on."""

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
        steer_model: Callable[[str, str, Path, str], None],
        cancel_model: Callable[[str, Path], None],
        read_activity: Callable[[str, Path, str | None], ModelActivity],
    ) -> None:
        self.directory = directory
        self._list_models = list_models
        self._view_model = view_model
        self._create_model = create_model
        self._steer_model = steer_model
        self._cancel_model = cancel_model
        self._read_activity = read_activity
        self._lock = threading.Lock()
        self._app: App | None = None
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
        """Stop serving the browser host page, if it was opened."""
        with self._lock:
            if self._app is not None:
                self._app.stop()
                self._app = None

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
            return ReadResourceResult(
                contents=[TextResourceContents(uri=VIEW_URI, mime_type=APP_MIME_TYPE, text=view())]
            )
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
        listing = self._list_models(self.directory)
        summary = next((model for model in listing.models if model.name == name), None)
        if summary is None:
            known = ", ".join(model.name for model in listing.models) or "none"
            raise Modeling3dError(f"There is no model named {name!r} in {listing.directory}. The models there: {known}.")
        # Only what the model's summary lists, so no other path in the directory can be read through this.
        listed = [*summary.files, *summary.references]
        readable = [file for file in listed if PurePosixPath(file).suffix.lower() in MODEL_FILE_TYPES]
        if path not in readable:
            raise Modeling3dError(
                f"{path!r} is not a file the app reads from model {name}. It has: {', '.join(readable) or 'none yet'}."
            )
        data = base64.b64encode((summary.directory / path).read_bytes()).decode("ascii")
        mime_type = MODEL_FILE_TYPES[PurePosixPath(path).suffix.lower()]
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
            return await self._create(arguments)
        if params.name == STEER_MODEL.name:
            await asyncio.to_thread(self._steer_model, arguments["name"], arguments["message"], self.directory, ORIGIN)
            return _text("Sent; the model's activity shows it once its agent has it.")
        if params.name == CANCEL_MODEL.name:
            await asyncio.to_thread(self._cancel_model, arguments["name"], self.directory)
            return _text("Stopping; the model's activity shows the run end.")
        if params.name == READ_ACTIVITY.name:
            activity = await asyncio.to_thread(
                self._read_activity, arguments["name"], self.directory, arguments.get("after")
            )
            return _structured(activity.model_dump(mode="json"))
        known = ", ".join(tool.name for tool in [OPEN_APP, *VIEW_TOOLS])
        raise Modeling3dError(f"'{params.name}' is not a tool of this server. The tools are: {known}.")

    async def _create(self, arguments: dict[str, Any]) -> CallToolResult:
        uploads = Path(tempfile.mkdtemp(prefix="modeling-3d-"))
        try:
            references = await asyncio.to_thread(_write_uploads, uploads, arguments.get("references") or [])
            references += await asyncio.to_thread(self._model_references, arguments.get("reference_models") or [])
            run = await self._create_model(
                prompt=arguments["prompt"],
                name=arguments["name"],
                directory=self.directory,
                references=references,
                resume_session=arguments.get("resume_session", False),
                origin=ORIGIN,
                detach=True,
            )
        finally:
            # The run has copied its references into the model by the time it starts.
            await asyncio.to_thread(shutil.rmtree, uploads, True)
        summary = await asyncio.to_thread(self._view_model, run.name, self.directory)
        return _structured(summary.model_dump(mode="json"))

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
            message = "Open the Modeling 3D app to watch the work and steer it."
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


def _write_uploads(folder: Path, uploads: list[dict[str, Any]]) -> list[Path]:
    """Write each file the view sent, under its own name, in a folder of its own so no two names collide."""
    paths: list[Path] = []
    for index, upload in enumerate(uploads):
        name = re.split(r"[\\/]", str(upload.get("name", "")))[-1].strip()
        if name in ("", ".", ".."):
            name = "reference"
        try:
            data = base64.b64decode(str(upload.get("data", "")), validate=True)
        except binascii.Error:
            raise Modeling3dError(
                f"The reference {name} did not arrive as base64. Add it again.", "bad-upload"
            ) from None
        path = folder / str(index) / name
        path.parent.mkdir()
        path.write_bytes(data)
        paths.append(path)
    return paths


def _image(path: str) -> bool:
    return MODEL_FILE_TYPES.get(PurePosixPath(path).suffix.lower(), "").startswith("image/")


def _text(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)])


def _structured(structured: dict[str, Any]) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(structured))], structured_content=structured)


def _takes_url_elicitation(ctx: ServerRequestContext[Any]) -> bool:
    capabilities = ctx.session.client_capabilities
    return capabilities is not None and capabilities.elicitation is not None and capabilities.elicitation.url is not None
