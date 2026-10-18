from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple, get_args

from pydantic import BaseModel, Field

ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max", "ultra"]
AgentProvider = Literal["claude", "codex"]
# Also the order an agent provider is picked in when none is named.
AGENT_PROVIDERS: tuple[AgentProvider, ...] = ("claude", "codex")

DEFAULT_INTELLIGENCE_MODELS: dict[AgentProvider, str] = {
    "claude": "claude-sonnet-5-5",
    "codex": "gpt-6.1-sol",
}
DEFAULT_REASONING_EFFORT: ReasoningEffort = "medium"
REASONING_EFFORTS: tuple[ReasoningEffort, ...] = get_args(ReasoningEffort)
# What a model the tool does not list may be asked for, by its agent provider.
PROVIDER_REASONING_EFFORTS: dict[AgentProvider, tuple[ReasoningEffort, ...]] = {
    "claude": ("low", "medium", "high", "xhigh", "max"),
    "codex": REASONING_EFFORTS,
}

SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


# Which failure it was, for a surface that words it for a person in its own terms rather than passing on the message.
FailureReason = Literal[
    "invalid-name",
    "name-in-use",
    "no-such-model",
    "no-such-session",
    "missing-reference",
    "no-reference-model",
    "already-running",
    "not-running",
    "provider-mismatch",
    "agent-unavailable",
    "start-failed",
    "bad-cursor",
    "no-such-tool-call",
    "bad-upload",
    "no-such-intelligence-model",
    "bad-reasoning-effort",
    "bad-settings",
]


