# Library Reference

Every capability of Modeling 3d is reachable from `modeling_3d.lib`.
All other surfaces, including the CLI, are thin wrappers over the library and add no capability of their own.

## Intelligence

Model-backed capabilities run through the `Intelligence` protocol in `modeling_3d.intelligence.interface`:

```python
class Intelligence(Protocol):
    implementation: str

    def preflight(self) -> None: ...
    def run(self, request: AgentRequest) -> AgentResult: ...
```

`preflight` raises `Modeling3dError` naming what to configure when the implementation cannot run.
`run` executes one agent: `AgentRequest` holds the prompt, model, optional workspace, and optional output schema; `AgentResult` holds the text, structured output, or error.
Setting `AgentRequest.resume` to an earlier `AgentResult.session_id` continues that session instead of starting a fresh one, so the agent keeps what it learned.

On `codex`, a request runs with full access and no approval prompts.

`resolve_intelligence(agent_provider)` returns a shipped implementation, one per agent provider, each installed through the extra of the same name:

- `codex`: `CodexIntelligence`, built on the [OpenAI Codex SDK](https://github.com/openai/codex/tree/main/sdk/python) and run with the user's Codex sign-in and `~/.codex/config.toml`. A session is a Codex thread, kept where Codex keeps its threads. An output schema is enforced by the model API in its strict form, every property required and an optional one nullable; the nulls are dropped before the answer is checked against the original schema.
- `claude`: `ClaudeIntelligence`, built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) and run with the user's Claude Code settings and the credentials Claude Code resolves: `ANTHROPIC_API_KEY`, or a cloud provider's, as [its docs](https://code.claude.com/docs/en/agent-sdk/quickstart) describe. Sessions are kept where Claude Code keeps them; a plain completion runs in the platform's per-user state directory, in `modeling-3d/claude`.

Without an agent provider named, the first installed in that order is used; one that is not installed raises `Modeling3dError` with the command that installs it.
`select_intelligence(intelligence, agent_provider, model, DEFAULT_INTELLIGENCE_MODELS)` is what a capability calls: an injected `intelligence` wins, and `model` falls back to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS`.
Another implementation is a module satisfying the protocol and a branch in that factory.

## App

A chat page on this machine where a person and an agent talk. Deterministic.

```python
def serve_app(on_message: Callable[[str], None] | None = None, port: int | None = None) -> App
```

Binds `127.0.0.1`, starts serving from a daemon thread, and returns once the port is listening. `on_message` is called on that thread with each message typed on the page. Without `port` a free one is chosen. Raises `Modeling3dError` when the port cannot be bound.

```python
class App:
    url: str

    def send(self, text: str) -> int: ...
    def stop(self) -> None: ...
```

`send` shows `text` as the agent's on every open page, from any thread, and returns how many are open. `stop` disconnects the pages and frees the port. A page from any other origin cannot connect, since it could otherwise type into a session.

## MCP server

The app as a Claude Code [channel](https://code.claude.com/docs/en/channels-reference) over stdio, a thin surface over the library like the CLI, in `modeling_3d.adapters.mcp`.

```python
def run_stdio() -> None
```

Its `open_app` tool calls `serve_app` and returns the URL, and `reply` calls `App.send`. Each message typed in the app is pushed to the session as a `notifications/claude/channel` notification. It stays on MCP SDK 1.x, since Claude Code does not register a channel that negotiates protocol revision 2026-07-28.

## Manifest

The tool's `SMART_TOOL.md` as structured data: the frontmatter as fields, the Markdown below it as `Manifest.body`.

```python
def load_manifest() -> Manifest
```

## Skill

What an agent reads once it has decided to drive the tool: the manifest body and the capability list, wrapped so the reader knows where the tool's files are.
Naming a capability returns that capability's own skill instead: the same wrapper, a heading carrying the capability's name, whether it is deterministic or model-backed, and the Markdown beside its code, which covers its arguments, a worked invocation, its result, and its failures.
The CLI's `--help` prints exactly this, the tool's at the root and the capability's on a command.
Raises `Modeling3dError` when the name is not a capability, naming the ones that are.

```python
def skill(capability: str | None = None) -> str
```

The capabilities the skill lists, one entry each, driven by the same table the CLI is built from:

```python
class Capability(NamedTuple):
    name: str
    summary: str
    model_backed: bool
    skill: str
    resources: tuple[str, ...] = ()
```

- `name` and `summary`: the command's name and its line in the tool's capability list.
- `model_backed`: whether it runs through the `Intelligence` interface, which decides the kind shown in both skills.
- `skill`: the capability's skill body, a Markdown file relative to `skill_directory()`, written without frontmatter, title, or kind line because the renderer supplies them.
- `resources`: the files that body refers to, relative to `skill_directory()`, listed under `<skill_resources>` in the capability's skill. The block is omitted when there are none.

The installed package root, resolved at runtime, where the files the skill names can be read.

```python
def skill_directory() -> Path
```

The files the skill lists under `<skill_resources>`, as paths relative to `skill_directory()`. Every one ships inside the package, so each resolves after installation.
The second does the same for one capability's skill, and raises `Modeling3dError` when the name is not a capability.

```python
def skill_resources() -> list[str]


def capability_skill_resources(capability: str) -> list[str]
```

The tool's canonical source, read from the package metadata's `[project.urls]` `Repository` entry, or `None` when the package declares none.
The skill carries it so a caller that can run the tool but not read its files still reaches the documentation.

```python
def repository_url() -> str | None
```

## Adding a capability

A capability's code goes in `modeling_3d/capabilities/<name>/`, with its prompts, templates, and its own `SKILL.md` beside it, named on its row in `core/skill.py` `CAPABILITIES`, and `lib.py` gets a facade function that imports it and is the only caller of it.
Each capability of the library gets a section here: what it does and when to reach for it, the signature `lib.py` exposes, what each argument means, and what it returns or raises.
Model-backed capabilities say so, and take `agent_provider`, `model`, `reasoning_effort`, and `intelligence`. `model` defaults to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS` and `reasoning_effort` to `medium`, both from `modeling_3d.schemas`.
