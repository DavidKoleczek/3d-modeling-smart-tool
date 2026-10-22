import asyncio
import base64
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
import os
from pathlib import Path
import re
import secrets
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
from modeling_3d.capabilities.create_3d_model import create, intelligence_models
from modeling_3d.schemas import (
    AppFolders,
    AppIntelligence,
    AppLayout,
    AppSettings,
    AppState,
    IntelligenceChoice,
    ModelActivity,
    ModelEvent,
    Modeling3dError,
    ModelListing,
    ModelRecord,
    ModelRunRecord,
    ModelSummary,
    PaneLayout,
    ToolCall,
)

TIMEOUT_SECONDS = 5
# A run started from the app runs in a Python process of its own, which takes a while to import the library.
RUN_TIMEOUT_SECONDS = 30
# What the view sends of a file at a time, well under the SDK's 4 MB limit for a request once in base64.
PIECE_BYTES = 2 * 1024 * 1024


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


async def send(client: Client, path: str, data: bytes, upload: str | None = None, piece: int = PIECE_BYTES) -> str:
    """Send a file to the app in pieces, as the view does, into `upload` or a new one, and return the upload."""
    upload = upload or secrets.token_hex(8)
    for offset in range(0, max(len(data), 1), piece):
        encoded = base64.b64encode(data[offset : offset + piece]).decode("ascii")
        result = await client.call_tool(
            "upload_reference", {"upload": upload, "path": path, "offset": offset, "data": encoded}
        )
        assert not result.is_error, text_of(result)
    return upload


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
    open_app: Callable[..., lib.AppServer], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads_directory: Path
) -> None:
    model_in(tmp_path, "bear")
    app_server = open_app(directory=tmp_path)

    async with Client(f"{app_server.open().url}/mcp") as client:
        sketch = await send(client, "sketch.png", b"sketch-bytes", piece=5)
        kit = await send(client, "kit/parts/wheel.png", b"wheel-bytes")
        await send(client, "kit/.git/HEAD", b"ref", upload=kit)
        marked = await send(client, "marked-view-1.png", b"marked-bytes")
        monkeypatch.setattr(create, "BACKGROUND_COMMAND", detached_agent.command("waits_for_steering"))
        created = await client.call_tool(
            "create_3d_model",
            {
                "prompt": "A cub",
                "name": "cub",
                "reference_models": ["bear"],
                "uploads": [sketch, kit],
                "agent_provider": "claude",
                "model": "claude-opus-5-5",
                "reasoning_effort": "high",
            },
        )
        listing = ModelListing.model_validate((await client.call_tool("list_3d_models", {})).structured_content)
        await client.call_tool("steer_3d_model", {"name": "cub", "message": "Smaller.", "uploads": [marked]})
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
    assert [entry.data.get("references") for entry in second.entries if entry.kind == "steered"] == [
        ["references/marked-view-1.png"]
    ]
    assert first.entries[0].data["references"] == [
        "references/sketch.png",
        "references/kit/",
        "references/model.py",
        "references/model.glb",
        "references/front view.png",
    ]
    assert [entry.data["resumed"] for entry in second.entries if entry.kind == "request"] == [False, True]
    assert [
        (entry.data["model"], entry.data["reasoning_effort"]) for entry in second.entries if entry.kind == "request"
    ] == [("claude-opus-5-5", "high"), ("claude-sonnet-5-5", "medium")]
    assert [entry.data["status"] for entry in second.entries if entry.kind == "ended"] == ["done", "cancelled"]
    assert ModelActivity.model_validate(since.structured_content).entries == []
    assert isinstance(sketched, BlobResourceContents)
    assert isinstance(render, BlobResourceContents)
    assert base64.b64decode(sketched.blob) == b"sketch-bytes"
    assert base64.b64decode(render.blob) == b"png-bytes"
    assert (tmp_path / "cub" / "references" / "kit" / "parts" / "wheel.png").read_bytes() == b"wheel-bytes"
    assert (tmp_path / "cub" / "references" / "marked-view-1.png").read_bytes() == b"marked-bytes"
    assert not (tmp_path / "cub" / "references" / "kit" / ".git").exists()
    assert list(uploads_directory.iterdir()) == []