class Modeling3dError(Exception):
    """Raised for any failure the library can name and explain how to fix.

    The message is for an agent or a terminal, naming the command or argument that fixes it. `reason` says which
    failure it is, and `model` names the model it is about, so a surface can word it for a person instead.
    """

    def __init__(self, message: str, reason: FailureReason | None = None, model: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.model = model


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

# region: Intelligence models


class IntelligenceModel(BaseModel):
    """One AI model a person can pick to run a model's agent, and the reasoning efforts it takes."""

    agent_provider: AgentProvider
    id: str
    label: str
    reasoning_efforts: list[ReasoningEffort]


# What a picker offers, in its order.
INTELLIGENCE_MODELS: tuple[IntelligenceModel, ...] = (
    IntelligenceModel(
        agent_provider="claude",
        id="claude-sonnet-5-5",
        label="Sonnet 5.5",
        reasoning_efforts=list(PROVIDER_REASONING_EFFORTS["claude"]),
    ),
    IntelligenceModel(
        agent_provider="claude",
        id="claude-opus-5-5",
        label="Opus 5.5",
        reasoning_efforts=list(PROVIDER_REASONING_EFFORTS["claude"]),
    ),
    IntelligenceModel(
        agent_provider="codex",
        id="gpt-6.1-sol",
        label="Sol 6.1",
        reasoning_efforts=list(PROVIDER_REASONING_EFFORTS["codex"]),
    ),
    IntelligenceModel(
        agent_provider="codex",
        id="gpt-6-astra",
        label="Astra 6",
        reasoning_efforts=list(PROVIDER_REASONING_EFFORTS["codex"]),
    ),
)


class IntelligenceChoice(BaseModel):
    """What runs a model's agent: the agent provider, the AI model, and how hard it thinks."""

    agent_provider: AgentProvider
    model: str
    reasoning_effort: ReasoningEffort


class IntelligenceModels(BaseModel):
    """The AI models to pick from, each with its reasoning efforts."""

    models: list[IntelligenceModel] = Field(description="Those of the agent providers that are installed")
    default: IntelligenceChoice = Field(description="What `create_3d_model` runs with when given neither")


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
    origin: str | None = Field(default=None, description="Who asked: `app`, `claude-code:<session id>`, or unknown")
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


ModelStatus = Literal["running", "crashed", "done", "failed", "cancelled", "timed-out"]


class ModelSummary(BaseModel):
    """One model as a gallery shows it: where it is, what state it is in, and its files."""

    name: str
    id: str
    directory: Path
    created: datetime
    updated: datetime = Field(description="The latest time its last run started, sent an event, or finished")
    built: datetime | None = Field(description="When model.glb was last written; None before the first build")
    status: ModelStatus | None = Field(
        description="Its last run's; `crashed` when that run is `running` but its process is gone; None if never run"
    )
    last_run: ModelRunRecord | None = Field(description="Its prompt, agent provider, and session, for a follow-up")
    files: list[str] = Field(description="The model's files, relative to its directory")
    references: list[str] = Field(
        default_factory=list, description="What its runs were given to work from, as copied into its directory"
    )


class ModelListing(BaseModel):
    """Every model in a directory, most recently updated first, and the one viewed last."""

    directory: Path
    models: list[ModelSummary]
    last_viewed: str | None = Field(description="None when nothing was viewed, or that model is gone")
    unreadable: list[str] = Field(default_factory=list, description="Why each broken model.json was skipped")


class ModelsState(BaseModel):
    """.state.json in a models directory: what the person last did there."""

    last_viewed: str | None = None


ActivityKind = Literal[
    "request", "said", "reasoning", "thought", "composing", "tool", "tool-result", "usage", "steered", "ended"
]


class ActivityEntry(BaseModel):
    """One step in making a model: a request, what its agent said or did, steering, or how a run ended."""

    time: datetime
    run_id: str
    kind: ActivityKind
    text: str = Field(
        description="The prompt, the agent's words, the summary of its reasoning, the tool's target, the message, or "
        "the outcome"
    )
    origin: str | None = Field(default=None, description="Who sent a request or steering message")
    data: dict[str, Any] = Field(default_factory=dict)


class ModelActivity(BaseModel):
    """A model's summary, its activity past a cursor, and the cursor to read on from."""

    model: ModelSummary
    entries: list[ActivityEntry]
    cursor: str = Field(description="Pass as `after` to read only what comes next")


class ToolCall(BaseModel):
    """One tool call of a model's agent in full: what it was called with, and what came back."""

    name: str = Field(description="The tool, as the agent provider names it")
    input: dict[str, Any] = Field(description="The arguments the agent called it with")
    output: str | None = Field(description="What came back, as text with any images left out; None while it runs")
    failed: bool


class BlenderOnPath(BaseModel):
    """Where Blender is, and whether it took a change for a new terminal to find it as `blender`."""

    executable: Path
    changed: bool
    message: str


# endregion

# region: App


class AppState(BaseModel):
    """.app.json in a models directory: what the person last picked in the app there."""

    intelligence: IntelligenceChoice | None = None


class AppIntelligence(IntelligenceModels):
    """What the app's picker offers, and what the person picked last in its directory."""

    chosen: IntelligenceChoice | None = Field(description="None when nothing was picked, or it is no longer offered")


ThemePreference = Literal["system", "light", "dark"]


class PaneLayout(BaseModel):
    """One side pane of the app at one of its widths: how wide it is, and whether it shows."""

    size: int | None = Field(default=None, ge=0, description="Its width in pixels; None for the default")
    open: bool = True


class AppLayout(BaseModel):
    """The app's side panes at one of its widths."""

    models: PaneLayout = Field(default_factory=PaneLayout)
    activity: PaneLayout = Field(default_factory=PaneLayout)


class AppSettings(BaseModel):
    """app-settings.json in the user's config directory: how the person set up the app, the same in every directory."""

    theme: ThemePreference = Field(default="system", description="`system` follows the host's theme")
    grid: bool = True
    wireframe: bool = False
    dimensions: bool = False
    wide: AppLayout = Field(default_factory=AppLayout, description="The panes from 1100 pixels wide")
    medium: AppLayout = Field(default_factory=AppLayout, description="The panes from 640 to 1100 pixels wide")
    steps: dict[str, dict[str, bool]] = Field(
        default_factory=dict,
        description="By model id, the groups of steps in its activity the person opened or closed, and which",
    )


class AppFolders(BaseModel):
    """Where the app keeps what it remembers."""

    settings: Path = Field(description="The person's settings, the same in every directory")
    models: Path = Field(description="The models the app shows, with what the person last picked and viewed there")


# endregion
