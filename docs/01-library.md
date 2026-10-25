# Library Reference

Every capability of 3D Modeling is reachable from `modeling_3d.lib`.
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
    async def steer(self, message: str, images: list[Path] | None = None) -> None: ...
    async def cancel(self) -> None: ...
    async def result(self) -> AgentResult: ...
```

`preflight` raises `Modeling3dError` naming what to configure when the implementation cannot run.
`start` starts one agent and returns once it runs. `AgentRequest` holds the prompt, any images to show with it, the model, an optional workspace, `skill_directories`, folders of Agent Skills the agent may use, and an optional `follow_up`. Failures after `start` end the run with `AgentResult.error` and never raise.
`follow_up` is asked each time the agent ends a turn with nothing queued. A message it gives goes on in the same session as a turn of its own, and `None` lets the run end.
`events` replays every event from the start, then live ones, ending with `terminal`. Each `AgentEvent` is one message from the agent provider as it gave it: its own name for the message in `type`, and its fields in `data`. No vocabulary is shared across agent providers.
`steer` sends a message, and any images with it, while the agent works. `steering` says how it lands: `mid-turn`, `queued` until the agent next reads input, or `restart`.
`cancel` stops the run at once, along with every command the agent started.
Setting `AgentRequest.resume` to an earlier `session_id` continues that session instead of starting a fresh one, so the agent keeps what it learned, even after a cancel. `AgentRequest.session_directory` also keeps a copy of the session there. On `claude` a resume can start from that copy alone; on `codex` the copy is for reading, and a resume needs the session where Codex keeps it.

`resolve_intelligence(agent_provider)` returns a shipped implementation, one per agent provider, each installed through the extra of the same name:

- `claude`: `ClaudeIntelligence`, built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) and run with the user's Claude Code settings and any of its other supported modes of [authentication](https://code.claude.com/docs/en/agent-sdk/quickstart). Steering is `queued`. It gets only the file and shell tools a run needs, so not Claude Code's tool for asking the user questions. Skills come as a local plugin named `modeling-3d`, with the `Skill` tool added and Claude Code's user, project, and local settings loaded. Sessions are kept where Claude Code keeps them; a plain completion runs in the platform's per-user state directory, in `modeling-3d/claude`.
- `codex`: `CodexIntelligence`, built on the [OpenAI Codex SDK](https://github.com/openai/codex/tree/main/sdk/python) and run with the user's Codex sign-in and configuration. Steering is `mid-turn`. A writable workspace runs without a sandbox and without approval prompts, as the agent runs tools such as Blender that write elsewhere. Its tool for asking the user questions is turned off. Skills come through the runtime's `skills/extraRoots/set`, which lasts as long as the run's own runtime, so nothing is written into the workspace. Sessions are kept where Codex keeps them, and copied into `session_directory` after each turn; a plain completion runs read-only in the platform's per-user state directory, in `modeling-3d/codex`.

Without an agent provider named, the first installed in that order is used; one that is not installed raises `Modeling3dError` with the command that installs it.
`select_intelligence(intelligence, agent_provider, model, DEFAULT_INTELLIGENCE_MODELS)` is what a capability calls: an injected `intelligence` wins, and `model` falls back to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS`.

## Create a 3D model

