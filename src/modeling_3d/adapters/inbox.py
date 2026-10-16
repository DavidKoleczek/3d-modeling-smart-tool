"""The inbox of the Claude Code session that launched this process, where a message starts a turn or joins one.

Claude Code binds one per session for cross-session messaging and hands its address and token to the processes it
launches, MCP servers included: https://code.claude.com/docs/en/cross-session-messaging#the-sessions-inbox-socket
"""

import json
import os
from pathlib import Path
import socket
import sys

SOCKET_VARIABLE = "CLAUDE_CODE_MESSAGING_SOCKET"
TOKEN_VARIABLE = "CLAUDE_CODE_MESSAGING_TOKEN"


class Inbox:
    """One Claude Code session's inbox: a Unix socket, or a named pipe on Windows."""

    def __init__(self, address: str, token: str | None) -> None:
        self.address = address
        self._token = token

    def post(self, text: str) -> None:
        """Deliver `text` to the session as a message. Raises OSError when the inbox cannot be reached."""
        # The frame is not in the public docs; it is the recipe Claude Code's own debug log prints. The auth line is
        # what lets the session verify the message came from its own child, and Windows refuses a connection without it.
        lines: list[dict[str, object]] = []
        if self._token:
            lines.append({"type": "auth", "token": self._token})
        lines.append({"type": "user", "message": {"role": "user", "content": text}})
        payload = "".join(json.dumps(line) + "\n" for line in lines).encode("utf-8")
        if sys.platform == "win32":
            with Path(self.address).open("wb", buffering=0) as pipe:
                pipe.write(payload)
        else:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.connect(self.address)
                connection.sendall(payload)


def session_inbox() -> Inbox | None:
    """The inbox of the Claude Code session that launched this process, or None when no session handed one down."""
    address = os.environ.get(SOCKET_VARIABLE)
    if not address:
        return None
    return Inbox(address, os.environ.get(TOKEN_VARIABLE))
