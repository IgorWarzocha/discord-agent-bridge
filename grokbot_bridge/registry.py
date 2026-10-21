"""SQLite map from a Discord user to one or more Grok Bot addresses."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from grokbot_bridge.address import GrokAddress, parse_link_email

MAX_LINKS = 20
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?")
RESERVED_LABELS = frozenset({"default"})


class InvalidLabel(ValueError):
    """The user typed a label this bridge will not store."""


class LinkLimitError(ValueError):
    """The user already has MAX_LINKS saved."""


class RegistryError(ValueError):
    """A stored row is no longer a valid Grok address."""


@dataclass(frozen=True)
class Link:
    discord_user_id: str
    label: str | None
    address: GrokAddress
    created_at: datetime


def parse_label(value: str | None) -> str | None:
    """None means the unlabeled default link. Labels are stored lowercase."""
    if value is None:
        return None
    label = value.strip().casefold()
    if not label:
        raise InvalidLabel(
            "Omit the label to save the default link. A blank label is not allowed."
        )
    if label in RESERVED_LABELS:
        raise InvalidLabel(
            'The label "default" is reserved for the unlabeled link.'
        )
    if len(label) > 32 or _LABEL_RE.fullmatch(label) is None:
        raise InvalidLabel(
            "Labels must start and end with a letter or number "
            "and may contain hyphens and underscores."
        )
    return label


class Registry:
    def __init__(self, path: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._conn = sqlite3.connect(self._path, timeout=5)
        self._conn.row_factory = sqlite3.Row
        self._closed = False
        self._init()

    def close(self) -> None:
        if not self._closed:
            self._conn.close()
            self._closed = True

    def __enter__(self) -> Registry:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def upsert(self, user_id: str, label: str | None, address: GrokAddress) -> str:
        user_id = _user_id(user_id)
        key = label or ""
        existing = self._conn.execute(
            "SELECT 1 FROM links WHERE discord_user_id = ? AND label = ?",
            (user_id, key),
        ).fetchone()
        if existing is None and self._count(user_id) >= MAX_LINKS:
            raise LinkLimitError(
                f"You can save {MAX_LINKS} links. Unlink one before adding another."
            )
        self._conn.execute(
            """
            INSERT INTO links (discord_user_id, label, email, mode, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(discord_user_id, label) DO UPDATE SET
                email = excluded.email,
                mode = excluded.mode
            """,
            (user_id, key, address.exact, address.mode, self._clock().isoformat()),
        )
        self._conn.commit()
        if existing is None:
            return "created"
        return "updated"

    def list_links(self, user_id: str) -> tuple[Link, ...]:
        user_id = _user_id(user_id)
        rows = self._conn.execute(
            """
            SELECT label, email, created_at
            FROM links
            WHERE discord_user_id = ?
            ORDER BY created_at, label
            """,
            (user_id,),
        ).fetchall()
        return tuple(self._to_link(user_id, row) for row in rows)

    def delete_label(self, user_id: str, label: str) -> bool:
        return self._delete(user_id, label)

    def delete_default(self, user_id: str) -> bool:
        return self._delete(user_id, "")

    def delete_all(self, user_id: str) -> int:
        user_id = _user_id(user_id)
        cursor = self._conn.execute(
            "DELETE FROM links WHERE discord_user_id = ?",
            (user_id,),
        )
        self._conn.commit()
        return int(cursor.rowcount)

    def _delete(self, user_id: str, label: str) -> bool:
        user_id = _user_id(user_id)
        cursor = self._conn.execute(
            "DELETE FROM links WHERE discord_user_id = ? AND label = ?",
            (user_id, label),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def _count(self, user_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM links WHERE discord_user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row[0])

    def _init(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                discord_user_id TEXT NOT NULL,
                label TEXT NOT NULL,
                email TEXT NOT NULL,
                mode TEXT NOT NULL CHECK (mode IN ('bot', 'routine')),
                created_at TEXT NOT NULL,
                PRIMARY KEY (discord_user_id, label)
            )
            """
        )
        self._conn.commit()

    def _to_link(self, user_id: str, row: sqlite3.Row) -> Link:
        try:
            address = parse_link_email(row["email"])
            created_at = datetime.fromisoformat(row["created_at"])
        except ValueError as exc:
            raise RegistryError(f"stored row for {user_id} is invalid") from exc
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        label = row["label"] or None
        return Link(
            discord_user_id=user_id,
            label=label,
            address=address,
            created_at=created_at,
        )


def _user_id(value: str) -> str:
    if not isinstance(value, str) or not value.isdigit():
        raise ValueError("Discord user id must be a numeric string.")
    return value