Model-backed. An agent creates a 3D model, or changes one, as a Blender script in the model's own directory: it writes `model.py`, builds `model.glb` with it, renders the result, looks at the renders, and fixes what does not match the request.
This is the model's shape, built from named parts in `model.py`, with each face's role recorded there, no materials unless the request asks for them, and small marks such as screws and seams left to its surface detail. Readying it to move, coloring it, and painting its surface detail are modes of their own, `rig_3d_model`, `color_3d_model`, and `detail_3d_model`. Each run records its mode, `shape` here, and a run never moves on to the next mode by itself. Changing the shape of a rigged, colored, or detailed model keeps its rig, colors, and detail working.
The agent is told not to stop and ask questions, since the person is likely not watching: where something is unclear, it chooses what serves the model and keeps going.
The agent runs in the working directory the tool was started in, usually the project the model is for, so it finds the project's docs, conventions, assets, and agent instructions. It may explore there, but writes only in the model's directory and runs commands from it, unless the work needs an exception, which it reports.
An `AGENTS.md` in `directory` is the project's guidance for its models. Neither agent provider loads it by itself, so a fresh session is told to read it, and the request decides over it.
A models directory the tool makes, or one holding only hidden files, gets a `.gitignore` of its own. It commits only `AGENTS.md` and each opted-in model's `model.json`, `model.py`, `validate.py`, and `README.md`, and a model is opted in with a line like `!/bear/`.
The agent has `check_3d_model` as a skill, run with this install's Python, and is told to check the model before it finishes. When it finishes without a check of the `model.glb` it left, the run checks it against the run's budgets and sends the agent the report to act on, at most once a run. A run that ends with an unchecked `model.glb` checks it once more for whoever looks next, without telling the agent.
`model.py` gets Blender from PyPI as an inline dependency and runs with `uv run --script`, so no Blender install is needed. Building runs on Windows, Linux x64, and macOS on Apple silicon.

