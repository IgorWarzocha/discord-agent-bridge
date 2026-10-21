"""Signed JSON POST to an HTTPS URL the user controls."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from discord_agent_bridge.connectors.http_post import HttpDeliveryError, HttpTransport, post_json
from discord_agent_bridge.connectors.protocol import Capabilities, DeliveryResult, InvalidConfig
from discord_agent_bridge.connectors.signing import signature_v2
from discord_agent_bridge.payload import BridgePayload, to_json

_HTTPS = re.compile(r"https://[^\s/?#]+(?:/[^\s?#]*)?")


class WebhookConnector:
    """The receiver checks `X-Webhook-Signature: sha256=<hex>` over `{timestamp}.{body}`."""

    type = "webhook"
    capabilities = Capabilities(supports_callback=True)

    def __init__(self, transport: HttpTransport, clock: Callable[[], datetime]) -> None:
        self._transport = transport
        self._clock = clock

    def validate(self, options: Mapping[str, str]) -> dict[str, str]:
        url = options.get("url", "").strip().rstrip("/")
        secret = options.get("secret", "")
        if _HTTPS.fullmatch(url) is None:
            raise InvalidConfig("Webhook url must be https.")
        if len(secret) < 16:
            raise InvalidConfig("Webhook secret must be at least 16 characters.")
        return {"url": url, "secret": secret}

    def describe(self, config: Mapping[str, str]) -> str:
        return config.get("url", "")

    def deliver(self, payload: BridgePayload, config: Mapping[str, str]) -> DeliveryResult:
        body = json.dumps(to_json(payload), separators=(",", ":")).encode("utf-8")
        timestamp = str(int(self._clock().astimezone(timezone.utc).timestamp()))
        signature = "sha256=" + signature_v2(config["secret"], timestamp, body)
        headers = {
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": signature,
            "User-Agent": "discord-agent-bridge",
        }
        try:
            post_json(self._transport, config["url"], headers, body)
        except HttpDeliveryError as exc:
            return DeliveryResult(False, f"Could not deliver the webhook (HTTP {exc.status}). Nothing was sent.")
        label = payload.label or "default"
        return DeliveryResult(True, f"Sent this to your webhook link `{label}`.")
