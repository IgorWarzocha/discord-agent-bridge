from datetime import timedelta

from discord_agent_bridge.burst import build_burst, build_tail
from discord_agent_bridge.connectors.grokbot import render_email
from discord_agent_bridge.payload import CallbackInstructions, build_payload, render_task
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
    payload = build_payload(
        channel_name="design",
        trigger=trigger,
        parent=parent,
        burst=burst,
        tail=tail,
        bot_id="42",
        label="research",
        callback=CallbackInstructions(
            reply_url="https://bridge.example/reply/TOKEN",
            react_url="https://bridge.example/react/TOKEN",
            expires_at=T0 + timedelta(hours=24),
            max_posts=5,
            text_limit=8000,
        ),
    )
    assert payload.subject == "[Discord] #design @ada: research check the palette"
    text = render_task(payload)
    assert text.index("--- Tagged message ---") < text.index("--- Parent ---")
    assert text.index("--- Parent ---") < text.index("--- Burst (same author, chronological) ---")
    burst_section = text.split("--- Burst (same author, chronological) ---\n", 1)[1].split(
        "\n\n--- Earlier channel", 1
    )[0]
    earlier = text.split("--- Earlier channel (not part of the burst) ---\n", 1)[1]
    assert "what shipped?" in text.split("--- Parent ---", 1)[1].split("--- Burst", 1)[0]
    assert burst_section.index("looking at the palette") < burst_section.index("mostly the blues")
    assert "earlier thought" in earlier and "earlier thought" not in burst_section
    assert "This link expires at 2026-10-22T12:00:00+00:00." in text
    assert "It allows 5 posts." in text
    assert "curl -sS -X POST 'https://bridge.example/reply/TOKEN' \\" in text
    assert "-d '{\"text\":\"your reply\"}'" in text
    assert "-d '{\"emoji\":\"👀\"}'" in text

    mail = render_email(payload, {"email": "ada+research@mail.grokbot.com", "mode": "routine"})
    assert mail.to == "ada+research@mail.grokbot.com"
    assert mail.subject == payload.subject
    assert "Mode: routine\n" in mail.text
    assert "To: ada+research@mail.grokbot.com\n" in mail.text

    long_trigger = message("1", "<@42> " + ("alpha " * 20) + "\nbeta", 0)
    long_payload = build_payload(
        channel_name="design\nsecret",
        trigger=long_trigger,
        parent=None,
        burst=(long_trigger,),
        tail=(),
        bot_id="42",
        label=None,
        callback=None,
    )
    assert "\n" not in long_payload.subject
    assert long_payload.subject.startswith("[Discord] #design secret @ada: ")
    assert long_payload.subject.endswith("...")
    assert "not configured (set CALLBACK_BASE_URL" in render_task(long_payload)
    assert ("alpha " * 20) + "\nbeta" in render_task(long_payload)
