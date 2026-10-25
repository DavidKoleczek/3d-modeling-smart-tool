"""OpenAI Codex SDK implementation of the intelligence interface."""

import asyncio
from collections.abc import AsyncIterator
import contextlib
from importlib.metadata import version
from pathlib import Path
import shutil
from typing import Any

from openai_codex import (
    ApprovalMode,
    AsyncCodex,
    AsyncThread,
    AsyncTurnHandle,
    InputItem,
    InvalidRequestError,
    LocalImageInput,
    RunInput,
    Sandbox,
    TextInput,
)
from openai_codex.generated.v2_all import SkillsExtraRootsSetResponse
from openai_codex.models import Notification, UnknownNotification
from openai_codex.types import (
    GetAccountResponse,
    ReasoningEffort,
    ReasoningSummary,
    TurnCompletedNotification,
    TurnStatus,
)

from modeling_3d.intelligence.interface import state_directory
from modeling_3d.intelligence.schemas import AgentEvent, AgentRequest, AgentResult, Steering
from modeling_3d.schemas import Modeling3dError

SIGN_IN_DOCUMENTATION = "https://developers.openai.com/codex/auth"
# How long a stopping run waits for Codex to end its turn before closing the runtime anyway.
INTERRUPT_SECONDS = 5
THREAD_CONFIG: dict[str, Any] = {
    # Without it the runtime leaves reasoning summaries out, and they are what the activity shows of reasoning.
    "model_reasoning_summary": "detailed",
    # Nobody answers a question while a run works, so its agent is not offered the tool for asking one. Codex only
    # takes it in Plan mode, but still lists it in the Default mode runs use.
    "tools.experimental_request_user_input.enabled": False,
}
SUMMARY = ReasoningSummary.model_validate("detailed")
# Each piece of a message, of reasoning, or of a command's output comes whole in the item it ends with, and the turn's
# diff repeats every file change, so these are not kept twice.
DROPPED_METHODS = frozenset(
    {
        "item/agentMessage/delta",
        "item/reasoning/summaryTextDelta",
        "item/reasoning/summaryPartAdded",
        "item/reasoning/textDelta",
        "item/commandExecution/outputDelta",
        "item/fileChange/outputDelta",
        "item/plan/delta",
        "turn/diff/updated",
        "turn/moderationMetadata",
    }
)
# Codex counts the session's tokens after every model call; the last count of a turn is kept, just before it ends.
USAGE_METHOD = "thread/tokenUsage/updated"
TURN_COMPLETED = "turn/completed"
SKILL_ROOTS_METHOD = "skills/extraRoots/set"


