"""Drives the Codex adapter with the SDK's client faked, so neither a Codex sign-in nor a model is needed."""

from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("openai_codex")

from openai_codex.types import GetAccountResponse

from modeling_3d.intelligence import codex as adapter
from modeling_3d.intelligence.codex import CodexIntelligence
from modeling_3d.intelligence.schemas import AgentRequest
from modeling_3d.schemas import Modeling3dError


class FakeWorld:
    """Stands in for AsyncCodex and answers the account question."""

    def __init__(self, account: GetAccountResponse | None = None) -> None:
        self.account = account

    def codex(self) -> Any:
        world = self

        class Codex:
            async def __aenter__(self) -> "Codex":
                return self

            async def __aexit__(self, *exc: object) -> None:
                pass

            async def account(self) -> GetAccountResponse | None:
                return world.account

        return Codex()


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeWorld]:
    def install(account: GetAccountResponse | None = None) -> FakeWorld:
        fake = FakeWorld(account=account)
        monkeypatch.setattr(adapter, "AsyncCodex", fake.codex)
        return fake

    return install


async def test_starting_an_agent_is_refused_naming_the_agent_provider_that_runs_one() -> None:
    intelligence = CodexIntelligence()

    with pytest.raises(Modeling3dError) as failure:
        await intelligence.start(AgentRequest(prompt="Do the work.", model="gpt-6.1-sol", timeout_seconds=60))

    assert "--agent-provider claude" in str(failure.value)
    assert intelligence.steering == "mid-turn"


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
