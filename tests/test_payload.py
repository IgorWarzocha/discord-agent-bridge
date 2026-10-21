from datetime import timedelta

from grokbot_bridge.address import parse_link_email
from grokbot_bridge.burst import build_burst, build_tail
from grokbot_bridge.payload import CallbackInstructions, format_mail
from tests.support import T0, message


def test_subject_body_and_callback_block() -> None:
    trigger = message("9", "<@42> research check the palette", 0)
    parent = message("parent", "what shipped?", -10, author_id="200", author_name="bob")
    prior = (
        message("a0", "c0", -40, author_id="300", author_name="cam"),
        message("old", "earlier thought", -20),
        parent,
        message("b1", "looking at the palette", -8),
        message("b2", "mostly the blues", -3),
    )
    burst = build_burst(prior, trigger)
    tail = build_tail(prior, trigger, burst, parent=parent)
    mail = format_mail(
        address=parse_link_email("ada@mail.grokbot.com", tag="research"),
        label="research",
        channel_name="design",
        trigger=trigger,
        parent=parent,
        burst=burst,
        tail=tail,
        bot_id="42",
        callback=CallbackInstructions(
            reply_url="https://bridge.example/reply/TOKEN",
            react_url="https://bridge.example/react/TOKEN",
            expires_at=T0 + timedelta(hours=24),
            max_posts=5,
            text_limit=8000,
        ),
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
    burst_section = text.split("--- Burst (same author, chronological) ---\n", 1)[1].split(
        "\n\n--- Earlier channel", 1
    )[0]
    earlier = text.split("--- Earlier channel (not part of the burst) ---\n", 1)[1]
    assert "what shipped?" in text.split("--- Parent ---", 1)[1].split("--- Burst", 1)[0]
    assert burst_section.index("looking at the palette") < burst_section.index("mostly the blues")
    assert "earlier thought" in earlier and "earlier thought" not in burst_section
    assert "what shipped?" not in earlier
    assert "Mode: routine\n" in text
    assert f"Timestamp: {T0.isoformat()}\n" in text
    assert "This link expires at 2026-10-22T12:00:00+00:00." in text
    assert "It allows 5 posts." in text
    assert "Each post replies to the original tagged message." in text
    assert "curl -sS -X POST 'https://bridge.example/reply/TOKEN' \\" in text
    assert "-d '{\"text\":\"your reply\"}'" in text
    assert "curl -sS -X POST 'https://bridge.example/react/TOKEN' \\" in text
    assert "-d '{\"emoji\":\"👀\"}'" in text
    assert 'JSON: {"text":"..."}' in text

    long_trigger = message("1", "<@42> " + ("alpha " * 20) + "\nbeta", 0)
    long_mail = format_mail(
        address=parse_link_email("ada@mail.grokbot.com"),
        label=None,
        channel_name="design\nsecret",
        trigger=long_trigger,
        parent=None,
        burst=(long_trigger,),
        tail=(),
        bot_id="42",
        callback=None,
    )
    assert "\n" not in long_mail.subject
    assert long_mail.subject.startswith("[Discord] #design secret @ada: ")
    assert long_mail.subject.endswith("...")
    assert len(long_mail.subject) <= 140
    assert "Mode: bot\n" in long_mail.text
    assert "not configured (set CALLBACK_BASE_URL" in long_mail.text
    assert ("alpha " * 20) + "\nbeta" in long_mail.text
