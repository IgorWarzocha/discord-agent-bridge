from grokbot_bridge.callbacks import TrackedMessage
from grokbot_bridge.hops import decide_forward, hop_limit_message


def _decision(**overrides):
    values = {
        "author_id": "100",
        "author_is_bot": False,
        "is_webhook": False,
        "bridge_user_id": "1",
        "allowlist": ("50",),
        "parent": None,
        "trigger_message_id": "9",
        "max_hops": 3,
    }
    values.update(overrides)
    return decide_forward(**values)


def test_humans_forward_and_the_bridge_never_does() -> None:
    human = _decision()
    assert human.forward and human.hop == 0 and human.reason == "human"
    own = _decision(author_id="1", author_is_bot=True, allowlist=("1", "50"))
    assert not own.forward and own.reason == "bridge"


def test_other_bots_and_webhooks_need_the_allowlist() -> None:
    stranger = _decision(author_id="77", author_is_bot=True)
    assert not stranger.forward and stranger.reason == "not_allowlisted"
    webhook = _decision(author_id="77", is_webhook=True)
    assert not webhook.forward and webhook.reason == "not_allowlisted"
    allowed = _decision(author_id="50", is_webhook=True)
    assert allowed.forward and allowed.hop == 1 and allowed.reason == "bot"


def test_bot_hops_stop_after_the_limit() -> None:
    parent = TrackedMessage("8", "2", "9", 2)
    third = _decision(author_id="50", author_is_bot=True, parent=parent)
    assert third.forward and third.hop == 3 and third.root_id == "9"
    parent = TrackedMessage("8", "2", "9", 3)
    stopped = _decision(author_id="50", author_is_bot=True, parent=parent)
    assert not stopped.forward and stopped.hop == 4 and stopped.reason == "hop_limit"
    assert hop_limit_message(3) == "Stopped: this thread is past the bot-to-bot hop limit (3)."
