from datetime import datetime, timedelta, timezone

from discord_agent_bridge.connectors.catalog import ConnectorCatalog
from discord_agent_bridge.connectors.grokbot import GrokbotConnector
from discord_agent_bridge.rate_limit import RateLimiter
from discord_agent_bridge.registry import Registry
from discord_agent_bridge.resend import ResendSender
from discord_agent_bridge.routing import NOT_LINKED, MentionContext, deliver_mention, select_link
from tests.support import T0, FakeResend, message


def _connectors() -> tuple[ConnectorCatalog, FakeResend]:
    fake = FakeResend()
    catalog = ConnectorCatalog({"grokbot": GrokbotConnector(ResendSender("test-resend-key", "bridge@example.com", transport=fake))})
    return catalog, fake


def _ctx(content: str, *, author_id: str = "100") -> MentionContext:
    return MentionContext(
        author_id=author_id,
        bot_id="42",
        channel_name="design",
        trigger=message("9", content, 0, author_id=author_id),
        prior=(),
        parent=None,
    )


def test_label_selects_only_that_users_link(tmp_path) -> None:
    registry = Registry(tmp_path / "links.sqlite3")
    connectors, fake = _connectors()
    missed = deliver_mention(_ctx("<@42> hello"), registry, RateLimiter(5, timedelta(minutes=10), clock=lambda: T0), connectors)
    assert missed.handoff == "none"
    assert missed.channel_reply == NOT_LINKED
    assert "/connect" in missed.channel_reply
    assert fake.calls == []

    registry.upsert("100", None, "grokbot", {"email": "ada@mail.grokbot.com", "mode": "bot"})
    registry.upsert("100", "research", "grokbot", {"email": "ada+research@mail.grokbot.com", "mode": "routine"})
    registry.upsert("200", "research", "grokbot", {"email": "bob+research@mail.grokbot.com", "mode": "routine"})
    limiter = RateLimiter(5, timedelta(minutes=10), clock=lambda: T0)
    chosen = deliver_mention(_ctx("<@42> research summarize the thread"), registry, limiter, connectors)
    assert chosen.handoff == "sent"
    assert fake.calls[-1][2]["to"] == ["ada+research@mail.grokbot.com"]
    assert "mail.grokbot.com" not in chosen.channel_reply

    fallback = deliver_mention(_ctx("<@42> please research this"), registry, limiter, connectors)
    assert fallback.handoff == "sent"
    assert fake.calls[-1][2]["to"] == ["ada@mail.grokbot.com"]

    links = registry.list_links("100")
    assert select_link(links, "research <@42> hello", "42").config["mode"] == "bot"
    assert select_link(links, "<@!42> Research now", "42").label == "research"
    assert select_link(links, "<@42> research, now", "42").label is None
    registry.close()

    times = iter([datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)])
    oldest = Registry(tmp_path / "oldest.sqlite3", clock=lambda: next(times))
    oldest.upsert("100", "zeta", "grokbot", {"email": "ada+zeta@mail.grokbot.com", "mode": "routine"})
    oldest.upsert("100", "alpha", "grokbot", {"email": "ada+alpha@mail.grokbot.com", "mode": "routine"})
    outcome = deliver_mention(_ctx("<@42> hello"), oldest, RateLimiter(5, timedelta(minutes=10), clock=lambda: T0), connectors)
    assert outcome.handoff == "sent"
    assert fake.calls[-1][2]["to"] == ["ada+zeta@mail.grokbot.com"]
    oldest.close()


def test_mention_rate_limit_is_per_user(tmp_path) -> None:
    registry = Registry(tmp_path / "links.sqlite3")
    connectors, fake = _connectors()
    registry.upsert("100", None, "grokbot", {"email": "ada@mail.grokbot.com", "mode": "bot"})
    registry.upsert("100", "research", "grokbot", {"email": "ada+research@mail.grokbot.com", "mode": "routine"})
    registry.upsert("200", None, "grokbot", {"email": "bob@mail.grokbot.com", "mode": "bot"})
    limiter = RateLimiter(1, timedelta(minutes=10), clock=lambda: T0)
    first = deliver_mention(_ctx("<@42> research go"), registry, limiter, connectors)
    second = deliver_mention(_ctx("<@42> hello"), registry, limiter, connectors)
    other = deliver_mention(_ctx("<@42> hello", author_id="200"), registry, limiter, connectors)
    assert first.handoff == "sent"
    assert fake.calls[0][2]["to"] == ["ada+research@mail.grokbot.com"]
    assert second.handoff == "none"
    assert second.channel_reply.startswith("Rate limit: 1 email per 10 minutes")
    assert other.handoff == "sent"
    assert fake.calls[-1][2]["to"] == ["bob@mail.grokbot.com"]
    registry.close()
