"""Slash-command decisions. Discord delivery lives in discord_app."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from discord_agent_bridge.connectors.catalog import ConnectorCatalog
from discord_agent_bridge.connectors.protocol import InvalidConfig
from discord_agent_bridge.registry import InvalidLabel, LinkLimitError, Registry, parse_label


@dataclass(frozen=True)
class CommandResult:
    message: str
    ok: bool


def connect_account(
    registry: Registry,
    connectors: ConnectorCatalog,
    *,
    user_id: str,
    connector_type: str,
    label: str | None,
    options: Mapping[str, str],
) -> CommandResult:
    connector = connectors.get(connector_type)
    if connector is None:
        known = ", ".join(connectors.types()) or "none"
        return CommandResult(f"Unknown connector `{connector_type}`. Choose one of: {known}.", ok=False)
    try:
        parsed_label = parse_label(label)
        config = connector.validate(options)
        state = registry.upsert(user_id, parsed_label, connector.type, config)
    except InvalidConfig as exc:
        return CommandResult(str(exc), ok=False)
    except InvalidLabel as exc:
        return CommandResult(str(exc), ok=False)
    except LinkLimitError as exc:
        return CommandResult(str(exc), ok=False)
    verb = "Updated" if state == "updated" else "Connected"
    where = "as the default" if parsed_label is None else f"with label `{parsed_label}`"
    return CommandResult(
        f"{verb} {connector.type} {connector.describe(config)} {where}.",
        ok=True,
    )


def link_grok(
    registry: Registry,
    connectors: ConnectorCatalog,
    *,
    user_id: str,
    email: str,
    tag: str | None,
    label: str | None,
) -> CommandResult:
    options = {"email": email}
    if tag:
        options["tag"] = tag
    return connect_account(
        registry,
        connectors,
        user_id=user_id,
        connector_type="grokbot",
        label=label,
        options=options,
    )


def disconnect_account(
    registry: Registry,
    *,
    user_id: str,
    label: str | None,
    only_default: bool,
) -> CommandResult:
    if label is not None and only_default:
        return CommandResult("Pass a label or only_default, not both.", ok=False)
    if only_default:
        if not registry.delete_default(user_id):
            return CommandResult("You do not have a default link.", ok=False)
        return CommandResult("Removed your default link.", ok=True)
    if label is not None:
        return _disconnect_label(registry, user_id, label)
    count = registry.delete_all(user_id)
    if count == 0:
        return CommandResult("You do not have any links. Use `/connect`.", ok=False)
    noun = "link" if count == 1 else "links"
    return CommandResult(f"Removed all {count} {noun}.", ok=True)


def status_account(
    registry: Registry,
    connectors: ConnectorCatalog,
    user_id: str,
) -> CommandResult:
    links = registry.list_links(user_id)
    if not links:
        return CommandResult("You have not connected an agent. Use `/connect`.", ok=True)
    ordered = sorted(links, key=lambda link: (link.label is not None, link.label or ""))
    lines = [
        "The first word after the mention selects a label. Anything else uses the default link.",
    ]
    for link in ordered:
        connector = connectors.get(link.connector_type)
        shown = connector.describe(link.config) if connector is not None else link.connector_type
        label = link.label or "default"
        lines.append(f"- {link.connector_type} · {label} · {shown}")
    return CommandResult("\n".join(lines), ok=True)


def _disconnect_label(registry: Registry, user_id: str, label: str) -> CommandResult:
    try:
        parsed = parse_label(label)
    except InvalidLabel as exc:
        return CommandResult(str(exc), ok=False)
    if parsed is None or not registry.delete_label(user_id, parsed):
        return CommandResult(f"You do not have a link labeled `{parsed}`.", ok=False)
    return CommandResult(f"Removed the link labeled `{parsed}`.", ok=True)
