# Library Reference

Every capability of Modeling 3D is reachable from `modeling_3d.lib`.
All other surfaces, including the CLI, are thin wrappers over the library and add no capability of their own.

## Intelligence

Model-backed capabilities run through the `Intelligence` protocol in `modeling_3d.intelligence.interface`:

```python
class Intelligence(Protocol):
    implementation: str
    steering: Steering

    def preflight(self) -> None: ...
    async def start(self, request: AgentRequest) -> AgentRun: ...


class AgentRun(Protocol):
    session_id: str | None

    def events(self) -> AsyncIterator[AgentEvent]: ...
    async def steer(self, message: str) -> None: ...
    async def cancel(self) -> None: ...
    async def result(self) -> AgentResult: ...
```

`preflight` raises `Modeling3dError` naming what to configure when the implementation cannot run.
`start` starts one agent and returns once it runs. `AgentRequest` holds the prompt, any images to show with it, the model, and an optional workspace. Failures after `start` end the run with `AgentResult.error` and never raise.
`events` replays every event from the start, then live ones, ending with `terminal`. Each `AgentEvent` is one message from the agent provider as it gave it: its own name for the message in `type`, and its fields in `data`. No vocabulary is shared across agent providers.
`steer` sends a message while the agent works. `steering` says how it lands: `mid-turn`, `queued` until the agent next reads input, or `restart`.
`cancel` stops the run at once, along with every command the agent started.
Setting `AgentRequest.resume` to an earlier `session_id` continues that session instead of starting a fresh one, so the agent keeps what it learned, even after a cancel. `AgentRequest.session_directory` also keeps a copy of the session there, and a resume can start from that copy alone.

`resolve_intelligence(agent_provider)` returns a shipped implementation, one per agent provider, each installed through the extra of the same name:

