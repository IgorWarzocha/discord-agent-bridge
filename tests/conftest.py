"""Block outbound network for the whole suite. Discord and Resend stay mocked.

The asyncio self-pipe is a local socketpair, so connect and bind are what fail.
"""

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket.socket, "bind", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
