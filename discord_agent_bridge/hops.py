"""Which mentions may be forwarded, and how deep a bot-to-bot thread may go."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from discord_agent_bridge.callbacks import TrackedMessage


@dataclass(frozen=True)
class ForwardDecision:
    forward: bool
    hop: int
    reason: str
    root_id: str


def decide_forward(
    *,
    author_id: str,
    author_is_bot: bool,
    is_webhook: bool,
    bridge_user_id: str,
    allowlist: Collection[str],
    parent: TrackedMessage | None,
    trigger_message_id: str,
    max_hops: int,
) -> ForwardDecision:
    """Humans start at hop 0. Allowlisted bots increment the tracked parent hop.

    The bridge's own user id never forwards, even if it is also on the allowlist.
    Other bots and webhooks forward only when their author id is allowlisted,
    and only while the next hop is still within max_hops.
    """
    if author_id == bridge_user_id:
        return ForwardDecision(False, 0, "bridge", trigger_message_id)
    if author_is_bot or is_webhook:
        if author_id not in allowlist:
            return ForwardDecision(False, 0, "not_allowlisted", trigger_message_id)
        if parent is None:
            hop = 1
            root = trigger_message_id
        else:
            hop = parent.hop + 1
            root = parent.root_message_id
        if hop > max_hops:
            return ForwardDecision(False, hop, "hop_limit", root)
        return ForwardDecision(True, hop, "bot", root)
    return ForwardDecision(True, 0, "human", trigger_message_id)


def hop_limit_message(max_hops: int) -> str:
    return f"Stopped: this thread is past the bot-to-bot hop limit ({max_hops})."
