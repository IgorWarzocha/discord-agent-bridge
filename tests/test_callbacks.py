import json
import sqlite3
from datetime import timedelta

from grokbot_bridge.address import parse_link_email
from grokbot_bridge.callbacks import CallbackStore
from grokbot_bridge.rate_limit import RateLimiter
from grokbot_bridge.registry import Registry
from grokbot_bridge.replies import (
    RAW_BODY_LIMIT,
    CallbackService,
    DiscordPostError,
    ReplyPoster,
    chunk_reply,
    log_line,
)
from grokbot_bridge.routing import MentionContext, OpenCallbacks, deliver_mention
from tests.support import T0, message


class FakePoster(ReplyPoster):
    def __init__(self) -> None:
        self.posts: list[tuple[str, str, tuple[str, ...]]] = []
        self.reactions: list[tuple[str, str, str]] = []
        self.fail_posts = False

    def post_chunks(self, *, channel_id: str, message_id: str, chunks: tuple[str, ...]) -> tuple[str, ...]:
        if self.fail_posts:
            raise DiscordPostError("discord post failed")
        self.posts.append((channel_id, message_id, chunks))
        start = sum(len(item[2]) for item in self.posts[:-1])
        return tuple(f"posted-{start + index}" for index, _chunk in enumerate(chunks))

    def add_reaction(self, *, channel_id: str, message_id: str, emoji: str) -> None:
        self.reactions.append((channel_id, message_id, emoji))


def _service(tmp_path, *, posts: int = 5, ttl: int = 24, rate: int = 20):
    now = {"t": T0}
    path = tmp_path / "links.sqlite3"
    store = CallbackStore(path)
    poster = FakePoster()
    service = CallbackService(
        store=store,
        poster=poster,
        limiter=RateLimiter(rate, timedelta(minutes=10), clock=lambda: now["t"]),
        text_limit=8000,
        clock=lambda: now["t"],
    )
    token = store.issue(
        channel_id="8",
        message_id="9",
        user_id="100",
        username="ada",
        root_message_id="9",
        hop=0,
        max_posts=posts,
        ttl_hours=ttl,
        now=T0,
    )
    return service, store, poster, token, now, path


def _stored_text(path) -> str:
    connection = sqlite3.connect(path)
    try:
        chunks: list[str] = []
        for table in ("callback_tokens", "tracked_messages"):
            for row in connection.execute(f"SELECT * FROM {table}"):
                chunks.extend(str(item) for item in row)
        return "\n".join(chunks)
    finally:
        connection.close()


def _reply(service: CallbackService, token: str, text: str = "done", reaction: str | None = None):
    body: dict[str, str] = {"text": text}
    if reaction is not None:
        body["reaction"] = reaction
    return service.handle(f"/reply/{token}", json.dumps(body).encode())


def test_token_is_hashed_and_replies_to_the_original_message(tmp_path) -> None:
    service, store, poster, token, _now, path = _service(tmp_path)
    result = _reply(service, token, "hello @everyone")
    assert result.status == 200
    assert result.body["posts_remaining"] == 4
    assert token not in _stored_text(path)
    assert token not in log_line(result, 12)
    assert token not in json.dumps(result.body)
    channel_id, message_id, chunks = poster.posts[0]
    assert (channel_id, message_id) == ("8", "9")
    assert chunks[0].startswith("↩ reply from ada's Grok Bot\n")
    assert "@everyone" in chunks[0]
    assert all(len(chunk) <= 2000 for chunk in chunks)
    tracked = store.tracked("posted-0")
    assert tracked is not None and tracked.hop == 0 and tracked.root_message_id == "9"
    store.close()


def test_post_budget_is_five_and_reactions_do_not_spend_it(tmp_path) -> None:
    service, store, poster, token, _now, _path = _service(tmp_path, posts=5)
    for _index in range(5):
        assert _reply(service, token, "note").status == 200
    blocked = _reply(service, token, "one more")
    assert blocked.status == 429
    assert blocked.body["error"] == "post budget used"
    reacted = service.handle(f"/react/{token}", json.dumps({"emoji": "👍"}).encode())
    assert reacted.status == 200
    assert reacted.body["posts_remaining"] == 0
    assert poster.reactions == [("8", "9", "👍")]
    assert len(poster.posts) == 5
    store.close()


def test_optional_reaction_on_a_reply_does_not_spend_a_second_post(tmp_path) -> None:
    service, store, poster, token, _now, _path = _service(tmp_path, posts=1)
    result = _reply(service, token, "final", reaction="✅")
    assert result.status == 200
    assert result.body["posts_remaining"] == 0
    assert poster.reactions == [("8", "9", "✅")]
    assert _reply(service, token, "again").status == 429
    store.close()


