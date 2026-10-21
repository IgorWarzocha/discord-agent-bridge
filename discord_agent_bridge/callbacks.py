"""Per-message callback tokens. The raw token is never stored."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DUMMY_DIGEST = hashlib.sha256(b"discord-agent-bridge-miss").hexdigest()


class CallbackError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CallbackTicket:
    token_hash: str
    channel_id: str
    message_id: str
    user_id: str
    username: str
    root_message_id: str
    hop: int
    posts_remaining: int


@dataclass(frozen=True)
class TrackedMessage:
    message_id: str
    channel_id: str
    root_message_id: str
    hop: int


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CallbackStore:
    """SQLite tokens and tracked message hops. Safe for the bot thread and HTTP thread."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, timeout=5, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._closed = False
        self._init()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def issue(
        self,
        *,
        channel_id: str,
        message_id: str,
        user_id: str,
        username: str,
        root_message_id: str,
        hop: int,
        max_posts: int,
        ttl_hours: int,
        now: datetime,
    ) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = None
        if ttl_hours > 0:
            expires_at = (now + timedelta(hours=ttl_hours)).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO callback_tokens (
                    token_hash, channel_id, message_id, user_id, username,
                    root_message_id, hop, posts_remaining, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    digest_token(token),
                    channel_id,
                    message_id,
                    user_id,
                    username,
                    root_message_id,
                    hop,
                    max_posts,
                    expires_at,
                    now.isoformat(),
                ),
            )
            self._conn.commit()
        return token

    def peek(self, token: str, now: datetime) -> CallbackTicket:
        """Validate a token without using a post. Reactions use this."""
        with self._lock:
            row = self._row(token)
            self._ensure_live(row, now)
            return _ticket(row)

    def take_post(self, token: str, now: datetime) -> CallbackTicket:
        """Reserve one post. Refund it if Discord rejects the send."""
        with self._lock:
            row = self._row(token)
            self._ensure_live(row, now)
            if int(row["posts_remaining"]) <= 0:
                raise CallbackError("budget")
            cursor = self._conn.execute(
                """
                UPDATE callback_tokens
                SET posts_remaining = posts_remaining - 1
                WHERE token_hash = ? AND posts_remaining > 0
                """,
                (row["token_hash"],),
            )
            self._conn.commit()
            if cursor.rowcount != 1:
                raise CallbackError("budget")
            remaining = int(row["posts_remaining"]) - 1
            return _ticket(row, posts_remaining=remaining)

    def refund_post(self, token_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE callback_tokens
                SET posts_remaining = posts_remaining + 1
                WHERE token_hash = ?
                """,
                (token_hash,),
            )
            self._conn.commit()

    def track(self, message_id: str, channel_id: str, root_message_id: str, hop: int) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO tracked_messages (message_id, channel_id, root_message_id, hop)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    root_message_id = excluded.root_message_id,
                    hop = excluded.hop
                """,
                (message_id, channel_id, root_message_id, hop),
            )
            self._conn.commit()

    def tracked(self, message_id: str) -> TrackedMessage | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT message_id, channel_id, root_message_id, hop
                FROM tracked_messages WHERE message_id = ?
                """,
                (message_id,),
            ).fetchone()
        if row is None:
            return None
        return TrackedMessage(
            message_id=row["message_id"],
            channel_id=row["channel_id"],
            root_message_id=row["root_message_id"],
            hop=int(row["hop"]),
        )

    def _row(self, token: str) -> sqlite3.Row:
        digest = digest_token(token) if len(token) <= 128 else _DUMMY_DIGEST
        row = self._conn.execute(
            "SELECT * FROM callback_tokens WHERE token_hash = ?",
            (digest,),
        ).fetchone()
        stored = row["token_hash"] if row is not None else _DUMMY_DIGEST
        if not hmac.compare_digest(stored, digest) or row is None:
            raise CallbackError("missing")
        return row

    def _ensure_live(self, row: sqlite3.Row, now: datetime) -> None:
        expires_at = row["expires_at"]
        if expires_at is None:
            return
        expires = datetime.fromisoformat(expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now >= expires:
            raise CallbackError("expired")

    def _init(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS callback_tokens (
                token_hash TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                root_message_id TEXT NOT NULL,
                hop INTEGER NOT NULL,
                posts_remaining INTEGER NOT NULL,
                expires_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracked_messages (
                message_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                root_message_id TEXT NOT NULL,
                hop INTEGER NOT NULL
            )
            """
        )
        self._conn.commit()


def _ticket(row: sqlite3.Row, *, posts_remaining: int | None = None) -> CallbackTicket:
    remaining = int(row["posts_remaining"]) if posts_remaining is None else posts_remaining
    return CallbackTicket(
        token_hash=row["token_hash"],
        channel_id=row["channel_id"],
        message_id=row["message_id"],
        user_id=row["user_id"],
        username=row["username"],
        root_message_id=row["root_message_id"],
        hop=int(row["hop"]),
        posts_remaining=remaining,
    )
