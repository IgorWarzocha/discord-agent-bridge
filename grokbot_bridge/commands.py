"""Slash-command decisions. Discord delivery lives in discord_app."""

from __future__ import annotations

from dataclasses import dataclass

from grokbot_bridge.address import InvalidAddress, parse_link_email
from grokbot_bridge.registry import (
    InvalidLabel,
    LinkLimitError,
    Registry,
    parse_label,
)


@dataclass(frozen=True)
class CommandResult:
    message: str
    ok: bool


def link_account(
    registry: Registry,
    *,
    user_id: str,
    email: str,
    tag: str | None,
    label: str | None,
) -> CommandResult:
    try:
        address = parse_link_email(email, tag=tag)
        parsed_label = parse_label(label)
        state = registry.upsert(user_id, parsed_label, address)
    except InvalidAddress as exc:
        return CommandResult(str(exc), ok=False)
    except InvalidLabel as exc:
        return CommandResult(str(exc), ok=False)
    except LinkLimitError as exc:
        return CommandResult(str(exc), ok=False)
    verb = "Updated" if state == "updated" else "Linked"
    if parsed_label is None:
        where = "as the default"
    else:
        where = f"with label `{parsed_label}`"
    return CommandResult(f"{verb} {address.mode} {address.exact} {where}.", ok=True)


def unlink_account(
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
        return _unlink_label(registry, user_id, label)
    count = registry.delete_all(user_id)
    if count == 0:
        return CommandResult("You do not have any links. Use `/link-grok`.", ok=False)
    noun = "link" if count == 1 else "links"
    return CommandResult(f"Removed all {count} {noun}.", ok=True)


def status_account(registry: Registry, user_id: str) -> CommandResult:
    links = registry.list_links(user_id)
    if not links:
        return CommandResult("You have not linked a Grok Bot. Use `/link-grok`.", ok=True)
    ordered = sorted(links, key=lambda link: (link.label is not None, link.label or ""))
    lines = [
        "The first word after @Grokbot selects a label. Anything else uses the default link.",
    ]
    for link in ordered:
        label = link.label or "default"
        lines.append(f"- {link.address.mode} · {label} · {link.address.exact}")
    return CommandResult("\n".join(lines), ok=True)


def _unlink_label(registry: Registry, user_id: str, label: str) -> CommandResult:
    try:
        parsed = parse_label(label)
    except InvalidLabel as exc:
        return CommandResult(str(exc), ok=False)
    if parsed is None:
        return CommandResult(
            "Pass a label, or set only_default to remove the default link.",
            ok=False,
        )
    if not registry.delete_label(user_id, parsed):
        return CommandResult(f"You do not have a link labeled `{parsed}`.", ok=False)
    return CommandResult(f"Removed the link labeled `{parsed}`.", ok=True)
