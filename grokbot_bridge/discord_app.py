"""Discord client. This is the only module that talks to Discord.

Running `main` logs in. Unit tests must not call it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta

import discord
from discord import app_commands

from grokbot_bridge.burst import ChannelMessage
from grokbot_bridge.commands import CommandResult, link_account, status_account, unlink_account
from grokbot_bridge.mentions import mentions_bot
from grokbot_bridge.rate_limit import RateLimiter
from grokbot_bridge.registry import Registry
from grokbot_bridge.resend import ResendError, ResendSender
from grokbot_bridge.routing import MentionContext, deliver_mention
from grokbot_bridge.settings import Settings

logger = logging.getLogger("grokbot_bridge")

_HISTORY_PAGE = 100
_HISTORY_CAP = 300
_LINK_DESCRIPTION = "Link your Grok Bot. A plain address is bot mode; a plus-tag is routine mode."
_STATUS_DESCRIPTION = "Show your linked bot and routine addresses."


def build_intents() -> discord.Intents:
    """Guilds, guild messages, and the privileged message content intent.

    Message content is required to read the instruction after the mention.
    Member and presence intents are not requested.
    """
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True
    return intents


class BridgeBot(discord.Client):
    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        limiter: RateLimiter,
        sender: ResendSender,
    ) -> None:
        super().__init__(intents=build_intents())
        self.settings = settings
        self.registry = registry
        self.limiter = limiter
        self.sender = sender
        self.tree = app_commands.CommandTree(self)
        register_commands(self)

    async def setup_hook(self) -> None:
        guild_id = self.settings.discord_guild_id
        if guild_id is None:
            await self.tree.sync()
            logger.info("synced global slash commands")
            return
        guild = discord.Object(id=guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info("synced slash commands to guild %s", guild_id)

    async def on_ready(self) -> None:
        user = self.user
        logger.info("logged in as %s", user.name if user else "unknown")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None:
            return
        if message.author.id == self.user.id:
            return
        if not _targets_bot(message, self.user.id):
            return
        try:
            await self._deliver(message)
        except Exception:
            logger.exception("mention delivery failed user=%s", message.author.id)
            await _safe_reply(message, "Something went wrong and no email was sent.")

    async def close(self) -> None:
        self.registry.close()
        await super().close()

    async def _deliver(self, message: discord.Message) -> None:
        assert self.user is not None
        outcome = deliver_mention(
            MentionContext(
                author_id=str(message.author.id),
                bot_id=str(self.user.id),
                channel_name=_channel_name(message.channel),
                trigger=_to_record(message),
                prior=tuple(await self._history(message)),
                parent=await self._parent(message),
                callback_webhook_url=self.settings.callback_webhook_url,
            ),
            self.registry,
            self.limiter,
            window=timedelta(seconds=self.settings.burst_window_seconds),
            gap=timedelta(seconds=self.settings.burst_gap_seconds),
            tail_count=self.settings.channel_tail_count,
        )
        if outcome.mail is not None:
            try:
                await asyncio.to_thread(self.sender.send, outcome.mail)
            except ResendError as exc:
                logger.warning("resend status=%s user=%s", exc.status, message.author.id)
                await message.reply(_resend_reply(exc))
                return
        logger.info(
            "mention user=%s sent=%s",
            message.author.id,
            outcome.mail is not None,
        )
        await message.reply(outcome.channel_reply)

    async def _history(self, message: discord.Message) -> list[ChannelMessage]:
        collected: list[ChannelMessage] = []
        cursor: discord.Message = message
        padding = timedelta(seconds=self.settings.burst_window_seconds + 60)
        cutoff = message.created_at - padding
        while len(collected) < _HISTORY_CAP:
            try:
                batch = [
                    item
                    async for item in message.channel.history(limit=_HISTORY_PAGE, before=cursor)
                ]
            except (discord.HTTPException, AttributeError):
                logger.warning("channel history failed channel=%s", getattr(message.channel, "id", "?"))
                break
            if not batch:
                break
            collected.extend(_to_record(item) for item in batch)
            cursor = batch[-1]
            if cursor.created_at <= cutoff or len(batch) < _HISTORY_PAGE:
                break
        return collected

    async def _parent(self, message: discord.Message) -> ChannelMessage | None:
        reference = message.reference
        if reference is None or reference.message_id is None:
            return None
        resolved = reference.resolved
        if isinstance(resolved, discord.Message):
            return _to_record(resolved)
        try:
            fetched = await message.channel.fetch_message(reference.message_id)
        except (discord.HTTPException, AttributeError):
            logger.warning("parent message was not available id=%s", reference.message_id)
            return None
        return _to_record(fetched)


def register_commands(bot: BridgeBot) -> None:
    """The caller is always interaction.user. One user cannot link another."""

    @bot.tree.command(name="link-grok", description=_LINK_DESCRIPTION)
    @app_commands.describe(
        email="Your mail.grokbot.com address. Plain is bot; name+tag is routine.",
        tag="Optional plus-tag. Builds name+tag@ from a plain address (routine).",
        label="Keyword after @Grokbot that selects this link. Omit for the default.",
    )
    async def link_grok(
        interaction: discord.Interaction,
        email: str,
        tag: str | None = None,
        label: str | None = None,
    ) -> None:
        await _respond(
            interaction,
            lambda: link_account(
                bot.registry,
                user_id=str(interaction.user.id),
                email=email,
                tag=tag,
                label=label,
            ),
        )

    @bot.tree.command(
        name="unlink-grok",
        description="Remove one label, only the default link, or every link you saved.",
    )
    @app_commands.describe(
        label="Remove only this labeled link.",
        only_default="Remove only the unlabeled default link.",
    )
    async def unlink_grok(
        interaction: discord.Interaction,
        label: str | None = None,
        only_default: bool = False,
    ) -> None:
        await _respond(
            interaction,
            lambda: unlink_account(
                bot.registry,
                user_id=str(interaction.user.id),
                label=label,
                only_default=only_default,
            ),
        )

    @bot.tree.command(name="grok-status", description=_STATUS_DESCRIPTION)
    async def grok_status(interaction: discord.Interaction) -> None:
        await _respond(interaction, lambda: status_account(bot.registry, str(interaction.user.id)))

    @bot.tree.command(name="link-status", description=_STATUS_DESCRIPTION)
    async def link_status(interaction: discord.Interaction) -> None:
        await _respond(interaction, lambda: status_account(bot.registry, str(interaction.user.id)))


async def _respond(
    interaction: discord.Interaction,
    producer: Callable[[], CommandResult],
) -> None:
    try:
        result = producer()
    except Exception:
        logger.exception("command failed user=%s", interaction.user.id)
        message = "Something went wrong. Nothing was changed."
    else:
        logger.info("command user=%s ok=%s", interaction.user.id, result.ok)
        message = result.message
    await interaction.response.send_message(message, ephemeral=True)


def _targets_bot(message: discord.Message, bot_id: int) -> bool:
    if any(user.id == bot_id for user in message.mentions):
        return True
    return mentions_bot(message.content or "", str(bot_id))


def _to_record(message: discord.Message) -> ChannelMessage:
    created = message.created_at
    return ChannelMessage(
        id=str(message.id),
        author_id=str(message.author.id),
        author_name=message.author.name,
        content=message.content or "",
        created_at=created,
        jump_url=message.jump_url,
    )


def _channel_name(channel: object) -> str:
    name = getattr(channel, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "dm"


def _resend_reply(exc: ResendError) -> str:
    if exc.status:
        return (
            f"Could not email your Grok Bot (Resend returned {exc.status}). Nothing was sent."
        )
    return "Could not reach Resend. Nothing was sent."


async def _safe_reply(message: discord.Message, text: str) -> None:
    try:
        await message.reply(text)
    except discord.HTTPException:
        logger.warning("could not send the error reply")
