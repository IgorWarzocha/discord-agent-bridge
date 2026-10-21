"""Same-author burst before a Grokbot mention, plus a short earlier tail."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DEFAULT_BURST_WINDOW = timedelta(seconds=45)
DEFAULT_BURST_GAP = timedelta(seconds=5)
DEFAULT_TAIL_COUNT = 5


@dataclass(frozen=True)
class ChannelMessage:
    id: str
    author_id: str
    author_name: str
    content: str
    created_at: datetime
    jump_url: str


def build_burst(
    prior: Sequence[ChannelMessage],
    trigger: ChannelMessage,
    *,
    window: timedelta = DEFAULT_BURST_WINDOW,
    gap: timedelta = DEFAULT_BURST_GAP,
) -> tuple[ChannelMessage, ...]:
    """Walk backward through the author's own messages and stop at a gap.

    A message is kept when it is inside `window` of the trigger and the gap
    to the next newer message from that same author is at most `gap`.
    Other people's messages do not join the burst and do not split it.
    The trigger is always included. The result is oldest first.
    """
    trigger_at = _utc(trigger.created_at)
    selected = [trigger]
    previous_at = trigger_at
    older = [
        message
        for message in prior
        if message.id != trigger.id
        and message.author_id == trigger.author_id
        and _utc(message.created_at) <= trigger_at
    ]
    older.sort(key=lambda message: (_utc(message.created_at), message.id), reverse=True)
    for message in older:
        message_at = _utc(message.created_at)
        if trigger_at - message_at > window:
            break
        if previous_at - message_at > gap:
            break
        selected.append(message)
        previous_at = message_at
    selected.reverse()
    return tuple(selected)


def build_tail(
    prior: Sequence[ChannelMessage],
    trigger: ChannelMessage,
    burst: Sequence[ChannelMessage],
    *,
    parent: ChannelMessage | None,
    limit: int = DEFAULT_TAIL_COUNT,
) -> tuple[ChannelMessage, ...]:
    """Up to `limit` channel messages strictly before the trigger.

    Burst messages and the parent (when this was a reply) are left out so
    the earlier-channel section does not repeat them. Oldest first.
    """
    if limit <= 0:
        return ()
    trigger_at = _utc(trigger.created_at)
    excluded = {message.id for message in burst}
    excluded.add(trigger.id)
    if parent is not None:
        excluded.add(parent.id)
    candidates = [
        message
        for message in prior
        if message.id not in excluded and _utc(message.created_at) < trigger_at
    ]
    candidates.sort(key=lambda message: (_utc(message.created_at), message.id))
    return tuple(candidates[-limit:])


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("message timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
