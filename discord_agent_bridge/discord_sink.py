"""Discord sends for callback replies. Mention pings are always off."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

import discord

from discord_agent_bridge.replies import DiscordPostError

logger = logging.getLogger("discord_agent_bridge")

HANDOFF_SENT = "📨"
HANDOFF_FAILED = "⚠️"


def handoff_emoji(sent: bool) -> str:
    """Bridge-only reactions. They are not on the callback emoji allowlist."""
    if sent:
        return HANDOFF_SENT
    return HANDOFF_FAILED


def mentions_none() -> discord.AllowedMentions:
    return discord.AllowedMentions.none()


async def post_reply(channel: discord.abc.Messageable, message_id: str, content: str) -> discord.Message:
    """Reply to the original tagged message. Nobody is pinged."""
    original = await channel.fetch_message(int(message_id))
    return await original.reply(
        content,
        mention_author=False,
        allowed_mentions=mentions_none(),
    )


async def add_reaction_to(channel: discord.abc.Messageable, message_id: str, emoji: str) -> None:
    original = await channel.fetch_message(int(message_id))
    await original.add_reaction(emoji)


async def react_handoff(message: discord.Message, *, sent: bool) -> None:
    try:
        await message.add_reaction(handoff_emoji(sent))
    except discord.HTTPException:
        logger.warning("handoff reaction failed sent=%s", sent)


class DiscordSink:
    """Blocking poster used from the HTTP thread. It schedules work on the bot loop."""

    def __init__(self, bot: discord.Client, loop: asyncio.AbstractEventLoop) -> None:
        self._bot = bot
        self._loop = loop

    def post_chunks(
        self, *, channel_id: str, message_id: str, chunks: tuple[str, ...]
    ) -> tuple[str, ...]:
        return tuple(self._run(self._post(channel_id, message_id, chunks)))

    def add_reaction(self, *, channel_id: str, message_id: str, emoji: str) -> None:
        self._run(self._react(channel_id, message_id, emoji))

    async def _post(self, channel_id: str, message_id: str, chunks: Sequence[str]) -> list[str]:
        channel = await self._channel(channel_id)
        ids: list[str] = []
        for content in chunks:
            sent = await post_reply(channel, message_id, content)
            ids.append(str(sent.id))
        return ids

    async def _react(self, channel_id: str, message_id: str, emoji: str) -> None:
        channel = await self._channel(channel_id)
        await add_reaction_to(channel, message_id, emoji)

    async def _channel(self, channel_id: str) -> discord.abc.Messageable:
        found = self._bot.get_channel(int(channel_id))
        if found is None:
            found = await self._bot.fetch_channel(int(channel_id))
        if not isinstance(found, discord.abc.Messageable):
            raise DiscordPostError("discord post failed")
        return found

    def _run(self, coro: asyncio.Future | object):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[arg-type]
        try:
            return future.result(timeout=30)
        except DiscordPostError:
            raise
        except Exception as exc:
            logger.warning("discord callback failed error=%s", type(exc).__name__)
            raise DiscordPostError("discord post failed") from None
