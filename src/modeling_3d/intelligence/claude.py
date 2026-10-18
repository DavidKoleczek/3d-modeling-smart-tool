"""Claude Agent SDK implementation of the intelligence interface."""

import asyncio
import base64
from collections.abc import AsyncIterator
import contextlib
import dataclasses
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import time
from typing import Any
import uuid

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    Message,
    ResultMessage,
    SessionKey,
    SessionListSubkeysKey,
    SessionStore,
    SessionStoreEntry,
    SessionStoreListEntry,
    SessionSummaryEntry,
    StreamEvent,
    SystemMessage,
    UserMessage,
    fold_session_summary,
)

from modeling_3d.intelligence.interface import state_directory
from modeling_3d.intelligence.schemas import IMAGE_MEDIA_TYPES, AgentEvent, AgentRequest, AgentResult, Steering
from modeling_3d.schemas import Modeling3dError

AUTHENTICATION_DOCUMENTATION = "https://code.claude.com/docs/en/agent-sdk/quickstart"
READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "Bash"]
WRITE_TOOLS = ["Edit", "Write"]
# How long a stopping run waits for Claude Code to abort its tools before ending the process anyway.
INTERRUPT_SECONDS = 5
# Claude Code sends an image the agent reads back as one base64 JSON line, and a render runs to megabytes, well past
# the SDK's 1 MB default for a line.
MAX_MESSAGE_BYTES = 64 * 1024 * 1024
# How often a tool call the agent is still writing out says how far it has got, from when it has taken that long, so
# a quick call says nothing and a long file keeps showing progress.
COMPOSING_SECONDS = 1.0
# Enough of the arguments written so far to find what the call works on, which comes first.
COMPOSING_HEAD_CHARACTERS = 500


@dataclasses.dataclass
class Composing:
    """A tool call the agent is still writing the arguments of, as far as it has got."""

    id: str
    name: str
    reported: float
    head: str = ""
    characters: int = 0


