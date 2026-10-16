"""OpenAI Codex SDK implementation of the intelligence interface."""

import asyncio
from importlib.metadata import version
from pathlib import Path
import tempfile
import time
from typing import Any

from openai_codex import ApprovalMode, AsyncCodex, AsyncThread, Sandbox, TurnResult
from openai_codex.types import GetAccountResponse, ReasoningEffort, TurnStatus

from modeling_3d.intelligence.schemas import AgentRequest, AgentResult
from modeling_3d.schemas import Modeling3dError

SIGN_IN_DOCUMENTATION = "https://developers.openai.com/codex/auth"


class CodexIntelligence:
    """Runs agents through a Codex runtime on this machine, with the user's Codex sign-in and configuration."""

    def __init__(self) -> None:
        self.implementation = f"openai-codex {version('openai-codex')}"

    def preflight(self) -> None:
        try:
            account = asyncio.run(_account())
        except Exception as error:  # whatever stops the runtime from starting, the remedy is the same
            raise Modeling3dError(
                f"The Codex runtime did not start: {type(error).__name__}: {error} "
                "Check that ~/.codex/config.toml is valid, and reinstall modeling-3d with the [codex] extra, which "
                "brings the runtime."
            ) from None
        if account.account is None and account.requires_openai_auth:
            raise Modeling3dError(
                "Codex is not signed in. Install the Codex CLI and run `codex login`, with ChatGPT or an API key as "
                f"{SIGN_IN_DOCUMENTATION} describes."
            )

    def run(self, request: AgentRequest) -> AgentResult:
        if request.workspace is not None:
            return asyncio.run(self._run(request, request.workspace.path))
        # A plain completion still runs in a directory Codex can read and write; never the caller's.
        with tempfile.TemporaryDirectory() as scratch:
            return asyncio.run(self._run(request, Path(scratch)))

    async def _run(self, request: AgentRequest, directory: Path) -> AgentResult:
        cwd = str(directory.resolve())
        # The shell and file tools are not sandboxed to the workspace; the caller's prompt bounds the agent
        # and the caller validates before anything the agent wrote is kept.
        thread_options: dict[str, Any] = {
            "cwd": cwd,
            "model": request.model,
            "sandbox": Sandbox.full_access,
            "approval_mode": ApprovalMode.deny_all,
            # A writable thread in a project without a trust level otherwise records the project as trusted in
            # the user's ~/.codex/config.toml. An entry for the exact cwd, resolved as Codex compares it, takes
            # precedence over one for the repository root.
            "config": {"projects": {cwd: {"trust_level": "trusted"}}},
        }
        deadline = time.monotonic() + request.timeout_seconds
        timed_out = f"The agent did not finish within {request.timeout_seconds} seconds."
        # Carried out of the try so the failure paths can name the session the caller could resume.
        session_id: str | None = None
        try:
            async with AsyncCodex() as codex:
                if request.resume is not None:
                    thread = await codex.thread_resume(request.resume, **thread_options)
                else:
                    thread = await codex.thread_start(**thread_options)
                session_id = thread.id
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return AgentResult(error=timed_out, session_id=session_id)
                result = await run_turn(thread, request.prompt, ReasoningEffort(request.reasoning_effort), remaining)
                if result is None:
                    return AgentResult(error=timed_out, session_id=session_id)
                text = result.final_response or ""
                if result.status != TurnStatus.completed:
                    error = result.error.message if result.error else f"The turn ended {result.status.value}."
                    return AgentResult(text=text, error=error, session_id=session_id)
                return AgentResult(text=text, session_id=session_id)
        except Exception as error:  # an SDK or runtime failure is the caller's data, not a crash
            return AgentResult(error=f"{type(error).__name__}: {error}", session_id=session_id)


async def run_turn(thread: AsyncThread, prompt: str, effort: ReasoningEffort, timeout: float) -> TurnResult | None:
    """The turn's result, or None when it ran out of time and was interrupted."""
    handle = await thread.turn(prompt, effort=effort)
    completed = asyncio.create_task(handle.run())
    try:
        return await asyncio.wait_for(asyncio.shield(completed), timeout)
    except TimeoutError:
        await handle.interrupt()
        # Draining to the completed event leaves the thread usable for a later resume.
        await completed
        return None


async def _account() -> GetAccountResponse:
    async with AsyncCodex() as codex:
        return await codex.account()
