"""What an intelligence implementation is asked to do, and what it answers with."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from modeling_3d.schemas import DEFAULT_REASONING_EFFORT, ReasoningEffort

# How a steering message lands: in the current turn, when the agent next reads input, or by restarting the run.
Steering = Literal["mid-turn", "queued", "restart"]
# The image types an agent can be shown inline, by file suffix.
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class HostWorkspace(BaseModel):
    """A directory on this machine; the agent's tools execute here."""

    path: Path


class AgentRequest(BaseModel):
    """One agent run: a prompt, a model, and optionally a place to work."""

    prompt: str
    model: str
    images: list[Path] = Field(default_factory=list, description="Images shown to the agent with the prompt")
    workspace: HostWorkspace | None = Field(
        default=None, description="Where the agent may read and run things; None means a plain completion, no tools"
    )
    writable: bool = Field(default=False, description="Whether the agent may create and modify files in the workspace")
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT
    timeout_seconds: int = Field(gt=0)
    resume: str | None = Field(
        default=None,
        description="The session_id of an earlier result to continue in, so the agent keeps what it learned; None starts fresh",
    )
    session_directory: Path | None = Field(
        default=None,
        description="Where the session is also kept, so it can be read and resumed from there; None keeps it only "
        "where the agent provider keeps its sessions",
    )


class AgentEvent(BaseModel):
    """One message from the agent provider, as it gave it; `terminal`, carrying the result, comes last, once."""

    time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    type: str = Field(
        description="The agent provider's own name for the message; `composing`, how far a tool call the agent is "
        "still writing has got; or `terminal`"
    )
    data: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """The run's outcome; in-flight agent failures set `error` instead of raising."""

    text: str = Field(default="", description="The agent's final message")
    error: str | None = None
    cancelled: bool = Field(default=False, description="Whether the run ended because it was cancelled")
    session_id: str | None = Field(
        default=None, description="Identifies this run's session so a later request can resume it"
    )


class AgentStep(BaseModel):
    """What one agent event amounts to in a model's activity: words for the person, reasoning, a tool call, or its result."""

    kind: Literal["said", "reasoning", "thought", "composing", "tool", "tool-result", "usage"]
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
