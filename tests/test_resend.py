import pytest

from grokbot_bridge.payload import OutboundMail
from grokbot_bridge.resend import RESEND_EMAILS_URL, ResendError, ResendSender
from tests.support import FakeResend


def test_resend_posts_text_and_hides_the_key() -> None:
    mail = OutboundMail(
        to="ada+research@mail.grokbot.com",
        subject="[Discord] #design @ada: research check",
        text="Mode: routine\n",
    )
    fake = FakeResend()
    sender = ResendSender("test-resend-key", "Bridge <bridge@example.com>", transport=fake)
    assert sender.send(mail) == "email_123"
    url, headers, payload = fake.calls[0]
    assert url == RESEND_EMAILS_URL
    assert headers["Authorization"] == "Bearer test-resend-key"
    assert set(payload) == {"from", "to", "subject", "text"}
    assert payload["to"] == ["ada+research@mail.grokbot.com"]
    assert "html" not in payload
    assert "test-resend-key" not in str(payload)

    failing = FakeResend(status=422, body='{"message":"invalid"}')
    sender = ResendSender("test-resend-key", "bridge@example.com", transport=failing)
    with pytest.raises(ResendError) as caught:
        sender.send(mail)
    assert caught.value.status == 422
    assert "test-resend-key" not in str(caught.value)