```python
async def create_3d_model(
    prompt: str,
    name: str,
    directory: Path | None = None,
    references: list[Path] | None = None,
    max_triangles: int | NotGiven | None = NOT_GIVEN,
    max_draw_calls: int | NotGiven | None = NOT_GIVEN,
    screen_size: tuple[int, int] | NotGiven | None = NOT_GIVEN,
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
- `max_triangles`, `max_draw_calls`, `screen_size`: The budgets of the model: the most triangles, the most draw calls, one for each material on each mesh object, and the smallest and largest the model is on screen, in pixels along its longest side at 1080p.
  `None` is no budget. A budget left out, `NOT_GIVEN`, is a default for a new model, from `DEFAULT_MAX_TRIANGLES`, `DEFAULT_MAX_DRAW_CALLS`, and `DEFAULT_SCREEN_SIZE` in `modeling_3d.schemas`, and the model's own for a change. Choose them for what the model is for rather than leave the defaults.
  Each run keeps the budgets it worked to in `runs.json`. A continued session is sent only the budgets the request sets, unless it last worked in another mode, when it is sent all of them with this mode's advice. A model with no budgets gets no budget instructions. A budget below 1, or a smallest size above the largest, raises `Modeling3dError`.
- `resume_session`: The agent session to continue, for a model that exists.
  If `True`, the agent continues the last session of the model. Thus the agent remembers the conversation from the earlier runs.
  If it is a session ID, the agent continues that session of the model. If `False`, the agent starts a new session.
  To find a session ID, look at the runs of the model. Each run keeps its session ID in `session_id` in `runs.json`.
  `read_3d_model_activity` gives the session ID of each request, and `list_3d_models` gives the session ID of the last run.
  If the model does not have the session ID, the request stops before the agent starts.
  A session that last worked in another mode can go on, and is told this mode's instructions, which it has not had.
- `agent_provider`: The service that runs the agent: `claude` or `codex`.
  If you do not give an agent provider, the tool uses the first one that is installed.
  When the agent continues a session, the tool uses the agent provider of that session, and another one raises `Modeling3dError`. Another model of the same agent provider can continue it.
- `model`: The AI model that the agent uses. If you do not give a model, the tool uses the default for the agent provider, from `DEFAULT_INTELLIGENCE_MODELS`.
- `reasoning_effort`: How much the AI model thinks before it acts: `low`, `medium`, `high`, `xhigh`, or `max`, and also `ultra` on `codex` models. The default is `medium`. `list_intelligence_models` gives the efforts each model takes; one the model does not take raises `Modeling3dError`.
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
Each `ModelEvent` has a `kind`: `started` (its `data` holding the request, with its `mode`), `agent` (one `AgentEvent`, as given, except that of the Claude stream only `composing` is kept, how far a tool call the agent is writing out has got, about once a second), `steered`, `checked` (the report of the check sent to the agent as it finished, in `text`, and in `data` the `report` path, or the `error` that stopped it), `finished`, or `failed`. The last carries the `ModelResult`: `status` (`done`, `failed`, `cancelled`, or `timed-out`), the model's `files`, the agent's final message, `session_id`, and in `next` the command that goes on changing the model in the same session and mode.
A run that ends without `model.py` and `model.glb` has failed.
`stopped_by_signals(run)` is a context manager for a process that waits on a run: inside it, every signal that ends the process, such as Ctrl+C or its console closing, stops the run first, so its session stays resumable and nothing its agent started outlives it.

A model's directory holds `model.json`, which marks it as a model made by this tool, and `runs.json`, which records each run: its mode, prompt, origin, status, process, last event, and session. A project commits `model.json` and leaves out `runs.json`, which changes with every event, so a model cloned without it has no runs. A run recorded before modes reads as `shape`. Beside them are `model.py`, `model.glb`, `renders/`, `references/`, `checks/` (the latest report of `check_3d_model`, with its renders), `sessions/` (a copy of each agent session), and `runs/<run id>/` with `events.jsonl` and, for a detached run, `process.log`, what its process printed.
From `runs.json` and `events.jsonl` alone, a UX can tell a run that is working, one busy in a long command, one whose process is gone, and one that ended.

```python
def steer_3d_model(
    name: str,
    message: str,
    directory: Path | None = None,
    origin: str | None = None,
    references: list[Path] | None = None,
) -> None
def cancel_3d_model(name: str, directory: Path | None = None) -> None
```

- `name`: The name of the model that the agent works on now.
- `message`: The text to send to the agent.
- `directory`: The directory that holds the models. If you do not give a directory, the tool uses `.modeling-3d` in the working directory.
- `origin`: A label that tells who sent the message, as for `create_3d_model`. The activity of the model shows it with the message.
- `references`: Files or folders to send with the message. They are copied into the model's `references/` as for `create_3d_model`, and named to the agent with the message. Images are also shown to it. The `steered` entry in the activity lists them as `references`.

Steer or stop the run working on a model from any process. Each writes a file in the run's directory that the process running it acts on within a second. The `steered` event of a message carries its `origin`. Both raise `Modeling3dError` when nothing is working on the model.

## Rig a 3D model

Model-backed. An agent rigs a model that `create_3d_model` has built, so it can move. It changes the model's `model.py` and leaves its shape alone unless asked.
Each part that moves on its own, or can be hidden or swapped for another, becomes its own named object, with its origin at its pivot and its motion declared as `check_3d_model` reads it. What bends gets a skeleton, every other part is joined into one object, and named empties mark the points other code uses. A model with nothing that moves comes out with its parts joined and its points marked.
When separate objects would go over the draw call budget, the moving parts stay in one mesh, each moved by a bone of its own. Parts that are hidden or swapped stay their own objects even then, since a bone cannot hide what it moves.
The run works to the model's own budgets, records its mode as `rig`, and ends once the model is rigged. Otherwise it is a run like those of `create_3d_model`: the agent has the check as a skill and is checked as it finishes, is told not to stop and ask questions, and the run is steered, stopped, followed, detached, and continued the same ways.

```python
async def rig_3d_model(
    name: str,
    prompt: str | None = None,
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

- `name`: The name of a model in `directory` that has been built, ignoring case. A model that does not exist, or has no `model.glb` yet, raises `Modeling3dError`.
- `prompt`: What moves and how, or what to change in the rig. If you do not give a prompt, the agent works out what moves from the model, its references, and the project's guidance, and the run records an empty prompt.
- `resume_session`: The agent session to continue, as for `create_3d_model`. A session that last shaped the model is told the rig's instructions as it goes on.
- The other arguments are as for `create_3d_model`.

It returns a `ModelRun` as `create_3d_model` does, and the result's `next` names `rig-3d-model`. A rig keeps the colors of a colored model working.

## Color a 3D model

Model-backed. An agent colors a model that `create_3d_model` has built, by role, in its `model.py`, and leaves its shape and rig alone unless asked, apart from cutting a face where a color changes.
Every mesh gets one material whose base color texture is a palette: a column for each role and a row for each color scheme, embedded in `model.glb` and sampled nearest. Each face's UVs land on the center of its role's swatch in the default scheme's row, so an app shows another scheme by moving the UVs a row. The roles that glow go in an emission palette of the same layout, and the material declares the roles and schemes as `check_3d_model` reads them.
The agent uses the project's roles and schemes where its guidance names them, adds a scheme as a new row, may move a part to another role, renders with Blender's Standard view transform, and finishes by listing each role's color in each scheme it set or changed.
The run works to the model's own budgets, records its mode as `color`, and ends once the model is colored. Otherwise it is a run like those of `create_3d_model`.

```python
async def color_3d_model(
    name: str,
    prompt: str | None = None,
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

- `name`: The name of a model in `directory` that has been built, ignoring case. A model that does not exist, or has no `model.glb` yet, raises `Modeling3dError`.
- `prompt`: The roles, schemes, or colors wanted, or what to change in them. If you do not give a prompt, the agent works them out from the model, its references, and the project's guidance, and the run records an empty prompt.
- `resume_session`: The agent session to continue, as for `create_3d_model`. A session that last worked in another mode is told the coloring's instructions as it goes on.
- The other arguments are as for `create_3d_model`.

It returns a `ModelRun` as `create_3d_model` does, and the result's `next` names `color-3d-model`.

## Paint a 3D model's surface detail

Model-backed. An agent paints the surface detail of a model that `create_3d_model` has built, in its `model.py`, and leaves its shape, rig, and colors alone unless asked.
It paints one grayscale texture from the geometry, such as seams, fasteners, highlights along edges, and wear, with seeded noise so every build paints the same marks. The faces it covers are unwrapped on the second set of texture coordinates at a density set by the largest size on screen, and every other face points at a neutral patch. The texture is saved beside `model.glb` as `model-detail.png`, since glTF has no place for it, and the material declares it as `check_3d_model` reads it.
A renderer multiplies the base color by twice the detail, so mid gray leaves a color as it is, and one texture works in every color scheme. The agent follows the project's guidance on how much to paint, renders with the detail applied as a renderer will, and finishes by listing what it painted where.
The run works to the model's own budgets, records its mode as `detail`, and ends once the detail is painted. Otherwise it is a run like those of `create_3d_model`.

```python
async def detail_3d_model(
    name: str,
    prompt: str | None = None,
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

- `name`: The name of a model in `directory` that has been built, ignoring case. A model that does not exist, or has no `model.glb` yet, raises `Modeling3dError`.
- `prompt`: The detail wanted, or what to change in it. If you do not give a prompt, the agent works out what the model would show from the model, its references, and the project's guidance, and the run records an empty prompt.
- `resume_session`: The agent session to continue, as for `create_3d_model`. A session that last worked in another mode is told the detailing's instructions as it goes on.
- The other arguments are as for `create_3d_model`.

It returns a `ModelRun` as `create_3d_model` does, and the result's `next` names `detail-3d-model`.

## Check a 3D model

Deterministic. Measures a model's `model.glb` against its budgets and the modeling workflow, for the agent building it or the person to decide what to act on. It is informational only: each check reports what it measured, and nothing passes or fails.

```python
def check_3d_model(
    name: str,
    directory: Path | None = None,
    checks: list[str] | None = None,
    max_triangles: int | NotGiven | None = NOT_GIVEN,
    max_draw_calls: int | NotGiven | None = NOT_GIVEN,
    screen_size: tuple[int, int] | NotGiven | None = NOT_GIVEN,
) -> ModelCheck
```

- `name`: The name of the model. It must be the same as the name of its directory, with the same upper case and lower case letters.
- `directory`: The directory that holds the models. If you do not give a directory, the tool uses `.modeling-3d` in the working directory.
- `checks`: The checks to run, by name or by group, `shape`, `rig`, `color`, or `detail`, as `CHECK_NAMES` and `CHECK_GROUPS` in `modeling_3d.schemas` list them. If you do not give checks, every check runs. An unknown name raises `Modeling3dError`, which lists the valid ones.
- `max_triangles`, `max_draw_calls`, `screen_size`: The budgets to measure against, as for `create_3d_model`. A budget left out is the model's own, the one its last run's prompt was given, and `None` is no budget. The defaults a new model gets are never used.

The shape checks are `triangles`; `sub-pixel`, triangles under a pixel at the smallest size on screen; `round-parts`, how far smooth shaded curves stray from true ones at the largest size, and where; `buried-faces`, triangles no ray from outside reaches, and where; and `on-screen`, renders at both sizes, scaled up beside the model's image references.
The rig checks are `draw-calls`, counting each swap group once, as its costliest part, since one of its parts shows at a time; `static-parts`, the mesh objects that neither move nor have a skin; `moving-parts`, each declared motion and anything its part touches through its range that it does not touch at rest; `skeleton`; `markers`, empties with nothing under them; and `poses`, renders of each motion. Parts moved by bones are described but not swept or posed. A check is skipped, saying why, when what it measures is absent, such as a budget, a motion, a palette, or a detail texture.

A part that moves declares its motion as a `motion` custom property exported as glTF extras, on its object, or on its bone for a part a bone moves: `slide` or `hinge` with an `axis` and a `range`, `spin` with an `axis`, `swap` with a `group`, or `hide`. Axes are in glTF's axes, in the parent's space, through the part's origin. glTF loaders such as three.js and Godot keep them on the node, so whatever loads the model can read them too.

The color checks read the palette, the base color texture most triangles are drawn with, as a column for each role and a row for each scheme. `palette` gives each swatch's color in each scheme, how the texture is sampled, the parts drawn with another material, and the swatches that changed since the last check; `face-roles`, the role each triangle's UVs land on, each role's share of the surface and its parts, and the triangles that land across swatches, off a swatch's center, or outside the palette; `emission`, the roles the emission palette lights; and `schemes`, renders in each scheme, lit flat so each face shows its swatch's color as stored.
The palette's material declares its `roles` and `schemes` in a `palette` custom property exported as glTF extras. Without one, each pixel is a swatch, named by its place. PNG palettes are read in Python.

The detail checks read the grayscale texture a material names in a `detail` custom property exported as glTF extras, beside `model.glb`, on the second set of texture coordinates. `detail-texture` gives its size, bit depth, channels, and chunks that would make a loader treat it as color; `detail-uvs`, where each triangle lands on it, each part's and each role's share of the surface with detail, its texels a meter and a pixel at the largest size on screen, how many texels a pixel spans at the smallest, and the triangles that are stretched or share texels; `detail-colors`, the detail's range under each role and the darkest and lightest color it shades the role to in each scheme, and how much clips at full brightness; and `detail-renders`, renders lit flat without the detail and with it, the detail alone on mid gray, and the texture with its islands outlined. A texture no material declares is not read.

What needs only the mesh is read from the GLB in Python. Buried faces, sweeps, the detail under each role, and renders run a Blender script through `uv run --script` with `BPY_REQUIREMENT` from `modeling_3d.schemas`, which downloads bpy the first time. When Blender cannot run, those checks are skipped with why, and the rest still report. It reads the exported `model.glb`, writes only in the model's `checks/`, and never writes `model.json` or `runs.json`, so it can run while an agent works on the model.

`ModelCheck` has `name`, `directory`, `checked`, `glb_sha256` (the `model.glb` it checked, to tell whether it has changed since), the budgets it used, `dimensions` and `bounds` in meters along glTF's axes, the counts of `triangles`, `mesh_objects`, and `materials`, and `checks`. Each `CheckResult` has `name`, a one line `summary`, whether it was `skipped`, `lines` for each part measured, `figures`, and `files`, its renders relative to the model's directory. The report is also kept in `checks/report.json`.

## List and view models

Deterministic. What a gallery of the models in a directory needs: each model's state and files, and the one the person viewed last.

```python
def list_3d_models(directory: Path | None = None) -> ModelListing
def view_3d_model(name: str, directory: Path | None = None) -> ModelSummary
```

- `directory`: The directory that holds the models. If you do not give a directory, the tool uses `.modeling-3d` in the working directory. If the directory does not exist, the list is empty.
- `name`: For `view_3d_model`, the name of the model to record. It must be the same as the name of its directory, with the same upper case and lower case letters.

`list_3d_models` only reads, so it is safe while runs write. `ModelListing` has the resolved `directory`, its `models` most recently updated first, `last_viewed`, and `unreadable`, one message for each model whose `model.json` or `runs.json` could not be read, naming what is wrong. A file in place of the directory raises `Modeling3dError`.
Each `ModelSummary` has `name`, `id`, `directory`, `created`, `updated` (when its last run last started, sent an event, or finished), `built` (when `model.glb` was last written, `None` before the first build), `checked` (when its latest check, `checks/report.json`, was written, `None` before the first), `status`, `last_run` (that run's entry in `runs.json`), `last_session` (the entry of the latest run with a session, the one `resume_session=True` continues), `resumable` (whether a run on this machine can continue that session), `files`, and `references`, every reference its runs were given. `status` is the last run's, or `crashed` when that run is `running` but its process is gone; the next run on the model marks it failed. `status`, `last_run`, and `last_session` are `None` for a model that never ran, and `resumable` is false.

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
Each `ActivityEntry` has `time`, `run_id`, `kind`, `text`, `origin`, and `data`. `kind` is `request` (a run's prompt, empty for a rig, coloring, or detailing asked for nothing in particular, with its `mode`, `references`, `resumed`, `agent_provider`, `model`, and `session_id`), `said` (the agent's words), `reasoning` (the agent started reasoning, as soon as it did), `thought` (the summary of that reasoning, when the agent gave one), `composing` (a call the agent is still writing out, with `id`, `name`, `target` once that much is written, and `characters` so far; only `claude` reports these), `tool` (a call, with `id`, `name`, and `target`, what it works on), `tool-result` (the end of the call with that `id`, and whether it `failed`), `usage` (at the end of each turn, what the session has used in all so far, with its `session_id`: `cost_usd` on `claude`, `tokens` on `codex`, which reports no cost; a resumed session's total includes its earlier runs), `steered` (with the `references` sent with it, if any), `checked` (the report of the check sent to the agent as its run finished, with `report` where it is kept, or the `error` that stopped it), or `ended` (`status`, `error`, and `files`). `origin` is who sent a request or steering message.
The activity is the one view of a run that every agent provider shares. Each provider's events stay in `events.jsonl` as it gave them, and `interface.agent_steps(agent_provider)` reads them into `said`, `reasoning`, `thought`, `composing`, `tool`, `tool-result`, and `usage`.

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
It can also show the renders the agent made, in a strip with the one picked large below; the model's latest check, read again whenever `checked` changes, by group, with each check's renders, whether `model.glb` changed since, and a button that checks it again; and the model's size and makeup, computed from the loaded GLB for display only.
Its rig view marks each marker and the pivot of each part that slides or turns, draws the path of each slide and the axis of each turn, and poses the model: a slider for each slide, hinge, and spin over its range, a switch for each part that can be hidden, and a pick of the part each swap group shows. A part a bone moves is hidden by shrinking its bone, since hiding a bone leaves the mesh skinned to it drawn.
A detail texture the model's materials declare shades it as a renderer would, its base color times twice the detail, whichever view is on.
Its surface view shows the model's colors and detail together, or either alone, the detail on mid gray. It reads the palette from the loaded GLB as the check does, with the roles and schemes its material declares, lists each role's swatch, color, and triangles, and what glows, and gives the detail texture's size and texels a meter. It shows another scheme by repeating that scheme's row down a copy of the palette, picks out a role hovered in the list by fading the rest, marks the role under the pointer on the model, and draws the colors unlit when Flat is on. A color tried on a swatch shows on the model at once, and Send puts the colors tried in the composer in Color mode, each from its color to the one tried. Nothing it does changes the model.
Beside the model it shows the model's activity, polled from `read_3d_model_activity`, with each run's mode and the check sent to its agent as it finished. The person creates a model there from a prompt, files, and models in the directory; asks for a change in the mode they pick, Shape, Rig, Color, or Detail, which starts as the mode of the model's last run, with a rig, coloring, or detailing needing no prompt; continues the model's session unless they switch that off, pick a model of another agent provider, or switch to a mode other than the session's; steers a run, with images too; and stops one. Boxes the person draws on the 3D view, with a note on each, go into the message as images with their notes, to send from there. Each step opens to the call in full from `read_3d_model_tool_call`, a few lines at first and all of it on request. Reference images and the images the agent looked at open large, and the model's folder opens in the person's file manager. Under the composer it totals what the agents' sessions on the model have cost, or used in tokens, from `usage`. The view calls the capabilities for each, as from `app`, and sends nothing to any session.

```python
def app_server(directory: Path | None = None) -> AppServer
```

- `directory`: The directory that holds the models that the app shows. If you do not give a directory, the tool uses `.modeling-3d` in the working directory. The `open_app` tool can change it.

The app's MCP server: `open_app`; the app-only `list_3d_models`, `view_3d_model`, `create_3d_model`, `rig_3d_model`, `steer_3d_model`, `cancel_3d_model`, `read_3d_model_activity`, and `read_3d_model_tool_call`, each the library's on the app's directory with origin `app`; the app-only `check_3d_model`, the library's against the model's own budgets, which returns `{"checking": true}` for a check still going after a while, so that a call never outlasts what a host waits for, and waits on the same check when called again; the app-only `list_intelligence_models` and `choose_intelligence_model`, the picker's options and the person's last pick, kept in `.app.json` in the app's directory; the app-only `read_app_settings` and `save_app_settings`, the person's theme, pane sizes, viewport tools, and the groups of steps they opened or closed in each model's activity, kept for every directory in `app-settings.json` in their config directory; the app-only `read_app_folders` and `open_app_folder`, which name where those are kept and open the settings folder, the app's directory, or a model's folder in the person's file manager; the view; and each model's GLB, renders, and reference images as base64 blob resources at `modeling-3d://models/{name}/{+path}`. Only the files a model's summary lists in `files` and `references`, and the files in the folders it lists there, and of those only the GLB and images, can be read, along with its latest check's `checks/report.json` and the renders beside it. Its `create_3d_model` and `rig_3d_model` always detach, so runs outlive the server. The app-only `upload_reference` takes each file or folder the person adds in pieces, under an upload id of the view's, and `create_3d_model`, `rig_3d_model`, and `steer_3d_model` name the uploads to send, so no request outgrows what the transport takes. Uploads no request took are cleared when the server closes, or a day on by the next to start.

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

A capability's code goes in `modeling_3d/capabilities/<name>/`, with its prompts, templates, and its own skill, `skill_<capability>.md`, anywhere under that folder. The skill is named on the capability's row in `core/skill.py` `CAPABILITIES`, and `lib.py` gets a facade function that imports the capability and is the only caller of it.
Each capability of the library gets a section here: what it does and when to reach for it, the signature `lib.py` exposes, what each argument means, and what it returns or raises.
Model-backed capabilities say so, and take `agent_provider`, `model`, `reasoning_effort`, and `intelligence`. `model` defaults to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS` and `reasoning_effort` to `DEFAULT_REASONING_EFFORT`, both from `modeling_3d.schemas`.
