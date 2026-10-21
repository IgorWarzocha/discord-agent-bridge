"""Plain-text subject and body for one Discord mention."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timezone

from grokbot_bridge.address import GrokAddress
from grokbot_bridge.burst import ChannelMessage
from grokbot_bridge.mentions import text_after_mention

_SUBJECT_LIMIT = 140
_WORDS_LIMIT = 48
_CALLBACK_NOTE = "this bridge does not post replies back to Discord"


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
    callback_webhook_url: str | None,
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
        callback_webhook_url=callback_webhook_url,
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
    callback_webhook_url: str | None,
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
        f"Callback webhook: {_callback(callback_webhook_url)}",
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


def _callback(url: str | None) -> str:
    if not url:
        return f"not configured (future work; {_CALLBACK_NOTE})"
    return f"{url} (placeholder only; {_CALLBACK_NOTE})"


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
