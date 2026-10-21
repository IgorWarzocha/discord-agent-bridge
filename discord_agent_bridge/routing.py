"""Choose the author's link and hand the normalised payload to its connector."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from discord_agent_bridge.burst import (
    DEFAULT_BURST_GAP,
    DEFAULT_BURST_WINDOW,
    DEFAULT_TAIL_COUNT,
    ChannelMessage,
    build_burst,
    build_tail,
)
from discord_agent_bridge.callbacks import CallbackStore
from discord_agent_bridge.connectors.catalog import ConnectorCatalog
from discord_agent_bridge.mentions import selection_keyword
from discord_agent_bridge.payload import BridgePayload, CallbackInstructions, build_payload
from discord_agent_bridge.rate_limit import RateLimiter
from discord_agent_bridge.registry import Link, Registry

NOT_LINKED = "You have not connected an agent. Use `/connect`."

Handoff = Literal["sent", "failed", "none"]


@dataclass(frozen=True)
class MentionContext:
    author_id: str
    bot_id: str
    channel_name: str
    trigger: ChannelMessage
    prior: tuple[ChannelMessage, ...]
    parent: ChannelMessage | None
    channel_id: str = ""
    hop: int = 0
    root_message_id: str = ""


@dataclass(frozen=True)
class OpenCallbacks:
    base_url: str
    ttl_hours: int
    max_posts: int
    text_limit: int
    store: CallbackStore
    now: datetime


@dataclass(frozen=True)
class MentionOutcome:
    summary: str
    handoff: Handoff


def select_link(links: Sequence[Link], content: str, bot_id: str) -> Link:
    """First word after the mention selects a label. Otherwise the unlabeled default.

    If every link has a label and none matches, the earliest link is used.
    """
    if not links:
        raise ValueError("select_link requires at least one link")
    keyword = selection_keyword(content, bot_id)
    if keyword is not None:
        for link in links:
            if link.label == keyword:
                return link
    for link in links:
        if link.label is None:
            return link
    return min(links, key=lambda link: (link.created_at, link.label or "", link.connector_type))


def deliver_mention(
    ctx: MentionContext,
    registry: Registry,
    limiter: RateLimiter,
    connectors: ConnectorCatalog,
    *,
    window: timedelta = DEFAULT_BURST_WINDOW,
    gap: timedelta = DEFAULT_BURST_GAP,
    tail_count: int = DEFAULT_TAIL_COUNT,
    callbacks: OpenCallbacks | None = None,
) -> MentionOutcome:
    """Look up only this author's links. A miss does not consume the rate limit."""
    if ctx.author_id != ctx.trigger.author_id:
        raise ValueError("mention author does not match the tagged message")
    links = registry.list_links(ctx.author_id)
    if not links:
        return MentionOutcome(NOT_LINKED, "none")
    link = select_link(links, ctx.trigger.content, ctx.bot_id)
    connector = connectors.get(link.connector_type)
    if connector is None:
        return MentionOutcome(f"The `{link.connector_type}` connector is not available.", "none")
    if not limiter.allow(ctx.author_id):
        return MentionOutcome(limiter.denial_message(), "none")
    burst = build_burst(ctx.prior, ctx.trigger, window=window, gap=gap)
    tail = build_tail(ctx.prior, ctx.trigger, burst, parent=ctx.parent, limit=tail_count)
    include_callback = connector.capabilities.supports_callback
    payload: BridgePayload = build_payload(
        channel_name=ctx.channel_name,
        trigger=ctx.trigger,
        parent=ctx.parent,
        burst=burst,
        tail=tail,
        bot_id=ctx.bot_id,
        label=link.label,
        callback=_issue_callback(ctx, callbacks) if include_callback else None,
    )
    result = connector.deliver(payload, link.config)
    return MentionOutcome(result.summary, "sent" if result.ok else "failed")


def _issue_callback(ctx: MentionContext, callbacks: OpenCallbacks | None) -> CallbackInstructions | None:
    if callbacks is None or not ctx.channel_id.isdigit() or not ctx.trigger.id.isdigit():
        return None
    root = ctx.root_message_id or ctx.trigger.id
    token = callbacks.store.issue(
        channel_id=ctx.channel_id,
        message_id=ctx.trigger.id,
        user_id=ctx.author_id,
        username=ctx.trigger.author_name,
        root_message_id=root,
        hop=ctx.hop,
        max_posts=callbacks.max_posts,
        ttl_hours=callbacks.ttl_hours,
        now=callbacks.now,
    )
    base = callbacks.base_url.rstrip("/")
    expires = None
    if callbacks.ttl_hours > 0:
        expires = callbacks.now + timedelta(hours=callbacks.ttl_hours)
    return CallbackInstructions(
        reply_url=f"{base}/reply/{token}",
        react_url=f"{base}/react/{token}",
        expires_at=expires,
        max_posts=callbacks.max_posts,
        text_limit=callbacks.text_limit,
    )
