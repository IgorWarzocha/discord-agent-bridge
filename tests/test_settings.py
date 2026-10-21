import pytest

from discord_agent_bridge.settings import SettingsError, load_settings


def test_http_connectors_do_not_require_resend() -> None:
    settings = load_settings({"DISCORD_BOT_TOKEN": "test-token"})
    assert settings.resend_api_key == settings.resend_from == ""


@pytest.mark.parametrize("fields", [
    {"RESEND_API_KEY": "test-key"},
    {"RESEND_FROM": "bridge@example.com"},
    {"RESEND_API_KEY": "test-key", "RESEND_FROM": "not-an-address"},
])
def test_incomplete_or_invalid_resend_configuration_is_rejected(fields) -> None:
    with pytest.raises(SettingsError):
        load_settings({"DISCORD_BOT_TOKEN": "test-token", **fields})


def test_complete_resend_configuration_is_kept() -> None:
    settings = load_settings({
        "DISCORD_BOT_TOKEN": "test-token",
        "RESEND_API_KEY": "test-key",
        "RESEND_FROM": "Bridge <bridge@example.com>",
    })
    assert settings.resend_api_key == "test-key"
    assert settings.resend_from == "Bridge <bridge@example.com>"
