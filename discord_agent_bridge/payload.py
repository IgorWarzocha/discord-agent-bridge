"""Normalised Discord task handed to every connector."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from discord_agent_bridge.burst import ChannelMessage
from discord_agent_bridge.mentions import text_after_mention

_SUBJECT_LIMIT = 140
_WORDS_LIMIT = 48


@dataclass(frozen=True)
class CallbackInstructions:
    reply_url: str
    react_url: str
    expires_at: datetime | None
    max_posts: int
    text_limit: int


@dataclass(frozen=True)
class BridgePayload:
    """One mention, independent of which agent receives it."""

    channel_name: str
    username: str
    user_id: str
    message_link: str
    timestamp: datetime
    instruction: str
    tagged_message: str
    parent: ChannelMessage | None
    burst: tuple[ChannelMessage, ...]
    tail: tuple[ChannelMessage, ...]
    callback: CallbackInstructions | None
    label: str | None

    @property
    def subject(self) -> str:
        return build_subject(self.channel_name, self.username, self.instruction)


class OutboundMail:
    """Plain-text email. Used by the grokbot connector."""

    def __init__(self, to: str, subject: str, text: str) -> None:
        self.to = to
        self.subject = subject
        self.text = text


def build_payload(
    *,
    channel_name: str,
    trigger: ChannelMessage,
    parent: ChannelMessage | None,
    burst: Sequence[ChannelMessage],
    tail: Sequence[ChannelMessage],
    bot_id: str,
    label: str | None,
    callback: CallbackInstructions | None,
) -> BridgePayload:
    channel = _single_line(channel_name).lstrip("#") or "channel"
    username = _single_line(trigger.author_name).lstrip("@") or "unknown"
    return BridgePayload(
        channel_name=channel,
        username=username,
        user_id=trigger.author_id,
        message_link=trigger.jump_url,
        timestamp=trigger.created_at.astimezone(timezone.utc),
        instruction=text_after_mention(trigger.content, bot_id),
        tagged_message=trigger.content if trigger.content.strip() else "(no text)",
        parent=parent,
        burst=tuple(burst),
        tail=tuple(tail),
        callback=callback,
        label=label,
    )


def build_subject(channel_name: str, username: str, instruction: str) -> str:
    """`[Discord] #channel @user: first words` — one line, capped at 140 characters."""
    channel = _single_line(channel_name).lstrip("#") or "channel"
    user = _single_line(username).lstrip("@") or "user"
    summary = first_words(instruction)
    subject = f"[Discord] #{channel} @{user}: {summary}"
    if len(subject) <= _SUBJECT_LIMIT:
        return subject
    return subject[: _SUBJECT_LIMIT - 3].rstrip() + "..."


def first_words(text: str, limit: int = _WORDS_LIMIT) -> str:
    words = _single_line(text)
    if not words:
        return "(no text)"
    if len(words) <= limit:
        return words
    return words[: limit - 3].rstrip() + "..."


def render_task(payload: BridgePayload) -> str:
    """Plain-text task. Connectors that need a string body use this."""
    blocks = [
        f"Channel: #{payload.channel_name}",
        f"Discord username: {payload.username}",
        f"Discord user id: {payload.user_id}",
        f"Message link: {payload.message_link}",
        f"Timestamp: {payload.timestamp.isoformat()}",
        f"Label: {payload.label or 'default'}",
        "",
        render_callback(payload.callback),
        "",
        "--- Tagged message ---",
        payload.tagged_message,
        "",
        "--- Parent ---",
        _render(payload.parent) if payload.parent is not None else "not a reply",
        "",
        "--- Burst (same author, chronological) ---",
        _render_many(payload.burst),
        "",
        "--- Earlier channel (not part of the burst) ---",
        _render_many(payload.tail),
        "",
    ]
    return "\n".join(blocks)


def to_json(payload: BridgePayload) -> dict[str, object]:
    """One JSON object for HTTP connectors. Secrets are not included."""
    callback: dict[str, object] | None
    if payload.callback is None:
        callback = None
    else:
        callback = {
            "reply_url": payload.callback.reply_url,
            "react_url": payload.callback.react_url,
            "expires_at": (
                None
                if payload.callback.expires_at is None
                else payload.callback.expires_at.astimezone(timezone.utc).isoformat()
            ),
            "max_posts": payload.callback.max_posts,
            "text_limit": payload.callback.text_limit,
            "text": render_task(payload),
        }
    return {
        "subject": payload.subject,
        "channel": payload.channel_name,
        "username": payload.username,
        "user_id": payload.user_id,
        "message_link": payload.message_link,
        "timestamp": payload.timestamp.isoformat(),
        "label": payload.label or "default",
        "instruction": payload.instruction,
        "tagged_message": payload.tagged_message,
        "parent": None if payload.parent is None else _render(payload.parent),
        "burst": [_render(item) for item in payload.burst],
        "earlier": [_render(item) for item in payload.tail],
        "callback": callback,
    }


def render_callback(callback: CallbackInstructions | None) -> str:
    """Instructions an agent can follow without guessing the URL or the JSON."""
    if callback is None:
        return (
            "--- Reply to Discord ---\n"
            "not configured (set CALLBACK_BASE_URL to an https address the bot can reach)"
        )
    if callback.expires_at is None:
        lifetime = "This link does not expire."
    else:
        stamp = callback.expires_at.astimezone(timezone.utc).isoformat()
        lifetime = f"This link expires at {stamp}."
    posts = "post" if callback.max_posts == 1 else "posts"
    reply = f"curl -sS -X POST '{callback.reply_url}' \\"
    react = f"curl -sS -X POST '{callback.react_url}' \\"
    return "\n".join(
        [
            "--- Reply to Discord ---",
            f"{lifetime} It allows {callback.max_posts} {posts}.",
            "Each post replies to the original tagged message. A reaction does not use a post.",
            (
                f"Text limit: {callback.text_limit} characters. "
                "Discord messages are capped at 2000; the bridge splits longer text."
            ),
            "Mentions are not pinged.",
            reply,
            "  -H 'content-type: application/json' \\",
            "  -d '{\"text\":\"your reply\"}'",
            'JSON: {"text":"..."}',
            'Optional reaction on the same call: {"text":"...","reaction":"👀"}',
            "Allowed emoji: 👀 ✅ ❌ ⏳ 👍",
            react,
            "  -H 'content-type: application/json' \\",
            "  -d '{\"emoji\":\"👀\"}'",
        ]
    )


def _render_many(messages: Sequence[ChannelMessage]) -> str:
    if not messages:
        return "none"
    return "\n".join(_render(message) for message in messages)


def _render(message: ChannelMessage) -> str:
    text = message.content if message.content.strip() else "(no text)"
    name = _single_line(message.author_name).lstrip("@") or "unknown"
    return f"[{message.created_at.astimezone(timezone.utc).isoformat()}] @{name}: {text}"


def _single_line(value: str) -> str:
    return " ".join(value.split())
