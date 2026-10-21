"""Send one plain-text email through Resend's HTTP API. No SMTP."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import NamedTuple, Protocol

from discord_agent_bridge.payload import OutboundMail

RESEND_EMAILS_URL = "https://api.resend.com/emails"


class ResendError(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status


class HttpResponse(NamedTuple):
    status: int
    body: str


class Transport(Protocol):
    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> HttpResponse: ...


def resend_payload(from_address: str, mail: OutboundMail) -> dict[str, object]:
    return {
        "from": from_address,
        "to": [mail.to],
        "subject": mail.subject,
        "text": mail.text,
    }


def urllib_transport(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
) -> HttpResponse:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return HttpResponse(response.status, response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, exc.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as exc:
        raise ResendError(0, "Could not reach Resend.") from exc


class ResendSender:
    def __init__(
        self,
        api_key: str,
        from_address: str,
        transport: Transport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Resend API key is required")
        if not from_address.strip():
            raise ValueError("Resend from address is required")
        self._api_key = api_key
        self._from = from_address
        self._transport = transport or urllib_transport

    def send(self, mail: OutboundMail) -> str:
        payload = resend_payload(self._from, mail)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": "discord-agent-bridge",
        }
        response = self._transport.post_json(RESEND_EMAILS_URL, headers, payload)
        if response.status < 200 or response.status >= 300:
            raise ResendError(response.status, f"Resend returned HTTP {response.status}")
        return _email_id(response.body)


def _email_id(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    email_id = data.get("id")
    if isinstance(email_id, str):
        return email_id
    return ""
