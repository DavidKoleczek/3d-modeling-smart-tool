"""The Windows app, when it is what started this server: the icon by the clock that keeps the server running, and keeps
what a server can't keep for itself, such as whether it starts at sign-in, its updates, and its Agent Skill.

It tells the server it starts where it listens on this machine and a token, in two environment variables. It is asked
in one line of JSON that has the token, and answers in one line.
"""

import json
import os
import socket
from typing import Any, NamedTuple

from pydantic import ValidationError

from modeling_3d.schemas import AgentProvider, Modeling3dError, SkillAgents, SkillMode, WindowsApp

PORT_VARIABLE = "MODELING_3D_WINDOWS_APP_PORT"
TOKEN_VARIABLE = "MODELING_3D_WINDOWS_APP_TOKEN"
HOST = "127.0.0.1"
CONNECT_SECONDS = 5
# Getting the skills CLI ready can mean downloading Node, and the Windows app gives up on it before this does.
ANSWER_SECONDS = 330
# Far past the longest answer there is, which is the list of agents.
MAX_ANSWER_BYTES = 256 * 1024
UNREADABLE = "The Windows app's answer couldn't be read. It may be another version; quit it and open it again."


class WindowsAppAddress(NamedTuple):
    """Where the Windows app that started this server listens, and the token it is asked with."""

    port: int
    token: str


def take_address() -> WindowsAppAddress | None:
    """Where the Windows app listens, when it started this process, or None when it didn't.

    Both variables are taken out of the environment, so nothing this process starts, such as a run's agent, inherits
    them and can drive the Windows app.
    """
    port, token = os.environ.pop(PORT_VARIABLE, ""), os.environ.pop(TOKEN_VARIABLE, "")
    return WindowsAppAddress(int(port), token) if port.isdecimal() and token else None


def state(address: WindowsAppAddress | None) -> WindowsApp | None:
    """What the Windows app is like, or None when it isn't what started this server.

    Raises:
        Modeling3dError: It started this server and doesn't answer.
    """
    return _ask(address, "state") if address is not None else None


def change(address: WindowsAppAddress | None, start_at_sign_in: bool | None = None) -> WindowsApp:
    """Changes the settings that are given, and returns what the Windows app is like after.

    Raises:
        Modeling3dError: The Windows app isn't what started this server, or it couldn't change them.
    """
    changes = {"start_at_sign_in": start_at_sign_in}
    return _ask(address, "set", **{name: value for name, value in changes.items() if value is not None})


def check_for_update(address: WindowsAppAddress | None) -> WindowsApp:
    """Has the Windows app look for a newer version, and returns what it is like after, with the version in `update`.

    Raises:
        Modeling3dError: The Windows app isn't what started this server, or it couldn't look.
    """
    return _ask(address, "check_for_update")


def install_update(address: WindowsAppAddress | None) -> WindowsApp:
    """Has the Windows app start installing the newer version, which ends this server and starts the new one.

    Raises:
        Modeling3dError: The Windows app isn't what started this server, or there is no newer version.
    """
    return _ask(address, "install_update")


def install_agent_provider(address: WindowsAppAddress | None, agent_provider: AgentProvider) -> WindowsApp:
    """Has the Windows app install the tool again with an agent provider it lacks, in a window of its own that asks
    about anything running from the tool first, which ends this server and starts it again once done.

    Raises:
        Modeling3dError: The Windows app isn't what started this server, or the agent provider is installed already.
    """
    return _ask(address, "install_agent_provider", agent_provider=agent_provider)


def list_agents(address: WindowsAppAddress | None) -> SkillAgents:
    """Has the Windows app get the skills CLI ready, which can take a while the first time, and list the agents.

    Raises:
        Modeling3dError: The Windows app isn't what started this server, or the agents couldn't be listed.
    """
    answer = _answer(address, "list_agents")
    try:
        return SkillAgents.model_validate(answer["agents"])
    except (KeyError, TypeError, ValidationError):
        raise Modeling3dError(UNREADABLE) from None


def install_skill(address: WindowsAppAddress | None, agents: list[str], mode: SkillMode) -> WindowsApp:
    """Has the Windows app install the Agent Skill in the shared folder and for these agents, and take it from others.

    `mode` is how an agent with a folder of its own gets it: a link to the shared copy, or a copy of its own.

    Raises:
        Modeling3dError: The Windows app isn't what started this server, or the skill wasn't installed everywhere.
    """
    return _ask(address, "install_skill", agents=agents, mode=mode)


def remove_skill(address: WindowsAppAddress | None) -> WindowsApp:
    """Has the Windows app remove the Agent Skill from every agent.

    Raises:
        Modeling3dError: The Windows app isn't what started this server, or the skill wasn't removed.
    """
    return _ask(address, "remove_skill")


def _ask(address: WindowsAppAddress | None, do: str, **more: Any) -> WindowsApp:
    answer = _answer(address, do, **more)
    try:
        return WindowsApp.model_validate(answer["state"])
    except (KeyError, TypeError, ValidationError):
        raise Modeling3dError(UNREADABLE) from None


def _answer(address: WindowsAppAddress | None, do: str, **more: Any) -> dict[str, Any]:
    """Asks the Windows app, and returns its answer when it did what was asked."""
    if address is None:
        raise Modeling3dError(
            "This is for the Windows app, which isn't what started this server. Install it from the repository's "
            "releases, and open the app from its shortcut.",
            "no-windows-app",
        )
    try:
        with socket.create_connection((HOST, address.port), timeout=CONNECT_SECONDS) as connection:
            connection.settimeout(ANSWER_SECONDS)
            connection.sendall((json.dumps({"token": address.token, "do": do, **more}) + "\n").encode())
            with connection.makefile("rb") as answered:
                line = answered.readline(MAX_ANSWER_BYTES)
    except OSError as error:
        raise Modeling3dError(
            f"The Windows app didn't answer: {error.strerror or error}. Check that its icon is by the clock, or open "
            "it from its shortcut."
        ) from None
    try:
        answer = json.loads(line)
        ok = answer["ok"]
        error = None if ok else str(answer["error"])
    except (ValueError, KeyError, TypeError):
        raise Modeling3dError(UNREADABLE) from None
    if error is not None:
        raise Modeling3dError(error)
    return answer
