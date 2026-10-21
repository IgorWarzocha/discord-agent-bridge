from datetime import datetime, timedelta

import pytest

from grokbot_bridge.burst import (
    DEFAULT_BURST_GAP,
    DEFAULT_BURST_WINDOW,
    DEFAULT_TAIL_COUNT,
    ChannelMessage,
    build_burst,
    build_tail,
)
from tests.support import message


def test_defaults_are_a_45_second_window_and_a_5_second_gap() -> None:
    assert DEFAULT_BURST_WINDOW == timedelta(seconds=45)
    assert DEFAULT_BURST_GAP == timedelta(seconds=5)
    assert DEFAULT_TAIL_COUNT == 5


def test_burst_keeps_a_continuous_run_and_stops_past_the_window() -> None:
    prior = [message(str(second), f"m{second}", second) for second in range(-50, 0, 5)]
    prior.append(message("bob", "side conversation", -7, author_id="200", author_name="bob"))
    trigger = message("0", "<@42> go", 0)
    burst = build_burst(prior, trigger)
    assert [item.id for item in burst] == [str(second) for second in range(-45, 0, 5)] + ["0"]
    assert "bob" not in {item.id for item in burst}
    assert [item.created_at for item in burst] == sorted(item.created_at for item in burst)


def test_burst_includes_a_gap_of_exactly_five_seconds() -> None:
    trigger = message("now", "<@42> go", 0)
    burst = build_burst([message("then", "then", -5)], trigger)
    assert [item.id for item in burst] == ["then", "now"]


def test_burst_stops_at_a_six_second_gap_inside_the_window() -> None:
    trigger = message("now", "<@42> go", 0)
    prior = [
        message("old", "old thought", -10),
        message("mid", "still going", -4),
        message("other", "ignore me", -2, author_id="200", author_name="bob"),
    ]
    burst = build_burst(prior, trigger)
    assert [item.id for item in burst] == ["mid", "now"]


def test_tail_is_the_latest_earlier_messages_without_burst_or_parent() -> None:
    trigger = message("9", "<@42> go", 0)
    parent = message("parent", "what shipped?", -10, author_id="200", author_name="bob")
    prior = [
        message("a0", "c0", -40, author_id="300", author_name="cam"),
        message("a1", "c1", -36, author_id="300", author_name="cam"),
        message("a2", "c2", -32, author_id="300", author_name="cam"),
        message("a3", "c3", -28, author_id="300", author_name="cam"),
        message("a4", "c4", -24, author_id="300", author_name="cam"),
        message("old", "earlier thought", -20),
        parent,
        message("b1", "looking", -8),
        message("b2", "mostly", -3),
    ]
    burst = build_burst(prior, trigger)
    tail = build_tail(prior, trigger, burst, parent=parent)
    assert [item.id for item in burst] == ["b1", "b2", "9"]
    assert [item.id for item in tail] == ["a1", "a2", "a3", "a4", "old"]
    assert set(item.id for item in tail).isdisjoint(item.id for item in burst)
    assert parent.id not in {item.id for item in tail}


def test_naive_timestamps_are_rejected() -> None:
    trigger = message("1", "hi", 0)
    naive = ChannelMessage(
        id="2",
        author_id="100",
        author_name="ada",
        content="hi",
        created_at=datetime(2026, 10, 21, 12, 0),
        jump_url="https://discord.com/channels/7/8/2",
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        build_burst([naive], trigger)