def test_expiry_and_never_expire(tmp_path) -> None:
    service, store, _poster, token, now, _path = _service(tmp_path, ttl=24)
    now["t"] = T0 + timedelta(hours=24) - timedelta(seconds=1)
    assert _reply(service, token, "still open").status == 200
    now["t"] = T0 + timedelta(hours=24)
    expired = _reply(service, token, "too late")
    assert expired.status == 410
    assert expired.body["error"] == "callback expired"
    open_token = store.issue(
        channel_id="8",
        message_id="9",
        user_id="100",
        username="ada",
        root_message_id="9",
        hop=0,
        max_posts=2,
        ttl_hours=0,
        now=T0,
    )
    now["t"] = T0 + timedelta(days=3650)
    assert _reply(service, open_token, "years later").status == 200
    missing = service.handle("/reply/not-a-real-token", b'{"text":"no"}')
    assert missing.status == 404
    assert missing.body["error"] == "callback rejected"
    store.close()


def test_failed_discord_post_refunds_the_budget(tmp_path) -> None:
    service, store, poster, token, _now, _path = _service(tmp_path, posts=1)
    poster.fail_posts = True
    failed = _reply(service, token, "nope")
    assert failed.status == 502
    poster.fail_posts = False
    assert _reply(service, token, "retry").status == 200
    store.close()


def test_channel_rate_limit_does_not_spend_a_post(tmp_path) -> None:
    service, store, poster, token, _now, _path = _service(tmp_path, posts=5, rate=1)
    assert _reply(service, token, "first").status == 200
    limited = _reply(service, token, "second")
    assert limited.status == 429
    assert limited.body["error"] == "rate limited"
    assert len(poster.posts) == 1
    reacted = service.handle(f"/react/{token}", json.dumps({"emoji": "👀"}).encode())
    assert reacted.status == 429
    assert poster.reactions == []
    store.close()


def test_emoji_allowlist_rejects_bridge_handoff_emoji(tmp_path) -> None:
    service, store, poster, token, _now, _path = _service(tmp_path, rate=10)
    for emoji in ("👀", "✅", "❌", "⏳", "👍"):
        result = service.handle(f"/react/{token}", json.dumps({"emoji": emoji}).encode())
        assert result.status == 200, emoji
    for emoji in ("📨", "⚠️", "eyes", ""):
        result = service.handle(f"/react/{token}", json.dumps({"emoji": emoji}).encode())
        assert result.status == 400
        assert result.body["error"] == "emoji not allowed"
    assert [item[2] for item in poster.reactions] == ["👀", "✅", "❌", "⏳", "👍"]
    huge = b'{"text":"' + (b"a" * (RAW_BODY_LIMIT + 10)) + b'"}'
    assert service.handle(f"/reply/{token}", huge).status == 413
    store.close()


def test_rejected_emoji_does_not_consume_the_rate_limit(tmp_path) -> None:
    service, _store, poster, token, _now, _path = _service(tmp_path, rate=1)
    rejected = service.handle(f"/react/{token}", json.dumps({"emoji": "📨"}).encode())
    assert rejected.status == 400
    assert service.handle(f"/react/{token}", json.dumps({"emoji": "👀"}).encode()).status == 200
    assert poster.reactions == [("8", "9", "👀")]


def test_long_text_is_chunked_under_the_discord_limit() -> None:
    text = "alpha\n" + ("b" * 3000)
    chunks = chunk_reply("@everyone ada", text)
    assert len(chunks) >= 2
    assert all(chunk.startswith("↩ reply from everyone ada's Grok Bot\n") for chunk in chunks)
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert "@" not in chunks[0].split("\n", 1)[0]
    bodies = [chunk.split("\n", 1)[1] for chunk in chunks]
    assert "".join(bodies) == text


def test_mention_mail_contains_the_callback_and_not_the_raw_token_on_disk(tmp_path) -> None:
    path = tmp_path / "links.sqlite3"
    registry = Registry(path)
    registry.upsert("100", None, parse_link_email("ada@mail.grokbot.com"))
    store = CallbackStore(path)
    trigger = message("9", "<@42> hello", 0)
    outcome = deliver_mention(
        MentionContext(
            author_id="100",
            bot_id="42",
            channel_name="design",
            trigger=trigger,
            prior=(),
            parent=None,
            channel_id="8",
        ),
        registry,
        RateLimiter(5, timedelta(minutes=10), clock=lambda: T0),
        callbacks=OpenCallbacks(
            base_url="https://bridge.example",
            ttl_hours=24,
            max_posts=5,
            text_limit=8000,
            store=store,
            now=T0,
        ),
    )
    assert outcome.mail is not None
    assert "https://bridge.example/reply/" in outcome.mail.text
    assert "It allows 5 posts." in outcome.mail.text
    token = outcome.mail.text.split("/reply/", 1)[1].split("'", 1)[0]
    assert token not in _stored_text(path)
    registry.close()
    store.close()
