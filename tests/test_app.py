import base64
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
import queue
import re
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mcp import Client, MCPError
from mcp.types import BlobResourceContents, TextContent, TextResourceContents
import pytest

from modeling_3d import lib
from modeling_3d.capabilities.app import server as server_module
from modeling_3d.schemas import Modeling3dError, ModelListing, ModelRecord, ModelSummary

TIMEOUT_SECONDS = 5


@pytest.fixture
def delivered() -> queue.Queue[str]:
    return queue.Queue()


@pytest.fixture
def open_app(delivered: queue.Queue[str]) -> Iterator[Callable[..., lib.AppServer]]:
    opened: list[lib.AppServer] = []

    def open_with(
        deliver: Callable[[str], None] | None = delivered.put, directory: Path | None = None
    ) -> lib.AppServer:
        app_server = lib.app_server(deliver, directory)
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


def model_in(directory: Path, name: str) -> Path:
    target = directory / name
    (target / "renders").mkdir(parents=True)
    record = ModelRecord(id=f"id-{name}", name=name, created=datetime.now(UTC))
    (target / "model.json").write_text(record.model_dump_json(), encoding="utf-8")
    (target / "model.py").write_text("# the model", encoding="utf-8")
    (target / "model.glb").write_bytes(b"glTF-bytes")
    (target / "renders" / "front view.png").write_bytes(b"png-bytes")
    return target


def test_the_host_page_points_at_a_sandbox_on_another_origin_with_the_view_csp_and_nothing_else(
    open_app: Callable[..., lib.AppServer],
) -> None:
    app = open_app().open()
    sandbox = sandbox_url(app)
    status, headers, page = get(f"{sandbox}/sandbox.html")

    assert sandbox != app.url
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


def test_a_held_port_is_a_named_failure_until_close_frees_it() -> None:
    first = lib.app_server()
    port = int(first.open().url.rsplit(":", 1)[1])

    with pytest.raises(Modeling3dError, match="could not bind"):
        lib.app_server().open(port)

    first.close()
    second = lib.app_server()
    second.open(port)
    second.close()


async def test_the_view_lists_views_and_reads_the_models_in_the_app_directory(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    model_in(tmp_path, "bear")
    app_server = open_app(directory=tmp_path)

    async with Client(f"{app_server.open().url}/mcp") as client:
        listed = await client.call_tool("list_3d_models", {})
        viewed = await client.call_tool("view_3d_model", {"name": "bear"})
        again = await client.call_tool("list_3d_models", {})
        glb = (await client.read_resource("modeling-3d://models/bear/model.glb")).contents[0]
        render = (await client.read_resource("modeling-3d://models/bear/renders/front%20view.png")).contents[0]

    listing = ModelListing.model_validate(listed.structured_content)
    assert listing.directory == tmp_path.resolve()
    assert [model.name for model in listing.models] == ["bear"]
    assert listing.last_viewed is None
    assert ModelSummary.model_validate(viewed.structured_content) == listing.models[0]
    assert ModelListing.model_validate(again.structured_content).last_viewed == "bear"
    assert isinstance(glb, BlobResourceContents)
    assert isinstance(render, BlobResourceContents)
    assert (glb.mime_type, base64.b64decode(glb.blob)) == ("model/gltf-binary", b"glTF-bytes")
    assert (render.mime_type, base64.b64decode(render.blob)) == ("image/png", b"png-bytes")


@pytest.mark.parametrize(
    ("uri", "message"),
    [
        ("modeling-3d://models/bear/model.json", "It has: model.glb, renders/front view.png."),
        ("modeling-3d://models/bear/model.py", "'model.py' is not a file the app reads from model bear"),
        ("modeling-3d://models/bear/../bear/model.glb", "'../bear/model.glb' is not a file the app reads"),
        ("modeling-3d://models/fox/model.glb", "There is no model named 'fox'"),
        ("modeling-3d://elsewhere", "is not a resource of this server"),
    ],
)
async def test_only_a_model_s_glb_and_renders_can_be_read(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, uri: str, message: str
) -> None:
    model_in(tmp_path, "bear")
    app_server = open_app(directory=tmp_path)

    async with Client(f"{app_server.open().url}/mcp") as client:
        with pytest.raises(MCPError) as failure:
            await client.read_resource(uri)

    assert message in str(failure.value)


async def test_viewing_a_model_that_does_not_exist_is_a_tool_error_naming_the_models(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    model_in(tmp_path, "bear")
    app_server = open_app(directory=tmp_path)

    async with Client(f"{app_server.open().url}/mcp") as client:
        result = await client.call_tool("view_3d_model", {"name": "fox"})

    assert result.is_error
    assert "The models there: bear." in text_of(result)
