import json
import sqlite3
from datetime import timedelta

from grokbot_bridge.callbacks import CallbackStore
from grokbot_bridge.rate_limit import RateLimiter
from grokbot_bridge.replies import CallbackService, DiscordPostError, ReplyPoster
from tests.support import T0


class FakePoster(ReplyPoster):
    def __init__(self) -> None:
        self.posts: list[tuple[str, str, tuple[str, ...]]] = []
        self.reactions: list[tuple[str, str, str]] = []
        self.fail_posts = False

    def post_chunks(self, *, channel_id: str, message_id: str, chunks: tuple[str, ...]) -> tuple[str, ...]:
        if self.fail_posts:
            raise DiscordPostError("discord post failed")
        self.posts.append((channel_id, message_id, chunks))
        return tuple(f"posted-{len(self.posts)}")

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


def _reply(service: CallbackService, token: str, text: str = "done") -> object:
    return service.handle(f"/reply/{token}", json.dumps({"text": text}).encode())


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


def test_token_expires_and_is_not_stored_in_clear(tmp_path) -> None:
    service, store, poster, token, now, path = _service(tmp_path, ttl=24)
    now["t"] = T0 + timedelta(hours=24) - timedelta(seconds=1)
    assert _reply(service, token, "still open").status == 200
    assert poster.posts[0][1] == "9"
    assert token not in _stored_text(path)
    now["t"] = T0 + timedelta(hours=24)
    expired = _reply(service, token, "too late")
    assert expired.status == 410
    assert expired.body["error"] == "callback expired"
    forever = store.issue(
        channel_id="8",
        message_id="9",
        user_id="100",
        username="ada",
        root_message_id="9",
        hop=0,
        max_posts=1,
        ttl_hours=0,
        now=T0,
    )
    now["t"] = T0 + timedelta(days=3650)
    assert _reply(service, forever, "years later").status == 200
    missing = service.handle("/reply/not-a-real-token", b'{"text":"no"}')
    assert missing.status == 404
    assert missing.body["error"] == "callback rejected"
    store.close()


def test_five_posts_then_reactions_still_work(tmp_path) -> None:
    service, store, poster, token, _now, _path = _service(tmp_path, posts=5)
    long_text = "alpha\n" + ("b" * 3000)
    first = _reply(service, token, long_text)
    assert first.status == 200
    chunks = poster.posts[0][2]
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert "".join(chunk.split("\n", 1)[1] for chunk in chunks) == long_text
    for _index in range(4):
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


def test_failed_discord_post_does_not_spend_a_post(tmp_path) -> None:
    service, store, poster, token, _now, _path = _service(tmp_path, posts=1)
    poster.fail_posts = True
    assert _reply(service, token, "nope").status == 502
    poster.fail_posts = False
    assert _reply(service, token, "retry").status == 200
    store.close()


def test_callback_rate_limit_does_not_spend_a_post(tmp_path) -> None:
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


def test_reaction_allowlist_rejects_other_emoji(tmp_path) -> None:
    service, store, poster, token, _now, _path = _service(tmp_path)
    for emoji in ("👀", "✅", "❌", "⏳", "👍"):
        result = service.handle(f"/react/{token}", json.dumps({"emoji": emoji}).encode())
        assert result.status == 200, emoji
        assert poster.reactions[-1] == ("8", "9", emoji)
    for emoji in ("📨", "⚠️", "eyes"):
        result = service.handle(f"/react/{token}", json.dumps({"emoji": emoji}).encode())
        assert result.status == 400
        assert result.body["error"] == "emoji not allowed"
    assert [item[2] for item in poster.reactions] == ["👀", "✅", "❌", "⏳", "👍"]
    store.close()
