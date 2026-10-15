from collections.abc import Iterator
import json
import queue
from urllib.request import urlopen

import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Origin

from modeling_3d import lib
from modeling_3d.schemas import Modeling3dError

TIMEOUT_SECONDS = 5


@pytest.fixture
def received() -> queue.Queue[str]:
    return queue.Queue()


@pytest.fixture
def app(received: queue.Queue[str]) -> Iterator[lib.App]:
    served = lib.serve_app(on_message=received.put)
    yield served
    served.stop()


def open_page(app: lib.App, origin: str | None = None) -> ClientConnection:
    return connect(app.url.replace("http://", "ws://") + "/ws", origin=Origin(origin or app.url))


def test_the_page_is_served(app: lib.App) -> None:
    with urlopen(app.url, timeout=TIMEOUT_SECONDS) as response:
        assert "<title>Modeling 3d</title>" in response.read().decode("utf-8")


def test_a_message_from_the_page_reaches_the_caller_and_every_page(app: lib.App, received: queue.Queue[str]) -> None:
    with open_page(app) as sender, open_page(app, app.url.replace("127.0.0.1", "localhost")) as watcher:
        sender.send("  make a cube  ")

        assert received.get(timeout=TIMEOUT_SECONDS) == "make a cube"
        for page in (sender, watcher):
            assert json.loads(page.recv(timeout=TIMEOUT_SECONDS)) == {"from": "you", "text": "make a cube"}


def test_send_shows_the_agent_message_on_every_open_page(app: lib.App) -> None:
    with open_page(app) as page:
        # The echo of its own message proves the app has registered the page.
        page.send("hello")
        page.recv(timeout=TIMEOUT_SECONDS)

        assert app.send("a cube it is") == 1
        assert json.loads(page.recv(timeout=TIMEOUT_SECONDS)) == {"from": "agent", "text": "a cube it is"}


def test_send_with_no_page_open_reaches_none(app: lib.App) -> None:
    assert app.send("anyone there?") == 0


def test_another_origin_cannot_connect(app: lib.App) -> None:
    with pytest.raises(InvalidStatus) as refused:
        open_page(app, "https://example.com")

    assert refused.value.response.status_code == 403


def test_a_held_port_is_a_named_failure(app: lib.App) -> None:
    port = int(app.url.rsplit(":", 1)[1])

    with pytest.raises(Modeling3dError, match="could not bind"):
        lib.serve_app(port=port)


def test_stop_frees_the_port() -> None:
    first = lib.serve_app()
    port = int(first.url.rsplit(":", 1)[1])
    first.stop()

    second = lib.serve_app(port=port)
    second.stop()
