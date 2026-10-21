import json
import sqlite3

from discord_agent_bridge.registry import Registry


def test_links_round_trip_and_legacy_grokbot_rows(tmp_path) -> None:
    path = tmp_path / "links.sqlite3"
    legacy = sqlite3.connect(path)
    legacy.execute(
        """
        CREATE TABLE links (
            discord_user_id TEXT NOT NULL,
            label TEXT NOT NULL,
            email TEXT NOT NULL,
            mode TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (discord_user_id, label)
        )
        """
    )
    legacy.execute(
        "INSERT INTO links VALUES ('100', 'research', 'ada+research@mail.grokbot.com', 'routine', '2026-01-01T00:00:00+00:00')"
    )
    legacy.execute(
        "INSERT INTO links VALUES ('200', '', 'bob@mail.grokbot.com', 'bot', '2026-01-02T00:00:00+00:00')"
    )
    legacy.commit()
    legacy.close()

    with Registry(path) as registry:
        ada = registry.list_links("100")
        bob = registry.list_links("200")
        assert registry.delete_all("100") == 1
    assert ada[0].connector_type == "grokbot"
    assert ada[0].label == "research"
    assert json.loads(json.dumps(ada[0].config))["email"] == "ada+research@mail.grokbot.com"
    assert ada[0].config["mode"] == "routine"
    assert bob[0].label is None and bob[0].config["mode"] == "bot"
    with Registry(path) as registry:
        assert registry.list_links("100") == ()
        assert registry.list_links("200")[0].config["email"] == "bob@mail.grokbot.com"
        registry.upsert("200", "hook", "webhook", {"url": "https://example.com/hook", "secret": "x" * 16})
        saved = registry.list_links("200")
    assert any(link.connector_type == "webhook" and link.label == "hook" for link in saved)
