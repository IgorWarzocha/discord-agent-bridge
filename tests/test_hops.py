from discord_agent_bridge.callbacks import TrackedMessage
from discord_agent_bridge.hops import decide_forward


def test_loop_guard_and_hop_limit() -> None:
    human = decide_forward(
        author_id="100",
        author_is_bot=False,
        is_webhook=False,
        bridge_user_id="1",
        allowlist=("50",),
        parent=None,
        trigger_message_id="9",
        max_hops=3,
    )
    assert human.forward and human.hop == 0 and human.reason == "human"

    own = decide_forward(
        author_id="1",
        author_is_bot=True,
        is_webhook=False,
        bridge_user_id="1",
        allowlist=("1", "50"),
        parent=None,
        trigger_message_id="9",
        max_hops=3,
    )
    assert not own.forward and own.reason == "bridge"

    stranger = decide_forward(
        author_id="77",
        author_is_bot=True,
        is_webhook=False,
        bridge_user_id="1",
        allowlist=("50",),
        parent=None,
        trigger_message_id="9",
        max_hops=3,
    )
    webhook = decide_forward(
        author_id="77",
        author_is_bot=False,
        is_webhook=True,
        bridge_user_id="1",
        allowlist=("50",),
        parent=None,
        trigger_message_id="9",
        max_hops=3,
    )
    assert not stranger.forward and stranger.reason == "not_allowlisted"
    assert not webhook.forward and webhook.reason == "not_allowlisted"

    allowed = decide_forward(
        author_id="50",
        author_is_bot=False,
        is_webhook=True,
        bridge_user_id="1",
        allowlist=("50",),
        parent=TrackedMessage("8", "2", "9", 2),
        trigger_message_id="11",
        max_hops=3,
    )
    assert allowed.forward and allowed.hop == 3 and allowed.root_id == "9"

    stopped = decide_forward(
        author_id="50",
        author_is_bot=True,
        is_webhook=False,
        bridge_user_id="1",
        allowlist=("50",),
        parent=TrackedMessage("8", "2", "9", 3),
        trigger_message_id="12",
        max_hops=3,
    )
    assert not stopped.forward and stopped.hop == 4 and stopped.reason == "hop_limit"
