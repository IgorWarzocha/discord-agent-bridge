from datetime import datetime, timedelta, timezone

from grokbot_bridge.address import parse_link_email
from grokbot_bridge.rate_limit import RateLimiter
from grokbot_bridge.registry import Registry
from grokbot_bridge.routing import NOT_LINKED, MentionContext, deliver_mention, select_link
from tests.support import T0, message


def _registry(tmp_path) -> Registry:
    return Registry(tmp_path / "links.sqlite3")


def _ctx(content: str, *, author_id: str = "100", prior: tuple = (), parent=None) -> MentionContext:
    trigger = message("9", content, 0, author_id=author_id)
    return MentionContext(
        author_id=author_id,
        bot_id="42",
        channel_name="design",
        trigger=trigger,
        prior=prior,
        parent=parent,
        callback_webhook_url=None,
    )


def _limiter(max_events: int = 5) -> RateLimiter:
    return RateLimiter(max_events, timedelta(minutes=10), clock=lambda: T0)


def test_keyword_selects_that_users_routine_only(tmp_path) -> None:
    registry = _registry(tmp_path)
    registry.upsert("100", None, parse_link_email("ada@mail.grokbot.com"))
    registry.upsert("100", "research", parse_link_email("ada@mail.grokbot.com", tag="research"))
    registry.upsert("200", "research", parse_link_email("bob+research@mail.grokbot.com"))
    outcome = deliver_mention(
        _ctx("<@42> research summarize the thread"),
        registry,
        _limiter(),
    )
    assert outcome.mail is not None
    assert outcome.mail.to == "ada+research@mail.grokbot.com"
    assert outcome.mail.subject == "[Discord] #design @ada: research summarize the thread"
    assert "Mode: routine" in outcome.mail.text
    assert "<@42> research summarize the thread" in outcome.mail.text
    assert outcome.channel_reply == "Sent this to your routine link `research`."
    assert "mail.grokbot.com" not in outcome.channel_reply
    registry.close()


def test_unmatched_first_word_uses_the_default_bot(tmp_path) -> None:
    registry = _registry(tmp_path)
    registry.upsert("100", None, parse_link_email("ada@mail.grokbot.com"))
    registry.upsert("100", "research", parse_link_email("ada+research@mail.grokbot.com"))
    outcome = deliver_mention(_ctx("<@42> please research this"), registry, _limiter())
    assert outcome.mail is not None
    assert outcome.mail.to == "ada@mail.grokbot.com"
    assert outcome.channel_reply == "Sent this to your default bot link."
    registry.close()


def test_keyword_is_the_first_word_after_the_mention(tmp_path) -> None:
    registry = _registry(tmp_path)
    registry.upsert("100", None, parse_link_email("ada@mail.grokbot.com"))
    registry.upsert("100", "research", parse_link_email("ada+research@mail.grokbot.com"))
    links = registry.list_links("100")
    assert select_link(links, "research <@42> hello", "42").address.mode == "bot"
    assert select_link(links, "<@!42> Research now", "42").label == "research"
    assert select_link(links, "<@42> research, now", "42").label is None
    registry.close()


def test_oldest_link_is_the_default_when_none_is_unlabeled(tmp_path) -> None:
    times = iter(
        [
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        ]
    )
    registry = Registry(tmp_path / "links.sqlite3", clock=lambda: next(times))
    registry.upsert("100", "zeta", parse_link_email("ada+zeta@mail.grokbot.com"))
    registry.upsert("100", "alpha", parse_link_email("ada+alpha@mail.grokbot.com"))
    outcome = deliver_mention(_ctx("<@42> hello"), registry, _limiter())
    assert outcome.mail is not None
    assert outcome.mail.to == "ada+zeta@mail.grokbot.com"
    assert outcome.channel_reply == "Sent this to your routine link `zeta`."
    registry.close()


def test_unlinked_author_is_told_to_use_link_grok_and_does_not_consume_quota(tmp_path) -> None:
    registry = _registry(tmp_path)
    limiter = _limiter(1)
    missed = deliver_mention(_ctx("<@42> hello"), registry, limiter)
    assert missed.mail is None
    assert missed.channel_reply == NOT_LINKED
    assert "/link-grok" in missed.channel_reply
    registry.upsert("100", None, parse_link_email("ada@mail.grokbot.com"))
    sent = deliver_mention(_ctx("<@42> hello"), registry, limiter)
    assert sent.mail is not None
    assert sent.mail.to == "ada@mail.grokbot.com"
    registry.close()


def test_rate_limit_is_shared_across_the_users_links(tmp_path) -> None:
    registry = _registry(tmp_path)
    registry.upsert("100", None, parse_link_email("ada@mail.grokbot.com"))
    registry.upsert("100", "research", parse_link_email("ada+research@mail.grokbot.com"))
    registry.upsert("200", None, parse_link_email("bob@mail.grokbot.com"))
    limiter = _limiter(1)
    first = deliver_mention(_ctx("<@42> research go"), registry, limiter)
    second = deliver_mention(_ctx("<@42> hello"), registry, limiter)
    other = deliver_mention(_ctx("<@42> hello", author_id="200"), registry, limiter)
    assert first.mail is not None and first.mail.to == "ada+research@mail.grokbot.com"
    assert second.mail is None
    assert second.channel_reply.startswith("Rate limit: 1 email per 10 minutes")
    assert other.mail is not None and other.mail.to == "bob@mail.grokbot.com"
    registry.close()
