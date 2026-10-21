from grokbot_bridge.burst import build_burst, build_tail
from tests.support import message


def test_burst_window_gap_and_tail() -> None:
    prior = [message(str(second), f"m{second}", second) for second in range(-50, 0, 5)]
    prior.append(message("bob", "side conversation", -7, author_id="200", author_name="bob"))
    trigger = message("0", "<@42> go", 0)
    burst = build_burst(prior, trigger)
    assert [item.id for item in burst] == [str(second) for second in range(-45, 0, 5)] + ["0"]
    assert "bob" not in {item.id for item in burst}
    assert [item.created_at for item in burst] == sorted(item.created_at for item in burst)

    exact = build_burst([message("then", "then", -5)], trigger)
    assert [item.id for item in exact] == ["then", "0"]

    gapped = build_burst(
        [
            message("old", "old thought", -10),
            message("mid", "still going", -4),
            message("other", "ignore me", -2, author_id="200", author_name="bob"),
        ],
        trigger,
    )
    assert [item.id for item in gapped] == ["mid", "0"]

    parent = message("parent", "what shipped?", -10, author_id="200", author_name="bob")
    context = [
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
    reply = message("9", "<@42> go", 0)
    kept = build_burst(context, reply)
    tail = build_tail(context, reply, kept, parent=parent)
    assert [item.id for item in kept] == ["b1", "b2", "9"]
    assert [item.id for item in tail] == ["a1", "a2", "a3", "a4", "old"]
    assert parent.id not in {item.id for item in tail}
