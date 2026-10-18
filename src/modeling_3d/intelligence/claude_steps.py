"""Claude Code's messages, as the Claude implementation keeps them, read into a model's activity.

Apart from claude.py, so reading a model's activity needs no Claude Agent SDK installed.
"""

from collections.abc import Iterable
import json
from pathlib import Path
import re
from typing import Any

from modeling_3d.intelligence.schemas import AgentEvent, AgentStep
from modeling_3d.schemas import ToolCall

# The arguments Claude Code's tools name what they work on with, in the order they are looked for.
TARGET_ARGUMENTS = ("file_path", "notebook_path", "command", "pattern", "url", "query", "description", "prompt")
MAX_FAILURE_CHARACTERS = 200
CD_PATTERN = re.compile(r"""^cd\s+(?P<quote>["']?)(?P<directory>.+?)(?P=quote)\s*(?:&&|;)\s*""")
ERROR_TAGS = re.compile(r"</?tool_use_error>")


def steps(event: AgentEvent, workspace: Path) -> list[AgentStep]:
    """What one of Claude Code's messages shows the person: the agent's words and reasoning, its tool calls, and their
    results.

    Reasoning shows as soon as its first tokens are counted, and its summary once it is done. A tool call shows how
    far the agent has got writing it out, until it is called, and each turn what the session has cost. Subagents' messages, the
    echoed prompt and steering, and other system and result messages show nothing: the run's own events already carry
    what matters of them.
    """
    if event.type == "SystemMessage":
        return [AgentStep(kind="reasoning")] if _starts_reasoning(event.data) else []
    if event.type == "composing":
        return [_composing(event.data, workspace)]
    if event.type == "ResultMessage":
        return _usage(event.data)
    blocks = _blocks(event)
    if event.type == "AssistantMessage":
        return [step for block in blocks if (step := _assistant_step(block, workspace)) is not None]
    if event.type == "UserMessage":
        return [_result(block) for block in blocks if "tool_use_id" in block]
    return []


def tool_call(events: Iterable[AgentEvent], call_id: str) -> ToolCall | None:
    """The call `call_id` in full among Claude Code's messages, with its result once that came; None if none has it."""
    call: ToolCall | None = None
    for event in events:
        for block in _blocks(event):
            if event.type == "AssistantMessage" and block.get("id") == call_id and "input" in block:
                arguments = block["input"]
                call = ToolCall(
                    name=str(block.get("name", "")),
                    input=arguments if isinstance(arguments, dict) else {},
                    output=None,
                    failed=False,
                )
            elif call is not None and event.type == "UserMessage" and block.get("tool_use_id") == call_id:
                return call.model_copy(
                    update={"output": _text(block.get("content")), "failed": bool(block.get("is_error"))}
                )
    return call


def _blocks(event: AgentEvent) -> list[dict[str, Any]]:
    """The message's content, or nothing for a subagent's, whose calls the run's own call to it stands for."""
    content = event.data.get("content")
    if event.data.get("parent_tool_use_id") is not None or not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _text(content: Any) -> str:
    if isinstance(content, str):
        return ERROR_TAGS.sub("", content).strip()
    if isinstance(content, list):
        return "\n".join(
            part["text"] for part in content if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _composing(data: dict[str, Any], workspace: Path) -> AgentStep:
    """How far a tool call the agent is writing out has got, with what it works on once that much is written."""
    head = str(data.get("head", ""))
    arguments: dict[str, str] = {}
    for name in TARGET_ARGUMENTS:
        # Only a whole value, closed by its quote, is what the call works on.
        found = re.search(rf'"{name}"\s*:\s*("(?:[^"\\]|\\.)*")', head)
        if found is not None:
            arguments[name] = json.loads(found[1])
    target = _target(arguments, workspace)
    data = {"id": data.get("id"), "name": data.get("name"), "target": target, "characters": data.get("characters", 0)}
    return AgentStep(kind="composing", text=target, data=data)


def _usage(data: dict[str, Any]) -> list[AgentStep]:
    """What the session has cost in all, as Claude Code reports at the end of each turn, counting a resumed session's
    earlier runs."""
    cost = data.get("total_cost_usd")
    if not isinstance(cost, int | float) or isinstance(cost, bool):
        return []
    return [AgentStep(kind="usage", data={"cost_usd": cost, "session_id": data.get("session_id")})]


def _starts_reasoning(data: dict[str, Any]) -> bool:
    """Whether the message is the first count of a stretch of reasoning, which counts up from nothing as it goes."""
    count = data.get("data")
    return (
        data.get("subtype") == "thinking_tokens"
        and isinstance(count, dict)
        and count.get("estimated_tokens") is not None
        and count.get("estimated_tokens") == count.get("estimated_tokens_delta")
    )


def _assistant_step(block: dict[str, Any], workspace: Path) -> AgentStep | None:
    text = block.get("text")
    if isinstance(text, str):
        return AgentStep(kind="said", text=text) if text.strip() else None
    # Empty when the model leaves its reasoning out.
    thinking = block.get("thinking")
    if isinstance(thinking, str):
        return AgentStep(kind="thought", text=thinking.strip()) if thinking.strip() else None
    if {"id", "name", "input"} <= block.keys():
        target = _target(block["input"], workspace)
        return AgentStep(kind="tool", text=target, data={"id": block["id"], "name": block["name"], "target": target})
    return None


def _target(arguments: Any, workspace: Path) -> str:
    if not isinstance(arguments, dict):
        return ""
    for name in TARGET_ARGUMENTS:
        value = arguments.get(name)
        if not isinstance(value, str) or not value.strip():
            continue
        if name.endswith("_path"):
            try:
                return Path(value).relative_to(workspace).as_posix()
            except ValueError:
                return value
        line = value.strip().splitlines()[0]
        return _without_cd(line, workspace) if name == "command" else line
    return ""


def _without_cd(command: str, workspace: Path) -> str:
    """The command without a leading change into the workspace, where it runs anyway."""
    found = CD_PATTERN.match(command)
    if found is None:
        return command
    # Git Bash on Windows names C:\ as /c/.
    directory = re.sub(r"^/([A-Za-z])/", r"\1:/", found["directory"])
    return command[found.end() :] if Path(directory) == workspace else command


def _result(block: dict[str, Any]) -> AgentStep:
    failed = bool(block.get("is_error"))
    content = block.get("content")
    text = ""
    if failed and isinstance(content, str):
        lines = ERROR_TAGS.sub("", content).strip().splitlines()
        text = lines[0][:MAX_FAILURE_CHARACTERS] if lines else ""
    return AgentStep(kind="tool-result", text=text, data={"id": block["tool_use_id"], "failed": failed})
