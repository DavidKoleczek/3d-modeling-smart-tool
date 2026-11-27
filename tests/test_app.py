import asyncio
import base64
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import detached_agent
from fakes import FileDialog, run_record
from glbs import Glb, box
from mcp import Client, MCPError
from mcp.types import BlobResourceContents, TextContent, TextResourceContents
import pytest

from modeling_3d import lib
from modeling_3d.capabilities.app import folders, mcp_server
from modeling_3d.capabilities.app import server as server_module
from modeling_3d.capabilities.app.folders import choose_files, choose_folder
from modeling_3d.capabilities.create_3d_model import constants, create, intelligence_models
from modeling_3d.capabilities.create_3d_model.check import check
from modeling_3d.capabilities.create_3d_model.record import write_record
from modeling_3d.schemas import (
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_REASONING_EFFORT,
    PROVIDER_REASONING_EFFORTS,
    AppFolders,
    AppIntelligence,
    AppLayout,
    AppLibrary,
    AppPins,
    AppSettings,
    AppState,
    AppSteps,
    AppWorkspaces,
    IntelligenceChoice,
    ModelActivity,
    ModelCheck,
    ModelEvent,
    Modeling3dError,
    ModelListing,
    ModelRecord,
    ModelSummary,
    PaneLayout,
    PinnedFolder,
    PinnedPrompt,
    PinnedReference,
    RecentWorkspace,
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

    def open_with(workspace: Path | None = None) -> lib.AppServer:
        if workspace is not None:
            workspace.mkdir(parents=True, exist_ok=True)
        app_server = lib.app_server(workspace)
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


def model_in(workspace: Path, name: str, references: list[str] | None = None, **run: Any) -> Path:
    """A model in `workspace` that has been built, whose one run was given `references`, and whatever else `run` sets."""
    target = workspace / ".modeling-3d" / name
    (target / "renders").mkdir(parents=True)
    runs = [] if references is None else [run_record(prompt=f"A {name}", references=references, **run)]
    record = ModelRecord(id=f"id-{name}", name=name, created=datetime.now(UTC), runs=runs)
    write_record(target, record)
    (target / "model.py").write_text("# the model", encoding="utf-8")
    (target / "model.glb").write_bytes(b"glTF-bytes")
    (target / "renders" / "front view.png").write_bytes(b"png-bytes")
    return target


def test_the_host_page_points_at_a_sandbox_on_another_origin_and_only_its_own_pages_reach_mcp(
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
    assert get(f"{app.url}/mcp", origin="https://example.com")[0] == 403


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


@pytest.mark.detached
async def test_the_view_creates_steers_and_stops_models_as_the_app_and_reads_their_activity(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads_directory: Path
) -> None:
    model_in(tmp_path, "bear")
    app_server = open_app(workspace=tmp_path)

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
                "max_triangles": 2000,
                "max_draw_calls": None,
                "screen_size": [40, 240],
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
        library = await client.call_tool("read_app_library", {})
        cancelled = await client.call_tool("cancel_3d_model", {"name": "cub"})
        second = await activity_until(client, "cub", 2)
        since = await client.call_tool("read_3d_model_activity", {"name": "cub", "after": second.cursor})
        sketched = (await client.read_resource("modeling-3d://models/cub/references/sketch.png")).contents[0]
        render = (await client.read_resource("modeling-3d://models/cub/references/front%20view.png")).contents[0]

    summary = ModelSummary.model_validate(created.structured_content)
    assert (summary.name, summary.status, listing.last_viewed) == ("cub", "running", None)
    assert AppLibrary.model_validate(library.structured_content).last_prompt == "A cub"
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
    ] == [("claude-opus-5-5", "high"), (DEFAULT_INTELLIGENCE_MODELS["claude"], DEFAULT_REASONING_EFFORT)]
    assert [
        (entry.data["max_triangles"], entry.data.get("max_draw_calls"), entry.data["screen_size"])
        for entry in second.entries
        if entry.kind == "request"
    ] == [(2000, None, [40, 240])] * 2
    assert [entry.data["status"] for entry in second.entries if entry.kind == "ended"] == ["done", "cancelled"]
    assert ModelActivity.model_validate(since.structured_content).entries == []
    assert isinstance(sketched, BlobResourceContents)
    assert isinstance(render, BlobResourceContents)
    assert base64.b64decode(sketched.blob) == b"sketch-bytes"
    assert base64.b64decode(render.blob) == b"png-bytes"
    cub = tmp_path / ".modeling-3d" / "cub"
    assert (cub / "references" / "kit" / "parts" / "wheel.png").read_bytes() == b"wheel-bytes"
    assert (cub / "references" / "marked-view-1.png").read_bytes() == b"marked-bytes"
    assert not (cub / "references" / "kit" / ".git").exists()
    assert list(uploads_directory.iterdir()) == []


@pytest.mark.detached
async def test_the_view_rigs_a_model_as_the_app_to_its_own_budgets(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_in(tmp_path, "bear", references=[], max_triangles=2000, max_draw_calls=2, screen_size=(40, 240))
    app_server = open_app(workspace=tmp_path)
    monkeypatch.setattr(create, "BACKGROUND_COMMAND", detached_agent.command("builds"))

    async with Client(f"{app_server.open().url}/mcp") as client:
        rigged = await client.call_tool("rig_3d_model", {"name": "bear", "reasoning_effort": "high"})
        told = await activity_until(client, "bear", 1)

    assert ModelSummary.model_validate(rigged.structured_content).status == "running"
    [request] = [entry for entry in told.entries if entry.kind == "request"]
    assert (request.text, request.origin, request.data["mode"]) == ("", "app", "rig")
    budgets = (request.data["max_triangles"], request.data["max_draw_calls"], request.data["screen_size"])
    assert budgets == (2000, 2, [40, 240])
    assert told.model.last_run is not None
    assert (told.model.last_run.mode, told.model.last_run.reasoning_effort) == ("rig", "high")


async def test_the_view_checks_a_model_waiting_again_on_a_long_check_and_reads_the_report(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bear = model_in(tmp_path, "bear", references=[])
    glb = Glb()
    glb.node("Box", mesh=glb.mesh(box()))
    glb.write(bear / "model.glb")
    (model_in(tmp_path, "fox") / "model.glb").unlink()
    app_server = open_app(workspace=tmp_path)

    async with Client(f"{app_server.open().url}/mcp") as client:
        unchecked = ModelSummary.model_validate(
            (await client.call_tool("view_3d_model", {"name": "bear"})).structured_content
        )
        monkeypatch.setattr(mcp_server, "CHECK_WAIT_SECONDS", 0)
        waiting = await client.call_tool("check_3d_model", {"name": "bear"})
        monkeypatch.setattr(mcp_server, "CHECK_WAIT_SECONDS", TIMEOUT_SECONDS)
        checked = await client.call_tool("check_3d_model", {"name": "bear"})
        kept = (await client.read_resource("modeling-3d://models/bear/checks/report.json")).contents[0]
        summary = ModelSummary.model_validate(
            (await client.call_tool("view_3d_model", {"name": "bear"})).structured_content
        )
        unbuilt = await client.call_tool("check_3d_model", {"name": "fox"})

    assert unchecked.checked is None
    assert waiting.structured_content == {"checking": True}
    assert checked.structured_content is not None
    report = checked.structured_content["report"]
    assert (report["name"], report["triangles"]) == ("bear", 12)
    assert isinstance(kept, BlobResourceContents)
    assert (kept.mime_type, json.loads(base64.b64decode(kept.blob))["glb_sha256"]) == (
        "application/json",
        report["glb_sha256"],
    )
    assert summary.checked is not None
    assert unbuilt.is_error
    assert unbuilt.structured_content == {"reason": "not-built", "model": "fox"}


async def test_a_view_tool_that_cannot_run_is_a_tool_error_naming_the_fix(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, uploads_directory: Path
) -> None:
    model_in(tmp_path, "bear")
    (tmp_path / ".modeling-3d" / "notes").mkdir()
    app_server = open_app(workspace=tmp_path)

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


def test_the_view_names_the_build_command_until_compiled_and_then_carries_the_tool_s_version_and_docs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    page = tmp_path / "mcp_app.html"
    monkeypatch.setattr(server_module, "VIEW", page)

    with pytest.raises(Modeling3dError, match=r"uv run build-app\.py"):
        lib.app_view()
    page.write_text(
        '<meta name="modeling-3d-version" content="{{version}}"><meta name="modeling-3d-repository" '
        'content="{{repository}}">',
        encoding="utf-8",
    )
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


async def test_the_view_lists_views_and_reads_the_models_in_the_app_s_workspace_and_their_agents_tool_calls(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    bear = model_in(tmp_path, "bear", references=["references/kit/"])
    (bear / "references" / "kit" / "parts").mkdir(parents=True)
    (bear / "references" / "kit" / "parts" / "wheel.png").write_bytes(b"wheel-bytes")
    call = {"id": "toolu_01", "name": "Bash", "input": {"command": "uv run --script model.py\necho built"}}
    result = {"tool_use_id": "toolu_01", "content": "Exported model.glb", "is_error": False}
    events = bear / "runs" / "run" / "events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(
        "".join(
            ModelEvent(run_id="run", kind="agent", text=kind, data={"content": [block]}).model_dump_json() + "\n"
            for kind, block in (("AssistantMessage", call), ("UserMessage", result))
        ),
        encoding="utf-8",
    )
    app_server = open_app(workspace=tmp_path)

    async with Client(f"{app_server.open().url}/mcp") as client:
        view = (await client.read_resource("ui://modeling-3d/app")).contents[0]
        listed = await client.call_tool("list_3d_models", {})
        viewed = await client.call_tool("view_3d_model", {"name": "bear"})
        again = await client.call_tool("list_3d_models", {})
        glb = (await client.read_resource("modeling-3d://models/bear/model.glb")).contents[0]
        render = (await client.read_resource("modeling-3d://models/bear/renders/front%20view.png")).contents[0]
        wheel = (await client.read_resource("modeling-3d://models/bear/references/kit/parts/wheel.png")).contents[0]
        read = await client.call_tool(
            "read_3d_model_tool_call", {"name": "bear", "run_id": "run", "call_id": "toolu_01"}
        )
        missing = await client.call_tool(
            "read_3d_model_tool_call", {"name": "bear", "run_id": "run", "call_id": "toolu_02"}
        )

    assert isinstance(view, TextResourceContents)
    assert view.text == lib.app_view()
    listing = ModelListing.model_validate(listed.structured_content)
    assert (listing.workspace, listing.directory) == (tmp_path.resolve(), tmp_path.resolve() / ".modeling-3d")
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
    assert ToolCall.model_validate(read.structured_content) == ToolCall(
        name="Bash", input=call["input"], output="Exported model.glb", failed=False
    )
    assert missing.is_error
    assert missing.structured_content == {"reason": "no-such-tool-call", "model": "bear"}


async def test_only_a_model_s_glb_renders_and_reference_images_can_be_read(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    bear = model_in(tmp_path, "bear", references=["references/a.png", "references/notes.txt", "references/kit/"])
    (bear / "references" / "kit").mkdir(parents=True)
    (bear / "references" / "kit" / "notes.txt").write_text("notes", encoding="utf-8")
    (tmp_path / ".modeling-3d" / "away.png").write_bytes(b"png-bytes")
    app_server = open_app(workspace=tmp_path)
    refused = {
        "modeling-3d://models/bear/model.json": "It has: model.glb, renders/front view.png, references/a.png.",
        "modeling-3d://models/bear/../bear/model.glb": "'../bear/model.glb' is not a file the app reads",
        "modeling-3d://models/bear/references/kit/notes.txt": "'references/kit/notes.txt' is not a file the app",
        "modeling-3d://models/bear/references/kit/../../../away.png": "is not a file the app reads",
        "modeling-3d://models/bear/checks/report.json": "'checks/report.json' is not a file the app reads",
        "modeling-3d://models/bear/checks/blender-request.json": "'checks/blender-request.json' is not a file",
        "modeling-3d://models/fox/model.glb": "There is no model named 'fox'",
        "modeling-3d://elsewhere": "is not a resource of this server",
    }

    async with Client(f"{app_server.open().url}/mcp") as client:
        for uri, message in refused.items():
            with pytest.raises(MCPError) as failure:
                await client.read_resource(uri)
            assert message in str(failure.value), uri


async def test_the_view_remembers_the_ai_model_picked_for_each_mode_in_the_app_s_workspace_until_it_is_not_offered(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: agent_provider == "claude")
    models = tmp_path / ".modeling-3d"
    models.mkdir()
    # As kept before picks were by mode: one for every mode, which none is held to now.
    old = {"agent_provider": "claude", "model": "claude-sonnet-5-5", "reasoning_effort": "medium"}
    (models / ".app.json").write_text(json.dumps({"intelligence": old, "last_prompt": "A cub"}), encoding="utf-8")
    app_server = open_app(workspace=tmp_path)
    options = lib.list_intelligence_models()
    picked = IntelligenceChoice(agent_provider="claude", model=options.models[-1].id, reasoning_effort="high")
    shaped = picked.model_copy(update={"model": options.models[0].id})

    async with Client(f"{app_server.open().url}/mcp") as client:
        before = await client.call_tool("list_intelligence_models", {})
        chosen = await client.call_tool(
            "choose_intelligence_model", {"mode": "color", "model": picked.model, "reasoning_effort": "high"}
        )
        await client.call_tool(
            "choose_intelligence_model", {"mode": "shape", "model": shaped.model, "reasoning_effort": "high"}
        )
        after = await client.call_tool("list_intelligence_models", {})
        unknown = await client.call_tool(
            "choose_intelligence_model", {"mode": "color", "model": "nope", "reasoning_effort": "high"}
        )
        ultra = await client.call_tool(
            "choose_intelligence_model", {"mode": "color", "model": picked.model, "reasoning_effort": "ultra"}
        )
        monkeypatch.setattr(intelligence_models, "installed", lambda agent_provider: False)
        gone = await client.call_tool("list_intelligence_models", {})

    assert AppIntelligence.model_validate(before.structured_content) == AppIntelligence(
        **options.model_dump(), chosen={}
    )
    assert AppIntelligence.model_validate(chosen.structured_content).chosen == {"color": picked}
    assert AppIntelligence.model_validate(after.structured_content).chosen == {"color": picked, "shape": shaped}
    state = AppState.model_validate_json((models / ".app-state" / "app.json").read_text(encoding="utf-8"))
    assert (state.last_intelligence, state.last_prompt) == ({"color": picked, "shape": shaped}, "A cub")
    assert not (models / ".app.json").exists()
    assert unknown.structured_content == {"reason": "no-such-intelligence-model", "model": None}
    assert ", ".join(model.id for model in options.models) in text_of(unknown)
    assert ultra.structured_content == {"reason": "bad-reasoning-effort", "model": None}
    assert ", ".join(PROVIDER_REASONING_EFFORTS["claude"]) in text_of(ultra)
    assert AppIntelligence.model_validate(gone.structured_content).chosen == {}


async def test_the_view_keeps_the_person_s_settings_in_their_config_directory_for_every_workspace(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, config_directory: Path
) -> None:
    toys = open_app(workspace=tmp_path / "toys")
    tools = open_app(workspace=tmp_path / "tools")
    settings = AppSettings(
        theme="dark",
        dimensions=True,
        wide=AppLayout(activity=PaneLayout(size=420), models=PaneLayout(open=False)),
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
    assert not (tmp_path / "toys" / ".modeling-3d" / "app-settings.json").exists()


async def test_the_steps_opened_in_a_model_s_activity_are_kept_for_the_app_s_workspace_and_forget_deleted_models(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, config_directory: Path
) -> None:
    model_in(tmp_path / "toys", "bear")
    model_in(tmp_path / "toys", "fox")
    toys = open_app(workspace=tmp_path / "toys")
    tools = open_app(workspace=tmp_path / "tools")

    async with Client(f"{toys.open().url}/mcp") as client:
        before = await client.call_tool("read_activity_steps", {})
        await client.call_tool("save_activity_step", {"model_id": "id-bear", "group": "run:1", "open": True})
        await client.call_tool("save_activity_step", {"model_id": "id-bear", "group": "run:3", "open": False})
        await client.call_tool("save_activity_step", {"model_id": "id-fox", "group": "run:1", "open": True})
        both = await client.call_tool("read_activity_steps", {})
        await client.call_tool("delete_3d_model", {"name": "fox"})
        after = await client.call_tool("save_activity_step", {"model_id": "id-bear", "group": "run:1", "open": False})
    async with Client(f"{tools.open().url}/mcp") as client:
        elsewhere = await client.call_tool("read_activity_steps", {})

    assert AppSteps.model_validate(before.structured_content) == AppSteps()
    assert AppSteps.model_validate(both.structured_content) == AppSteps(
        steps={"id-bear": {"run:1": True, "run:3": False}, "id-fox": {"run:1": True}}
    )
    assert AppSteps.model_validate(after.structured_content) == AppSteps(
        steps={"id-bear": {"run:1": False, "run:3": False}}
    )
    assert AppSteps.model_validate(elsewhere.structured_content) == AppSteps()
    kept = tmp_path / "toys" / ".modeling-3d" / ".app-state" / "steps.json"
    assert AppSteps.model_validate_json(kept.read_text(encoding="utf-8")) == AppSteps.model_validate(
        after.structured_content
    )
    assert not any(config_directory.rglob("*steps*"))


async def test_settings_that_are_not_valid_are_refused_naming_the_field_and_kept_ones_read_as_far_as_they_can(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, config_directory: Path
) -> None:
    app_server = open_app(workspace=tmp_path)
    kept = config_directory / "modeling-3d" / "app-settings.json"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text("{not json", encoding="utf-8")

    async with Client(f"{app_server.open().url}/mcp") as client:
        unreadable = await client.call_tool("read_app_settings", {})
        bad = await client.call_tool("save_app_settings", {"settings": {"theme": "sepia"}})
        nested = await client.call_tool("save_app_settings", {"settings": {"wide": {"models": {"size": -1}}}})
        untouched = kept.read_text(encoding="utf-8")
        # What an earlier version kept, which has a setting this one no longer has.
        kept.write_text('{"theme": "dark", "activity_detail": "every-step"}', encoding="utf-8")
        earlier = await client.call_tool("read_app_settings", {})

    assert AppSettings.model_validate(unreadable.structured_content) == AppSettings()
    assert bad.is_error
    assert bad.structured_content == {"reason": "bad-settings", "model": None}
    assert "The app setting theme is not valid" in text_of(bad)
    assert "The app setting wide.models.size is not valid" in text_of(nested)
    assert untouched == "{not json"
    assert AppSettings.model_validate(earlier.structured_content) == AppSettings(theme="dark")


async def test_files_chosen_in_the_file_dialog_are_staged_as_uploads_a_request_takes(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, file_dialog: FileDialog, uploads_directory: Path
) -> None:
    pictures = tmp_path / "pictures"
    pictures.mkdir()
    (pictures / "bear.png").write_bytes(b"png-bytes")
    (pictures / "notes.txt").write_text("brown fur", encoding="utf-8")
    file_dialog.files = [pictures / "bear.png", pictures / "notes.txt"]
    app_server = open_app(workspace=tmp_path / "project")

    async with Client(f"{app_server.open().url}/mcp") as client:
        result = await client.call_tool("choose_reference_files", {"directory": str(pictures)})
        file_dialog.files = []
        cancelled = await client.call_tool("choose_reference_files", {"directory": str(pictures)})

    assert not result.is_error, text_of(result)
    bear, notes = result.structured_content["files"]
    assert (bear["name"], bear["path"], bear["kind"], bear["size"]) == (
        "bear.png",
        str((pictures / "bear.png").resolve()),
        "file",
        len(b"png-bytes"),
    )
    assert bear["preview"] == f"data:image/png;base64,{base64.b64encode(b'png-bytes').decode('ascii')}"
    assert notes["preview"] is None
    assert (uploads_directory / notes["upload"] / "notes.txt").read_text(encoding="utf-8") == "brown fur"
    assert sorted(path.name for path in uploads_directory.iterdir()) == sorted([bear["upload"], notes["upload"]])
    assert file_dialog.shown == [pictures, pictures]
    assert cancelled.structured_content == {"files": []}


async def test_files_and_folders_named_by_path_are_staged_as_uploads(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, uploads_directory: Path
) -> None:
    kit = tmp_path / "kit"
    (kit / ".git").mkdir(parents=True)
    (kit / ".git" / "HEAD").write_text("main", encoding="utf-8")
    (kit / "wheel.glb").write_bytes(b"glTF")
    (kit / "parts").mkdir()
    (kit / "parts" / "axle.obj").write_text("v 0 0 0", encoding="utf-8")
    app_server = open_app(workspace=tmp_path / "project")

    async with Client(f"{app_server.open().url}/mcp") as client:
        result = await client.call_tool("stage_reference_files", {"paths": [str(kit), str(kit / "wheel.glb")]})
        missing = await client.call_tool("stage_reference_files", {"paths": [str(tmp_path / "gone.png")]})

    assert not result.is_error, text_of(result)
    folder, wheel = result.structured_content["files"]
    assert (folder["kind"], folder["files"], folder["size"]) == ("folder", 2, len(b"glTF") + len("v 0 0 0"))
    assert not (uploads_directory / folder["upload"] / "kit" / ".git").exists()
    assert (uploads_directory / folder["upload"] / "kit" / "parts" / "axle.obj").is_file()
    assert (wheel["kind"], wheel["preview"]) == ("file", None)
    assert missing.structured_content == {"reason": "missing-reference", "model": None}
    assert "is not a file or a folder on this machine" in text_of(missing)


async def test_a_folder_chosen_in_the_folder_dialog_comes_back_by_path(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, file_dialog: FileDialog
) -> None:
    file_dialog.folder = tmp_path / "pictures"
    app_server = open_app(workspace=tmp_path / "project")

    async with Client(f"{app_server.open().url}/mcp") as client:
        chosen = await client.call_tool("choose_reference_folder", {})
        file_dialog.folder = None
        cancelled = await client.call_tool("choose_reference_folder", {})

    assert chosen.structured_content == {"path": str(tmp_path / "pictures")}
    assert cancelled.structured_content == {"path": None}
    assert file_dialog.shown == [Path.home(), Path.home()]


def test_the_file_dialog_names_a_folder_that_is_not_there(tmp_path: Path) -> None:
    with pytest.raises(Modeling3dError, match="is not a folder on this machine"):
        choose_files(tmp_path / "gone", "Choose references", mcp_server.DROP_INSTEAD)


async def test_the_person_s_pins_are_kept_for_the_app_s_workspace_alone_and_refused_when_not_valid(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, config_directory: Path
) -> None:
    pins = {
        "references": [{"path": str(tmp_path / "bear.png"), "kind": "file"}],
        "folders": [{"path": str(tmp_path / "pictures"), "shows": "dialog"}],
        "prompts": [{"text": "A low poly fox", "mode": "shape"}],
    }
    here = open_app(workspace=tmp_path / "here")
    elsewhere = open_app(workspace=tmp_path / "elsewhere")

    async with Client(f"{here.open().url}/mcp") as client:
        before = AppLibrary.model_validate((await client.call_tool("read_app_library", {})).structured_content)
        saved = await client.call_tool("save_app_pins", {"pins": pins})
        bad = await client.call_tool("save_app_pins", {"pins": {"prompts": [{"text": "", "mode": "shape"}]}})
    async with Client(f"{elsewhere.open().url}/mcp") as client:
        other = AppLibrary.model_validate((await client.call_tool("read_app_library", {})).structured_content)
    async with Client(f"{open_app(workspace=tmp_path / 'here').open().url}/mcp") as client:
        again = AppLibrary.model_validate((await client.call_tool("read_app_library", {})).structured_content)

    assert before == AppLibrary(used=[], last_prompt=None, default_prompts=constants.UNASKED)
    assert AppPins.model_validate(saved.structured_content) == AppPins.model_validate(pins)
    assert other == AppLibrary(used=[], last_prompt=None, default_prompts=constants.UNASKED)
    assert AppPins.model_validate(again.model_dump(include={"references", "folders", "prompts"})) == (
        AppPins.model_validate(pins)
    )
    kept = AppState.model_validate_json(
        (tmp_path / "here" / ".modeling-3d" / ".app-state" / "app.json").read_text(encoding="utf-8")
    )
    assert kept.pins == AppPins.model_validate(pins)
    assert not any(config_directory.rglob("*pins*"))
    assert bad.structured_content == {"reason": "bad-pins", "model": None}
    assert "The app pin prompts.0.text is not valid" in text_of(bad)


async def test_what_was_sent_or_given_to_a_model_is_used_before_newest_first_and_at_most_50(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, file_dialog: FileDialog, monkeypatch: pytest.MonkeyPatch
) -> None:
    bear = model_in(tmp_path / "project", "bear", references=["references/bear.png", "references/gone.png"])
    (bear / "references").mkdir()
    (bear / "references" / "bear.png").write_bytes(b"png-bytes")
    cub = model_in(tmp_path / "project", "cub", references=["references/bear.png"])
    (cub / "references").mkdir()
    (cub / "references" / "bear.png").write_bytes(b"png-bytes")
    pictures = tmp_path / "pictures"
    pictures.mkdir()
    for index in range(60):
        (pictures / f"{index:02}.png").write_bytes(b"png-bytes")
    file_dialog.files = [pictures / "00.png"]

    def steer(name: str, message: str, workspace: Path, origin: str, references: list[Path]) -> None:
        if message == "Refused.":
            raise Modeling3dError(f"No run is working on {name}.")

    monkeypatch.setattr(create, "steer_3d_model", steer)
    app_server = open_app(workspace=tmp_path / "project")

    async def library() -> AppLibrary:
        return AppLibrary.model_validate((await client.call_tool("read_app_library", {})).structured_content)

    async def stage(paths: list[Path]) -> list[str]:
        staged = await client.call_tool("stage_reference_files", {"paths": [str(path) for path in paths]})
        return [file["upload"] for file in staged.structured_content["files"]]

    async with Client(f"{app_server.open().url}/mcp") as client:
        given = await library()
        chosen = await client.call_tool("choose_reference_files", {})
        await client.call_tool("choose_reference_folder", {})
        picked = [file["upload"] for file in chosen.structured_content["files"]] + await stage([pictures / "01.png"])
        unsent = await library()
        await client.call_tool("steer_3d_model", {"name": "bear", "message": "Refused.", "uploads": picked})
        refused = await library()
        await client.call_tool("steer_3d_model", {"name": "bear", "message": "Smaller.", "uploads": picked})
        sent = await library()
        everything = await stage(sorted(pictures.iterdir()))
        await client.call_tool("steer_3d_model", {"name": "bear", "message": "Smaller.", "uploads": everything})
        capped = await library()

    assert [entry.name for entry in given.used] == ["bear.png"]
    assert file_dialog.shown == [Path.home(), pictures]
    assert unsent.used == refused.used == given.used
    assert [entry.path for entry in sent.used] == [pictures / "00.png", pictures / "01.png", given.used[0].path]
    assert len(capped.used) == 50
    assert capped.used[0].path == pictures / "00.png"


async def test_pinned_folders_list_what_is_in_them_and_only_the_library_s_images_can_be_read(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    pictures = tmp_path / "pictures"
    (pictures / "sketches").mkdir(parents=True)
    (pictures / ".cache").mkdir()
    (pictures / "Fox.png").write_bytes(b"fox-bytes")
    (pictures / "bear.png").write_bytes(b"bear-bytes")
    (tmp_path / "away.png").write_bytes(b"away-bytes")
    bear = model_in(tmp_path / "project", "bear", references=["references/bear.png"])
    (bear / "references").mkdir()
    (bear / "references" / "bear.png").write_bytes(b"given-bytes")
    pins = {"folders": [{"path": str(pictures), "shows": "files"}, {"path": str(tmp_path), "shows": "dialog"}]}
    app_server = open_app(workspace=tmp_path / "project")

    def uri(path: Path) -> str:
        return f"modeling-3d://references/{quote(str(path), safe='')}"

    async with Client(f"{app_server.open().url}/mcp") as client:
        await client.call_tool("save_app_pins", {"pins": pins})
        listed = await client.call_tool("list_reference_folder", {"path": str(pictures)})
        unlisted = await client.call_tool("list_reference_folder", {"path": str(tmp_path)})
        fox = (await client.read_resource(uri(pictures / "Fox.png"))).contents[0]
        given = (await client.read_resource(uri(bear / "references" / "bear.png"))).contents[0]
        with pytest.raises(MCPError) as refused:
            await client.read_resource(uri(tmp_path / "away.png"))

    entries = [(entry["name"], entry["kind"]) for entry in listed.structured_content["entries"]]
    assert entries == [("sketches", "folder"), ("bear.png", "file"), ("Fox.png", "file")]
    assert "is not a folder pinned to show its files" in text_of(unlisted)
    assert isinstance(fox, BlobResourceContents)
    assert base64.b64decode(fox.blob) == b"fox-bytes"
    assert isinstance(given, BlobResourceContents)
    assert base64.b64decode(given.blob) == b"given-bytes"
    assert "is not an image the app offers to work from" in str(refused.value)


async def test_a_dropped_file_pinned_is_kept_in_the_app_s_workspace_until_it_is_unpinned(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    app_server = open_app(workspace=tmp_path / "project")

    async with Client(f"{app_server.open().url}/mcp") as client:
        pasted = await send(client, "pasted.png", b"pasted-bytes")
        kept = Path((await client.call_tool("keep_upload", {"upload": pasted})).structured_content["path"])
        reference = {"path": str(kept), "kind": "file"}
        await client.call_tool("save_app_pins", {"pins": {"references": [reference]}})
        pinned = kept.read_bytes()
        await client.call_tool("save_app_pins", {"pins": {}})

    assert kept.is_relative_to(tmp_path / "project" / ".modeling-3d" / ".app-state" / "pins")
    assert pinned == b"pasted-bytes"
    assert not kept.parent.exists()


async def test_the_view_renames_and_deletes_models_but_not_one_the_app_is_checking(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_in(tmp_path, "bear", references=[])
    model_in(tmp_path, "fox", references=[])
    released = threading.Event()

    def held_check(name: str, workspace: Path) -> ModelCheck:
        released.wait(TIMEOUT_SECONDS)
        raise Modeling3dError(f"The check of {name} was stopped.")

    monkeypatch.setattr(check, "check_3d_model", held_check)
    monkeypatch.setattr(mcp_server, "CHECK_WAIT_SECONDS", 0)
    app_server = open_app(workspace=tmp_path)

    async with Client(f"{app_server.open().url}/mcp") as client:
        checking = await client.call_tool("check_3d_model", {"name": "bear"})
        held_rename = await client.call_tool("rename_3d_model", {"name": "bear", "new_name": "grizzly"})
        held_delete = await client.call_tool("delete_3d_model", {"name": "bear"})
        released.set()
        monkeypatch.setattr(mcp_server, "CHECK_WAIT_SECONDS", TIMEOUT_SECONDS)
        stopped = await client.call_tool("check_3d_model", {"name": "bear"})
        renamed = await client.call_tool("rename_3d_model", {"name": "bear", "new_name": "grizzly"})
        taken = await client.call_tool("rename_3d_model", {"name": "grizzly", "new_name": "Fox"})
        deleted = await client.call_tool("delete_3d_model", {"name": "fox"})
        listing = ModelListing.model_validate((await client.call_tool("list_3d_models", {})).structured_content)

    assert checking.structured_content == {"checking": True}
    for held in (held_rename, held_delete):
        assert held.structured_content == {"reason": "model-busy", "model": "bear"}
        assert "being checked in the app" in text_of(held)
    assert stopped.is_error
    assert ModelSummary.model_validate(renamed.structured_content).directory == tmp_path / ".modeling-3d" / "grizzly"
    assert taken.structured_content == {"reason": "name-in-use", "model": "fox"}
    assert (deleted.is_error, text_of(deleted)) == (False, "Deleted fox.")
    assert [model.name for model in listing.models] == ["grizzly"]


def test_renaming_or_deleting_a_model_moves_or_drops_the_person_s_pins_of_it_and_what_was_used_from_it(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    root = workspace / ".modeling-3d"
    bear = model_in(workspace, "bear", references=[])
    model_in(workspace, "fox", references=[])
    pictures = tmp_path / "pictures"
    pins = AppPins(
        references=[
            PinnedReference(path=bear, kind="model"),
            PinnedReference(path=bear / "renders" / "front view.png", kind="file"),
            PinnedReference(path=root / "fox", kind="model"),
            PinnedReference(path=root / "bearish", kind="folder"),
        ],
        folders=[PinnedFolder(path=bear / "renders", shows="files"), PinnedFolder(path=pictures, shows="dialog")],
        prompts=[PinnedPrompt(text="A bear", mode="shape")],
    )
    state = AppState(
        used=[bear / "renders" / "front view.png", pictures / "cub.png"], last_folder=bear / "renders", pins=pins
    )
    (root / ".app-state").mkdir()
    (root / ".app-state" / "app.json").write_text(state.model_dump_json(), encoding="utf-8")

    lib.rename_3d_model("bear", "grizzly", workspace)
    renamed_state = AppState.model_validate_json((root / ".app-state" / "app.json").read_text(encoding="utf-8"))
    renamed = renamed_state.pins
    lib.delete_3d_model("grizzly", workspace)
    deleted_state = AppState.model_validate_json((root / ".app-state" / "app.json").read_text(encoding="utf-8"))
    deleted = deleted_state.pins

    grizzly = root / "grizzly"
    assert [reference.path for reference in renamed.references] == [
        grizzly,
        grizzly / "renders" / "front view.png",
        root / "fox",
        root / "bearish",
    ]
    assert [folder.path for folder in renamed.folders] == [grizzly / "renders", pictures]
    assert renamed.prompts == pins.prompts
    assert renamed_state.model_dump(exclude={"pins"}) == AppState(
        used=[grizzly / "renders" / "front view.png", pictures / "cub.png"], last_folder=grizzly / "renders"
    ).model_dump(exclude={"pins"})
    assert [reference.path for reference in deleted.references] == [root / "fox", root / "bearish"]
    assert [folder.path for folder in deleted.folders] == [pictures]
    assert deleted_state.model_dump(exclude={"pins"}) == AppState(
        used=[pictures / "cub.png"], last_folder=None
    ).model_dump(exclude={"pins"})


async def test_the_view_names_and_opens_the_folders_where_the_app_keeps_things(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, config_directory: Path, opened_folders: list[Path]
) -> None:
    bear = model_in(tmp_path / "project", "bear")
    app_server = open_app(workspace=tmp_path / "project")

    async with Client(f"{app_server.open().url}/mcp") as client:
        folders = await client.call_tool("read_app_folders", {})
        for folder in ("settings", "workspace", "models"):
            result = await client.call_tool("open_app_folder", {"folder": folder})
            assert not result.is_error, text_of(result)
        named = await client.call_tool("open_app_folder", {"folder": "model", "name": "bear"})
        missing = await client.call_tool("open_app_folder", {"folder": "model", "name": "fox"})
        unnamed = await client.call_tool("open_app_folder", {"folder": "model"})

    workspace = (tmp_path / "project").resolve()
    assert AppFolders.model_validate(folders.structured_content) == AppFolders(
        settings=config_directory / "modeling-3d", workspace=workspace, models=workspace / ".modeling-3d"
    )
    assert not named.is_error, text_of(named)
    assert opened_folders == [config_directory / "modeling-3d", workspace, workspace / ".modeling-3d", bear.resolve()]
    assert missing.structured_content == {"reason": "no-such-model", "model": "fox"}
    assert "The models there: bear." in text_of(missing)
    assert "Pass `settings`, `workspace`, `models`, or `model` with the model's `name`." in text_of(unnamed)


async def test_with_no_workspace_given_the_app_opens_on_the_last_one_opened_that_is_still_a_folder_or_on_none(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    unopened = tmp_path / "unopened"
    unopened.mkdir()
    before = lib.app_server().workspace
    first = open_app(workspace=tmp_path / "first").workspace
    second = open_app(workspace=tmp_path / "second").workspace
    lib.app_server(unopened)
    assert first is not None
    assert second is not None
    last = lib.app_server().workspace
    second.rmdir()
    earlier = lib.app_server().workspace
    first.rmdir()
    app_server = open_app()

    async with Client(f"{app_server.open().url}/mcp") as client:
        workspaces = await client.call_tool("read_app_workspaces", {})
        listed = await client.call_tool("list_3d_models", {})
        settings = await client.call_tool("read_app_settings", {})
        folders = await client.call_tool("read_app_folders", {})
        settings_folder = await client.call_tool("open_app_folder", {"folder": "settings"})
        models_folder = await client.call_tool("open_app_folder", {"folder": "models"})
        opened = await client.call_tool("open_app", {})

    assert (before, last, earlier, app_server.workspace) == (None, second, first, None)
    assert AppWorkspaces.model_validate(workspaces.structured_content) == AppWorkspaces(
        current=None,
        recent=[RecentWorkspace(path=second, missing=True), RecentWorkspace(path=first, missing=True)],
        new_in=second.parent,
    )
    assert listed.structured_content == {"reason": "no-workspace", "model": None}
    assert "The app shows no workspace yet." in text_of(listed)
    assert not settings.is_error, text_of(settings)
    assert (AppFolders.model_validate(folders.structured_content).workspace, settings_folder.is_error) == (None, False)
    assert models_folder.structured_content == {"reason": "no-workspace", "model": None}
    assert "It shows no workspace yet" in text_of(opened)


async def test_the_view_switches_workspaces_showing_each_one_s_models_last_viewed_model_and_pins(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    garden, harbor, empty = tmp_path / "garden", tmp_path / "harbor", tmp_path / "empty"
    model_in(garden, "bear")
    model_in(harbor, "boat")
    model_in(harbor, "gull")
    empty.mkdir()
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    app_server = open_app(workspace=garden)

    async with Client(f"{app_server.open().url}/mcp") as client:
        await client.call_tool("view_3d_model", {"name": "bear"})
        await client.call_tool("save_app_pins", {"pins": {"prompts": [{"text": "A low poly fox", "mode": "shape"}]}})
        switched = await client.call_tool("open_app_workspace", {"path": str(harbor / ".modeling-3d")})
        await client.call_tool("view_3d_model", {"name": "gull"})
        there = ModelListing.model_validate((await client.call_tool("list_3d_models", {})).structured_content)
        there_library = AppLibrary.model_validate((await client.call_tool("read_app_library", {})).structured_content)
        refused = await client.call_tool("open_app_workspace", {"path": str(tmp_path / "notes.txt")})
        kept = ModelListing.model_validate((await client.call_tool("list_3d_models", {})).structured_content)
        await client.call_tool("open_app_workspace", {"path": str(empty)})
        await client.call_tool("open_app_workspace", {"path": str(garden)})
        back = ModelListing.model_validate((await client.call_tool("list_3d_models", {})).structured_content)
        back_library = AppLibrary.model_validate((await client.call_tool("read_app_library", {})).structured_content)

    assert AppWorkspaces.model_validate(switched.structured_content).current == harbor.resolve()
    assert (sorted(model.name for model in there.models), there.last_viewed) == (["boat", "gull"], "gull")
    assert there_library.prompts == []
    assert refused.structured_content == {"reason": "no-such-workspace", "model": None}
    assert kept.workspace == harbor.resolve()
    assert ([model.name for model in back.models], back.last_viewed) == (["bear"], "bear")
    assert [prompt.text for prompt in back_library.prompts] == ["A low poly fox"]
    assert list(empty.iterdir()) == []


async def test_the_workspaces_opened_are_offered_newest_first_each_once_at_most_20_and_forgetting_one_leaves_it(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    projects = [tmp_path / f"project-{index}" for index in range(22)]
    for project in projects:
        project.mkdir()
    app_server = open_app(workspace=projects[0])

    async with Client(f"{app_server.open().url}/mcp") as client:
        for project in projects[1:]:
            await client.call_tool("open_app_workspace", {"path": str(project)})
        # The same folders, spelled another way.
        await client.call_tool("open_app_workspace", {"path": f"{projects[5]}{os.sep}"})
        again = await client.call_tool("open_app_workspace", {"path": str(projects[9] / ".." / projects[9].name)})
        forgotten = await client.call_tool("forget_app_workspace", {"path": str(projects[20])})

    newest = [projects[9], projects[5], *(projects[index] for index in range(21, 1, -1) if index not in (5, 9))]
    offered = AppWorkspaces.model_validate(again.structured_content)
    assert offered.current == projects[9].resolve()
    assert [workspace.path for workspace in offered.recent] == [project.resolve() for project in newest]
    assert not any(workspace.missing for workspace in offered.recent)
    assert [workspace.path for workspace in AppWorkspaces.model_validate(forgotten.structured_content).recent] == [
        project.resolve() for project in newest if project != projects[20]
    ]
    assert projects[20].is_dir()


async def test_a_workspace_chosen_in_the_folder_dialog_comes_back_by_path_and_a_dialog_that_cannot_show_names_the_command(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, file_dialog: FileDialog, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_dialog.folder = tmp_path / "harbor"
    app_server = open_app(workspace=tmp_path / "garden")

    async with Client(f"{app_server.open().url}/mcp") as client:
        chosen = await client.call_tool("choose_app_workspace", {})
        file_dialog.folder = None
        cancelled = await client.call_tool("choose_app_workspace", {})
    monkeypatch.setattr(folders, "choose_folder", choose_folder)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "no-python"))
    async with Client(f"{open_app(workspace=tmp_path / 'garden').open().url}/mcp") as client:
        unshown = await client.call_tool("choose_app_workspace", {})

    assert chosen.structured_content == {"path": str((tmp_path / "harbor").resolve())}
    assert cancelled.structured_content == {"path": None}
    assert file_dialog.shown == [tmp_path.resolve(), tmp_path.resolve()]
    assert "Could not show a file dialog" in text_of(unshown)
    assert "`modeling-3d app --workspace <folder>`" in text_of(unshown)


async def test_a_new_workspace_is_a_folder_made_where_asked_and_opened_and_one_that_cannot_be_is_refused(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, file_dialog: FileDialog
) -> None:
    projects = tmp_path / "projects"
    app_server = open_app(workspace=projects / "garden")
    garden = app_server.workspace
    (projects / "notes.txt").write_text("", encoding="utf-8")
    file_dialog.folder = tmp_path / "elsewhere"

    async with Client(f"{app_server.open().url}/mcp") as client:
        before = AppWorkspaces.model_validate((await client.call_tool("read_app_workspaces", {})).structured_content)
        chosen = await client.call_tool("choose_app_workspace", {"parent": True})
        made = await client.call_tool("create_app_workspace", {"name": " harbor ", "parent": str(before.new_in)})
        refused = [
            await client.call_tool("create_app_workspace", {"name": name, "parent": str(before.new_in)})
            for name in ("garden", "notes.txt", "a/b", "..", "")
        ]
        nowhere = await client.call_tool("create_app_workspace", {"name": "dock", "parent": str(tmp_path / "gone")})

    harbor = (projects / "harbor").resolve()
    workspaces = AppWorkspaces.model_validate(made.structured_content)
    assert before.new_in == projects.resolve()
    assert chosen.structured_content == {"path": str((tmp_path / "elsewhere").resolve())}
    assert file_dialog.shown == [projects.resolve()]
    assert (workspaces.current, app_server.workspace) == (harbor, harbor)
    assert [workspace.path for workspace in workspaces.recent] == [harbor, garden]
    assert list(harbor.iterdir()) == []
    assert "already exists. Open it with Open Workspace, or choose another name." in text_of(refused[0])
    assert "already exists" in text_of(refused[1])
    assert all("is not a folder's name" in text_of(result) for result in refused[2:])
    assert "is not a folder, so no workspace can be made in it" in text_of(nowhere)
    assert sorted(path.name for path in projects.iterdir()) == ["garden", "harbor", "notes.txt"]
    assert not (tmp_path / "gone").exists()


async def test_every_app_offers_the_workspaces_the_others_opened_too(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    garden, harbor, empty = tmp_path / "garden", tmp_path / "harbor", tmp_path / "empty"
    empty.mkdir()
    url = open_app(workspace=garden).open().url
    open_app(workspace=harbor)

    async with Client(f"{url}/mcp") as client:
        switched = await client.call_tool("open_app_workspace", {"path": str(empty)})

    offered = [workspace.path for workspace in AppWorkspaces.model_validate(switched.structured_content).recent]
    assert offered == [empty.resolve(), harbor.resolve(), garden.resolve()]
    assert lib.app_server().workspace == empty.resolve()


async def test_a_call_for_a_workspace_the_app_no_longer_shows_is_refused_and_changes_nothing(
    open_app: Callable[..., lib.AppServer], tmp_path: Path
) -> None:
    garden, harbor = tmp_path / "garden", tmp_path / "harbor"
    bears = [model_in(garden, "bear"), model_in(harbor, "bear")]
    app_server = open_app(workspace=garden)
    sent = str(app_server.workspace)
    pins = {"prompts": [{"text": "A low poly fox", "mode": "shape"}]}

    async with Client(f"{app_server.open().url}/mcp") as client:
        before = await client.call_tool("list_3d_models", {"workspace": sent})
        await client.call_tool("open_app_workspace", {"path": str(harbor)})
        polled = await client.call_tool("list_3d_models", {"workspace": sent})
        deleted = await client.call_tool("delete_3d_model", {"name": "bear", "workspace": sent})
        pinned = await client.call_tool("save_app_pins", {"pins": pins, "workspace": sent})
        settings = await client.call_tool("read_app_settings", {"workspace": sent})
        here = await client.call_tool("list_3d_models", {"workspace": str(harbor.resolve())})

    assert not before.is_error, text_of(before)
    for refused in (polled, deleted, pinned):
        assert refused.structured_content == {"reason": "workspace-changed", "model": None}
        assert f"The app now shows {harbor.resolve()}, so this call, sent for {sent}, was not made." in text_of(refused)
    assert all(bear.is_dir() for bear in bears)
    assert not (harbor / ".modeling-3d" / ".app-state").exists()
    assert not settings.is_error, text_of(settings)
    assert [model.name for model in ModelListing.model_validate(here.structured_content).models] == ["bear"]


async def test_a_workspace_removed_while_the_app_shows_it_is_refused_and_not_made_again(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, opened_folders: list[Path]
) -> None:
    garden = tmp_path / "garden"
    app_server = open_app(workspace=garden)
    garden.rmdir()

    async with Client(f"{app_server.open().url}/mcp") as client:
        listed = await client.call_tool("list_3d_models", {})
        pinned = await client.call_tool("save_app_pins", {"pins": {"prompts": []}})
        opened = await client.call_tool("open_app_folder", {"folder": "workspace"})
        workspaces = AppWorkspaces.model_validate(
            (await client.call_tool("read_app_workspaces", {})).structured_content
        )
        forgotten = await client.call_tool("forget_app_workspace", {"path": str(garden)})

    assert AppWorkspaces.model_validate(forgotten.structured_content) == AppWorkspaces(
        current=None, recent=[], new_in=garden.resolve().parent
    )
    for refused in (listed, pinned, opened):
        assert refused.structured_content == {"reason": "no-such-workspace", "model": None}
    assert f"The workspace {garden.resolve()} is no longer a folder." in text_of(pinned)
    assert not garden.exists()
    assert opened_folders == []
    assert workspaces.current is None
    assert [workspace.missing for workspace in workspaces.recent] == [True]


@pytest.mark.detached
async def test_a_request_sent_just_before_a_switch_creates_its_model_and_keeps_its_prompt_where_it_was_sent_for(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    garden, harbor = tmp_path / "garden", tmp_path / "harbor"
    harbor.mkdir()
    arrived, switched = threading.Event(), threading.Event()
    start = create.create_3d_model

    async def after_the_switch(**arguments: Any) -> Any:
        arrived.set()
        await asyncio.to_thread(switched.wait, RUN_TIMEOUT_SECONDS)
        return await start(**arguments)

    monkeypatch.setattr(create, "create_3d_model", after_the_switch)
    monkeypatch.setattr(create, "BACKGROUND_COMMAND", detached_agent.command("builds"))
    app_server = open_app(workspace=garden)
    sent = str(app_server.workspace)

    async with Client(f"{app_server.open().url}/mcp") as client, Client(f"{app_server.open().url}/mcp") as other:
        request = asyncio.create_task(
            client.call_tool("create_3d_model", {"prompt": "A cub", "name": "cub", "workspace": sent})
        )
        await asyncio.to_thread(arrived.wait, RUN_TIMEOUT_SECONDS)
        await other.call_tool("open_app_workspace", {"path": str(harbor)})
        switched.set()
        created = await request
        await other.call_tool("open_app_workspace", {"path": sent})
        ended = await activity_until(client, "cub", 1)

    assert (
        ModelSummary.model_validate(created.structured_content).directory == garden.resolve() / ".modeling-3d" / "cub"
    )
    assert not (harbor / ".modeling-3d").exists()
    kept = AppState.model_validate_json(
        (garden / ".modeling-3d" / ".app-state" / "app.json").read_text(encoding="utf-8")
    )
    assert kept.last_prompt == "A cub"
    assert [entry.data["status"] for entry in ended.entries if entry.kind == "ended"] == ["done"]


@pytest.mark.detached
async def test_a_run_goes_on_while_the_app_shows_another_workspace_and_is_there_whole_on_switching_back(
    open_app: Callable[..., lib.AppServer], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    garden, harbor = tmp_path / "garden", tmp_path / "harbor"
    model_in(harbor, "boat")
    monkeypatch.setattr(create, "BACKGROUND_COMMAND", detached_agent.command("waits_for_steering"))
    app_server = open_app(workspace=garden)

    async with Client(f"{app_server.open().url}/mcp") as client:
        await client.call_tool("create_3d_model", {"prompt": "A cub", "name": "cub"})
        await client.call_tool("open_app_workspace", {"path": str(harbor)})
        away = ModelListing.model_validate((await client.call_tool("list_3d_models", {})).structured_content)
        await client.call_tool("open_app_workspace", {"path": str(garden)})
        steered = await client.call_tool("steer_3d_model", {"name": "cub", "message": "Smaller."})
        ended = await activity_until(client, "cub", 1)

    assert [model.name for model in away.models] == ["boat"]
    assert not steered.is_error, text_of(steered)
    kinds = [(entry.kind, entry.text) for entry in ended.entries if entry.kind in ("request", "steered", "ended")]
    assert kinds[:2] == [("request", "A cub"), ("steered", "Smaller.")]
    assert [entry.data["status"] for entry in ended.entries if entry.kind == "ended"] == ["done"]