- `claude`: `ClaudeIntelligence`, built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) and run with the user's Claude Code settings and  any of its other supported modes of [authentication](https://code.claude.com/docs/en/agent-sdk/quickstart). Steering is `queued`. Sessions are kept where Claude Code keeps them; a plain completion runs in the platform's per-user state directory, in `modeling-3d/claude`.
- `codex`: `CodexIntelligence`, built on the [OpenAI Codex SDK](https://github.com/openai/codex/tree/main/sdk/python). It checks the user's Codex sign-in, but does not run agents yet: `start` raises `Modeling3dError` naming `claude`.

Without an agent provider named, the first installed in that order is used; one that is not installed raises `Modeling3dError` with the command that installs it.
`select_intelligence(intelligence, agent_provider, model, DEFAULT_INTELLIGENCE_MODELS)` is what a capability calls: an injected `intelligence` wins, and `model` falls back to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS`.

## Create a 3D model

Model-backed. An agent creates a 3D model, or changes one, as a Blender script in the model's own directory: it writes `model.py`, builds `model.glb` with it, renders the result, looks at the renders, and fixes what does not match the request.
`model.py` gets Blender from PyPI as an inline dependency and runs with `uv run --script`, so no Blender install is needed. Building runs on Windows, Linux x64, and macOS on Apple silicon.

```python
async def create_3d_model(
    prompt: str,
    name: str,
    directory: Path | None = None,
    references: list[Path] | None = None,
    edit: bool = False,
    resume: bool = False,
    agent_provider: AgentProvider | None = None,
    model: str | None = None,
    reasoning_effort: ReasoningEffort = "medium",
    timeout_seconds: int = 3600,
    intelligence: Intelligence | None = None,
) -> ModelRun
```

- `prompt`: what to build, or what to change.
- `name`: the model's name and its directory under `directory`. A new model's name must not be taken there, ignoring case, or it is refused before anything starts; the caller then chooses another name or edits the model that has it.
- `directory`: where models are kept, `.modeling-3d` in the working directory when omitted.
- `references`: images and models to work from, copied into the model's `references/`. Images are also shown to the agent with the prompt.
- `edit`: change the existing model named `name`, in a fresh session that reads `model.py` first, which holds the whole model. Naming a model that does not exist is refused.
- `resume`: implies `edit`, continuing the session that last worked on the model, on the agent provider that made it. Use it for a follow-up soon after the last run, while the session's context is still cached, after a run that was cut short, or when the request refers back to the conversation. Coming back later, `edit` alone costs only the conversation and starts from a small context.

It returns once the agent runs. `ModelRun` has `name`, `directory`, `run_id`, and `session_id`, and the same `events`, `steer`, `cancel`, and `result` as an `AgentRun`.
Each `ModelEvent` has a `kind`: `started`, `agent` (one `AgentEvent`, as given), `steered`, `finished`, or `failed`. The last carries the `ModelResult`: `status` (`done`, `failed`, `cancelled`, or `timed-out`), the model's `files`, the agent's final message, `session_id`, and in `next` the command that goes on changing the model.
A run that ends without `model.py` and `model.glb` has failed.

A model's directory holds `model.json`, which marks it as a model made by this tool and records each run: its prompt, status, process, last event, and session. Beside it are `model.py`, `model.glb`, `renders/`, `references/`, `sessions/` (a copy of each agent session), and `runs/<run id>/events.jsonl`.
From `model.json` and `events.jsonl` alone, a UX can tell a run that is working, one busy in a long command, one whose process is gone, and one that ended.

```python
def steer_3d_model(name: str, message: str, directory: Path | None = None) -> None
def cancel_3d_model(name: str, directory: Path | None = None) -> None
```

Steer or stop the run working on a model from any process. Each writes a file in the run's directory that the process running it acts on within a second. Both raise `Modeling3dError` when nothing is working on the model.

## List and view models

Deterministic. What a gallery of the models in a directory needs: each model's state and files, and the one the person viewed last.

```python
def list_3d_models(directory: Path | None = None) -> ModelListing
def view_3d_model(name: str, directory: Path | None = None) -> ModelSummary
```

`list_3d_models` only reads, so it is safe while runs write. `ModelListing` has the resolved `directory`, its `models` most recently updated first, `last_viewed`, and `unreadable`, one message for each `model.json` that could not be read, naming what is wrong. A directory that does not exist lists as empty; a file in its place raises `Modeling3dError`.
Each `ModelSummary` has `name`, `id`, `directory`, `created`, `updated` (when its last run last started, sent an event, or finished), `status`, `last_run` (that run's entry in `model.json`), and `files`. `status` is the last run's, or `crashed` when that run is `running` but its process is gone; the next run on the model marks it failed. Both are `None` for a model that never ran.

`view_3d_model` records the model as viewed last in `.state.json` in the models directory, and returns its summary. `name` must match the model's directory exactly; an unknown one raises `Modeling3dError` naming the models there. `last_viewed` is `None` when nothing was viewed, or that model is gone.

## Blender on PATH

Deterministic. Makes `blender` run an installed Blender from terminals opened afterward, for opening models in Blender. Building models does not need it.

```python
def add_blender_to_path(blender_path: Path | None = None) -> BlenderOnPath
```

`blender_path` is Blender's executable or its folder; without it, the newest Blender installed where the platform puts it. On Windows it adds Blender's folder to the user PATH in the registry; on macOS and Linux it links `~/.local/bin/blender`. When `blender` already runs one, nothing changes. `BlenderOnPath` holds the `executable`, whether anything `changed`, and a `message` saying what to do next.

## App

Its view is an [MCP App](https://github.com/modelcontextprotocol/ext-apps): one HTML file that speaks only to its host. It should be used for hosts that renders MCP Apps can show it inline, otherwise `app_server` should be used.

```python
def app_view() -> str
```

The view's HTML, compiled from `app/` and offered as the `ui://modeling-3d/app` resource in the MCP server. It sends the person's messages as `ui/message` and polls the `app_updates` tool for the agent's. Raises `Modeling3dError` naming the build command when the view is not compiled.

```python
def app_server(deliver: Callable[[str], None] | None = None) -> AppServer
```

The app's MCP server: `open_app`, `reply`, the app-only `app_updates` and `app_message`, and the view. `deliver` is called on a worker thread with each message the person sends from the browser page, and raises `OSError` when it cannot deliver; without it, or when it raises, the message comes back with the agent's next tool result.

```python
class AppServer:
    server: Server

    def open(self, port: int | None = None) -> App: ...
    def say(self, text: str) -> None: ...
    def updates(self, after: int = 0) -> list[str]: ...
    def close(self) -> None: ...
```

`server` is an MCP SDK low-level server to run over any transport; several at once share the state. `open` serves the browser host page on `127.0.0.1` from daemon threads and returns once it listens, or returns the one already open. The page reaches the same server at its own `/mcp` and renders the view behind a sandbox proxy on a second port, a separate origin as the MCP Apps spec requires. Without `port` a free one is chosen; a held one raises `Modeling3dError`. `say` adds to the agent's messages, which every open view shows on its next poll, and `updates` returns those past the first `after`. `close` stops serving. `App.url` is where to open the page.

## MCP server

The app's MCP server over stdio, a thin surface over the library like the CLI, in `modeling_3d.adapters.mcp`.

```python
def run_stdio() -> None
```

It runs `app_server().server` over stdio. Its `deliver` posts each message from the browser page into the inbox of the Claude Code session that launched it; where there is none, the message comes back with the next tool result.

## Manifest

The tool's `SMART_TOOL.md` as structured data: the frontmatter as fields, the Markdown below it as `Manifest.body`.

```python
def load_manifest() -> Manifest
```

## Skill

The agent skill for the given capability. Without providing a capability it return the overall skill text for this tool.

```python
def skill(capability: str | None = None) -> str
```

The valid values for `capability` are the names the tool's skill lists under `## Capabilities`. Any other name raises `Modeling3dError` listing the valid ones.

The installed package's version, from its metadata. The skill carries it too.

```python
def version() -> str
```

## Adding a capability

A capability's code goes in `modeling_3d/capabilities/<name>/`, with its prompts, templates, and its own skill, `skill_<capability>.md`, beside it, named on its row in `core/skill.py` `CAPABILITIES`, and `lib.py` gets a facade function that imports it and is the only caller of it.
Each capability of the library gets a section here: what it does and when to reach for it, the signature `lib.py` exposes, what each argument means, and what it returns or raises.
Model-backed capabilities say so, and take `agent_provider`, `model`, `reasoning_effort`, and `intelligence`. `model` defaults to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS` and `reasoning_effort` to `DEFAULT_REASONING_EFFORT`, both from `modeling_3d.schemas`.
