"""Run the Discord bot. This connects to Discord; unit tests do not import it."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from grokbot_bridge.discord_app import BridgeBot
from grokbot_bridge.rate_limit import RateLimiter
from grokbot_bridge.registry import Registry
from grokbot_bridge.resend import ResendSender
from grokbot_bridge.settings import SettingsError, load_dotenv, load_settings


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
    try:
        bot = BridgeBot(
            settings,
            registry,
            RateLimiter(
                settings.rate_limit_max,
                timedelta(seconds=settings.rate_limit_window_seconds),
            ),
            ResendSender(settings.resend_api_key, settings.resend_from),
        )
        bot.run(settings.discord_token, log_handler=None)
    finally:
        registry.close()


if __name__ == "__main__":
    main()
