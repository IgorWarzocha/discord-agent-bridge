from datetime import timedelta

from grokbot_bridge.discord_app import BridgeBot, build_intents
from grokbot_bridge.rate_limit import RateLimiter
from grokbot_bridge.registry import Registry
from grokbot_bridge.resend import ResendSender
from grokbot_bridge.settings import load_settings
from tests.support import FakeResend


def test_message_content_intent_is_required_and_privileged_extras_are_not() -> None:
    intents = build_intents()
    assert intents.guilds
    assert intents.guild_messages
    assert intents.message_content
    assert not intents.members
    assert not intents.presences


def test_slash_commands_name_bot_and_routine(tmp_path) -> None:
    settings = load_settings(
        {
            "DISCORD_BOT_TOKEN": "test-discord-token",
            "RESEND_API_KEY": "test-resend-key",
            "RESEND_FROM": "bridge@example.com",
        }
    )
    registry = Registry(tmp_path / "links.sqlite3")
    bot = BridgeBot(
        settings,
        registry,
        RateLimiter(5, timedelta(minutes=10)),
        ResendSender("test-resend-key", "bridge@example.com", transport=FakeResend()),
    )
    try:
        commands = {command.name: command.description for command in bot.tree.get_commands()}
        assert set(commands) == {"link-grok", "unlink-grok", "grok-status", "link-status"}
        assert "bot" in commands["link-grok"]
        assert "routine" in commands["link-grok"]
        assert "bot" in commands["grok-status"]
        assert "routine" in commands["grok-status"]
    finally:
        registry.close()
