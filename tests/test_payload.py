from grokbot_bridge.address import parse_link_email
from grokbot_bridge.burst import build_burst, build_tail
from grokbot_bridge.payload import format_mail
from tests.support import T0, message


def _scenario() -> tuple[object, object, object, tuple[object, ...], tuple[object, ...]]:
    trigger = message("9", "<@42> research check the palette", 0)
    parent = message("parent", "what shipped?", -10, author_id="200", author_name="bob")
    prior = (
        message("a0", "c0", -40, author_id="300", author_name="cam"),
        message("a1", "c1", -36, author_id="300", author_name="cam"),
        message("a2", "c2", -32, author_id="300", author_name="cam"),
        message("a3", "c3", -28, author_id="300", author_name="cam"),
        message("a4", "c4", -24, author_id="300", author_name="cam"),
        message("old", "earlier thought", -20),
        parent,
        message("b1", "looking at the palette", -8),
        message("b2", "mostly the blues", -3),
    )
    burst = build_burst(prior, trigger)
    tail = build_tail(prior, trigger, burst, parent=parent)
    return trigger, parent, prior, burst, tail


def test_subject_and_body_keep_burst_parent_and_tail_apart() -> None:
    trigger, parent, _prior, burst, tail = _scenario()
    mail = format_mail(
        address=parse_link_email("ada@mail.grokbot.com", tag="research"),
        label="research",
        channel_name="design",
        trigger=trigger,
        parent=parent,
        burst=burst,
        tail=tail,
        bot_id="42",
        callback_webhook_url=None,
    )
    assert mail.to == "ada+research@mail.grokbot.com"
    assert mail.subject == "[Discord] #design @ada: research check the palette"
    text = mail.text
    assert text.index("--- Tagged message ---") < text.index("--- Parent ---")
    assert text.index("--- Parent ---") < text.index("--- Burst (same author, chronological) ---")
    assert text.index("--- Burst (same author, chronological) ---") < text.index(
        "--- Earlier channel (not part of the burst) ---"
    )
    tagged = text.split("--- Tagged message ---\n", 1)[1].split("\n\n--- Parent ---", 1)[0]
    assert tagged == "<@42> research check the palette"
    parent_section = text.split("--- Parent ---\n", 1)[1].split("\n\n--- Burst", 1)[0]
    burst_section = text.split("--- Burst (same author, chronological) ---\n", 1)[1].split(
        "\n\n--- Earlier channel", 1
    )[0]
    earlier = text.split("--- Earlier channel (not part of the burst) ---\n", 1)[1]
    assert "what shipped?" in parent_section
    assert burst_section.index("looking at the palette") < burst_section.index("mostly the blues")
    assert burst_section.index("mostly the blues") < burst_section.index("research check the palette")
    assert "earlier thought" not in burst_section
    assert "what shipped?" not in burst_section
    assert "earlier thought" in earlier
    assert "c0" not in text
    assert "what shipped?" not in earlier
    assert "looking at the palette" not in earlier
    assert "Channel: #design\n" in text
    assert "Discord username: ada\n" in text
    assert "Discord user id: 100\n" in text
    assert "Message link: https://discord.com/channels/7/8/9\n" in text
    assert f"Timestamp: {T0.isoformat()}\n" in text
    assert "Mode: routine\n" in text
    assert "Label: research\n" in text
    assert "To: ada+research@mail.grokbot.com\n" in text
    assert (
        "Callback webhook: not configured (future work; this bridge does not post replies back to Discord)"
        in text
    )


def test_bot_mode_subject_and_empty_parent_and_tail() -> None:
    trigger = message("1", "<@42> hello there", 0)
    mail = format_mail(
        address=parse_link_email("ada@mail.grokbot.com"),
        label=None,
        channel_name="ops",
        trigger=trigger,
        parent=None,
        burst=(trigger,),
        tail=(),
        bot_id="42",
        callback_webhook_url="https://example.com/hook",
    )
    assert mail.subject == "[Discord] #ops @ada: hello there"
    assert mail.to == "ada@mail.grokbot.com"
    assert "Mode: bot\n" in mail.text
    assert "Label: default\n" in mail.text
    assert "not a reply" in mail.text
    assert "\nnone\n" in mail.text
    assert (
        "Callback webhook: https://example.com/hook "
        "(placeholder only; this bridge does not post replies back to Discord)"
        in mail.text
    )


def test_subject_is_one_line_and_the_body_keeps_the_full_message() -> None:
    words = "alpha " * 20
    trigger = message("1", f"<@42> {words}\nbeta", 0)
    mail = format_mail(
        address=parse_link_email("ada@mail.grokbot.com"),
        label=None,
        channel_name="design\nsecret",
        trigger=trigger,
        parent=None,
        burst=(trigger,),
        tail=(),
        bot_id="42",
        callback_webhook_url=None,
    )
    assert "\n" not in mail.subject
    assert mail.subject.startswith("[Discord] #design secret @ada: ")
    assert mail.subject.endswith("...")
    assert len(mail.subject) <= 140
    assert f"{words}\nbeta" in mail.text
