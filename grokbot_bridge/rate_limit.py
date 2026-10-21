"""In-memory per-Discord-user send limit. Resets when the process restarts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone


class RateLimiter:
    def __init__(
        self,
        max_events: int,
        window: timedelta,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        if window.total_seconds() <= 0:
            raise ValueError("window must be positive")
        self._max = max_events
        self._window = window
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._hits: dict[str, list[datetime]] = {}

    def allow(self, user_id: str) -> bool:
        now = self._clock()
        recent = [hit for hit in self._hits.get(user_id, []) if now - hit < self._window]
        if len(recent) >= self._max:
            self._hits[user_id] = recent
            return False
        recent.append(now)
        self._hits[user_id] = recent
        return True

    def denial_message(self) -> str:
        minutes = max(1, round(self._window.total_seconds() / 60))
        emails = "email" if self._max == 1 else "emails"
        unit = "minute" if minutes == 1 else "minutes"
        return (
            f"Rate limit: {self._max} {emails} per {minutes} {unit} for your Discord user. "
            "Wait before tagging your Grok Bot again."
        )
