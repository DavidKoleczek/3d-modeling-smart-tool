"""The app's MCP server: tools that open the app and talk through it, and its view as an MCP App resource."""

import asyncio
from collections.abc import Callable
import json
import threading
from typing import Any
import uuid

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID, client_supports_apps
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ElicitRequest,
    ElicitRequestURLParams,
    ElicitResult,
    InputRequiredResult,
    ListResourcesResult,
    ListToolsResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    Resource,
    TextContent,
    TextResourceContents,
    Tool,
)

from modeling_3d.capabilities.app.server import App, serve_app, view
from modeling_3d.schemas import Modeling3dError

VIEW_URI = "ui://modeling-3d/app"
# The key `open_app` files its request to open the browser under, when the client answers by retrying the call.
OPEN_REQUEST = "open"
INSTRUCTIONS = """\
Modeling 3D has an app where the user watches the work and steers it. Call `open_app` when they ask for it.

What they write in the app reaches you as a message that names the app. They read the app, not this conversation, so \
answer those messages with `reply`."""

OPEN_APP = Tool(
    name="open_app",
    description="Show the Modeling 3D app, where the user watches the work and steers it, and return its browser URL. "
    "Hosts that render MCP Apps show it inline. Opening it again returns the same URL.",
    input_schema={"type": "object", "properties": {}},
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
VIEW = Resource(uri=VIEW_URI, name="Modeling 3D app", mime_type=APP_MIME_TYPE)


class AppServer:
    """The app's MCP server, what the agent has said in the app, and the browser host page once it is open.

    Serve `server` over any MCP transport. Several at once share this state, so the browser host page reaches the
    same server the agent's session does.
    """

    def __init__(self, server_name: str, version: str, deliver: Callable[[str], None] | None = None) -> None:
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
            return ListToolsResult(tools=[OPEN_APP, REPLY, APP_UPDATES, APP_MESSAGE])
        return ListToolsResult(tools=[OPEN_APP, REPLY])

    async def _list_resources(
        self, ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(resources=[VIEW] if client_supports_apps(ctx) else [])

    async def _read_resource(
        self, ctx: ServerRequestContext[Any], params: ReadResourceRequestParams
    ) -> ReadResourceResult:
        if params.uri != VIEW_URI:
            raise MCPError(
                INVALID_PARAMS, f"'{params.uri}' is not a resource of this server. The only one is {VIEW_URI}."
            )
        return ReadResourceResult(contents=[TextResourceContents(uri=VIEW_URI, mime_type=APP_MIME_TYPE, text=view())])

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
            structured = {"messages": self.updates(arguments.get("after", 0))}
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(structured))], structured_content=structured
            )
        if params.name == APP_MESSAGE.name:
            return CallToolResult(content=[TextContent(type="text", text=await self._hand_over(arguments["text"]))])
        raise Modeling3dError(f"'{params.name}' is not a tool of this server. The tools are: open_app, reply.")

    async def _open_app(
        self, ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
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
        return self._result(_opened_text(app.url, embedded, opened, pushed=self._deliver is not None))

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
