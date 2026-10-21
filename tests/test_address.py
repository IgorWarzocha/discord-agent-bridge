import pytest

from grokbot_bridge.address import InvalidAddress, parse_link_email


def test_plain_tagged_and_bad_addresses() -> None:
    plain = parse_link_email("Ada@mail.grokbot.com")
    assert plain.exact == "ada@mail.grokbot.com"
    assert plain.mode == "bot"
    assert plain.tag is None

    tagged = parse_link_email("ada+notes@mail.grokbot.com")
    assert tagged.exact == "ada+notes@mail.grokbot.com"
    assert tagged.mode == "routine"
    assert tagged.tag == "notes"

    built = parse_link_email("Ada@MAIL.GROKBOT.COM", tag="Notes")
    assert built.exact == "ada+notes@mail.grokbot.com"
    assert built.mode == "routine"

    for email, tag in (
        ("ada@gmail.com", None),
        ("ada@mail.grokbot.com.evil.com", None),
        ("ada@sub.mail.grokbot.com", None),
        ("ada+tag+more@mail.grokbot.com", None),
        ("ada+tag@mail.grokbot.com", "other"),
        ("ada+@mail.grokbot.com", None),
        ("+tag@mail.grokbot.com", None),
        ("ada..b@mail.grokbot.com", None),
        ("", None),
    ):
        with pytest.raises(InvalidAddress):
            parse_link_email(email, tag=tag)
