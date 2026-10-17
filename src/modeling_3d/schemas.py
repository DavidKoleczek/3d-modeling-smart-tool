from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, Field

ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]
AgentProvider = Literal["claude", "codex"]
# Also the order an agent provider is picked in when none is named.
AGENT_PROVIDERS: tuple[AgentProvider, ...] = ("claude", "codex")

DEFAULT_INTELLIGENCE_MODELS: dict[AgentProvider, str] = {
    "claude": "claude-sonnet-5-5",
    "codex": "gpt-6.1-sol",
}
DEFAULT_REASONING_EFFORT: ReasoningEffort = "medium"

SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class Modeling3dError(Exception):
    """Raised for any failure the library can name and explain how to fix."""


# region: Manifest


class ManifestRequirement(BaseModel):
    """One environment prerequisite; `install` references documentation, never a command."""

    name: str
    purpose: str
    install: str
    optional: bool = False


class Manifest(BaseModel):
    """The structured form of SMART_TOOL.md."""

    smart_tool_format: int
    name: str = Field(pattern=SLUG_PATTERN)
    version: str = Field(pattern=SEMVER_PATTERN)
    description: str
    use_cases: list[str]
    platforms: list[str]
    requires: list[ManifestRequirement] = Field(default_factory=list)
    body: str = Field(description="The Markdown below the frontmatter: the skill `--help` renders")


# endregion

# region: Skill


class Capability(NamedTuple):
    """One capability of the tool: its line in the skill's capability list and its own skill."""

    name: str
    summary: str
    model_backed: bool
    skill: str  # the capability's skill body, a Markdown file relative to the skill directory
    resources: tuple[str, ...] = ()  # the files that skill refers to, relative to the skill directory


# endregion

# region: 3D models

ModelRunStatus = Literal["running", "done", "failed", "cancelled", "timed-out"]
ModelEventKind = Literal["started", "agent", "steered", "finished", "failed"]


class ModelRunRecord(BaseModel):
    """One request to create or change a model, as model.json keeps it while it runs and after."""

    id: str
    prompt: str
    references: list[str] = Field(default_factory=list, description="The references given, as copied into the model")
    resumed: bool = Field(description="Whether the run continued the session of the run before it")
    agent_provider: AgentProvider
    model: str
    reasoning_effort: ReasoningEffort
    session_id: str | None = None
    status: ModelRunStatus = "running"
    pid: int = Field(description="The process running it; a `running` run whose process is gone has crashed")
    started: datetime
    last_event: datetime | None = None
    finished: datetime | None = None


class ModelRecord(BaseModel):
    """model.json: what marks a directory as a 3D model made by this tool, and every request it has run."""

    tool: Literal["modeling-3d"] = "modeling-3d"
    id: str = Field(description="Stays the same when the model's directory is renamed")
    name: str
    created: datetime
    runs: list[ModelRunRecord] = Field(default_factory=list)


class ModelEvent(BaseModel):
    """One line of a run's events.jsonl: the run's own milestones, and every message from its agent as given."""

    time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str
    kind: ModelEventKind
    text: str = Field(default="", description="For `agent`, the agent provider's name for the message")
    data: dict[str, Any] = Field(default_factory=dict)


class ModelResult(BaseModel):
    """How a run ended, and where its model is."""

    name: str
    directory: Path
    run_id: str
    status: ModelRunStatus
    text: str = Field(default="", description="The agent's final message")
    error: str | None = None
    session_id: str | None = None
    agent_provider: AgentProvider
    files: list[str] = Field(default_factory=list, description="The model's files, relative to its directory")
    next: str = Field(description="The command that goes on changing this model in the same session")


class BlenderOnPath(BaseModel):
    """Where Blender is, and whether it took a change for a new terminal to find it as `blender`."""

    executable: Path
    changed: bool
    message: str


# endregion
