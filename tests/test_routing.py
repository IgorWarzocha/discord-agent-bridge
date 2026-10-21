from datetime import datetime, timedelta, timezone

from grokbot_bridge.address import parse_link_email
from grokbot_bridge.rate_limit import RateLimiter
from grokbot_bridge.registry import Registry
from grokbot_bridge.routing import NOT_LINKED, MentionContext, deliver_mention, select_link
from tests.support import T0, message


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
    missed = deliver_mention(
        _ctx("<@42> hello"),
        registry,
        RateLimiter(5, timedelta(minutes=10), clock=lambda: T0),
    )
    assert missed.mail is None
    assert missed.channel_reply == NOT_LINKED
    assert "/link-grok" in missed.channel_reply

    registry.upsert("100", None, parse_link_email("ada@mail.grokbot.com"))
    registry.upsert("100", "research", parse_link_email("ada+research@mail.grokbot.com"))
    registry.upsert("200", "research", parse_link_email("bob+research@mail.grokbot.com"))
    limiter = RateLimiter(5, timedelta(minutes=10), clock=lambda: T0)
    chosen = deliver_mention(_ctx("<@42> research summarize the thread"), registry, limiter)
    assert chosen.mail is not None
    assert chosen.mail.to == "ada+research@mail.grokbot.com"
    assert chosen.mail.subject == "[Discord] #design @ada: research summarize the thread"
    assert "mail.grokbot.com" not in chosen.channel_reply

    fallback = deliver_mention(_ctx("<@42> please research this"), registry, limiter)
    assert fallback.mail is not None and fallback.mail.to == "ada@mail.grokbot.com"

    links = registry.list_links("100")
    assert select_link(links, "research <@42> hello", "42").address.mode == "bot"
    assert select_link(links, "<@!42> Research now", "42").label == "research"
    assert select_link(links, "<@42> research, now", "42").label is None
    registry.close()

    times = iter(
        [
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        ]
    )
    oldest = Registry(tmp_path / "oldest.sqlite3", clock=lambda: next(times))
    oldest.upsert("100", "zeta", parse_link_email("ada+zeta@mail.grokbot.com"))
    oldest.upsert("100", "alpha", parse_link_email("ada+alpha@mail.grokbot.com"))
    outcome = deliver_mention(
        _ctx("<@42> hello"),
        oldest,
        RateLimiter(5, timedelta(minutes=10), clock=lambda: T0),
    )
    assert outcome.mail is not None
    assert outcome.mail.to == "ada+zeta@mail.grokbot.com"
    oldest.close()


def test_mention_rate_limit_is_per_user(tmp_path) -> None:
    registry = Registry(tmp_path / "links.sqlite3")
    registry.upsert("100", None, parse_link_email("ada@mail.grokbot.com"))
    registry.upsert("100", "research", parse_link_email("ada+research@mail.grokbot.com"))
    registry.upsert("200", None, parse_link_email("bob@mail.grokbot.com"))
    limiter = RateLimiter(1, timedelta(minutes=10), clock=lambda: T0)
    first = deliver_mention(_ctx("<@42> research go"), registry, limiter)
    second = deliver_mention(_ctx("<@42> hello"), registry, limiter)
    other = deliver_mention(_ctx("<@42> hello", author_id="200"), registry, limiter)
    assert first.mail is not None and first.mail.to == "ada+research@mail.grokbot.com"
    assert second.mail is None
    assert second.channel_reply.startswith("Rate limit: 1 email per 10 minutes")
    assert other.mail is not None and other.mail.to == "bob@mail.grokbot.com"
    registry.close()
