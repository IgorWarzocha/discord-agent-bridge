"""Plain-text subject and body for one Discord mention."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from grokbot_bridge.address import GrokAddress
from grokbot_bridge.burst import ChannelMessage
from grokbot_bridge.mentions import text_after_mention

_SUBJECT_LIMIT = 140
_WORDS_LIMIT = 48


@dataclass(frozen=True)
class CallbackInstructions:
    reply_url: str
    react_url: str
    expires_at: datetime | None
    max_posts: int
    text_limit: int


class OutboundMail:
    """What Resend sends. The body is plain text; there is no HTML part."""

    def __init__(self, to: str, subject: str, text: str) -> None:
        self.to = to
        self.subject = subject
        self.text = text


def format_mail(
    *,
    address: GrokAddress,
    label: str | None,
    channel_name: str,
    trigger: ChannelMessage,
    parent: ChannelMessage | None,
    burst: Sequence[ChannelMessage],
    tail: Sequence[ChannelMessage],
    bot_id: str,
    callback: CallbackInstructions | None,
) -> OutboundMail:
    instruction = text_after_mention(trigger.content, bot_id)
    subject = build_subject(channel_name, trigger.author_name, instruction)
    text = build_body(
        address=address,
        label=label,
        channel_name=channel_name,
        trigger=trigger,
        parent=parent,
        burst=burst,
        tail=tail,
        callback=callback,
    )
    return OutboundMail(to=address.exact, subject=subject, text=text)


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


def build_body(
    *,
    address: GrokAddress,
    label: str | None,
    channel_name: str,
    trigger: ChannelMessage,
    parent: ChannelMessage | None,
    burst: Sequence[ChannelMessage],
    tail: Sequence[ChannelMessage],
    callback: CallbackInstructions | None,
) -> str:
    channel = _single_line(channel_name).lstrip("#") or "channel"
    username = _single_line(trigger.author_name).lstrip("@") or "unknown"
    tagged = trigger.content if trigger.content.strip() else "(no text)"
    blocks = [
        f"Channel: #{channel}",
        f"Discord username: {username}",
        f"Discord user id: {trigger.author_id}",
        f"Message link: {trigger.jump_url}",
        f"Timestamp: {_stamp(trigger)}",
        f"Mode: {address.mode}",
        f"Label: {label or 'default'}",
        f"To: {address.exact}",
        "",
        render_callback(callback),
        "",
        "--- Tagged message ---",
        tagged,
        "",
        "--- Parent ---",
        _render(parent) if parent is not None else "not a reply",
        "",
        "--- Burst (same author, chronological) ---",
        _render_many(burst),
        "",
        "--- Earlier channel (not part of the burst) ---",
        _render_many(tail),
        "",
    ]
    return "\n".join(blocks)


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
    return f"[{_stamp(message)}] @{name}: {text}"


def _stamp(message: ChannelMessage) -> str:
    return message.created_at.astimezone(timezone.utc).isoformat()


def _single_line(value: str) -> str:
    return " ".join(value.split())
