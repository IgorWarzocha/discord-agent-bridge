from types import SimpleNamespace

import pytest

from discord_agent_bridge.discord_app import _targets_bot
from discord_agent_bridge.mentions import mentions_bot, selection_keyword, text_after_mention


@pytest.mark.parametrize("mention", ["@bot", "@Bot", "<@42>", "<@!42>"])
def test_text_trigger_and_native_mentions_share_request_parsing(mention) -> None:
    content = f"context before {mention} research summarise this"
    message = SimpleNamespace(content=content, mentions=[])
    assert _targets_bot(message, 42)
    assert text_after_mention(content, "42") == "research summarise this"
    assert selection_keyword(content, "42") == "research"


@pytest.mark.parametrize("content", [
    "someone@bot.example", "@botany hello", "@bot_name hello",
    "@bot-other hello", "@@bot hello", "<@99> hello",
])
def test_unrelated_handles_and_email_do_not_trigger(content) -> None:
    assert not mentions_bot(content, "42")


def test_discord_reply_mention_admits_followup_without_text_tag() -> None:
    message = SimpleNamespace(content="you seein this reply?", mentions=[SimpleNamespace(id=42)])
    assert _targets_bot(message, 42)
    message.mentions = []
    assert not _targets_bot(message, 42)
