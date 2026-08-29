"""Shared rules for identifying authoritative component-serving ports."""

from __future__ import annotations

from typing import Any, Iterable


def is_authoritative_component_port(
    item: dict[str, Any],
    verified_pattern: dict[str, Any] | None = None,
) -> bool:
    """Return whether a port can serve as a component's deployment boundary.

    Most components require an explicit application port. A verified static
    frontend may instead expose that boundary through an explicitly configured
    proxy such as a repository Nginx configuration. The original port type is
    retained; this rule only lets downstream consumers use the verified fact.
    """
    if item.get("conflict") or item.get("port") is None:
        return False
    if item.get("port_type") == "application":
        return True
    return bool(
        verified_pattern
        and verified_pattern.get("category") == "static_frontend"
        and item.get("port_type") == "proxy"
    )


def authoritative_component_ports(
    items: Iterable[dict[str, Any]],
    verified_pattern: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return non-conflicting ports accepted by the bounded deployment rule."""
    return [item for item in items if is_authoritative_component_port(item, verified_pattern)]
