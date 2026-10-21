import asyncio

from grokbot_bridge.discord_sink import handoff_emoji, post_reply, react_handoff


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
