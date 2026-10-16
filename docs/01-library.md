# Library Reference

Every capability of Modeling 3D is reachable from `modeling_3d.lib`.
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
`run` executes one agent: `AgentRequest` holds the prompt, model, and optional workspace; `AgentResult` holds the text or error.
Setting `AgentRequest.resume` to an earlier `AgentResult.session_id` continues that session instead of starting a fresh one, so the agent keeps what it learned.

On `codex`, a request runs with full access and no approval prompts.

`resolve_intelligence(agent_provider)` returns a shipped implementation, one per agent provider, each installed through the extra of the same name:

- `codex`: `CodexIntelligence`, built on the [OpenAI Codex SDK](https://github.com/openai/codex/tree/main/sdk/python) and run with the user's Codex sign-in and `~/.codex/config.toml`. A session is a Codex thread, kept where Codex keeps its threads.
- `claude`: `ClaudeIntelligence`, built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) and run with the user's Claude Code settings and the credentials Claude Code resolves: `ANTHROPIC_API_KEY`, or a cloud provider's, as [its docs](https://code.claude.com/docs/en/agent-sdk/quickstart) describe. Sessions are kept where Claude Code keeps them; a plain completion runs in the platform's per-user state directory, in `modeling-3d/claude`.

Without an agent provider named, the first installed in that order is used; one that is not installed raises `Modeling3dError` with the command that installs it.
`select_intelligence(intelligence, agent_provider, model, DEFAULT_INTELLIGENCE_MODELS)` is what a capability calls: an injected `intelligence` wins, and `model` falls back to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS`.
Another implementation is a module satisfying the protocol and a branch in that factory.

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

A capability's code goes in `modeling_3d/capabilities/<name>/`, with its prompts, templates, and its own `SKILL.md` beside it, named on its row in `core/skill.py` `CAPABILITIES`, and `lib.py` gets a facade function that imports it and is the only caller of it.
Each capability of the library gets a section here: what it does and when to reach for it, the signature `lib.py` exposes, what each argument means, and what it returns or raises.
Model-backed capabilities say so, and take `agent_provider`, `model`, `reasoning_effort`, and `intelligence`. `model` defaults to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS` and `reasoning_effort` to `medium`, both from `modeling_3d.schemas`.
