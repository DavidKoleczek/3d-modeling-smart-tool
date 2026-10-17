"""The app's MCP server: tools that open the app and talk through it, and its view as an MCP App resource."""

import asyncio
import base64
from collections.abc import Callable
import json
from pathlib import Path, PurePosixPath
import threading
from typing import Any
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
from modeling_3d.schemas import Modeling3dError, ModelListing, ModelSummary

VIEW_URI = "ui://modeling-3d/app"
MODEL_FILE_PREFIX = "modeling-3d://models/"
# What the view reads of a model: its GLB and its renders. The rest, such as model.py and its sessions, stays put.
MODEL_FILE_TYPES = {
    ".glb": "model/gltf-binary",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
# The key `open_app` files its request to open the browser under, when the client answers by retrying the call.
OPEN_REQUEST = "open"
INSTRUCTIONS = """\
Modeling 3D has an app where the user watches the work and steers it. Call `open_app` when they ask for it. It \
shows the models in one directory, and `modeling-3d view-3d-model --name <name>` brings one up in it.

What they write in the app reaches you as a message that names the app. They read the app, not this conversation, so \
answer those messages with `reply`."""

OPEN_APP = Tool(
    name="open_app",
    description="Show the Modeling 3D app, where the user watches the models in a directory being made and steers "
    "the work, and return its browser URL. Hosts that render MCP Apps show it inline. Opening it again returns the "
    "same URL.",
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
REPLY = Tool(
    name="reply",
    description="Show a message to the user in the app. The app must be open.",
    input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
)
APP_UPDATES = Tool(
    name="app_updates",
    description="The agent's messages the app's view has not shown yet, past the first `after`. Called by the view.",
    input_schema={"type": "object", "properties": {"after": {"type": "integer", "minimum": 0}}},
    _meta={"ui": {"resourceUri": VIEW_URI, "visibility": ["app"]}},
)
APP_MESSAGE = Tool(
    name="app_message",
    description="Hand the agent a message the user wrote in the app. Called by the app's browser host page.",
    input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    _meta={"ui": {"resourceUri": VIEW_URI, "visibility": ["app"]}},
)
LIST_MODELS = Tool(
    name="list_3d_models",
    description="The models in the app's directory, newest first, with their state, and the one viewed last. Called "
    "by the view.",
    input_schema={"type": "object", "properties": {}},
    _meta={"ui": {"resourceUri": VIEW_URI, "visibility": ["app"]}},
)
VIEW_MODEL = Tool(
    name="view_3d_model",
    description="Record a model in the app's directory as the one viewed last, and return its summary. Called by the "
    "view.",
    input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    _meta={"ui": {"resourceUri": VIEW_URI, "visibility": ["app"]}},
)
VIEW = Resource(uri=VIEW_URI, name="Modeling 3D app", mime_type=APP_MIME_TYPE)
MODEL_FILE = ResourceTemplate(
    name="Model file",
    uri_template=f"{MODEL_FILE_PREFIX}{{name}}/{{+path}}",
    description="A model's GLB or one of its renders, as base64, for the app's view.",
)


class AppServer:
    """The app's MCP server, what the agent has said in the app, and the browser host page once it is open.

    Serve `server` over any MCP transport. Several at once share this state, so the browser host page reaches the
    same server the agent's session does.
    """

    def __init__(
        self,
        server_name: str,
        version: str,
        directory: Path,
        list_models: Callable[[Path], ModelListing],
        view_model: Callable[[str, Path], ModelSummary],
        deliver: Callable[[str], None] | None = None,
    ) -> None:
        self.directory = directory
        self._list_models = list_models
        self._view_model = view_model
        self._deliver = deliver
        self._lock = threading.Lock()
        self._said: list[str] = []
        # Messages from the app that never reached the agent, handed to it with its next tool result instead.
        self._undelivered: list[str] = []
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

    def say(self, text: str) -> None:
        """Show `text` as the agent's in every open view, each on its next poll."""
        with self._lock:
            self._said.append(text)

    def updates(self, after: int = 0) -> list[str]:
        """What the agent has said, past the first `after` messages: what a view that has shown `after` is missing."""
        with self._lock:
            return self._said[after:]

    def close(self) -> None:
        """Stop serving the browser host page, if it was opened."""
        with self._lock:
            if self._app is not None:
                self._app.stop()
                self._app = None

    async def _list_tools(
        self, ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        # Tools only the app calls stay hidden from clients that would show them to the model.
        if client_supports_apps(ctx):
            return ListToolsResult(tools=[OPEN_APP, REPLY, APP_UPDATES, APP_MESSAGE, LIST_MODELS, VIEW_MODEL])
        return ListToolsResult(tools=[OPEN_APP, REPLY])

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
            f"'{params.uri}' is not a resource of this server. It has {VIEW_URI}, and each model's GLB and renders at "
            f"{MODEL_FILE.uri_template}.",
        )

    def _model_file(self, uri: str) -> ReadResourceResult:
        name, _, path = (unquote(part) for part in uri.removeprefix(MODEL_FILE_PREFIX).partition("/"))
        listing = self._list_models(self.directory)
        summary = next((model for model in listing.models if model.name == name), None)
        if summary is None:
            known = ", ".join(model.name for model in listing.models) or "none"
            raise Modeling3dError(f"There is no model named {name!r} in {listing.directory}. The models there: {known}.")
        # Only what the model's summary lists, so no other path in the directory can be read through this.
        readable = [file for file in summary.files if PurePosixPath(file).suffix.lower() in MODEL_FILE_TYPES]
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
            return CallToolResult(content=[TextContent(type="text", text=str(error))], is_error=True)

    async def _call_tool(
        self, ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        arguments = params.arguments or {}
        if params.name == OPEN_APP.name:
            return await self._open_app(ctx, params)
        if params.name == REPLY.name:
            if self._app is None:
                raise Modeling3dError("The app is not open. Call open_app and give the user its URL first.")
            self.say(arguments["text"])
            return self._result("shown in the app")
        if params.name == APP_UPDATES.name:
            return _structured({"messages": self.updates(arguments.get("after", 0))})
        if params.name == APP_MESSAGE.name:
            return CallToolResult(content=[TextContent(type="text", text=await self._hand_over(arguments["text"]))])
        if params.name == LIST_MODELS.name:
            listing = await asyncio.to_thread(self._list_models, self.directory)
            return _structured(listing.model_dump(mode="json"))
        if params.name == VIEW_MODEL.name:
            summary = await asyncio.to_thread(self._view_model, arguments["name"], self.directory)
            return _structured(summary.model_dump(mode="json"))
        raise Modeling3dError(f"'{params.name}' is not a tool of this server. The tools are: open_app, reply.")

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
        text = _opened_text(app.url, embedded, opened, pushed=self._deliver is not None)
        return self._result(f"{text} It shows the models in {self.directory}.")

    async def _hand_over(self, text: str) -> str:
        if self._deliver is not None:
            try:
                await asyncio.to_thread(self._deliver, text)
                return "delivered to the agent"
            except OSError as error:
                text = f"{text}\n(It could not be delivered: {error}.)"
        with self._lock:
            self._undelivered.append(text)
        return "held for the agent, who sees it with its next call to this server"

    def _result(self, text: str) -> CallToolResult:
        content = [TextContent(type="text", text=text)]
        with self._lock:
            undelivered, self._undelivered = self._undelivered, []
        if undelivered:
            messages = "\n\n".join(undelivered)
            content.append(TextContent(type="text", text=f"The user wrote this in the app meanwhile:\n\n{messages}"))
        return CallToolResult(content=content)


def _structured(structured: dict[str, Any]) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(structured))], structured_content=structured)


def _takes_url_elicitation(ctx: ServerRequestContext[Any]) -> bool:
    capabilities = ctx.session.client_capabilities
    return capabilities is not None and capabilities.elicitation is not None and capabilities.elicitation.url is not None


def _opened_text(url: str, embedded: bool, opened: bool, pushed: bool) -> str:
    if embedded:
        return (
            f"The app is shown to the user inline, and at {url} for a browser. What they write in the inline app "
            "arrives as their own message. Use `reply` to show progress in it."
        )
    where = f"The user opened the app at {url}." if opened else f"Give the user this URL to open the app: {url}"
    if pushed:
        return (
            f"{where} What they write there reaches this session as a message naming the app, between tool calls or "
            "as a new turn. Answer it with `reply`."
        )
    return (
        f"{where} This client gives the server no way to reach you, so what they write there comes back with the "
        "result of your next call to `reply` or `open_app`."
    )
