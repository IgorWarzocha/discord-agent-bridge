import os

import pytest

from grokbot_bridge.settings import SettingsError, load_dotenv, load_settings


def _env(**overrides: str) -> dict[str, str]:
    env = {
        "DISCORD_BOT_TOKEN": "test-discord-token",
        "RESEND_API_KEY": "test-resend-key",
        "RESEND_FROM": "Grokbot Bridge <bridge@example.com>",
    }
    env.update(overrides)
    return env


def test_defaults_and_required_secrets() -> None:
    settings = load_settings(_env())
    assert settings.burst_window_seconds == 45
    assert settings.burst_gap_seconds == 5
    assert settings.channel_tail_count == 5
    assert settings.rate_limit_max == 5
    assert settings.rate_limit_window_seconds == 600
    assert settings.discord_guild_id is None
    assert settings.callback_base_url is None
    assert settings.callback_ttl_hours == 24
    assert settings.callback_max_posts == 5
    assert settings.max_hops == 3
    assert settings.http_host == "127.0.0.1"
    assert settings.http_port == 8787
    with pytest.raises(SettingsError, match="DISCORD_BOT_TOKEN"):
        load_settings(_env(DISCORD_BOT_TOKEN=""))


@pytest.mark.parametrize("window", ["29", "61"])
def test_burst_window_must_stay_between_30_and_60(window: str) -> None:
    with pytest.raises(SettingsError, match="BURST_WINDOW_SECONDS"):
        load_settings(_env(BURST_WINDOW_SECONDS=window))
    assert load_settings(_env(BURST_WINDOW_SECONDS="60")).burst_window_seconds == 60


def test_callback_base_url_must_be_https_and_from_must_be_an_email() -> None:
    with pytest.raises(SettingsError, match="CALLBACK_BASE_URL"):
        load_settings(_env(CALLBACK_BASE_URL="javascript:alert(1)"))
    with pytest.raises(SettingsError, match="CALLBACK_BASE_URL"):
        load_settings(_env(CALLBACK_BASE_URL="http://example.com"))
    with pytest.raises(SettingsError, match="RESEND_FROM"):
        load_settings(_env(RESEND_FROM="not-an-email"))
    settings = load_settings(_env(CALLBACK_BASE_URL="https://example.com/hook/"))
    assert settings.callback_base_url == "https://example.com/hook"
    assert load_settings(_env(RESEND_FROM="bridge@example.com")).resend_from == "bridge@example.com"
    assert load_settings(_env(CALLBACK_TTL_HOURS="0")).callback_ttl_hours == 0
    with pytest.raises(SettingsError, match="CALLBACK_TTL_HOURS"):
        load_settings(_env(CALLBACK_TTL_HOURS="-1"))


def test_dotenv_does_not_override_existing_variables(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEPT_KEY", "from-env")
    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            [
                "# comment",
                "KEPT_KEY=from-file",
                "export EXAMPLE_DOTENV_KEY=from-file",
                "EXAMPLE_DOTENV_BLANK=",
            ]
        ),
        encoding="utf-8",
    )
    try:
        load_dotenv(path)
        assert os.environ["KEPT_KEY"] == "from-env"
        assert os.environ["EXAMPLE_DOTENV_KEY"] == "from-file"
    finally:
        os.environ.pop("EXAMPLE_DOTENV_KEY", None)
        os.environ.pop("EXAMPLE_DOTENV_BLANK", None)