class ClaudeRun:
    """One agent in its own Claude Code process: its messages as they come, steering, and a hard stop."""

    def __init__(self, request: AgentRequest, client: ClaudeSDKClient) -> None:
        self._request = request
        self._client = client
        self._session_id = request.resume
        self._events: list[AgentEvent] = []
        # Replaced on every append, so a reader waits on the one current when it ran out of events.
        self._appended = asyncio.Event()
        # User messages sent and not yet echoed back by Claude Code. A result ends the run only when there are
        # none, since a steering message that arrives late in a turn starts another one.
        self._unechoed: set[str] = set()
        self._composing: dict[int, Composing] = {}
        self._answered = False
        self._began = asyncio.Event()
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(self._drive())

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def events(self) -> AsyncIterator[AgentEvent]:
        return self._replay()

    async def running(self) -> None:
        """Wait until the prompt is sent, or the run ended trying."""
        await self._began.wait()

    async def steer(self, message: str) -> None:
        await self._began.wait()
        if self._answered or self._task.done():
            raise Modeling3dError(
                "The agent run has ended, so the steering message was not delivered. Start a new run that resumes "
                f"session {self._session_id} with the message as its prompt."
            )
        await self._send(message, [])

    async def cancel(self) -> None:
        self._stopping.set()
        await asyncio.wait([self._task])

    async def result(self) -> AgentResult:
        return await asyncio.shield(self._task)

    async def _drive(self) -> AgentResult:
        # The client keeps a task group open from connect to disconnect, so both happen here, in one task.
        stopping = asyncio.create_task(self._stopping.wait())
        reading: asyncio.Task[AgentResult] | None = None
        try:
            async with asyncio.timeout(self._request.timeout_seconds):
                await self._client.connect()
                await self._send(self._request.prompt, self._request.images)
                self._began.set()
                reading = asyncio.create_task(self._read())
                await asyncio.wait([reading, stopping], return_when=asyncio.FIRST_COMPLETED)
            cancelled = AgentResult(cancelled=True, session_id=self._session_id)
            result = reading.result() if reading.done() else cancelled
        except TimeoutError:
            result = AgentResult(
                error=f"The agent did not finish within {self._request.timeout_seconds} seconds.",
                session_id=self._session_id,
            )
        except Exception as error:  # an SDK or runtime failure is the caller's data, not a crash
            result = AgentResult(error=f"{type(error).__name__}: {error}", session_id=self._session_id)
        finally:
            stopping.cancel()
            if reading is not None:
                reading.cancel()
            self._began.set()
            await self._close(interrupt=not self._answered)
        self._emit("terminal", result.model_dump(mode="json"))
        return result

    async def _read(self) -> AgentResult:
        async for message in self._client.receive_messages():
            self._note(message)
            if isinstance(message, UserMessage) and message.uuid is not None:
                self._unechoed.discard(message.uuid)
            if isinstance(message, ResultMessage) and not self._unechoed:
                self._answered = True
                return outcome(message)
        raise RuntimeError("Claude Code ended the conversation without a result.")

    async def _send(self, text: str, images: list[Path]) -> None:
        # Claude Code echoes a user message under the uuid it was sent with, which is how the run sees it taken.
        identifier = str(uuid.uuid4())
        content: str | list[dict[str, Any]] = text
        if images:
            content = [{"type": "text", "text": text}, *(image_block(path) for path in images)]
        self._unechoed.add(identifier)
        message = {
            "type": "user",
            "uuid": identifier,
            "message": {"role": "user", "content": content},
            "parent_tool_use_id": None,
        }
        await self._client.query(_one(message))

    async def _close(self, interrupt: bool) -> None:
        """End the Claude Code process; an unfinished run first has it abort its tools, so none outlive it."""
        if interrupt:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._client.interrupt(), INTERRUPT_SECONDS)
        with contextlib.suppress(Exception):
            await self._client.disconnect()

    def _note(self, message: Message) -> None:
        session_id = (
            message.data.get("session_id")
            if isinstance(message, SystemMessage)
            else getattr(message, "session_id", None)
        )
        if isinstance(session_id, str):
            self._session_id = session_id
        if isinstance(message, StreamEvent):
            self._stream(message)
        else:
            self._emit(type(message).__name__, as_data(message))

    def _stream(self, message: StreamEvent) -> None:
        """Keep of the stream only `composing`, how far each tool call the agent is writing out has got.

        The rest comes whole in the messages that follow, so it is not kept twice.
        """
        if message.parent_tool_use_id is not None:
            return
        event = message.event
        index = event.get("index")
        block = event.get("content_block") or {}
        delta = event.get("delta") or {}
        if not isinstance(index, int):
            return
        if event.get("type") == "content_block_start" and block.get("type") == "tool_use":
            self._composing[index] = Composing(
                id=str(block.get("id", "")), name=str(block.get("name", "")), reported=time.monotonic()
            )
        elif event.get("type") == "content_block_stop":
            self._composing.pop(index, None)
        elif (composing := self._composing.get(index)) is not None and delta.get("type") == "input_json_delta":
            written = str(delta.get("partial_json", ""))
            composing.head = (composing.head + written)[:COMPOSING_HEAD_CHARACTERS]
            composing.characters += len(written)
            now = time.monotonic()
            if now - composing.reported >= COMPOSING_SECONDS:
                composing.reported = now
                self._emit(
                    "composing",
                    {
                        "id": composing.id,
                        "name": composing.name,
                        "head": composing.head,
                        "characters": composing.characters,
                    },
                )

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        self._events.append(AgentEvent(type=kind, data=data))
        self._appended.set()
        self._appended = asyncio.Event()

    async def _replay(self) -> AsyncIterator[AgentEvent]:
        index = 0
        while True:
            appended = self._appended
            while index < len(self._events):
                event = self._events[index]
                index += 1
                yield event
                if event.type == "terminal":
                    return
            if self._task.done():
                return
            await appended.wait()


class FolderSessionStore(SessionStore):
    """A copy of every transcript of a session in one directory, from which the session can also be resumed."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    async def append(self, key: SessionKey, entries: list[SessionStoreEntry]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as transcript:
            transcript.writelines(json.dumps(entry) + "\n" for entry in entries)

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    async def list_sessions(self, project_key: str) -> list[SessionStoreListEntry]:
        return [
            {"session_id": path.stem, "mtime": path.stat().st_mtime_ns // 1_000_000}
            for path in sorted(self.directory.glob("*.jsonl"))
        ]

    async def list_session_summaries(self, project_key: str) -> list[SessionSummaryEntry]:
        summaries: list[SessionSummaryEntry] = []
        for session in await self.list_sessions(project_key):
            key: SessionKey = {"project_key": project_key, "session_id": session["session_id"]}
            summary = fold_session_summary(None, key, await self.load(key) or [])
            summary["mtime"] = session["mtime"]
            summaries.append(summary)
        return summaries

    async def delete(self, key: SessionKey) -> None:
        self._path(key).unlink(missing_ok=True)
        if not key.get("subpath"):
            shutil.rmtree(self.directory / key["session_id"], ignore_errors=True)

    async def list_subkeys(self, key: SessionListSubkeysKey) -> list[str]:
        folder = self.directory / key["session_id"]
        return sorted(path.relative_to(folder).with_suffix("").as_posix() for path in folder.rglob("*.jsonl"))

    def _path(self, key: SessionKey) -> Path:
        # The directory belongs to one caller, so the project key Claude Code scopes sessions by is left out.
        subpath = key.get("subpath")
        if subpath:
            return self.directory / key["session_id"] / f"{subpath}.jsonl"
        return self.directory / f"{key['session_id']}.jsonl"


class ClaudeIntelligence:
    """Runs agents through the Claude Code runtime the SDK bundles, with the user's Claude Code settings."""

    def __init__(self) -> None:
        self.implementation = f"claude-agent-sdk {version('claude-agent-sdk')}"
        self.steering: Steering = "queued"

    def preflight(self) -> None:
        try:
            account = asyncio.run(_account())
        except Exception as error:  # whatever stops the runtime from starting, the remedy is the same
            raise Modeling3dError(
                f"The Claude Code runtime did not start: {type(error).__name__}: {error} "
                "Check that ~/.claude/settings.json is valid, and reinstall modeling-3d with the [claude] extra, "
                "which brings the runtime.",
                "agent-unavailable",
            ) from None
        if not signed_in(account):
            raise Modeling3dError(
                "The Claude Agent SDK has no credentials. Set ANTHROPIC_API_KEY to a Claude Console API key, or set "
                "CLAUDE_CODE_USE_BEDROCK, CLAUDE_CODE_USE_ANTHROPIC_AWS, CLAUDE_CODE_USE_VERTEX, or "
                f"CLAUDE_CODE_USE_FOUNDRY to 1 with that cloud's credentials, as {AUTHENTICATION_DOCUMENTATION} "
                "describes.",
                "agent-unavailable",
            )

    async def start(self, request: AgentRequest) -> ClaudeRun:
        run = ClaudeRun(request, ClaudeSDKClient(options=options(request)))
        await run.running()
        return run


