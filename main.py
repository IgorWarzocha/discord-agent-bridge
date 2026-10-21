"""Run the Discord bot. This connects to Discord; unit tests do not import it."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from discord_agent_bridge.callbacks import CallbackStore
from discord_agent_bridge.connectors.catalog import build_connectors
from discord_agent_bridge.connectors.http_post import urllib_post
from discord_agent_bridge.discord_app import BridgeBot
from discord_agent_bridge.rate_limit import RateLimiter
from discord_agent_bridge.registry import Registry
from discord_agent_bridge.resend import ResendSender
from discord_agent_bridge.settings import SettingsError, load_dotenv, load_settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    load_dotenv(Path(".env"))
    try:
        settings = load_settings()
    except SettingsError as exc:
        raise SystemExit(str(exc)) from exc
    registry = Registry(settings.database_path)
    callbacks = CallbackStore(settings.database_path)
    connectors = build_connectors(
        ResendSender(settings.resend_api_key, settings.resend_from) if settings.resend_api_key else None,
        urllib_post,
        lambda: datetime.now(timezone.utc),
    )
    try:
        bot = BridgeBot(
            settings,
            registry,
            RateLimiter(
                settings.rate_limit_max,
                timedelta(seconds=settings.rate_limit_window_seconds),
            ),
            connectors,
            callbacks,
            RateLimiter(
                settings.callback_rate_limit_max,
                timedelta(seconds=settings.callback_rate_limit_window_seconds),
            ),
        )
        bot.run(settings.discord_token, log_handler=None)
    finally:
        registry.close()
        callbacks.close()


if __name__ == "__main__":
    main()