class CodexRun:
    """One agent in its own Codex runtime: its notifications as they come, mid-turn steering, and a hard stop."""

    def __init__(self, request: AgentRequest, codex: AsyncCodex) -> None:
        self._request = request
        self._codex = codex
        self._session_id = request.resume
        self._thread: AsyncThread | None = None
        self._turn: AsyncTurnHandle | None = None
        self._events: list[AgentEvent] = []
        # Replaced on every append, so a reader waits on the one current when it ran out of events.
        self._appended = asyncio.Event()
        # Steering that arrived as a turn ended, which goes on in a turn of its own.
        self._pending: list[list[InputItem]] = []
        self._usage: AgentEvent | None = None
        self._text = ""
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

    async def steer(self, message: str, images: list[Path] | None = None) -> None:
        await self._began.wait()
        if self._answered or self._task.done() or self._turn is None:
            raise self._ended()
        content = _content(message, images or [])
        try:
            await self._turn.steer(content)
        except InvalidRequestError:
            # The turn ended as the message went out; unless the run did too, it goes on in a turn of its own.
            if self._answered or self._task.done():
                raise self._ended() from None
            self._pending.append(content)

    async def cancel(self) -> None:
        self._stopping.set()
        await asyncio.wait([self._task])

    async def result(self) -> AgentResult:
        return await asyncio.shield(self._task)

    async def _drive(self) -> AgentResult:
        # The runtime's client is opened and closed in one task, since closing it ends what its turns started.
        stopping = asyncio.create_task(self._stopping.wait())
        reading: asyncio.Task[AgentResult] | None = None
        try:
            async with asyncio.timeout(self._request.timeout_seconds):
                await self._start()
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

    async def _start(self) -> None:
        cwd, sandbox = workspace(self._request)
        if self._request.resume is None:
            self._thread = await self._codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                config=THREAD_CONFIG,
                cwd=str(cwd),
                model=self._request.model,
                sandbox=sandbox,
            )
        else:
            self._thread = await self._codex.thread_resume(
                self._request.resume,
                approval_mode=ApprovalMode.deny_all,
                config=THREAD_CONFIG,
                cwd=str(cwd),
                model=self._request.model,
                sandbox=sandbox,
            )
        self._session_id = self._thread.id
        if self._request.skill_directories:
            # Codex takes extra skill directories only for its whole runtime, and the SDK starts one for each run. The
            # SDK has no method for it, so it goes through the client the SDK keeps.
            await self._codex._client.request(
                SKILL_ROOTS_METHOD,
                {"extraRoots": [str(path.resolve()) for path in self._request.skill_directories]},
                response_model=SkillsExtraRootsSetResponse,
            )
        await self._begin(_content(self._request.prompt, self._request.images))

    async def _begin(self, content: RunInput) -> None:
        if self._thread is None:
            raise RuntimeError("A turn began before its thread.")
        self._turn = await self._thread.turn(
            content, effort=ReasoningEffort(self._request.reasoning_effort), summary=SUMMARY
        )

    async def _read(self) -> AgentResult:
        while True:
            turn = self._turn
            if turn is None:
                raise RuntimeError("Codex was read from before a turn began.")
            completed: TurnCompletedNotification | None = None
            async for notification in turn.stream():
                if isinstance(notification.payload, TurnCompletedNotification):
                    completed = notification.payload
                self._note(notification)
            if completed is None:
                raise RuntimeError("Codex ended the turn without saying how.")
            await self._keep_session()
            if completed.turn.status == TurnStatus.completed and self._pending:
                await self._begin(self._pending.pop(0))
                continue
            if completed.turn.status == TurnStatus.completed and self._request.follow_up is not None:
                follow_up = await self._request.follow_up()
                # Steering that came while it was asked for goes first, and the follow up after it.
                if follow_up is not None:
                    self._pending.append(_content(follow_up, []))
                if self._pending:
                    await self._begin(self._pending.pop(0))
                    continue
            self._answered = True
            return self._outcome(completed)

    def _outcome(self, completed: TurnCompletedNotification) -> AgentResult:
        turn = completed.turn
        if turn.status == TurnStatus.completed:
            return AgentResult(text=self._text, session_id=self._session_id)
        if turn.status == TurnStatus.interrupted:
            return AgentResult(text=self._text, cancelled=True, session_id=self._session_id)
        reason = turn.error.message if turn.error is not None else f"The turn ended {turn.status.value}."
        return AgentResult(text=self._text, error=reason, session_id=self._session_id)

    def _note(self, notification: Notification) -> None:
        method = notification.method
        if method in DROPPED_METHODS:
            return
        data = as_data(notification)
        if method == USAGE_METHOD:
            self._usage = AgentEvent(type=method, data=data)
            return
        item = data.get("item")
        if method == "item/completed" and isinstance(item, dict) and item.get("type") == "agentMessage":
            self._text = str(item.get("text", ""))
        if method == TURN_COMPLETED and self._usage is not None:
            self._emit(self._usage.type, self._usage.data)
            self._usage = None
        self._emit(method, data)

    async def _keep_session(self) -> None:
        """Copy the session's rollout to the session directory, where it can be read without the runtime."""
        directory = self._request.session_directory
        if directory is None or self._thread is None:
            return
        rollout = (await self._thread.read()).thread.path
        if rollout is None:
            return
        directory.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, rollout, directory / f"{self._thread.id}.jsonl")

    async def _close(self, interrupt: bool) -> None:
        """End the Codex runtime; an unfinished turn is interrupted first, so nothing it started outlives it."""
        if interrupt and self._turn is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._turn.interrupt(), INTERRUPT_SECONDS)
        with contextlib.suppress(Exception):
            await self._codex.close()

    def _ended(self) -> Modeling3dError:
        return Modeling3dError(
            "The agent run has ended, so the steering message was not delivered. Start a new run that resumes "
            f"session {self._session_id} with the message as its prompt."
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


class CodexIntelligence:
    """Runs agents through a Codex runtime on this machine, with the user's Codex sign-in and configuration."""

    def __init__(self) -> None:
        self.implementation = f"openai-codex {version('openai-codex')}"
        self.steering: Steering = "mid-turn"

    def preflight(self) -> None:
        try:
            account = asyncio.run(_account())
        except Exception as error:  # whatever stops the runtime from starting, the remedy is the same
            raise Modeling3dError(
                f"The Codex runtime did not start: {type(error).__name__}: {error} "
                "Check that ~/.codex/config.toml is valid, and reinstall modeling-3d with the [codex] extra, which "
                "brings the runtime.",
                "agent-unavailable",
            ) from None
        if account.account is None and account.requires_openai_auth:
            raise Modeling3dError(
                "Codex is not signed in. Install the Codex CLI and run `codex login`, with ChatGPT or an API key as "
                f"{SIGN_IN_DOCUMENTATION} describes.",
                "agent-unavailable",
            )

    async def start(self, request: AgentRequest) -> CodexRun:
        run = CodexRun(request, AsyncCodex())
        await run.running()
        return run


def workspace(request: AgentRequest) -> tuple[Path, Sandbox]:
    """Where the agent works and what it may touch there."""
    if request.workspace is None:
        # Never the caller's directory. One fixed directory keeps every plain session in one place.
        directory = scratch_directory()
        directory.mkdir(parents=True, exist_ok=True)
        return directory, Sandbox.read_only
    # Not sandboxed to the workspace when writable, as the agent runs tools such as Blender that write elsewhere; the
    # caller's prompt bounds the agent and the caller validates before anything the agent wrote is kept.
    return request.workspace.path.resolve(), Sandbox.full_access if request.writable else Sandbox.read_only


def _content(text: str, images: list[Path]) -> list[InputItem]:
    return [TextInput(text), *(LocalImageInput(str(path)) for path in images)]


def as_data(notification: Notification) -> dict[str, Any]:
    """The notification's payload as Codex gave it, in JSON's types and names."""
    payload = notification.payload
    if isinstance(payload, UnknownNotification):
        return dict(payload.params)
    return payload.model_dump(mode="json", by_alias=True, exclude_none=True)


def scratch_directory() -> Path:
    """Where plain completions run."""
    return state_directory("codex")


async def _account() -> GetAccountResponse:
    async with AsyncCodex() as codex:
        return await codex.account()
