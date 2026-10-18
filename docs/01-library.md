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
    resume_session: bool | str = False,
    agent_provider: AgentProvider | None = None,
    model: str | None = None,
    reasoning_effort: ReasoningEffort = "medium",
    timeout_seconds: int = 3600,
    origin: str | None = None,
    detach: bool = False,
    intelligence: Intelligence | None = None,
) -> ModelRun
```

- `prompt`: The text that tells the agent what to do. For a new model, it tells what to build. For a model that exists, it tells what to change.
- `name`: The name of the model. The model is in a directory with this name, in `directory` which must be unique.
  If a model with this name exists, the tool works with that model. If not, the tool makes a new model.
- `directory`: The directory that holds the models. If you do not give a directory, the tool uses `.modeling-3d` in the working directory.
- `references`: Files and folders that the agent uses as examples, such as images, 3D models, or a folder of them.
  To use another model as an example, give its files, such as its `model.py`, its `model.glb`, and a render.
  The tool copies each into `references/` in the directory of the model, a folder whole but for its hidden folders, `node_modules`, and `__pycache__`.
  The agent also sees each image given as a file with the prompt.
- `resume_session`: The agent session to continue, for a model that exists.
  If `True`, the agent continues the last session of the model. Thus the agent remembers the conversation from the earlier runs.
  If it is a session ID, the agent continues that session of the model. If `False`, the agent starts a new session.
  To find a session ID, look at the runs of the model. Each run keeps its session ID in `session_id` in `model.json`.
  `read_3d_model_activity` gives the session ID of each request, and `list_3d_models` gives the session ID of the last run.
  If the model does not have the session ID, the request stops before the agent starts.
- `agent_provider`: The service that runs the agent: `claude` or `codex`. At this time, only `claude` can run agents.
  If you do not give an agent provider, the tool uses the first one that is installed.
  When the agent continues a session, the tool uses the agent provider of that session.
- `model`: The AI model that the agent uses. If you do not give a model, the tool uses the default for the agent provider, from `DEFAULT_INTELLIGENCE_MODELS`.
- `reasoning_effort`: How much the AI model thinks before it acts: `low`, `medium`, `high`, `xhigh`, or `max`. The default is `medium`.
- `timeout_seconds`: The maximum time for the run, in seconds. After this time, the tool stops the run.
  You can continue the session of a stopped run later. The default is 3600, one hour.
- `origin`: A label that tells who sent the request. The tool keeps the label with the run. The activity of the model shows the label with the request.
  The app uses `app`. A Claude Code session uses `claude-code:<session id>`. Other callers can use their own label.
- `detach`: If `True`, the run occurs in a separate process. That process continues when the caller stops.
  The function still returns when the agent starts. If the request cannot start, the function still raises `Modeling3dError`.
  You cannot use `detach` with `intelligence`.
- `intelligence`: An object that runs the agent in place of the agent provider. Tests use it to replace the agent with a fake agent.
  You cannot use it with `detach`, because the separate process cannot get the object.

It returns once the agent runs. `ModelRun` is a protocol with `name`, `directory`, `run_id`, and `session_id`, and the same `events`, `steer`, `cancel`, and `result` as an `AgentRun`. A detached run's handle follows the run through its files: its events from `events.jsonl`, steering and stopping as `steer_3d_model` and `cancel_3d_model` do, and its result once it ends. Steering through a handle is from the run's `origin`.
Each `ModelEvent` has a `kind`: `started` (its `data` holding the request), `agent` (one `AgentEvent`, as given, except that of the Claude stream only `composing` is kept, how far a tool call the agent is writing out has got, about once a second), `steered`, `finished`, or `failed`. The last carries the `ModelResult`: `status` (`done`, `failed`, `cancelled`, or `timed-out`), the model's `files`, the agent's final message, `session_id`, and in `next` the command that goes on changing the model.
A run that ends without `model.py` and `model.glb` has failed.

A model's directory holds `model.json`, which marks it as a model made by this tool and records each run: its prompt, origin, status, process, last event, and session. Beside it are `model.py`, `model.glb`, `renders/`, `references/`, `sessions/` (a copy of each agent session), and `runs/<run id>/` with `events.jsonl` and, for a detached run, `process.log`, what its process printed.
From `model.json` and `events.jsonl` alone, a UX can tell a run that is working, one busy in a long command, one whose process is gone, and one that ended.

```python
def steer_3d_model(name: str, message: str, directory: Path | None = None, origin: str | None = None) -> None
def cancel_3d_model(name: str, directory: Path | None = None) -> None
```

- `name`: The name of the model that the agent works on now.
- `message`: The text to send to the agent.
- `directory`: The directory that holds the models. If you do not give a directory, the tool uses `.modeling-3d` in the working directory.
- `origin`: A label that tells who sent the message, as for `create_3d_model`. The activity of the model shows it with the message.

Steer or stop the run working on a model from any process. Each writes a file in the run's directory that the process running it acts on within a second. The `steered` event of a message carries its `origin`. Both raise `Modeling3dError` when nothing is working on the model.

## List and view models

Deterministic. What a gallery of the models in a directory needs: each model's state and files, and the one the person viewed last.

```python
def list_3d_models(directory: Path | None = None) -> ModelListing
def view_3d_model(name: str, directory: Path | None = None) -> ModelSummary
```

- `directory`: The directory that holds the models. If you do not give a directory, the tool uses `.modeling-3d` in the working directory. If the directory does not exist, the list is empty.
- `name`: For `view_3d_model`, the name of the model to record. It must be the same as the name of its directory, with the same upper case and lower case letters.

`list_3d_models` only reads, so it is safe while runs write. `ModelListing` has the resolved `directory`, its `models` most recently updated first, `last_viewed`, and `unreadable`, one message for each `model.json` that could not be read, naming what is wrong. A file in place of the directory raises `Modeling3dError`.
Each `ModelSummary` has `name`, `id`, `directory`, `created`, `updated` (when its last run last started, sent an event, or finished), `built` (when `model.glb` was last written, `None` before the first build), `status`, `last_run` (that run's entry in `model.json`), `files`, and `references`, every reference its runs were given. `status` is the last run's, or `crashed` when that run is `running` but its process is gone; the next run on the model marks it failed. Both are `None` for a model that never ran.

`view_3d_model` records the model as viewed last in `.state.json` in the models directory, and returns its summary. An unknown name raises `Modeling3dError` naming the models there. `last_viewed` is `None` when nothing was viewed, or that model is gone.

## Read a model's activity

Deterministic. Everything about how a model is being made, for a session picking up work it did not start, and for the app beside the model.

```python
def read_3d_model_activity(name: str, directory: Path | None = None, after: str | None = None) -> ModelActivity
```

- `name`: The name of the model. It must be the same as the name of its directory, with the same upper case and lower case letters.
- `directory`: The directory that holds the models. If you do not give a directory, the tool uses `.modeling-3d` in the working directory.
- `after`: The `cursor` from an earlier read. If you give it, you get only the activity that occurred after that read. If you do not give it, you get all the activity.
  A cursor that is not from this model raises `Modeling3dError`.

`ModelActivity` has `model`, the model's summary as `list_3d_models` gives it, its activity across every run in `entries`, and a `cursor`. It only reads, so it is safe while runs write, and a read past a cursor takes only what was written since.
Each `ActivityEntry` has `time`, `run_id`, `kind`, `text`, `origin`, and `data`. `kind` is `request` (a run's prompt, with `references`, `resumed`, `agent_provider`, `model`, and `session_id`), `said` (the agent's words), `reasoning` (the agent started reasoning, as soon as it did), `thought` (the summary of that reasoning, when the agent gave one), `composing` (a call the agent is still writing out, with `id`, `name`, `target` once that much is written, and `characters` so far), `tool` (a call, with `id`, `name`, and `target`, what it works on), `tool-result` (the end of the call with that `id`, and whether it `failed`), `usage` (at the end of each turn, what the session has cost in all so far, `cost_usd`, with its `session_id`; a resumed session's total includes its earlier runs), `steered`, or `ended` (`status`, `error`, and `files`). `origin` is who sent a request or steering message.
The activity is the one view of a run that every agent provider shares. Each provider's events stay in `events.jsonl` as it gave them, and `interface.agent_steps(agent_provider)` reads them into `said`, `reasoning`, `thought`, `composing`, `tool`, `tool-result`, and `usage`; Codex has no reader yet.

```python
def read_3d_model_tool_call(name: str, run_id: str, call_id: str, directory: Path | None = None) -> ToolCall
```

- `name`: The name of the model, as for `read_3d_model_activity`.
- `run_id`: The `run_id` of the call's `tool` entry in the model's activity.
- `call_id`: The `id` in that entry's `data`.
- `directory`: The directory that holds the models, as for `read_3d_model_activity`.

The activity names each call only by what it works on. `ToolCall` is the call in full: the tool's `name`, the `input` it was called with, the `output` that came back as text with any images left out, or `None` while it runs, and whether it `failed`. A call the run does not have raises `Modeling3dError`. `interface.agent_tool_call(agent_provider)` reads it from the run's events.

## Blender on PATH

Deterministic. Makes `blender` run an installed Blender from terminals opened afterward, for opening models in Blender. Building models does not need it.

```python
def add_blender_to_path(blender_path: Path | None = None) -> BlenderOnPath
```

- `blender_path`: The Blender program, or the folder that holds it. If you do not give a path, the tool finds the newest Blender in the usual location for the platform.

On Windows it adds Blender's folder to the user PATH in the registry; on macOS and Linux it links `~/.local/bin/blender`. When `blender` already runs one, nothing changes. `BlenderOnPath` holds the `executable`, whether anything `changed`, and a `message` saying what to do next.

## App

Its view is an [MCP App](https://github.com/modelcontextprotocol/ext-apps): one HTML file that speaks only to its host. It should be used for hosts that renders MCP Apps can show it inline, otherwise `app_server` should be used.

```python
def app_view() -> str
```

The view's HTML, compiled from `app/` and offered as the `ui://modeling-3d/app` resource in the MCP server. Raises `Modeling3dError` naming the build command when the view is not compiled.
It shows the models in the server's directory: it polls `list_3d_models`, opens on `last_viewed`, and renders the model in view in 3D, reading its GLB again whenever `built` changes. Picking a model calls `view_3d_model`. It switches models on its own when `last_viewed` changes to one it did not pick, so `view_3d_model` from anywhere brings a model up, and when a new model appears.
It can also show the renders the agent made, in a strip with the one picked large below, and the model's size and makeup, computed from the loaded GLB for display only.
Beside the model it shows the model's activity, polled from `read_3d_model_activity`. The person creates a model there from a prompt, files, and models in the directory; asks for a change, continuing the model's session unless they switch that off; and steers or stops a run. Each step opens to the call in full from `read_3d_model_tool_call`, a few lines at first and all of it on request. Reference images and the images the agent looked at open large, and the model's folder opens in the person's file manager. Under the composer it totals what the agents' sessions on the model have cost, from `usage`. The view calls the capabilities for each, as from `app`, and sends nothing to any session.

