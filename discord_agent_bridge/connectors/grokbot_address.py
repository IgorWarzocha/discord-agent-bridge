"""Grok Bot addresses on mail.grokbot.com.

A plain address is bot mode; one plus-tag selects routine mode. Both require
an email-triggered routine on the receiving bot. These modes describe address
routing, not whether the bot wakes automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

GROK_DOMAIN = "mail.grokbot.com"

_BASE_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_TAG_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?")

Mode = Literal["bot", "routine"]


class InvalidAddress(ValueError):
    """The user typed an address this bridge will not store."""


@dataclass(frozen=True)
class GrokAddress:
    local: str
    tag: str | None

    def __post_init__(self) -> None:
        if self.tag == "":
            raise ValueError("tag must be None or non-empty")

    @property
    def mode(self) -> Mode:
        if self.tag is None:
            return "bot"
        return "routine"

    @property
    def exact(self) -> str:
        if self.tag is None:
            return f"{self.local}@{GROK_DOMAIN}"
        return f"{self.local}+{self.tag}@{GROK_DOMAIN}"


def parse_link_email(email: str, tag: str | None = None) -> GrokAddress:
    """Accept a plain or plus-tagged address, optionally adding `tag` to a plain one.

    Stored addresses are lowercase. A tag option is rejected when the address
    already contains a plus-tag, so the saved address cannot silently change.
    """
    extra = _parse_tag_option(tag)
    raw = email.strip().casefold()
    if not raw:
        raise InvalidAddress("Enter an address at mail.grokbot.com.")
    if any(char.isspace() for char in raw) or raw.count("@") != 1:
        raise InvalidAddress("Email must be an address at mail.grokbot.com.")
    local, domain = raw.split("@", 1)
    if domain != GROK_DOMAIN:
        raise InvalidAddress("Email must be an address at mail.grokbot.com.")
    base, plus = _split_local(local, extra)
    if not _valid_base(base):
        raise InvalidAddress(
            "The mailbox name must start and end with a letter or number "
            "and may contain dots, hyphens, and underscores."
        )
    if plus is not None and not _valid_tag(plus):
        raise InvalidAddress(
            "Tags must start and end with a letter or number "
            "and may contain hyphens and underscores."
        )
    if plus is not None and len(base) + 1 + len(plus) > 64:
        raise InvalidAddress("That address is too long.")
    return GrokAddress(local=base, tag=plus)


def _parse_tag_option(tag: str | None) -> str | None:
    if tag is None:
        return None
    value = tag.strip().casefold()
    if not value:
        raise InvalidAddress("Omit the tag option, or provide a plus-tag such as research.")
    if not _valid_tag(value):
        raise InvalidAddress(
            "Tags must start and end with a letter or number "
            "and may contain hyphens and underscores."
        )
    return value


def _split_local(local: str, extra: str | None) -> tuple[str, str | None]:
    if local.count("+") > 1:
        raise InvalidAddress("Use at most one plus-tag, like name+tag@mail.grokbot.com.")
    if "+" not in local:
        return local, extra
    base, existing = local.split("+", 1)
    if extra is not None:
        raise InvalidAddress(
            "That address already has a plus-tag. Omit the tag option, "
            "or pass the plain address and a tag."
        )
    if not existing:
        raise InvalidAddress("Use at most one plus-tag, like name+tag@mail.grokbot.com.")
    return base, existing


def _valid_base(value: str) -> bool:
    return (
        1 <= len(value) <= 64
        and ".." not in value
        and _BASE_RE.fullmatch(value) is not None
    )


def _valid_tag(value: str) -> bool:
    return 1 <= len(value) <= 32 and _TAG_RE.fullmatch(value) is not None
