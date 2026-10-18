"""Codex's notifications, as the Codex implementation keeps them, read into a model's activity.

Apart from codex.py, so reading a model's activity needs no Codex SDK installed.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from modeling_3d.intelligence.schemas import AgentEvent, AgentStep
from modeling_3d.schemas import ToolCall

# The items that are a call to a tool, rather than words, reasoning, or the turn's own bookkeeping.
TOOL_ITEMS = frozenset(
    {
        "commandExecution",
        "fileChange",
        "imageView",
        "webSearch",
        "mcpToolCall",
        "dynamicToolCall",
        "collabAgentToolCall",
        "imageGeneration",
    }
)
# The items whose tool is named by the call rather than by the item.
NAMED_BY_TOOL = frozenset({"mcpToolCall", "dynamicToolCall", "collabAgentToolCall"})
# The arguments a tool of an MCP server or the runtime names what it works on with, in the order they are looked for.
TARGET_ARGUMENTS = ("path", "file_path", "command", "query", "url", "prompt", "description")
# What a call's item carries beside what the agent called it with.
CALL_RESULT_FIELDS = frozenset(
    {
        "id",
        "type",
        "status",
        "aggregatedOutput",
        "exitCode",
        "durationMs",
        "processId",
        "source",
        "result",
        "results",
        "error",
        "contentItems",
        "success",
        "agentsStates",
    }
)
MAX_FAILURE_CHARACTERS = 200
FAILED_STATUSES = ("failed", "declined")


def steps(event: AgentEvent, workspace: Path) -> list[AgentStep]:
    """What one of Codex's notifications shows the person: the agent's words and reasoning, its tool calls, and their
    results.

    Reasoning shows when it starts, and its summary once it is done. Each turn shows what the session has used in
    tokens, since Codex reports no cost. The prompt, steering, and the turn's own notifications show nothing: the run's
    own events already carry what matters of them.
    """
    if event.type == "thread/tokenUsage/updated":
        return _usage(event.data)
    item = event.data.get("item")
    if not isinstance(item, dict):
        return []
    kind = item.get("type")
    if event.type == "item/started":
        if kind == "reasoning":
            return [AgentStep(kind="reasoning")]
        if kind in TOOL_ITEMS:
            target = _target(item, workspace)
            data = {"id": item.get("id"), "name": _name(item), "target": target}
            return [AgentStep(kind="tool", text=target, data=data)]
        return []
    if event.type != "item/completed":
        return []
    if kind == "agentMessage":
        text = str(item.get("text", ""))
        return [AgentStep(kind="said", text=text)] if text.strip() else []
    if kind == "reasoning":
        summary = "\n\n".join(part for part in item.get("summary") or [] if isinstance(part, str)).strip()
        return [AgentStep(kind="thought", text=summary)] if summary else []
    if kind in TOOL_ITEMS:
        failed = _failed(item)
        text = _failure(item) if failed else ""
        return [AgentStep(kind="tool-result", text=text, data={"id": item.get("id"), "failed": failed})]
    return []


def tool_call(events: Iterable[AgentEvent], call_id: str) -> ToolCall | None:
    """The call `call_id` in full among Codex's notifications, with its result once that came; None if none has it."""
    call: ToolCall | None = None
    for event in events:
        item = event.data.get("item")
        if not isinstance(item, dict) or item.get("id") != call_id or item.get("type") not in TOOL_ITEMS:
            continue
        if event.type == "item/started":
            call = ToolCall(name=_name(item), input=_input(item), output=None, failed=False)
        elif event.type == "item/completed":
            return ToolCall(name=_name(item), input=_input(item), output=_output(item), failed=_failed(item))
    return call