```python
def app_server(directory: Path | None = None) -> AppServer
```

- `directory`: The directory that holds the models that the app shows. If you do not give a directory, the tool uses `.modeling-3d` in the working directory. The `open_app` tool can change it.

The app's MCP server: `open_app`; the app-only `list_3d_models`, `view_3d_model`, `create_3d_model`, `steer_3d_model`, `cancel_3d_model`, `read_3d_model_activity`, and `read_3d_model_tool_call`, each the library's on the app's directory with origin `app`; the app-only `list_intelligence_models` and `choose_intelligence_model`, the picker's options and the person's last pick, kept in `.app.json` in the app's directory; the app-only `read_app_settings` and `save_app_settings`, the person's theme, pane sizes, viewport tools, and the groups of steps they opened or closed in each model's activity, kept for every directory in `app-settings.json` in their config directory; the app-only `read_app_folders` and `open_app_folder`, which name where those are kept and open the settings folder, the app's directory, or a model's folder in the person's file manager; the view; and each model's GLB, renders, and reference images as base64 blob resources at `modeling-3d://models/{name}/{+path}`. Only the files a model's summary lists in `files` and `references`, and the files in the folders it lists there, and of those only the GLB and images, can be read. Its `create_3d_model` always detaches, so runs outlive the server. The app-only `upload_reference` takes each file or folder the person adds in pieces, under an upload id of the view's, and `create_3d_model` names the uploads to work from, so no request outgrows what the transport takes. Uploads no request took are cleared when the server closes, or a day on by the next to start.

