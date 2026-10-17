import asyncio
import base64
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
import re
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import detached_agent
from mcp import Client, MCPError
from mcp.types import BlobResourceContents, TextContent, TextResourceContents
import pytest

from modeling_3d import lib
from modeling_3d.capabilities.app import server as server_module
from modeling_3d.capabilities.create_3d_model import create
from modeling_3d.schemas import ModelActivity, Modeling3dError, ModelListing, ModelRecord, ModelRunRecord, ModelSummary

TIMEOUT_SECONDS = 5
# A run started from the app runs in a Python process of its own, which takes a while to import the library.
RUN_TIMEOUT_SECONDS = 30


@pytest.fixture
def open_app() -> Iterator[Callable[..., lib.AppServer]]:
    opened: list[lib.AppServer] = []

    def open_with(directory: Path | None = None) -> lib.AppServer:
        app_server = lib.app_server(directory)
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


def model_in(directory: Path, name: str, references: list[str] | None = None) -> Path:
    """A model that has been built, whose one run was given `references`."""
    target = directory / name
    (target / "renders").mkdir(parents=True)
    runs = []
    if references is not None:
        run = ModelRunRecord(
            id="run",
            prompt=f"A {name}",
            references=references,
            resumed=False,
            agent_provider="claude",
            model="claude-sonnet-5-5",
            reasoning_effort="medium",
            status="done",
            pid=1,
            started=datetime.now(UTC),
        )
        runs.append(run)
    record = ModelRecord(id=f"id-{name}", name=name, created=datetime.now(UTC), runs=runs)
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


async def test_the_browser_host_reaches_the_server_over_mcp(open_app: Callable[..., lib.AppServer]) -> None:
    app_server = open_app()

    async with Client(f"{app_server.open().url}/mcp") as client:
        view = (await client.read_resource("ui://modeling-3d/app")).contents[0]
        tools = {tool.name for tool in (await client.list_tools()).tools}

    assert isinstance(view, TextResourceContents)
    assert view.text == lib.app_view()
    assert {"reply", "app_updates", "app_message"}.isdisjoint(tools)


async def activity_until(client: Client, name: str, ends: int) -> ModelActivity:
    """The model's activity once `ends` of its runs have ended."""
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        activity = ModelActivity.model_validate(
            (await client.call_tool("read_3d_model_activity", {"name": name})).structured_content
        )
        if sum(entry.kind == "ended" for entry in activity.entries) >= ends and activity.model.status != "running":
            return activity
        await asyncio.sleep(0.05)
    raise AssertionError(f"Model {name} did not end {ends} runs.")


async def test_the_view_creates_steers_and_stops_models_as_the_app_and_reads_their_activity(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_in(tmp_path, "bear")
    app_server = open_app(directory=tmp_path)
    sketch = {"name": "sketch.png", "data": base64.b64encode(b"sketch-bytes").decode("ascii")}

    async with Client(f"{app_server.open().url}/mcp") as client:
        monkeypatch.setattr(create, "BACKGROUND_COMMAND", detached_agent.command("waits_for_steering"))
        created = await client.call_tool(
            "create_3d_model",
            {"prompt": "A cub", "name": "cub", "reference_models": ["bear"], "references": [sketch]},
        )
        listing = ModelListing.model_validate((await client.call_tool("list_3d_models", {})).structured_content)
        await client.call_tool("steer_3d_model", {"name": "cub", "message": "Smaller."})
        first = await activity_until(client, "cub", 1)
        monkeypatch.setattr(create, "BACKGROUND_COMMAND", detached_agent.command("works_forever"))
        await client.call_tool("create_3d_model", {"prompt": "Go on", "name": "cub", "resume_session": True})
        cancelled = await client.call_tool("cancel_3d_model", {"name": "cub"})
        second = await activity_until(client, "cub", 2)
        since = await client.call_tool("read_3d_model_activity", {"name": "cub", "after": second.cursor})
        sketched = (await client.read_resource("modeling-3d://models/cub/references/sketch.png")).contents[0]
        render = (await client.read_resource("modeling-3d://models/cub/references/front%20view.png")).contents[0]

    summary = ModelSummary.model_validate(created.structured_content)
    assert (summary.name, summary.status, listing.last_viewed) == ("cub", "running", "cub")
    assert not cancelled.is_error, text_of(cancelled)
    kinds = [(entry.kind, entry.origin, entry.text) for entry in second.entries if entry.kind != "ended"]
    assert kinds == [("request", "app", "A cub"), ("steered", "app", "Smaller."), ("request", "app", "Go on")]
    assert first.entries[0].data["references"] == [
        "references/sketch.png",
        "references/model.py",
        "references/model.glb",
        "references/front view.png",
    ]
    assert [entry.data["resumed"] for entry in second.entries if entry.kind == "request"] == [False, True]
    assert [entry.data["status"] for entry in second.entries if entry.kind == "ended"] == ["done", "cancelled"]
    assert ModelActivity.model_validate(since.structured_content).entries == []
    assert isinstance(sketched, BlobResourceContents)
    assert isinstance(render, BlobResourceContents)
    assert base64.b64decode(sketched.blob) == b"sketch-bytes"
    assert base64.b64decode(render.blob) == b"png-bytes"


async def test_a_view_tool_that_cannot_run_is_a_tool_error_naming_the_fix(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    model_in(tmp_path, "bear")
    (tmp_path / "notes").mkdir()
    app_server = open_app(directory=tmp_path)

    async with Client(f"{app_server.open().url}/mcp") as client:
        taken = await client.call_tool("create_3d_model", {"prompt": "Notes", "name": "notes"})
        unbuilt = await client.call_tool(
            "create_3d_model", {"prompt": "A fox", "name": "fox", "reference_models": ["wolf"]}
        )
        idle = await client.call_tool("steer_3d_model", {"name": "bear", "message": "Smaller."})
        broken = await client.call_tool(
            "create_3d_model", {"prompt": "A fox", "name": "fox", "references": [{"name": "a.png", "data": "%%"}]}
        )
        # Past the SDK's 4 MB default for a request, so the photo reaches the library, which refuses the name.
        photo = {"name": "photo.png", "data": base64.b64encode(bytes(6 * 1024 * 1024)).decode("ascii")}
        large = await client.call_tool("create_3d_model", {"prompt": "Notes", "name": "notes", "references": [photo]})

    assert taken.is_error
    assert "already exists and is not a model" in text_of(taken)
    assert taken.structured_content == {"reason": "name-in-use", "model": "notes"}
    assert unbuilt.structured_content == {"reason": "no-reference-model", "model": "wolf"}
    assert idle.is_error
    assert "is not being worked on" in text_of(idle)
    assert idle.structured_content == {"reason": "not-running", "model": "bear"}
    assert broken.is_error
    assert "did not arrive as base64" in text_of(broken)
    assert broken.structured_content == {"reason": "bad-upload", "model": None}
    assert "already exists and is not a model" in text_of(large)


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
        ("modeling-3d://models/bear/model.json", "It has: model.glb, renders/front view.png, references/a.png."),
        ("modeling-3d://models/bear/model.py", "'model.py' is not a file the app reads from model bear"),
        ("modeling-3d://models/bear/../bear/model.glb", "'../bear/model.glb' is not a file the app reads"),
        ("modeling-3d://models/fox/model.glb", "There is no model named 'fox'"),
        ("modeling-3d://elsewhere", "is not a resource of this server"),
    ],
)
async def test_only_a_model_s_glb_renders_and_reference_images_can_be_read(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, uri: str, message: str
) -> None:
    model_in(tmp_path, "bear", references=["references/a.png", "references/notes.txt"])
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
