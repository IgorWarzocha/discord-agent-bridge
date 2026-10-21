"""OpenClaw gateway hook.

Documented inbound API: https://docs.openclaw.ai/gateway/config-hooks
and https://docs.openclaw.ai/automation/cron-jobs/webhooks

`POST /hooks/agent` with `Authorization: Bearer <token>` and JSON
`{"message": "..."}`. `deliver` is set false so OpenClaw does not also
announce to another channel; the bridge callback is inside the message.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from discord_agent_bridge.connectors.http_post import HttpDeliveryError, HttpTransport, post_json
from discord_agent_bridge.connectors.protocol import Capabilities, DeliveryResult, InvalidConfig
from discord_agent_bridge.payload import BridgePayload, render_task

_HTTPS = re.compile(r"https://[^\s/?#]+(?:/[^\s?#]*)?")


class OpenClawConnector:
    type = "openclaw"
    capabilities = Capabilities(supports_callback=True)

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def validate(self, options: Mapping[str, str]) -> dict[str, str]:
        url = _agent_url(options.get("url", ""))
        token = options.get("token", "").strip()
        if url is None:
            raise InvalidConfig("OpenClaw url must be the https gateway origin or the /hooks/agent URL.")
        if not token:
            raise InvalidConfig("OpenClaw requires the hook token.")
        config = {"url": url, "token": token}
        agent_id = options.get("agent_id", "").strip()
        if agent_id:
            config["agent_id"] = agent_id
        return config

    def describe(self, config: Mapping[str, str]) -> str:
        agent = config.get("agent_id")
        url = config.get("url", "")
        if agent:
            return f"{url} agent {agent}"
        return url

    def deliver(self, payload: BridgePayload, config: Mapping[str, str]) -> DeliveryResult:
        message: dict[str, object] = {
            "message": render_task(payload),
            "name": "Discord",
            "deliver": False,
        }
        agent_id = config.get("agent_id")
        if agent_id:
            message["agentId"] = agent_id
        body = json.dumps(message, separators=(",", ":")).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {config['token']}",
            "User-Agent": "discord-agent-bridge",
        }
        try:
            post_json(self._transport, config["url"], headers, body)
        except HttpDeliveryError as exc:
            return DeliveryResult(False, f"Could not deliver to OpenClaw (HTTP {exc.status}). Nothing was sent.")
        label = payload.label or "default"
        return DeliveryResult(True, f"Sent this to your openclaw link `{label}`.")


def _agent_url(value: str) -> str | None:
    raw = value.strip().rstrip("/")
    if _HTTPS.fullmatch(raw) is None:
        return None
    if raw.endswith("/hooks/agent"):
        return raw
    if raw.endswith("/hooks"):
        return raw + "/agent"
    return raw + "/hooks/agent"
