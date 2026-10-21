from grokbot_bridge.address import parse_link_email
from grokbot_bridge.registry import Registry


def test_links_round_trip_per_user(tmp_path) -> None:
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
