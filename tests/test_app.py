from collections.abc import Callable, Iterator
import queue
import re
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mcp import Client
from mcp.types import TextContent, TextResourceContents
import pytest

from modeling_3d import lib
from modeling_3d.capabilities.app import server as server_module
from modeling_3d.schemas import Modeling3dError

TIMEOUT_SECONDS = 5


@pytest.fixture
def delivered() -> queue.Queue[str]:
    return queue.Queue()


@pytest.fixture
def open_app(delivered: queue.Queue[str]) -> Iterator[Callable[..., lib.AppServer]]:
    opened: list[lib.AppServer] = []

    def open_with(deliver: Callable[[str], None] | None = delivered.put) -> lib.AppServer:
        app_server = lib.app_server(deliver)
        app_server.open()
        opened.append(app_server)
        return app_server

    yield open_with
    for app_server in opened:
        app_server.close()


def get(url: str, origin: str | None = None) -> tuple[int, dict[str, str], str]:
    request = Request(url, headers={"Origin": origin} if origin else {})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read().decode("utf-8")


def sandbox_url(app: server_module.App) -> str:
    _, _, page = get(app.url)
    port = re.search(r'name="modeling-3d-sandbox-port" content="(\d+)"', page)
    assert port is not None
    return f"http://127.0.0.1:{port[1]}"


def text_of(result: Any) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


def test_the_host_page_points_at_a_sandbox_on_another_origin(open_app: Callable[..., lib.AppServer]) -> None:
    app = open_app().open()

    assert sandbox_url(app) != app.url


def test_the_sandbox_carries_the_view_csp_and_nothing_else(open_app: Callable[..., lib.AppServer]) -> None:
    app = open_app().open()
    sandbox = sandbox_url(app)
    status, headers, page = get(f"{sandbox}/sandbox.html")

    assert status == 200
    assert "connect-src 'none'" in headers["content-security-policy"]
    assert f'content="{app.url.rsplit(":", 1)[1]}"' in page
    assert get(f"{sandbox}/")[0] == 404


async def test_the_browser_host_reaches_the_agents_server_over_mcp(
    open_app: Callable[..., lib.AppServer], delivered: queue.Queue[str]
) -> None:
    app_server = open_app()
    app_server.say("a cube it is")

    async with Client(f"{app_server.open().url}/mcp") as client:
        view = (await client.read_resource("ui://modeling-3d/app")).contents[0]
        handed = await client.call_tool("app_message", {"text": "make the legs longer"})
        updates = await client.call_tool("app_updates", {"after": 0})

    assert isinstance(view, TextResourceContents)
    assert view.text == lib.app_view()
    assert text_of(handed) == "delivered to the agent"
    assert delivered.get(timeout=TIMEOUT_SECONDS) == "make the legs longer"
    assert updates.structured_content == {"messages": ["a cube it is"]}


@pytest.mark.parametrize("failure", [None, OSError("the inbox is gone")])
async def test_an_undelivered_message_comes_back_with_the_next_tool_result(
    open_app: Callable[..., lib.AppServer], failure: OSError | None
) -> None:
    def refuse(text: str) -> None:
        raise failure or OSError

    app_server = open_app(None if failure is None else refuse)

    async with Client(f"{app_server.open().url}/mcp") as client:
        handed = await client.call_tool("app_message", {"text": "make the legs longer"})
        first = await client.call_tool("reply", {"text": "on it"})
        second = await client.call_tool("reply", {"text": "done"})

    assert text_of(handed).startswith("held for the agent")
    assert "make the legs longer" in text_of(first)
    assert failure is None or "the inbox is gone" in text_of(first)
    assert "make the legs longer" not in text_of(second)


def test_a_page_from_another_origin_cannot_reach_mcp(open_app: Callable[..., lib.AppServer]) -> None:
    app = open_app().open()

    assert get(f"{app.url}/mcp", origin="https://example.com")[0] == 403


def test_an_uncompiled_view_names_the_build_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(server_module, "VIEW", tmp_path / "mcp_app.html")

    with pytest.raises(Modeling3dError, match=r"uv run build-app\.py"):
        lib.app_view()


def test_a_held_port_is_a_named_failure(open_app: Callable[..., lib.AppServer]) -> None:
    port = int(open_app().open().url.rsplit(":", 1)[1])

    with pytest.raises(Modeling3dError, match="could not bind"):
        lib.app_server().open(port)


def test_close_frees_the_port() -> None:
    first = lib.app_server()
    port = int(first.open().url.rsplit(":", 1)[1])
    first.close()

    second = lib.app_server()
    second.open(port)
    second.close()