```python
class AppServer:
    server: Server
    directory: Path

    def open(self, port: int | None = None) -> App: ...
    def close(self) -> None: ...
```

- `port`: The port for the browser page, on `127.0.0.1`. If you do not give a port, the tool selects a free port. If another program uses the port, `open` raises `Modeling3dError`.

`server` is an MCP SDK low-level server to run over any transport; several at once share the state. `open` serves the browser host page on `127.0.0.1` from daemon threads and returns once it listens, or returns the one already open. The page reaches the same server at its own `/mcp` and renders the view behind a sandbox proxy on a second port, a separate origin as the MCP Apps spec requires. `close` stops serving. `App.url` is where to open the page.

## MCP server

The app's MCP server over stdio, a thin surface over the library like the CLI, in `modeling_3d.adapters.mcp`.

```python
def run_stdio(directory: Path | None = None) -> None
```

- `directory`: The directory that holds the models that the app shows, as for `app_server`.

It runs `app_server(directory=directory).server` over stdio. Nothing the person does in the app is sent to the session; the server's instructions point it at `list_3d_models` and `read_3d_model_activity`.

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

- `capability`: The name of one capability, as the tool's skill lists it under `## Capabilities`.
  If you give a name, you get the skill of that capability. If you do not give a name, you get the skill of the tool.
  An unknown name raises `Modeling3dError`, which lists the valid names.

The installed package's version, from its metadata. The skill carries it too.

```python
def version() -> str
```

## Adding a capability

A capability's code goes in `modeling_3d/capabilities/<name>/`, with its prompts, templates, and its own skill, `skill_<capability>.md`, beside it, named on its row in `core/skill.py` `CAPABILITIES`, and `lib.py` gets a facade function that imports it and is the only caller of it.
Each capability of the library gets a section here: what it does and when to reach for it, the signature `lib.py` exposes, what each argument means, and what it returns or raises.
Model-backed capabilities say so, and take `agent_provider`, `model`, `reasoning_effort`, and `intelligence`. `model` defaults to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS` and `reasoning_effort` to `DEFAULT_REASONING_EFFORT`, both from `modeling_3d.schemas`.
