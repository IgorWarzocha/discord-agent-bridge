"""Turn a callback POST into Discord reply chunks. Mentions stay disabled."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from grokbot_bridge.callbacks import CallbackError, CallbackStore, CallbackTicket
from grokbot_bridge.rate_limit import RateLimiter

logger = logging.getLogger("grokbot_bridge")

DISCORD_LIMIT = 2000
RAW_BODY_LIMIT = 32 * 1024
ALLOWED_EMOJI = frozenset({"👀", "✅", "❌", "⏳", "👍"})
_ERRORS = {
    "missing": (404, "callback rejected"),
    "expired": (410, "callback expired"),
    "budget": (429, "post budget used"),
    "rate": (429, "rate limited"),
}


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: dict[str, object]
    route: str
    user_id: str
    channel_id: str


class DiscordPostError(Exception):
    """Discord did not accept the reply. The message has no token and no body text."""


class ReplyPoster:
    """Sync boundary the HTTP thread can call. Implementations must not ping anyone."""

    def post_chunks(
        self, *, channel_id: str, message_id: str, chunks: tuple[str, ...]
    ) -> tuple[str, ...]:
        raise NotImplementedError

    def add_reaction(self, *, channel_id: str, message_id: str, emoji: str) -> None:
        raise NotImplementedError


def attribution(username: str) -> str:
    name = " ".join(username.replace("@", "").split())[:32] or "user"
    return f"↩ reply from {name}'s Grok Bot\n"


def chunk_reply(username: str, text: str) -> tuple[str, ...]:
    """Every chunk is at most 2000 characters and names whose bot is speaking."""
    prefix = attribution(username)
    room = DISCORD_LIMIT - len(prefix)
    if room < 1:
        raise ValueError("attribution exceeds the Discord limit")
    return tuple(prefix + part for part in _split_text(text, room))


def log_line(result: HttpResult, byte_count: int) -> str:
    """Request log. The token and the reply text are not included."""
    return (
        f"callback route={result.route} status={result.status} "
        f"user={result.user_id or '-'} channel={result.channel_id or '-'} bytes={byte_count}"
    )


class CallbackService:
    def __init__(
        self,
        *,
        store: CallbackStore,
        poster: ReplyPoster,
        limiter: RateLimiter,
        text_limit: int,
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._poster = poster
        self._limiter = limiter
        self._text_limit = text_limit
        self._clock = clock

    def handle(self, path: str, raw: bytes) -> HttpResult:
        route, token = _route(path)
        if route is None or token is None:
            return _result(404, "not found", "unknown")
        if len(raw) > RAW_BODY_LIMIT:
            return _result(413, "body too large", route)
        try:
            payload = _payload(raw)
            text, emoji = _fields(route, payload)
        except ValueError as exc:
            return _result(400, str(exc), route)
        if text is not None and len(text) > self._text_limit:
            return _result(400, "text too long", route)
        now = self._clock()
        try:
            if text is None:
                return self._react(token, emoji, now, route)
            return self._reply(token, text, emoji, now, route)
        except CallbackError as exc:
            status, message = _ERRORS.get(exc.code, (404, "callback rejected"))
            return _result(status, message, route)
        except DiscordPostError:
            return _result(502, "discord post failed", route)

    def _reply(self, token: str, text: str, emoji: str | None, now: datetime, route: str) -> HttpResult:
        preview = self._store.peek(token, now)
        if preview.posts_remaining <= 0:
            raise CallbackError("budget")
        if not self._limiter.allow(preview.channel_id):
            raise CallbackError("rate")
        ticket = self._store.take_post(token, now)
        chunks = chunk_reply(ticket.username, text)
        try:
            posted_ids = self._poster.post_chunks(
                channel_id=ticket.channel_id,
                message_id=ticket.message_id,
                chunks=chunks,
            )
        except DiscordPostError:
            self._store.refund_post(ticket.token_hash)
            raise
        self._track(ticket, posted_ids)
        if emoji is not None:
            self._react_quietly(ticket, emoji)
        return _result(200, "ok", route, ticket, extra={"posts_remaining": ticket.posts_remaining})

    def _react(self, token: str, emoji: str | None, now: datetime, route: str) -> HttpResult:
        if emoji is None:
            return _result(400, "emoji is required", route)
        ticket = self._store.peek(token, now)
        if not self._limiter.allow(ticket.channel_id):
            raise CallbackError("rate")
        self._poster.add_reaction(
            channel_id=ticket.channel_id,
            message_id=ticket.message_id,
            emoji=emoji,
        )
        return _result(200, "ok", route, ticket, extra={"posts_remaining": ticket.posts_remaining})

    def _track(self, ticket: CallbackTicket, message_ids: Sequence[str]) -> None:
        for message_id in message_ids:
            self._store.track(message_id, ticket.channel_id, ticket.root_message_id, ticket.hop)

    def _react_quietly(self, ticket: CallbackTicket, emoji: str) -> None:
        try:
            self._poster.add_reaction(
                channel_id=ticket.channel_id,
                message_id=ticket.message_id,
                emoji=emoji,
            )
        except DiscordPostError:
            logger.warning("callback reaction failed user=%s", ticket.user_id)


def _route(path: str) -> tuple[str | None, str | None]:
    bare = path.split("?", 1)[0].strip("/")
    parts = bare.split("/")
    if len(parts) != 2 or parts[0] not in {"reply", "react"}:
        return None, None
    token = parts[1].strip()
    if not token or len(token) > 128:
        return parts[0], None
    return parts[0], token


def _payload(raw: bytes) -> dict[str, object]:
    try:
        decoded = raw.decode("utf-8")
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid json") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid json")
    return data


def _fields(route: str, payload: dict[str, object]) -> tuple[str | None, str | None]:
    if route == "react":
        return None, _emoji(payload.get("emoji"), required=True)
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required")
    reaction = payload.get("reaction")
    emoji = None if reaction is None else _emoji(reaction, required=True)
    return text, emoji


def _emoji(value: object, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError("emoji not allowed")
    emoji = value.strip()
    if emoji not in ALLOWED_EMOJI:
        raise ValueError("emoji not allowed")
    return emoji


def _result(
    status: int,
    message: str,
    route: str,
    ticket: CallbackTicket | None = None,
    *,
    extra: dict[str, object] | None = None,
) -> HttpResult:
    if status == 200:
        body: dict[str, object] = {"ok": True}
        if extra:
            body.update(extra)
    else:
        body = {"error": message}
    return HttpResult(
        status=status,
        body=body,
        route=route,
        user_id="" if ticket is None else ticket.user_id,
        channel_id="" if ticket is None else ticket.channel_id,
    )


def _split_text(text: str, room: int) -> list[str]:
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= room:
            chunks.append(rest)
            break
        window = rest[:room]
        newline = window.rfind("\n")
        if newline >= room // 2:
            cut = newline
            nxt = newline + 1
        else:
            cut = room
            nxt = room
        chunks.append(rest[:cut])
        rest = rest[nxt:]
    return chunks
