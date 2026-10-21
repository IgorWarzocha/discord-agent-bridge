"""Discord client. This is the only module that talks to Discord.

Running `main` logs in. Unit tests must not call it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from discord_agent_bridge.burst import ChannelMessage
from discord_agent_bridge.callbacks import CallbackStore
from discord_agent_bridge.commands import (
    CommandResult,
    connect_account,
    disconnect_account,
    status_account,
)
from discord_agent_bridge.connectors.catalog import CONNECTOR_TYPES, ConnectorCatalog
from discord_agent_bridge.discord_sink import DiscordSink, react_handoff
from discord_agent_bridge.hops import decide_forward, hop_limit_message
from discord_agent_bridge.http_api import serve_in_thread, stop_http
from discord_agent_bridge.mentions import mentions_bot
from discord_agent_bridge.rate_limit import RateLimiter
from discord_agent_bridge.registry import Registry
from discord_agent_bridge.replies import CallbackService
from discord_agent_bridge.routing import MentionContext, OpenCallbacks, deliver_mention
from discord_agent_bridge.settings import Settings

logger = logging.getLogger("discord_agent_bridge")

_HISTORY_PAGE = 100
_HISTORY_CAP = 300
_CONNECT_DESCRIPTION = "Connect an agent. type chooses grokbot, webhook, hermes, or openclaw."
_STATUS_DESCRIPTION = "Show your connected agents, labels, and addresses."
_TYPE_CHOICES = [app_commands.Choice(name=name, value=name) for name in CONNECTOR_TYPES]


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
        connectors: ConnectorCatalog,
        callbacks: CallbackStore | None = None,
        callback_limiter: RateLimiter | None = None,
    ) -> None:
        super().__init__(intents=build_intents())
        self.settings = settings
        self.registry = registry
        self.limiter = limiter
        self.connectors = connectors
        self.callbacks = callbacks
        self.callback_limiter = callback_limiter
        self._http = None
        self.tree = app_commands.CommandTree(self)
        register_commands(self)

    async def setup_hook(self) -> None:
        guild_id = self.settings.discord_guild_id
        if guild_id is None:
            await self.tree.sync()
            logger.info("synced global slash commands")
        else:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("synced slash commands to guild %s", guild_id)
        self._start_callbacks()

    async def on_ready(self) -> None:
        user = self.user
        logger.info("logged in as %s", user.name if user else "unknown")

    async def on_message(self, message: discord.Message) -> None:
        if self.user is None or not _targets_bot(message, self.user.id):
            return
        decision = decide_forward(
            author_id=str(message.author.id),
            author_is_bot=bool(message.author.bot),
            is_webhook=message.webhook_id is not None,
            bridge_user_id=str(self.user.id),
            allowlist=self.settings.bot_allowlist,
            parent=self._tracked_parent(message),
            trigger_message_id=str(message.id),
            max_hops=self.settings.max_hops,
        )
        if not decision.forward:
            if decision.reason == "hop_limit":
                await _safe_reply(message, hop_limit_message(self.settings.max_hops))
            return
        if self.callbacks is not None:
            self.callbacks.track(
                str(message.id),
                str(getattr(message.channel, "id", "")),
                decision.root_id,
                decision.hop,
            )
        try:
            await self._deliver(message, decision.hop, decision.root_id)
        except Exception:
            logger.exception("mention delivery failed user=%s", message.author.id)
            await _safe_reply(message, "Something went wrong and no email was sent.")

    async def close(self) -> None:
        if self._http is not None:
            stop_http(self._http)
            self._http = None
        self.registry.close()
        if self.callbacks is not None:
            self.callbacks.close()
        await super().close()

    async def _deliver(self, message: discord.Message, hop: int, root_id: str) -> None:
        assert self.user is not None
        outcome = await asyncio.to_thread(
            deliver_mention,
            MentionContext(
                author_id=str(message.author.id),
                bot_id=str(self.user.id),
                channel_name=_channel_name(message.channel),
                trigger=_to_record(message),
                prior=tuple(await self._history(message)),
                parent=await self._parent(message),
                channel_id=str(getattr(message.channel, "id", "")),
                hop=hop,
                root_message_id=root_id,
            ),
            self.registry,
            self.limiter,
            self.connectors,
            window=timedelta(seconds=self.settings.burst_window_seconds),
            gap=timedelta(seconds=self.settings.burst_gap_seconds),
            tail_count=self.settings.channel_tail_count,
            callbacks=self._open_callbacks(),
        )
        if outcome.handoff != "none":
            await react_handoff(message, sent=outcome.handoff == "sent")
        logger.info("mention user=%s handoff=%s", message.author.id, outcome.handoff)
        await message.reply(outcome.channel_reply)

    def _open_callbacks(self) -> OpenCallbacks | None:
        if self.callbacks is None or not self.settings.callback_base_url:
            return None
        return OpenCallbacks(
            base_url=self.settings.callback_base_url,
            ttl_hours=self.settings.callback_ttl_hours,
            max_posts=self.settings.callback_max_posts,
            text_limit=self.settings.callback_text_limit,
            store=self.callbacks,
            now=datetime.now(timezone.utc),
        )

    def _start_callbacks(self) -> None:
        if self.callbacks is None or not self.settings.callback_base_url:
            logger.info("callback http not started")
            return
        limiter = self.callback_limiter or RateLimiter(
            self.settings.callback_rate_limit_max,
            timedelta(seconds=self.settings.callback_rate_limit_window_seconds),
        )
        service = CallbackService(
            store=self.callbacks,
            poster=DiscordSink(self, asyncio.get_running_loop()),
            limiter=limiter,
            text_limit=self.settings.callback_text_limit,
            clock=lambda: datetime.now(timezone.utc),
        )
        self._http = serve_in_thread(self.settings.http_host, self.settings.http_port, service)
        logger.info(
            "callback http listening host=%s port=%s",
            self.settings.http_host,
            self.settings.http_port,
        )

    def _tracked_parent(self, message: discord.Message):
        reference = message.reference
        if self.callbacks is None or reference is None or reference.message_id is None:
            return None
        return self.callbacks.tracked(str(reference.message_id))

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

    @bot.tree.command(name="connect", description=_CONNECT_DESCRIPTION)
    @app_commands.describe(
        type="Which agent receives your mentions.",
        label="Keyword after the mention that selects this link. Omit for the default.",
        email="Grokbot address on mail.grokbot.com. Plain is bot; name+tag is routine.",
        tag="Grokbot plus-tag. Builds name+tag@ from a plain address.",
        url="HTTPS URL for webhook, Hermes, or OpenClaw.",
        secret="HMAC secret for webhook or Hermes. Never shown in status.",
        token="OpenClaw hook token. Never shown in status.",
        agent_id="Optional OpenClaw agentId.",
    )
    @app_commands.choices(type=_TYPE_CHOICES)
    async def connect(
        interaction: discord.Interaction,
        type: str,
        label: str | None = None,
        email: str | None = None,
        tag: str | None = None,
        url: str | None = None,
        secret: str | None = None,
        token: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        options = _options(email=email, tag=tag, url=url, secret=secret, token=token, agent_id=agent_id)
        await _respond(
            interaction,
            lambda: connect_account(
                bot.registry,
                bot.connectors,
                user_id=str(interaction.user.id),
                connector_type=type,
                label=label,
                options=options,
            ),
        )

    @bot.tree.command(name="disconnect", description="Remove one label, the default link, or every link.")
    @app_commands.describe(
        label="Remove only this labeled link.",
        only_default="Remove only the unlabeled default link.",
    )
    async def disconnect(
        interaction: discord.Interaction,
        label: str | None = None,
        only_default: bool = False,
    ) -> None:
        await _respond(
            interaction,
            lambda: disconnect_account(
                bot.registry,
                user_id=str(interaction.user.id),
                label=label,
                only_default=only_default,
            ),
        )

    @bot.tree.command(name="status", description=_STATUS_DESCRIPTION)
    async def status(interaction: discord.Interaction) -> None:
        await _respond(
            interaction,
            lambda: status_account(bot.registry, bot.connectors, str(interaction.user.id)),
        )


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


def _options(**values: str | None) -> dict[str, str]:
    return {key: value.strip() for key, value in values.items() if value and value.strip()}


async def _safe_reply(message: discord.Message, text: str) -> None:
    try:
        await message.reply(text)
    except discord.HTTPException:
        logger.warning("could not send the error reply")
