"""Process configuration. Read at startup, never at import."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_FROM_RE = re.compile(r"(?:[^<>\n]+\s*<([^<>\s]+)>|([^<>\s]+))")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_HTTPS_RE = re.compile(r"https://[^\s/?#]+(?:/[^\s?#]*)?")


class SettingsError(ValueError):
    """The process cannot start with this environment."""


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    resend_api_key: str
    resend_from: str
    database_path: Path
    rate_limit_max: int
    rate_limit_window_seconds: int
    burst_window_seconds: int
    burst_gap_seconds: int
    channel_tail_count: int
    callback_base_url: str | None
    callback_ttl_hours: int
    callback_max_posts: int
    callback_text_limit: int
    callback_rate_limit_max: int
    callback_rate_limit_window_seconds: int
    max_hops: int
    bot_allowlist: tuple[str, ...]
    http_host: str
    http_port: int


def load_dotenv(path: Path) -> None:
    """Fill missing environment variables from a local env file.

    Existing variables win, so a shell export is not overwritten by the file.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    token = source.get("DISCORD_BOT_TOKEN", "").strip()
    api_key = source.get("RESEND_API_KEY", "").strip()
    if not token:
        raise SettingsError("DISCORD_BOT_TOKEN is required.")
    if not api_key:
        raise SettingsError("RESEND_API_KEY is required.")
    database = source.get("DATABASE_PATH", "").strip() or "data/links.sqlite3"
    return Settings(
        discord_token=token,
        discord_guild_id=_guild_id(source),
        resend_api_key=api_key,
        resend_from=_from_address(source.get("RESEND_FROM", "")),
        database_path=Path(database),
        rate_limit_max=_int_env(source, "RATE_LIMIT_MAX", 5, 1, 100),
        rate_limit_window_seconds=_int_env(source, "RATE_LIMIT_WINDOW_SECONDS", 600, 60, 86400),
        burst_window_seconds=_int_env(source, "BURST_WINDOW_SECONDS", 45, 30, 60),
        burst_gap_seconds=_int_env(source, "BURST_GAP_SECONDS", 5, 2, 10),
        channel_tail_count=_int_env(source, "CHANNEL_TAIL_COUNT", 5, 0, 10),
        callback_base_url=_base_url(source),
        callback_ttl_hours=_int_env(source, "CALLBACK_TTL_HOURS", 24, 0, 8760),
        callback_max_posts=_int_env(source, "CALLBACK_MAX_POSTS", 5, 1, 50),
        callback_text_limit=_int_env(source, "CALLBACK_TEXT_LIMIT", 8000, 1, 16000),
        callback_rate_limit_max=_int_env(source, "CALLBACK_RATE_LIMIT_MAX", 20, 1, 1000),
        callback_rate_limit_window_seconds=_int_env(
            source, "CALLBACK_RATE_LIMIT_WINDOW_SECONDS", 600, 60, 86400
        ),
        max_hops=_int_env(source, "MAX_HOPS", 3, 1, 20),
        bot_allowlist=_allowlist(source),
        http_host=_http_host(source),
        http_port=_int_env(source, "HTTP_PORT", 8787, 1, 65535),
    )


def _guild_id(source: Mapping[str, str]) -> int | None:
    raw = source.get("DISCORD_GUILD_ID", "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise SettingsError("DISCORD_GUILD_ID must be a numeric server id.")
    return int(raw)


def _from_address(value: str) -> str:
    raw = value.strip()
    match = _FROM_RE.fullmatch(raw)
    email = ""
    if match is not None:
        email = match.group(1) or match.group(2) or ""
    if match is None or _EMAIL_RE.fullmatch(email) is None:
        raise SettingsError("RESEND_FROM must be an email on your verified Resend domain.")
    return raw


def _base_url(source: Mapping[str, str]) -> str | None:
    raw = source.get("CALLBACK_BASE_URL", "").strip().rstrip("/")
    if not raw:
        return None
    if _HTTPS_RE.fullmatch(raw) is None:
        raise SettingsError(
            "CALLBACK_BASE_URL must be an https origin the bot can reach, or be left empty."
        )
    return raw


def _http_host(source: Mapping[str, str]) -> str:
    host = source.get("HTTP_HOST", "").strip() or "127.0.0.1"
    if "/" in host or " " in host:
        raise SettingsError("HTTP_HOST must be a host name or address, without a path.")
    return host


def _allowlist(source: Mapping[str, str]) -> tuple[str, ...]:
    raw = source.get("BOT_ALLOWLIST", "").strip()
    if not raw:
        return ()
    ids: list[str] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if not item.isdigit():
            raise SettingsError("BOT_ALLOWLIST must be comma-separated Discord user ids.")
        if item not in ids:
            ids.append(item)
    return tuple(ids)


def _int_env(source: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = source.get(name, "").strip()
    if not raw:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise SettingsError(f"{name} must be an integer.") from exc
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}.")
    return value
