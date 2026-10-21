"""The connector registry. Adding a type is a module plus one entry here."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from discord_agent_bridge.connectors.grokbot import GrokbotConnector
from discord_agent_bridge.connectors.hermes import HermesConnector
from discord_agent_bridge.connectors.http_post import HttpTransport
from discord_agent_bridge.connectors.openclaw import OpenClawConnector
from discord_agent_bridge.connectors.protocol import Connector
from discord_agent_bridge.connectors.webhook import WebhookConnector
from discord_agent_bridge.resend import ResendSender

class ConnectorCatalog:
    def __init__(self, connectors: Mapping[str, Connector]) -> None:
        self._connectors = dict(connectors)

    def get(self, connector_type: str) -> Connector | None:
        return self._connectors.get(connector_type)

    def types(self) -> tuple[str, ...]:
        return tuple(self._connectors)


def build_connectors(
    sender: ResendSender | None,
    transport: HttpTransport,
    clock: Callable[[], datetime],
) -> ConnectorCatalog:
    connectors: dict[str, Connector] = {
        "webhook": WebhookConnector(transport, clock),
        "hermes": HermesConnector(transport, clock),
        "openclaw": OpenClawConnector(transport),
    }
    if sender is not None:
        connectors = {"grokbot": GrokbotConnector(sender), **connectors}
    return ConnectorCatalog(connectors)
