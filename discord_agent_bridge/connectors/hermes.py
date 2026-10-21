"""Nous Research Hermes Agent webhook route.

Documented inbound POST: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks
Signature source: https://github.com/NousResearch/hermes-agent/blob/72ff3e90/gateway/platforms/webhook.py

V2 (recommended in the docs): `X-Webhook-Signature-V2` is HMAC-SHA256 hex of
`{timestamp}.{body}`, with `X-Webhook-Timestamp` in unix seconds.
V1 (the gateway source above): `X-Webhook-Signature` is HMAC-SHA256 hex of the body.
Both headers are sent so either validator accepts the request.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from discord_agent_bridge.connectors.http_post import HttpDeliveryError, HttpTransport, post_json
from discord_agent_bridge.connectors.protocol import Capabilities, DeliveryResult, InvalidConfig
from discord_agent_bridge.connectors.signing import signature_v1, signature_v2
from discord_agent_bridge.payload import BridgePayload, to_json

_HTTPS = re.compile(r"https://[^\s/?#]+(?:/[^\s?#]*)?")


class HermesConnector:
    type = "hermes"
    capabilities = Capabilities(supports_callback=True)

    def __init__(self, transport: HttpTransport, clock: Callable[[], datetime]) -> None:
        self._transport = transport
        self._clock = clock

    def validate(self, options: Mapping[str, str]) -> dict[str, str]:
        url = options.get("url", "").strip().rstrip("/")
        secret = options.get("secret", "")
        if _HTTPS.fullmatch(url) is None:
            raise InvalidConfig("Hermes url must be the https route, like https://host/webhooks/discord.")
        if not secret:
            raise InvalidConfig("Hermes requires the route HMAC secret.")
        return {"url": url, "secret": secret}

    def describe(self, config: Mapping[str, str]) -> str:
        return config.get("url", "")

    def deliver(self, payload: BridgePayload, config: Mapping[str, str]) -> DeliveryResult:
        body = json.dumps(to_json(payload), separators=(",", ":")).encode("utf-8")
        timestamp = str(int(self._clock().astimezone(timezone.utc).timestamp()))
        headers = {
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": signature_v1(config["secret"], body),
            "X-Webhook-Signature-V2": signature_v2(config["secret"], timestamp, body),
            "User-Agent": "discord-agent-bridge",
        }
        try:
            post_json(self._transport, config["url"], headers, body)
        except HttpDeliveryError as exc:
            return DeliveryResult(False, f"Could not deliver to Hermes (HTTP {exc.status}). Nothing was sent.")
        label = payload.label or "default"
        return DeliveryResult(True, f"Sent this to your hermes link `{label}`.")
