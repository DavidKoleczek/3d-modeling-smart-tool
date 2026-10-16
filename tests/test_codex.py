"""Drives the Codex adapter with the SDK's client faked, so neither a Codex sign-in nor a model is needed."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("openai_codex")

from openai_codex import ApprovalMode, Sandbox, TurnResult
from openai_codex.types import GetAccountResponse, TurnError, TurnStatus

from modeling_3d.intelligence import codex as adapter
from modeling_3d.intelligence.codex import CodexIntelligence
from modeling_3d.intelligence.schemas import AgentRequest, HostWorkspace
from modeling_3d.schemas import Modeling3dError

SESSION = "fake-thread"


def completed(text: str | None, status: TurnStatus = TurnStatus.completed, error: str | None = None) -> TurnResult:
    return TurnResult(
        id="turn",
        status=status,
        error=TurnError(message=error) if error is not None else None,
        started_at=None,
        completed_at=None,
        duration_ms=None,
        final_response=text,
        items=[],
        usage=None,
    )


class FakeHandle:
    def __init__(self, result: TurnResult | None) -> None:
        self.result = result
        self.interrupted = asyncio.Event()

    async def run(self) -> TurnResult:
        if self.result is None:
            await self.interrupted.wait()
            self.result = completed(None, TurnStatus.interrupted)
        return self.result

    async def interrupt(self) -> None:
        self.interrupted.set()


class FakeThread:
    def __init__(self, world: "FakeWorld", thread_id: str) -> None:
        self.id = thread_id
        self._world = world

    async def turn(self, prompt: str, effort: Any) -> FakeHandle:
        self._world.prompts.append(prompt)
        self._world.turns.append({"effort": effort})
        handle = FakeHandle(self._world.results.pop(0))
        self._world.handles.append(handle)
        return handle


class FakeWorld:
    """Stands in for AsyncCodex and records what the adapter asked of it."""

    def __init__(self, *results: TurnResult | None, account: GetAccountResponse | None = None) -> None:
        self.results = list(results)
        self.account = account
        self.started: list[dict[str, Any]] = []
        self.resumed: list[tuple[str, dict[str, Any]]] = []
        self.prompts: list[str] = []
        self.turns: list[dict[str, Any]] = []
        self.handles: list[FakeHandle] = []
        self.directories_existed: list[bool] = []

    def codex(self) -> Any:
        world = self

        class Codex:
            async def __aenter__(self) -> "Codex":
                return self

            async def __aexit__(self, *exc: object) -> None:
                pass

            async def account(self) -> GetAccountResponse | None:
                return world.account

            async def thread_start(self, **options: Any) -> FakeThread:
                world.started.append(options)
                world.directories_existed.append(Path(options["cwd"]).is_dir())
                return FakeThread(world, SESSION)

            async def thread_resume(self, thread_id: str, **options: Any) -> FakeThread:
                world.resumed.append((thread_id, options))
                return FakeThread(world, thread_id)

        return Codex()


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeWorld]:
    def install(*results: TurnResult | None, account: GetAccountResponse | None = None) -> FakeWorld:
        fake = FakeWorld(*results, account=account)
        monkeypatch.setattr(adapter, "AsyncCodex", fake.codex)
        return fake

    return install


def request(workspace: Path | None = None, **fields: Any) -> AgentRequest:
    return AgentRequest(
        prompt="Do the work.",
        model="gpt-6.1-sol",
        workspace=HostWorkspace(path=workspace) if workspace is not None else None,
        reasoning_effort=fields.pop("reasoning_effort", "high"),
        timeout_seconds=fields.pop("timeout_seconds", 60),
        **fields,
    )


def test_a_workspace_run_has_full_access_without_approvals_and_keeps_the_trust_entry_out_of_the_users_config(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(completed("done"))

    result = CodexIntelligence().run(request(tmp_path, reasoning_effort="max"))

    assert result.error is None
    assert result.text == "done"
    assert result.session_id == SESSION
    options = fake.started[0]
    cwd = str(tmp_path.resolve())
    assert options["cwd"] == cwd
    assert options["model"] == "gpt-6.1-sol"
    assert options["sandbox"] == Sandbox.full_access
    assert options["approval_mode"] == ApprovalMode.deny_all
    assert options["config"] == {"projects": {cwd: {"trust_level": "trusted"}}}
    assert fake.turns[0]["effort"] == "max"


def test_a_plain_completion_runs_in_a_scratch_directory_never_the_callers(world: Callable[..., FakeWorld]) -> None:
    fake = world(completed("Hello."))
    caller = str(Path.cwd().resolve())

    result = CodexIntelligence().run(request())

    assert result.text == "Hello."
    cwd = fake.started[0]["cwd"]
    assert cwd != caller
    assert fake.directories_existed == [True]
    assert not Path(cwd).exists()
    assert fake.started[0]["config"] == {"projects": {cwd: {"trust_level": "trusted"}}}


def test_a_resumed_run_continues_the_named_thread_with_the_same_options(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(completed("again"))

    result = CodexIntelligence().run(request(tmp_path, resume="earlier-thread"))

    assert fake.started == []
    thread_id, options = fake.resumed[0]
    assert thread_id == "earlier-thread"
    assert options["sandbox"] == Sandbox.full_access
    assert options["approval_mode"] == ApprovalMode.deny_all
    assert options["config"] == {"projects": {str(tmp_path.resolve()): {"trust_level": "trusted"}}}
    assert result.session_id == "earlier-thread"


def test_a_turn_past_the_deadline_is_interrupted_and_drained(world: Callable[..., FakeWorld]) -> None:
    fake = world(None)

    result = CodexIntelligence().run(request(timeout_seconds=1))

    assert result.error == "The agent did not finish within 1 seconds."
    assert result.session_id == SESSION
    assert fake.handles[0].interrupted.is_set()
    assert fake.handles[0].result is not None
    assert fake.handles[0].result.status == TurnStatus.interrupted


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (completed("partial", TurnStatus.failed, "The model is not available."), "The model is not available."),
        (completed("partial", TurnStatus.interrupted), "The turn ended interrupted."),
    ],
    ids=["failed-turn", "interrupted-turn"],
)
def test_a_turn_that_did_not_complete_carries_its_error_and_the_thread(
    world: Callable[..., FakeWorld], result: TurnResult, error: str
) -> None:
    world(result)

    outcome = CodexIntelligence().run(request())

    assert outcome.error == error
    assert outcome.text == "partial"
    assert outcome.session_id == SESSION


def test_a_runtime_failure_is_the_result_not_a_crash(
    world: Callable[..., FakeWorld], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = world()

    async def fails(thread: Any, *arguments: Any) -> None:
        raise RuntimeError("turn failed with status failed")

    monkeypatch.setattr(adapter, "run_turn", fails)

    result = CodexIntelligence().run(request())

    assert result.error == "RuntimeError: turn failed with status failed"
    assert result.session_id == SESSION
    assert fake.started


@pytest.mark.parametrize(
    "account",
    [
        GetAccountResponse.model_validate(
            {
                "account": {"type": "chatgpt", "email": "user@example.com", "planType": "plus"},
                "requiresOpenaiAuth": True,
            }
        ),
        GetAccountResponse.model_validate({"account": None, "requiresOpenaiAuth": False}),
    ],
    ids=["signed-in", "custom-provider"],
)
def test_preflight_passes_when_signed_in_or_when_the_provider_needs_no_openai_sign_in(
    world: Callable[..., FakeWorld], account: GetAccountResponse
) -> None:
    world(account=account)

    CodexIntelligence().preflight()


def test_preflight_names_both_ways_to_sign_in_when_codex_is_not_signed_in(world: Callable[..., FakeWorld]) -> None:
    world(account=GetAccountResponse.model_validate({"account": None, "requiresOpenaiAuth": True}))

    with pytest.raises(Modeling3dError) as failure:
        CodexIntelligence().preflight()

    message = str(failure.value)
    assert "not signed in" in message
    assert "codex login" in message
    assert adapter.SIGN_IN_DOCUMENTATION in message


def test_preflight_names_the_runtime_when_it_cannot_start(monkeypatch: pytest.MonkeyPatch) -> None:
    class Unstartable:
        async def __aenter__(self) -> None:
            raise FileNotFoundError("codex")

        async def __aexit__(self, *exc: object) -> None:
            pass

    monkeypatch.setattr(adapter, "AsyncCodex", Unstartable)

    with pytest.raises(Modeling3dError) as failure:
        CodexIntelligence().preflight()

    message = str(failure.value)
    assert "did not start" in message
    assert "FileNotFoundError" in message
    assert "[codex]" in message
