"""How a Discord message names this bot and selects a link label."""

from __future__ import annotations

import re


def mentions_bot(content: str, bot_id: str) -> bool:
    return _mention(content, bot_id) is not None


def text_after_mention(content: str, bot_id: str) -> str:
    """Text that follows the first mention of this bot.

    Words before the mention do not count. The selection keyword and the
    subject line both use this text, so they stay aligned.
    """
    match = _mention(content, bot_id)
    if match is None:
        return ""
    return content[match.end() :].strip()


def selection_keyword(content: str, bot_id: str) -> str | None:
    """First word after the mention, compared case-insensitively to labels.

    The word is kept in the email body. It only chooses the recipient.
    Punctuation stays attached, so `research,` does not match `research`.
    """
    rest = text_after_mention(content, bot_id)
    if not rest:
        return None
    return rest.split(None, 1)[0].casefold()


def _mention(content: str, bot_id: str) -> re.Match[str] | None:
    if not bot_id.isdigit():
        return None
    return re.search(rf"<@!?{bot_id}>", content)
