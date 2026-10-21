from grokbot_bridge.commands import link_account, status_account, unlink_account
from grokbot_bridge.registry import Registry


def _registry(tmp_path) -> Registry:
    return Registry(tmp_path / "links.sqlite3")


def test_link_reports_bot_or_routine_and_the_exact_address(tmp_path) -> None:
    registry = _registry(tmp_path)
    bot = link_account(
        registry,
        user_id="100",
        email="Ada@mail.grokbot.com",
        tag=None,
        label=None,
    )
    routine = link_account(
        registry,
        user_id="100",
        email="ada@mail.grokbot.com",
        tag="Research",
        label="Research",
    )
    assert bot.ok
    assert bot.message == "Linked bot ada@mail.grokbot.com as the default."
    assert routine.ok
    assert routine.message == "Linked routine ada+research@mail.grokbot.com with label `research`."
    status = status_account(registry, "100")
    assert "bot · default · ada@mail.grokbot.com" in status.message
    assert "routine · research · ada+research@mail.grokbot.com" in status.message
    assert status.message.index("bot · default") < status.message.index("routine · research")
    registry.close()


def test_link_rejects_other_domains_without_storing_them(tmp_path) -> None:
    registry = _registry(tmp_path)
    result = link_account(
        registry,
        user_id="100",
        email="ada@gmail.com",
        tag=None,
        label=None,
    )
    assert not result.ok
    assert "mail.grokbot.com" in result.message
    assert registry.list_links("100") == ()
    registry.close()


def test_reserved_label_is_rejected(tmp_path) -> None:
    registry = _registry(tmp_path)
    result = link_account(
        registry,
        user_id="100",
        email="ada@mail.grokbot.com",
        tag=None,
        label="Default",
    )
    assert not result.ok
    assert "default" in result.message
    assert registry.list_links("100") == ()
    registry.close()


def test_unlink_can_remove_one_label_or_every_link(tmp_path) -> None:
    registry = _registry(tmp_path)
    link_account(registry, user_id="100", email="ada@mail.grokbot.com", tag=None, label=None)
    link_account(
        registry,
        user_id="100",
        email="ada+research@mail.grokbot.com",
        tag=None,
        label="research",
    )
    link_account(registry, user_id="200", email="bob@mail.grokbot.com", tag=None, label=None)
    both = unlink_account(registry, user_id="100", label="research", only_default=True)
    assert not both.ok
    removed = unlink_account(registry, user_id="100", label="research", only_default=False)
    assert removed.ok
    assert [link.address.mode for link in registry.list_links("100")] == ["bot"]
    cleared = unlink_account(registry, user_id="100", label=None, only_default=False)
    assert cleared.message == "Removed all 1 link."
    assert registry.list_links("100") == ()
    assert registry.list_links("200")[0].address.exact == "bob@mail.grokbot.com"
    registry.close()
