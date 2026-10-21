import asyncio
from datetime import timedelta
from types import SimpleNamespace

import discord
import pytest

from discord_agent_bridge.connectors.catalog import build_connectors
from discord_agent_bridge.discord_app import BridgeBot
from discord_agent_bridge.discord_sink import handoff_emoji, post_reply, react_handoff
from discord_agent_bridge.rate_limit import RateLimiter
from discord_agent_bridge.registry import Registry
from discord_agent_bridge.resend import ResendSender
from discord_agent_bridge.settings import load_settings
from tests.support import T0, FakeResend


class _Sent:
    def __init__(self, message_id: int) -> None:
        self.id = message_id


class _Original:
    def __init__(self) -> None:
        self.kwargs = None
        self.reactions: list[str] = []

    async def reply(self, content: str, **kwargs: object) -> _Sent:
        self.kwargs = {"content": content, **kwargs}
        return _Sent(50)

    async def add_reaction(self, emoji: str) -> None:
        self.reactions.append(emoji)


class _Channel:
    def __init__(self, original: _Original) -> None:
        self.original = original

    async def fetch_message(self, message_id: int) -> _Original:
        assert message_id == 9
        return self.original


def test_replies_disable_mentions_and_handoff_reacts() -> None:
    original = _Original()
    asyncio.run(post_reply(_Channel(original), "9", "hello @everyone <@1>"))
    assert original.kwargs is not None
    assert original.kwargs["mention_author"] is False
    allowed = original.kwargs["allowed_mentions"]
    assert allowed.everyone is False
    assert allowed.users is False
    assert allowed.roles is False
    assert allowed.replied_user is False
    assert allowed.to_dict()["parse"] == []
    assert "@everyone" in original.kwargs["content"]
    assert handoff_emoji(True) == "📨"
    assert handoff_emoji(False) == "⚠️"
    message = _Original()
    asyncio.run(react_handoff(message, sent=True))
    asyncio.run(react_handoff(message, sent=False))
    assert message.reactions == ["📨", "⚠️"]


@pytest.mark.parametrize("linked,status,emoji", [(True, 200, "📨"), (True, 500, "⚠️"), (False, 200, "⚠️")])
def test_mention_delivery_only_reacts_without_replying(tmp_path, linked, status, emoji) -> None:
    async def run():
        with Registry(tmp_path / "links.sqlite3") as registry:
            if linked:
                registry.upsert("100", None, "grokbot", {"email": "ada@mail.grokbot.com", "mode": "bot"})
            sender = ResendSender("test-key", "bridge@example.com", transport=FakeResend(status=status))
            bot = BridgeBot(
                load_settings({"DISCORD_BOT_TOKEN": "test-token"}), registry,
                RateLimiter(5, timedelta(minutes=10)),
                build_connectors(sender, lambda *args: pytest.fail("unexpected HTTP connector"), lambda: T0),
            )
            bot._connection.user = discord.ClientUser(
                state=bot._connection,
                data={"id": "42", "username": "bot", "discriminator": "0000", "avatar": None},
            )

            class Channel:
                id = 8
                name = "test"

                async def history(self, **kwargs):
                    for item in ():
                        yield item

            message = _Original()
            message.id = 9
            message.author = SimpleNamespace(id=100, name="ada")
            message.content = "@bot hello"
            message.created_at = T0
            message.jump_url = "https://discord.com/channels/7/8/9"
            message.channel = Channel()
            message.reference = None
            try:
                await bot._deliver(message, 0, "9")
                assert message.reactions == [emoji]
                assert message.kwargs is None
            finally:
                await bot.close()

    asyncio.run(run())
