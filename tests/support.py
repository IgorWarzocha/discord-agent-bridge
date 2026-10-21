"""Shared fixtures for message records. Not production code."""

from datetime import datetime, timedelta, timezone

from grokbot_bridge.burst import ChannelMessage
from grokbot_bridge.resend import HttpResponse

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def message(
    id: str,
    content: str,
    seconds: float,
    *,
    author_id: str = "100",
    author_name: str = "ada",
) -> ChannelMessage:
    return ChannelMessage(
        id=id,
        author_id=author_id,
        author_name=author_name,
        content=content,
        created_at=at(seconds),
        jump_url=f"https://discord.com/channels/7/8/{id}",
    )


class FakeResend:
    """In-memory Resend. Tests fail if the sender touches the network instead."""

    def __init__(self, status: int = 200, body: str = '{"id":"email_123"}') -> None:
        self.status = status
        self.body = body
        self.calls: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def post_json(self, url: str, headers: dict[str, str], payload: dict[str, object]) -> HttpResponse:
        self.calls.append((url, dict(headers), dict(payload)))
        return HttpResponse(self.status, self.body)