def options(request: AgentRequest) -> ClaudeAgentOptions:
    tools: list[str]
    if request.workspace is not None:
        cwd = request.workspace.path.resolve()
        tools = READ_ONLY_TOOLS + WRITE_TOOLS if request.writable else READ_ONLY_TOOLS
    else:
        # Never the caller's directory. One fixed directory keeps every plain session in a single
        # ~/.claude/projects entry instead of one per run.
        cwd = scratch_directory()
        cwd.mkdir(parents=True, exist_ok=True)
        tools = []
    # The shell is not sandboxed to the workspace; the caller's prompt bounds the agent and the caller
    # validates before anything the agent wrote is kept.
    return ClaudeAgentOptions(
        cwd=cwd,
        model=request.model,
        tools=tools,
        permission_mode="bypassPermissions",
        effort=request.reasoning_effort,
        # Newer models leave their reasoning out unless asked; its summary is what the activity shows of it.
        thinking={"type": "adaptive", "display": "summarized"},
        resume=request.resume,
        extra_args={"replay-user-messages": None},
        include_partial_messages=True,
        # Otherwise the API holds each argument back until it is whole, so a long file shows nothing until written.
        env={"CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING": "1"},
        max_buffer_size=MAX_MESSAGE_BYTES,
        session_store=None if request.session_directory is None else FolderSessionStore(request.session_directory),
        session_store_flush="eager",
    )


def outcome(result: ResultMessage) -> AgentResult:
    text = result.result or ""
    if result.is_error:
        return AgentResult(text=text, error=describe(result), session_id=result.session_id)
    return AgentResult(text=text, session_id=result.session_id)


def describe(result: ResultMessage) -> str:
    """Why a run that ended in error failed, in the runtime's own words where it gave any."""
    return "; ".join(result.errors or []) or result.result or f"The run ended {result.subtype}."


def image_block(path: Path) -> dict[str, Any]:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    source = {"type": "base64", "media_type": IMAGE_MEDIA_TYPES[path.suffix.lower()], "data": data}
    return {"type": "image", "source": source}


def as_data(message: Message) -> dict[str, Any]:
    """The message as Claude Code gave it, in JSON's types."""
    if dataclasses.is_dataclass(message) and not isinstance(message, type):
        return json.loads(json.dumps(dataclasses.asdict(message), default=str))
    return {"value": str(message)}


def signed_in(account: dict[str, Any]) -> bool:
    """Whether the account Claude Code resolved at startup can make requests."""
    # A cloud provider authenticates with that cloud's credentials and reports no Anthropic key or token.
    if account.get("apiProvider", "firstParty") != "firstParty":
        return True
    # A Claude subscription signed in through Claude Code reports its plan, with neither a key nor a token source.
    if account.get("subscriptionType"):
        return True
    return bool(account.get("apiKeySource")) or account.get("tokenSource", "none") != "none"


def scratch_directory() -> Path:
    """Where plain completions run, one directory so their sessions share a single ~/.claude/projects entry."""
    return state_directory("claude")


async def _one(message: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    yield message


async def _account() -> dict[str, Any]:
    directory = scratch_directory()
    directory.mkdir(parents=True, exist_ok=True)
    async with ClaudeSDKClient(options=ClaudeAgentOptions(cwd=directory, tools=[])) as client:
        info = await client.get_server_info()
    return (info or {}).get("account") or {}
