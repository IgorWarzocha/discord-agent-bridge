from discord_agent_bridge.registry import Registry


def test_links_round_trip_per_user(tmp_path) -> None:
    path = tmp_path / "links.sqlite3"
    with Registry(path) as registry:
        registry.upsert(
            "100",
            "research",
            "grokbot",
            {"email": "ada+research@mail.grokbot.com", "mode": "routine"},
        )
        registry.upsert("200", None, "grokbot", {"email": "bob@mail.grokbot.com", "mode": "bot"})
    with Registry(path) as registry:
        ada = registry.list_links("100")
        bob = registry.list_links("200")
        assert registry.delete_all("100") == 1
    assert len(ada) == 1
    assert ada[0].connector_type == "grokbot"
    assert ada[0].label == "research"
    assert ada[0].config["email"] == "ada+research@mail.grokbot.com"
    assert ada[0].config["mode"] == "routine"
    assert bob[0].label is None and bob[0].config["mode"] == "bot"
    with Registry(path) as registry:
        assert registry.list_links("100") == ()
        kept = registry.list_links("200")
        assert kept[0].config["email"] == "bob@mail.grokbot.com"
        registry.upsert(
            "200",
            "hook",
            "webhook",
            {"url": "https://example.com/hook", "secret": "x" * 16},
        )
        saved = registry.list_links("200")
    assert any(link.connector_type == "webhook" and link.label == "hook" for link in saved)
    assert any(link.config.get("email") == "bob@mail.grokbot.com" for link in saved)