def _usage(data: dict[str, Any]) -> list[AgentStep]:
    """What the session has used in all, counting a resumed session's earlier runs."""
    usage = data.get("tokenUsage")
    total = usage.get("total") if isinstance(usage, dict) else None
    tokens = total.get("totalTokens") if isinstance(total, dict) else None
    if not isinstance(tokens, int) or isinstance(tokens, bool):
        return []
    return [AgentStep(kind="usage", data={"tokens": tokens, "session_id": data.get("threadId")})]


def _name(item: dict[str, Any]) -> str:
    kind = str(item.get("type", ""))
    return str(item.get("tool") or kind) if kind in NAMED_BY_TOOL else kind


def _command(item: dict[str, Any]) -> str:
    """The command as the agent wrote it, without the shell Codex wraps it in."""
    actions = [
        action["command"]
        for action in item.get("commandActions") or []
        if isinstance(action, dict) and isinstance(action.get("command"), str)
    ]
    return " && ".join(actions) if actions else str(item.get("command", ""))


def _target(item: dict[str, Any], workspace: Path) -> str:
    match item.get("type"):
        case "commandExecution":
            return _first_line(_command(item))
        case "fileChange":
            changes = [change for change in item.get("changes") or [] if isinstance(change, dict)]
            return ", ".join(_relative(str(change.get("path", "")), workspace) for change in changes)
        case "imageView":
            return _relative(str(item.get("path", "")), workspace)
        case "webSearch":
            return _first_line(str(item.get("query", "")))
        case "collabAgentToolCall":
            return _first_line(str(item.get("prompt") or ""))
        case "imageGeneration":
            return _first_line(str(item.get("revisedPrompt") or ""))
    arguments = item.get("arguments")
    if not isinstance(arguments, dict):
        return ""
    for name in TARGET_ARGUMENTS:
        value = arguments.get(name)
        if isinstance(value, str) and value.strip():
            return _relative(value, workspace) if "path" in name else _first_line(value)
    return ""


def _input(item: dict[str, Any]) -> dict[str, Any]:
    """What the agent called the tool with."""
    match item.get("type"):
        case "commandExecution":
            return {"command": _command(item), "cwd": item.get("cwd")}
        case "mcpToolCall" | "dynamicToolCall":
            arguments = item.get("arguments")
            return arguments if isinstance(arguments, dict) else {"arguments": arguments}
    return {key: value for key, value in item.items() if key not in CALL_RESULT_FIELDS}


def _output(item: dict[str, Any]) -> str:
    """What came back, as text with any images left out."""
    match item.get("type"):
        case "commandExecution":
            return str(item.get("aggregatedOutput") or "")
        case "mcpToolCall":
            error = item.get("error")
            if isinstance(error, dict):
                return str(error.get("message", ""))
            result = item.get("result")
            return _text(result.get("content") if isinstance(result, dict) else None)
        case "dynamicToolCall":
            return _text(item.get("contentItems"))
    return ""


def _failed(item: dict[str, Any]) -> bool:
    exit_code = item.get("exitCode")
    return (
        item.get("status") in FAILED_STATUSES
        or (isinstance(exit_code, int) and exit_code != 0)
        or isinstance(item.get("error"), dict)
        or item.get("success") is False
    )


def _failure(item: dict[str, Any]) -> str:
    """One line of why the call failed, in the tool's own words where it gave any."""
    lines = [line.strip() for line in _output(item).splitlines() if line.strip()]
    if lines:
        # A command prints its error last, after whatever it printed on the way.
        line = lines[-1] if item.get("type") == "commandExecution" else lines[0]
        return line[:MAX_FAILURE_CHARACTERS]
    exit_code = item.get("exitCode")
    return f"Exited with code {exit_code}" if isinstance(exit_code, int) else ""


def _text(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    return "\n".join(part["text"] for part in content if isinstance(part, dict) and isinstance(part.get("text"), str))


def _relative(path: str, workspace: Path) -> str:
    try:
        return Path(path).relative_to(workspace).as_posix()
    except ValueError:
        return path


def _first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0] if lines else ""
