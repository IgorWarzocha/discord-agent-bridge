import pytest

from grokbot_bridge.payload import OutboundMail
from grokbot_bridge.resend import RESEND_EMAILS_URL, ResendError, ResendSender, resend_payload
from tests.support import FakeResend


def _mail() -> OutboundMail:
    return OutboundMail(
        to="ada+research@mail.grokbot.com",
        subject="[Discord] #design @ada: research check",
        text="Mode: routine\nTo: ada+research@mail.grokbot.com\n",
    )


def test_payload_is_plain_text_to_the_selected_address() -> None:
    payload = resend_payload("Bridge <bridge@example.com>", _mail())
    assert set(payload) == {"from", "to", "subject", "text"}
    assert payload["to"] == ["ada+research@mail.grokbot.com"]
    assert payload["subject"] == "[Discord] #design @ada: research check"
    assert "html" not in payload


def test_sender_posts_to_resend_with_a_fake_transport() -> None:
    fake = FakeResend()
    sender = ResendSender("test-resend-key", "Bridge <bridge@example.com>", transport=fake)
    email_id = sender.send(_mail())
    assert email_id == "email_123"
    assert len(fake.calls) == 1
    url, headers, payload = fake.calls[0]
    assert url == RESEND_EMAILS_URL
    assert headers["Authorization"] == "Bearer test-resend-key"
    assert headers["Accept"] == "application/json"
    assert "test-resend-key" not in str(payload)
    assert payload["text"] == _mail().text


def test_non_success_raises_without_leaking_the_key() -> None:
    fake = FakeResend(status=422, body='{"message":"invalid"}')
    sender = ResendSender("test-resend-key", "bridge@example.com", transport=fake)
    with pytest.raises(ResendError) as caught:
        sender.send(_mail())
    assert caught.value.status == 422
    assert "test-resend-key" not in str(caught.value)
    assert len(fake.calls) == 1


def test_missing_api_key_does_not_call_the_transport() -> None:
    fake = FakeResend()
    with pytest.raises(ValueError):
        ResendSender("  ", "bridge@example.com", transport=fake)
    assert fake.calls == []
