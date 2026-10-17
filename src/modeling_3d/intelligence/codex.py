"""OpenAI Codex SDK implementation of the intelligence interface."""

import asyncio
from importlib.metadata import version

from openai_codex import AsyncCodex
from openai_codex.types import GetAccountResponse

from modeling_3d.intelligence.interface import AgentRun
from modeling_3d.intelligence.schemas import AgentRequest, Steering
from modeling_3d.schemas import Modeling3dError

SIGN_IN_DOCUMENTATION = "https://developers.openai.com/codex/auth"


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

    async def start(self, request: AgentRequest) -> AgentRun:
        raise Modeling3dError(
            "The codex agent provider cannot run agents yet; only claude can. Pass --agent-provider claude "
            "(agent_provider='claude'), and install modeling-3d with the [claude] extra if it is not.",
            "agent-unavailable",
        )


async def _account() -> GetAccountResponse:
    async with AsyncCodex() as codex:
        return await codex.account()
