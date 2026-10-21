"""Decide which of the author's links receives a mention, and build the mail."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from grokbot_bridge.burst import (
    DEFAULT_BURST_GAP,
    DEFAULT_BURST_WINDOW,
    DEFAULT_TAIL_COUNT,
    ChannelMessage,
    build_burst,
    build_tail,
)
from grokbot_bridge.mentions import selection_keyword
from grokbot_bridge.payload import OutboundMail, format_mail
from grokbot_bridge.rate_limit import RateLimiter
from grokbot_bridge.registry import Link, Registry

NOT_LINKED = (
    "You have not linked a Grok Bot. Use `/link-grok` to connect a bot address "
    "(name@mail.grokbot.com) or a routine address (name+tag@mail.grokbot.com)."
)


@dataclass(frozen=True)
class MentionContext:
    author_id: str
    bot_id: str
    channel_name: str
    trigger: ChannelMessage
    prior: tuple[ChannelMessage, ...]
    parent: ChannelMessage | None
    callback_webhook_url: str | None = None


@dataclass(frozen=True)
class MentionOutcome:
    channel_reply: str
    mail: OutboundMail | None


def select_link(links: Sequence[Link], content: str, bot_id: str) -> Link:
    """Pick the link for this mention.

    The first word after the bot mention selects a label when it matches one.
    Otherwise the unlabeled link is the default. If every saved link has a
    label and none matches, the earliest link the user saved is the default.
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
    return min(links, key=lambda link: (link.created_at, link.label or "", link.address.exact))


def deliver_mention(
    ctx: MentionContext,
    registry: Registry,
    limiter: RateLimiter,
    *,
    window: timedelta = DEFAULT_BURST_WINDOW,
    gap: timedelta = DEFAULT_BURST_GAP,
    tail_count: int = DEFAULT_TAIL_COUNT,
) -> MentionOutcome:
    """Look up only this author's links. A miss does not consume the rate limit."""
    if ctx.author_id != ctx.trigger.author_id:
        raise ValueError("mention author does not match the tagged message")
    links = registry.list_links(ctx.author_id)
    if not links:
        return MentionOutcome(channel_reply=NOT_LINKED, mail=None)
    link = select_link(links, ctx.trigger.content, ctx.bot_id)
    if not limiter.allow(ctx.author_id):
        return MentionOutcome(channel_reply=limiter.denial_message(), mail=None)
    burst = build_burst(ctx.prior, ctx.trigger, window=window, gap=gap)
    tail = build_tail(ctx.prior, ctx.trigger, burst, parent=ctx.parent, limit=tail_count)
    mail = format_mail(
        address=link.address,
        label=link.label,
        channel_name=ctx.channel_name,
        trigger=ctx.trigger,
        parent=ctx.parent,
        burst=burst,
        tail=tail,
        bot_id=ctx.bot_id,
        callback_webhook_url=ctx.callback_webhook_url,
    )
    return MentionOutcome(channel_reply=_sent_reply(link), mail=mail)


def _sent_reply(link: Link) -> str:
    if link.label is None:
        return f"Sent this to your default {link.address.mode} link."
    return f"Sent this to your {link.address.mode} link `{link.label}`."