async def test_a_view_tool_that_cannot_run_is_a_tool_error_naming_the_fix(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, uploads_directory: Path
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
        upload = secrets.token_hex(8)
        broken = await client.call_tool(
            "upload_reference", {"upload": upload, "path": "a.png", "offset": 0, "data": "%%"}
        )
        escaping = [
            await client.call_tool("upload_reference", {"upload": upload, "path": path, "offset": 0, "data": ""})
            for path in ("../a.png", "C:/a.png", "/a.png", "kit//a.png")
        ]
        unnamed = await client.call_tool(
            "upload_reference", {"upload": "../up", "path": "a.png", "offset": 0, "data": ""}
        )
        skipped = await client.call_tool(
            "upload_reference", {"upload": upload, "path": "a.png", "offset": 4, "data": ""}
        )
        gone = await client.call_tool("create_3d_model", {"prompt": "A fox", "name": "fox", "uploads": [upload]})
        # Far past the SDK's 4 MB limit for a request, in pieces, so the photo reaches the library, which refuses the
        # name; the upload is kept for the request sent again.
        photo = await send(client, "photo.png", bytes(10 * 1024 * 1024))
        large = await client.call_tool("create_3d_model", {"prompt": "Notes", "name": "notes", "uploads": [photo]})

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
    assert all("is not a file's name or its path in a folder" in text_of(result) for result in escaping)
    assert "is not an upload id" in text_of(unnamed)
    assert "arrived at byte 4, but only 0 bytes had. Send it from byte 0." in text_of(skipped)
    assert "holds nothing" in text_of(gone)
    assert "already exists and is not a model" in text_of(large)
    assert (uploads_directory / photo / "photo.png").stat().st_size == 10 * 1024 * 1024
    assert [path.name for path in uploads_directory.iterdir()] == [photo]


async def test_uploads_no_request_took_are_cleared_when_the_app_closes_or_a_day_on(
    tmp_path: Path, uploads_directory: Path
) -> None:
    stale, recent = uploads_directory / ("a" * 16), uploads_directory / ("b" * 16)
    stale.mkdir()
    recent.mkdir()
    long_ago = time.time() - 2 * 24 * 60 * 60
    os.utime(stale, (long_ago, long_ago))

    app_server = lib.app_server(tmp_path)
    try:
        async with Client(f"{app_server.open().url}/mcp") as client:
            sketch = await send(client, "sketch.png", b"sketch-bytes")
        kept = sorted(path.name for path in uploads_directory.iterdir())
    finally:
        app_server.close()

    assert kept == sorted([recent.name, sketch])
    assert [path.name for path in uploads_directory.iterdir()] == [recent.name]


def test_a_page_from_another_origin_cannot_reach_mcp(open_app: Callable[..., lib.AppServer]) -> None:
    app = open_app().open()

    assert get(f"{app.url}/mcp", origin="https://example.com")[0] == 403


def test_an_uncompiled_view_names_the_build_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(server_module, "VIEW", tmp_path / "mcp_app.html")

    with pytest.raises(Modeling3dError, match=r"uv run build-app\.py"):
        lib.app_view()


def test_the_view_carries_the_tool_s_version_and_where_its_docs_are(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    page = tmp_path / "mcp_app.html"
    page.write_text(
        '<meta name="modeling-3d-version" content="{{version}}"><meta name="modeling-3d-repository" '
        'content="{{repository}}">',
        encoding="utf-8",
    )
    monkeypatch.setattr(server_module, "VIEW", page)
    monkeypatch.setattr(server_module, "repository_url", lambda: "https://example.com/tool?a=1&b=2")

    assert lib.app_view() == (
        f'<meta name="modeling-3d-version" content="{lib.version()}"><meta name="modeling-3d-repository" '
        'content="https://example.com/tool?a=1&amp;b=2">'
    )


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
    bear = model_in(tmp_path, "bear", references=["references/kit/"])
    (bear / "references" / "kit" / "parts").mkdir(parents=True)
    (bear / "references" / "kit" / "parts" / "wheel.png").write_bytes(b"wheel-bytes")
    app_server = open_app(directory=tmp_path)

    async with Client(f"{app_server.open().url}/mcp") as client:
        listed = await client.call_tool("list_3d_models", {})
        viewed = await client.call_tool("view_3d_model", {"name": "bear"})
        again = await client.call_tool("list_3d_models", {})
        glb = (await client.read_resource("modeling-3d://models/bear/model.glb")).contents[0]
        render = (await client.read_resource("modeling-3d://models/bear/renders/front%20view.png")).contents[0]
        wheel = (await client.read_resource("modeling-3d://models/bear/references/kit/parts/wheel.png")).contents[0]

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
    assert isinstance(wheel, BlobResourceContents)
    assert base64.b64decode(wheel.blob) == b"wheel-bytes"


@pytest.mark.parametrize(
    ("uri", "message"),
    [
        ("modeling-3d://models/bear/model.json", "It has: model.glb, renders/front view.png, references/a.png."),
        ("modeling-3d://models/bear/model.py", "'model.py' is not a file the app reads from model bear"),
        ("modeling-3d://models/bear/../bear/model.glb", "'../bear/model.glb' is not a file the app reads"),
        ("modeling-3d://models/bear/references/kit/notes.txt", "'references/kit/notes.txt' is not a file the app"),
        ("modeling-3d://models/bear/references/kit/../../../away.png", "is not a file the app reads"),
        ("modeling-3d://models/fox/model.glb", "There is no model named 'fox'"),
        ("modeling-3d://elsewhere", "is not a resource of this server"),
    ],
)
async def test_only_a_model_s_glb_renders_and_reference_images_can_be_read(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, uri: str, message: str
) -> None:
    bear = model_in(tmp_path, "bear", references=["references/a.png", "references/notes.txt", "references/kit/"])
    (bear / "references" / "kit").mkdir(parents=True)
    (bear / "references" / "kit" / "notes.txt").write_text("notes", encoding="utf-8")
    (tmp_path / "away.png").write_bytes(b"png-bytes")
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


async def test_the_view_reads_a_tool_call_of_a_model_s_agent_in_full(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    target = model_in(tmp_path, "bear", references=[])
    call = {"id": "toolu_01", "name": "Bash", "input": {"command": "uv run --script model.py\necho built"}}
    result = {"tool_use_id": "toolu_01", "content": "Exported model.glb", "is_error": False}
    events = target / "runs" / "run" / "events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(
        "".join(
            ModelEvent(run_id="run", kind="agent", text=kind, data={"content": [block]}).model_dump_json() + "\n"
            for kind, block in (("AssistantMessage", call), ("UserMessage", result))
        ),
        encoding="utf-8",
    )
    app_server = open_app(directory=tmp_path)

    async with Client(f"{app_server.open().url}/mcp") as client:
        read = await client.call_tool(
            "read_3d_model_tool_call", {"name": "bear", "run_id": "run", "call_id": "toolu_01"}
        )
        missing = await client.call_tool(
            "read_3d_model_tool_call", {"name": "bear", "run_id": "run", "call_id": "toolu_02"}
        )

    assert ToolCall.model_validate(read.structured_content) == ToolCall(
        name="Bash", input=call["input"], output="Exported model.glb", failed=False
    )
    assert missing.is_error
    assert missing.structured_content == {"reason": "no-such-tool-call", "model": "bear"}


async def test_the_view_remembers_the_ai_model_picked_in_the_app_directory_until_it_is_no_longer_offered(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: agent_provider == "claude")
    directory = tmp_path / "models"
    app_server = open_app(directory=directory)
    opus = IntelligenceChoice(agent_provider="claude", model="claude-opus-5-5", reasoning_effort="high")
    options = lib.list_intelligence_models()

    async with Client(f"{app_server.open().url}/mcp") as client:
        before = await client.call_tool("list_intelligence_models", {})
        chosen = await client.call_tool(
            "choose_intelligence_model", {"model": "claude-opus-5-5", "reasoning_effort": "high"}
        )
        after = await client.call_tool("list_intelligence_models", {})
        unknown = await client.call_tool("choose_intelligence_model", {"model": "nope", "reasoning_effort": "high"})
        extreme = await client.call_tool(
            "choose_intelligence_model", {"model": "claude-opus-5-5", "reasoning_effort": "extreme"}
        )
        ultra = await client.call_tool(
            "choose_intelligence_model", {"model": "claude-opus-5-5", "reasoning_effort": "ultra"}
        )
        monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: False)
        gone = await client.call_tool("list_intelligence_models", {})

    assert AppIntelligence.model_validate(before.structured_content) == AppIntelligence(
        **options.model_dump(), chosen=None
    )
    assert AppIntelligence.model_validate(chosen.structured_content).chosen == opus
    assert AppIntelligence.model_validate(after.structured_content).chosen == opus
    assert AppState.model_validate_json((directory / ".app.json").read_text(encoding="utf-8")).intelligence == opus
    assert unknown.structured_content == {"reason": "no-such-intelligence-model", "model": None}
    assert "It offers: claude-sonnet-5-5, claude-opus-5-5." in text_of(unknown)
    assert extreme.structured_content == {"reason": "bad-reasoning-effort", "model": None}
    assert ultra.structured_content == {"reason": "bad-reasoning-effort", "model": None}
    assert "Pass one of: low, medium, high, xhigh, max." in text_of(ultra)
    assert AppIntelligence.model_validate(gone.structured_content).chosen is None


async def test_the_view_keeps_the_person_s_settings_in_their_config_directory_for_every_directory(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, config_directory: Path
) -> None:
    toys = open_app(directory=tmp_path / "toys")
    tools = open_app(directory=tmp_path / "tools")
    settings = AppSettings(
        theme="dark",
        dimensions=True,
        wide=AppLayout(activity=PaneLayout(size=420), models=PaneLayout(open=False)),
        steps={"id-bear": {"run:1": True, "run:3": False}},
    )

    async with Client(f"{toys.open().url}/mcp") as client:
        before = await client.call_tool("read_app_settings", {})
        saved = await client.call_tool("save_app_settings", {"settings": settings.model_dump(mode="json")})
    async with Client(f"{tools.open().url}/mcp") as client:
        elsewhere = await client.call_tool("read_app_settings", {})

    assert AppSettings.model_validate(before.structured_content) == AppSettings()
    assert AppSettings.model_validate(saved.structured_content) == settings
    assert AppSettings.model_validate(elsewhere.structured_content) == settings
    kept = config_directory / "modeling-3d" / "app-settings.json"
    assert AppSettings.model_validate_json(kept.read_text(encoding="utf-8")) == settings
    assert not (tmp_path / "toys" / "app-settings.json").exists()


async def test_settings_that_are_not_valid_are_refused_naming_the_field_and_unreadable_ones_read_as_defaults(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, config_directory: Path
) -> None:
    app_server = open_app(directory=tmp_path)
    kept = config_directory / "modeling-3d" / "app-settings.json"
    kept.parent.mkdir(parents=True)
    kept.write_text("{not json", encoding="utf-8")

    async with Client(f"{app_server.open().url}/mcp") as client:
        unreadable = await client.call_tool("read_app_settings", {})
        bad = await client.call_tool("save_app_settings", {"settings": {"theme": "sepia"}})
        nested = await client.call_tool("save_app_settings", {"settings": {"wide": {"models": {"size": -1}}}})

    assert AppSettings.model_validate(unreadable.structured_content) == AppSettings()
    assert bad.is_error
    assert bad.structured_content == {"reason": "bad-settings", "model": None}
    assert "The app setting theme is not valid" in text_of(bad)
    assert "The app setting wide.models.size is not valid" in text_of(nested)
    assert kept.read_text(encoding="utf-8") == "{not json"


async def test_settings_kept_by_an_earlier_version_still_read_with_what_it_no_longer_has_left_out(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, config_directory: Path
) -> None:
    app_server = open_app(directory=tmp_path)
    kept = config_directory / "modeling-3d" / "app-settings.json"
    kept.parent.mkdir(parents=True)
    kept.write_text('{"theme": "dark", "activity_detail": "every-step"}', encoding="utf-8")

    async with Client(f"{app_server.open().url}/mcp") as client:
        read = await client.call_tool("read_app_settings", {})

    assert AppSettings.model_validate(read.structured_content) == AppSettings(theme="dark")


async def test_the_view_names_and_opens_the_folders_where_the_app_keeps_things(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, config_directory: Path, opened_folders: list[Path]
) -> None:
    bear = model_in(tmp_path / "models", "bear")
    app_server = open_app(directory=tmp_path / "models")

    async with Client(f"{app_server.open().url}/mcp") as client:
        folders = await client.call_tool("read_app_folders", {})
        for arguments in ({"folder": "settings"}, {"folder": "models"}, {"folder": "model", "name": "bear"}):
            result = await client.call_tool("open_app_folder", arguments)
            assert not result.is_error, text_of(result)
        missing = await client.call_tool("open_app_folder", {"folder": "model", "name": "fox"})
        unnamed = await client.call_tool("open_app_folder", {"folder": "model"})

    assert AppFolders.model_validate(folders.structured_content) == AppFolders(
        settings=config_directory / "modeling-3d", models=(tmp_path / "models").resolve()
    )
    assert opened_folders == [config_directory / "modeling-3d", (tmp_path / "models").resolve(), bear.resolve()]
    assert missing.structured_content == {"reason": "no-such-model", "model": "fox"}
    assert "The models there: bear." in text_of(missing)
    assert "Pass `settings`, `models`, or `model` with the model's `name`." in text_of(unnamed)
