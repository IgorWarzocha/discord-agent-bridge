import hashlib
import hmac
import json
from io import BytesIO
from datetime import datetime, timezone

from discord_agent_bridge.connectors.catalog import build_connectors
from discord_agent_bridge.connectors.grokbot import GrokbotConnector
from discord_agent_bridge.connectors.hermes import HermesConnector
from discord_agent_bridge.connectors.http_post import HttpResult, urllib_post
from discord_agent_bridge.connectors.openclaw import OpenClawConnector
from discord_agent_bridge.connectors.protocol import InvalidConfig
from discord_agent_bridge.connectors.signing import signature_v1, signature_v2
from discord_agent_bridge.connectors.webhook import WebhookConnector
from discord_agent_bridge.commands import connect_account, status_account
from discord_agent_bridge.payload import BridgePayload
from discord_agent_bridge.registry import Registry
from discord_agent_bridge.resend import ResendSender
from tests.support import T0, FakeResend


class RecordingHttp:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls: list[tuple[str, dict[str, str], bytes]] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes) -> HttpResult:
        self.calls.append((url, dict(headers), body))
        return HttpResult(self.status, "")


def _payload() -> BridgePayload:
    return BridgePayload(
        channel_name="design",
        username="ada",
        user_id="100",
        message_link="https://discord.com/channels/7/8/9",
        timestamp=T0,
        instruction="hello",
        tagged_message="<@42> hello",
        parent=None,
        burst=(),
        tail=(),
        callback=None,
        label=None,
    )


def test_grokbot_address_and_resend_delivery() -> None:
    fake = FakeResend()
    connector = GrokbotConnector(ResendSender("test-resend-key", "Bridge <bridge@example.com>", transport=fake))
    plain = connector.validate({"email": "Ada@mail.grokbot.com"})
    assert plain == {"email": "ada@mail.grokbot.com", "mode": "bot"}
    tagged = connector.validate({"email": "ada@mail.grokbot.com", "tag": "notes"})
    assert tagged["email"] == "ada+notes@mail.grokbot.com" and tagged["mode"] == "routine"
    try:
        connector.validate({"email": "ada@gmail.com"})
    except InvalidConfig as exc:
        assert "mail.grokbot.com" in str(exc)
    else:
        raise AssertionError("gmail was accepted")

    result = connector.deliver(_payload(), tagged)
    assert result.ok
    url, headers, payload = fake.calls[0]
    assert url.endswith("/emails")
    assert headers["Authorization"] == "Bearer test-resend-key"
    assert payload["to"] == ["ada+notes@mail.grokbot.com"]
    assert str(payload["subject"]).startswith("[Discord] #design @ada:")
    assert "test-resend-key" not in str(payload)
    assert "Mode: routine" in str(payload["text"])


def test_webhook_signs_the_json_body() -> None:
    http = RecordingHttp()
    when = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    connector = WebhookConnector(http, lambda: when)
    try:
        connector.validate({"url": "http://example.com/hook", "secret": "s" * 16})
    except InvalidConfig:
        pass
    else:
        raise AssertionError("http url was accepted")
    config = connector.validate({"url": "https://example.com/hook", "secret": "s" * 16})
    assert "secret" not in connector.describe(config)
    result = connector.deliver(_payload(), config)
    assert result.ok
    url, headers, body = http.calls[0]
    assert url == "https://example.com/hook"
    timestamp = headers["X-Webhook-Timestamp"]
    assert headers["X-Webhook-Signature"] == "sha256=" + signature_v2(config["secret"], timestamp, body)
    assert json.loads(body)["subject"].startswith("[Discord] #")
    assert config["secret"] not in body.decode()


def test_hermes_sends_documented_signatures() -> None:
    http = RecordingHttp()
    when = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    connector = HermesConnector(http, lambda: when)
    config = connector.validate({"url": "https://hermes.example/webhooks/discord", "secret": "route-secret"})
    assert connector.deliver(_payload(), config).ok
    _url, headers, body = http.calls[0]
    timestamp = headers["X-Webhook-Timestamp"]
    assert headers["X-Webhook-Signature"] == signature_v1(config["secret"], body)
    assert headers["X-Webhook-Signature-V2"] == signature_v2(config["secret"], timestamp, body)
    assert config["secret"] not in body.decode()
    # The V1 header matches the gateway's generic HMAC of the raw body.
    expected = hmac.new(b"route-secret", body, hashlib.sha256).hexdigest()
    assert headers["X-Webhook-Signature"] == expected


def test_openclaw_posts_a_bearer_hook() -> None:
    http = RecordingHttp()
    connector = OpenClawConnector(http)
    config = connector.validate(
        {"url": "https://gateway.example.com", "token": "hook-token", "agent_id": "main"}
    )
    assert config["url"] == "https://gateway.example.com/hooks/agent"
    assert "hook-token" not in connector.describe(config)
    assert connector.deliver(_payload(), config).ok
    url, headers, body = http.calls[0]
    assert url == "https://gateway.example.com/hooks/agent"
    assert headers["Authorization"] == "Bearer hook-token"
    decoded = json.loads(body)
    assert decoded["deliver"] is False
    assert decoded["agentId"] == "main"
    assert decoded["message"].startswith("Channel: #design")
    assert "hook-token" not in body.decode()


def test_connect_rejects_a_bad_webhook_and_hides_the_secret(tmp_path) -> None:
    registry = Registry(tmp_path / "links.sqlite3")
    http = RecordingHttp()
    catalog = build_connectors(
        ResendSender("test-resend-key", "bridge@example.com", transport=FakeResend()),
        http,
        lambda: T0,
    )
    bad = connect_account(
        registry,
        catalog,
        user_id="100",
        connector_type="webhook",
        label=None,
        options={"url": "https://example.com/hook", "secret": "short"},
    )
    assert not bad.ok
    assert registry.list_links("100") == ()
    secret = "super-secret-value"
    ok = connect_account(
        registry,
        catalog,
        user_id="100",
        connector_type="webhook",
        label="ops",
        options={"url": "https://example.com/hook", "secret": secret},
    )
    assert ok.ok
    status = status_account(registry, catalog, "100")
    assert "webhook · ops · https://example.com/hook" in status.message
    assert secret not in status.message
    registry.close()


def test_catalog_delivers_through_production_http_transport(monkeypatch) -> None:
    requests = []

    class Response(BytesIO):
        status = 200

    def urlopen(request, *, timeout):
        requests.append(request)
        assert timeout == 20
        return Response(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    catalog = build_connectors(
        ResendSender("test-key", "bridge@example.com", transport=FakeResend()),
        urllib_post, lambda: T0,
    )
    for kind, options in (
        ("webhook", {"url": "https://example.com/hook", "secret": "s" * 16}),
        ("hermes", {"url": "https://example.com/webhooks/discord", "secret": "secret"}),
        ("openclaw", {"url": "https://example.com", "token": "token"}),
    ):
        connector = catalog.get(kind)
        assert connector is not None
        assert connector.deliver(_payload(), connector.validate(options)).ok
    assert len(requests) == 3
    assert all(request.method == "POST" and request.data for request in requests)
