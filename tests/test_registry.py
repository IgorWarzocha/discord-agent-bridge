from datetime import datetime, timezone

import pytest

from grokbot_bridge.address import parse_link_email
from grokbot_bridge.registry import MAX_LINKS, LinkLimitError, Registry


def test_links_survive_a_restart_and_stay_per_user(tmp_path) -> None:
    path = tmp_path / "links.sqlite3"
    with Registry(path) as registry:
        registry.upsert("100", "research", parse_link_email("Ada+Research@mail.grokbot.com"))
        registry.upsert("200", None, parse_link_email("bob@mail.grokbot.com"))
    with Registry(path) as registry:
        ada = registry.list_links("100")
        bob = registry.list_links("200")
        assert registry.delete_all("100") == 1
    assert len(ada) == 1
    assert ada[0].label == "research"
    assert ada[0].address.exact == "ada+research@mail.grokbot.com"
    assert ada[0].address.mode == "routine"
    assert bob[0].address.mode == "bot"
    with Registry(path) as registry:
        assert registry.list_links("100") == ()
        assert registry.list_links("200")[0].address.exact == "bob@mail.grokbot.com"


def test_replacing_a_label_keeps_the_original_created_at(tmp_path) -> None:
    times = iter(
        [
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 6, 1, tzinfo=timezone.utc),
        ]
    )
    registry = Registry(tmp_path / "links.sqlite3", clock=lambda: next(times))
    assert registry.upsert("100", "research", parse_link_email("ada+old@mail.grokbot.com")) == "created"
    assert registry.upsert("100", "research", parse_link_email("ada+new@mail.grokbot.com")) == "updated"
    link = registry.list_links("100")[0]
    assert link.address.exact == "ada+new@mail.grokbot.com"
    assert link.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    registry.close()


def test_link_cap_blocks_a_new_label_and_still_allows_updates(tmp_path) -> None:
    registry = Registry(tmp_path / "links.sqlite3")
    registry.upsert("100", None, parse_link_email("ada@mail.grokbot.com"))
    for index in range(MAX_LINKS - 1):
        registry.upsert("100", f"l{index}", parse_link_email(f"ada+l{index}@mail.grokbot.com"))
    with pytest.raises(LinkLimitError):
        registry.upsert("100", "extra", parse_link_email("ada+extra@mail.grokbot.com"))
    state = registry.upsert("100", "l0", parse_link_email("ada+renamed@mail.grokbot.com"))
    assert state == "updated"
    emails = {link.address.exact for link in registry.list_links("100")}
    assert "ada+renamed@mail.grokbot.com" in emails
    assert "ada+extra@mail.grokbot.com" not in emails
    assert len(emails) == MAX_LINKS
    registry.close()
