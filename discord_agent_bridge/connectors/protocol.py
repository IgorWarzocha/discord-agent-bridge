"""Typed connector plugin. One module plus one registry entry adds a type."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from discord_agent_bridge.payload import BridgePayload

ConnectorType = Literal["grokbot", "webhook", "hermes", "openclaw"]


class InvalidConfig(ValueError):
    """The options for this connector type are not valid."""


@dataclass(frozen=True)
class Capabilities:
    supports_callback: bool


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    summary: str


class Connector(Protocol):
    type: ConnectorType
    capabilities: Capabilities

    def validate(self, options: Mapping[str, str]) -> dict[str, str]:
        """Return the config that will be stored. Reject anything else."""

    def describe(self, config: Mapping[str, str]) -> str:
        """Status text. Must not include secrets."""

    def deliver(self, payload: BridgePayload, config: Mapping[str, str]) -> DeliveryResult:
        """Hand the normalised payload to the linked agent."""
