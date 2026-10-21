"""Resend email to a mail.grokbot.com address. Plain is bot, tagged is routine."""

from __future__ import annotations

from collections.abc import Mapping

from discord_agent_bridge.connectors.grokbot_address import InvalidAddress, parse_link_email
from discord_agent_bridge.connectors.protocol import Capabilities, DeliveryResult, InvalidConfig
from discord_agent_bridge.payload import BridgePayload, OutboundMail, render_task
from discord_agent_bridge.resend import ResendError, ResendSender


class GrokbotConnector:
    type = "grokbot"
    capabilities = Capabilities(supports_callback=True)

    def __init__(self, sender: ResendSender) -> None:
        self._sender = sender

    def validate(self, options: Mapping[str, str]) -> dict[str, str]:
        email = options.get("email", "")
        if not email:
            raise InvalidConfig("Grokbot requires email on mail.grokbot.com.")
        try:
            address = parse_link_email(email, tag=options.get("tag"))
        except InvalidAddress as exc:
            raise InvalidConfig(str(exc)) from exc
        return {"email": address.exact, "mode": address.mode}

    def describe(self, config: Mapping[str, str]) -> str:
        return f"{config.get('mode', 'bot')} {config.get('email', '')}"

    def deliver(self, payload: BridgePayload, config: Mapping[str, str]) -> DeliveryResult:
        mail = _email(payload, config)
        try:
            self._sender.send(mail)
        except ResendError as exc:
            if exc.status:
                return DeliveryResult(False, f"Could not email your Grok Bot (Resend returned {exc.status}). Nothing was sent.")
            return DeliveryResult(False, "Could not reach Resend. Nothing was sent.")
        label = payload.label
        mode = config.get("mode", "bot")
        if label is None:
            return DeliveryResult(True, f"Sent this to your default {mode} link.")
        return DeliveryResult(True, f"Sent this to your {mode} link `{label}`.")


def render_email(payload: BridgePayload, config: Mapping[str, str]) -> OutboundMail:
    mode = config.get("mode", "bot")
    email = config.get("email", "")
    stamp = f"Timestamp: {payload.timestamp.isoformat()}\n"
    text = render_task(payload).replace(stamp, f"{stamp}Mode: {mode}\nTo: {email}\n", 1)
    return OutboundMail(to=email, subject=payload.subject, text=text)


def _email(payload: BridgePayload, config: Mapping[str, str]) -> OutboundMail:
    return render_email(payload, config)
