from grokbot_bridge.commands import link_account, status_account
from grokbot_bridge.registry import Registry


def test_link_reports_bot_or_routine_and_rejects_other_domains(tmp_path) -> None:
    registry = Registry(tmp_path / "links.sqlite3")
    rejected = link_account(
        registry, user_id="100", email="ada@gmail.com", tag=None, label=None
    )
    assert not rejected.ok
    assert registry.list_links("100") == ()

    bot = link_account(
        registry, user_id="100", email="Ada@mail.grokbot.com", tag=None, label=None
    )
    routine = link_account(
        registry,
        user_id="100",
        email="ada@mail.grokbot.com",
        tag="Research",
        label="Research",
    )
    assert bot.message == "Linked bot ada@mail.grokbot.com as the default."
    assert routine.message == "Linked routine ada+research@mail.grokbot.com with label `research`."
    status = status_account(registry, "100")
    assert "bot · default · ada@mail.grokbot.com" in status.message
    assert "routine · research · ada+research@mail.grokbot.com" in status.message
    registry.close()
