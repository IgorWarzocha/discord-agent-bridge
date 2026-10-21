import pytest

from grokbot_bridge.address import InvalidAddress, parse_link_email


@pytest.mark.parametrize(
    ("email", "tag", "exact", "mode"),
    [
        ("Ada@mail.grokbot.com", None, "ada@mail.grokbot.com", "bot"),
        ("ada+notes@mail.grokbot.com", None, "ada+notes@mail.grokbot.com", "routine"),
        ("Ada@MAIL.GROKBOT.COM", "Notes", "ada+notes@mail.grokbot.com", "routine"),
        ("a.b_c-d@mail.grokbot.com", None, "a.b_c-d@mail.grokbot.com", "bot"),
        ("  ada@mail.grokbot.com  ", None, "ada@mail.grokbot.com", "bot"),
    ],
)
def test_accepts_plain_bot_and_tagged_routine(email: str, tag: str | None, exact: str, mode: str) -> None:
    address = parse_link_email(email, tag=tag)
    assert address.exact == exact
    assert address.mode == mode
    assert address.tag is None if mode == "bot" else address.tag == exact.split("@", 1)[0].split("+", 1)[1]


@pytest.mark.parametrize(
    ("email", "tag"),
    [
        ("ada@gmail.com", None),
        ("ada@mail.grokbot.com.evil.com", None),
        ("ada@sub.mail.grokbot.com", None),
        ("ada@mail.grokbot.co", None),
        ("not an email", None),
        ("ada@@mail.grokbot.com", None),
        ("@mail.grokbot.com", None),
        ("ada@", None),
        ("ada+@mail.grokbot.com", None),
        ("+tag@mail.grokbot.com", None),
        ("ada+tag+more@mail.grokbot.com", None),
        ("ada+tag@mail.grokbot.com", "other"),
        (".ada@mail.grokbot.com", None),
        ("ada.@mail.grokbot.com", None),
        ("ada..b@mail.grokbot.com", None),
        ("ada b@mail.grokbot.com", None),
        ("Ada <ada@mail.grokbot.com>", None),
        ("ada+a.b@mail.grokbot.com", None),
        ("ada@mail.grokbot.com", "bad tag"),
        ("ada@mail.grokbot.com", "a+b"),
        ("ada@mail.grokbot.com", " "),
        ("ada@mail.grokbot.com", ""),
        ("", None),
    ],
)
def test_rejects_non_grok_and_malformed_plus_tags(email: str, tag: str | None) -> None:
    with pytest.raises(InvalidAddress):
        parse_link_email(email, tag=tag)
