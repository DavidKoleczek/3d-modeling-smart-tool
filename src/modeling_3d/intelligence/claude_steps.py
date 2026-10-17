"""Claude Code's messages, as the Claude implementation keeps them, read into a model's activity.

Apart from claude.py, so reading a model's activity needs no Claude Agent SDK installed.
"""

from pathlib import Path
import re
from typing import Any

from modeling_3d.intelligence.schemas import AgentEvent, AgentStep

# The arguments Claude Code's tools name what they work on with, in the order they are looked for.
TARGET_ARGUMENTS = ("file_path", "notebook_path", "command", "pattern", "url", "query", "description", "prompt")
MAX_FAILURE_CHARACTERS = 200
CD_PATTERN = re.compile(r"""^cd\s+(?P<quote>["']?)(?P<directory>.+?)(?P=quote)\s*(?:&&|;)\s*""")


def steps(event: AgentEvent, workspace: Path) -> list[AgentStep]:
    """What one of Claude Code's messages shows the person: the agent's words, its tool calls, and their results.

    Subagents' messages, the echoed prompt and steering, and system and result messages show nothing: the run's own
    events already carry what matters of them.
    """
    content = event.data.get("content")
    if event.data.get("parent_tool_use_id") is not None or not isinstance(content, list):
        return []
    blocks = [block for block in content if isinstance(block, dict)]
    if event.type == "AssistantMessage":
        return [step for block in blocks if (step := _assistant_step(block, workspace)) is not None]
    if event.type == "UserMessage":
        return [_result(block) for block in blocks if "tool_use_id" in block]
    return []


def _assistant_step(block: dict[str, Any], workspace: Path) -> AgentStep | None:
    text = block.get("text")
    if isinstance(text, str):
        return AgentStep(kind="said", text=text) if text.strip() else None
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
        lines = re.sub(r"</?tool_use_error>", "", content).strip().splitlines()
        text = lines[0][:MAX_FAILURE_CHARACTERS] if lines else ""
    return AgentStep(kind="tool-result", text=text, data={"id": block["tool_use_id"], "failed": failed})
