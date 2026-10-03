"""Format declared application compatibility against the active session."""

from __future__ import annotations

import re
from collections.abc import Mapping


STATUS_LABELS = {
        "supported": "Supported",
        "partial": "Partial support",
        "unsupported": "Unsupported",
}


def _key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-")


def _status(value: str | None) -> str:
        return STATUS_LABELS.get(value or "", "Not specified")


def declared_compatibility(compatibility: Mapping[str, Mapping[str, str]]) -> list[str]:
        """Summarize explicit environment support claims for compact catalog rows."""
        details = []
        for layer in ("desktop_environments", "display_servers"):
                for name, status in sorted(compatibility.get(layer, {}).items()):
                        details.append(
                                f"{name.replace('_', ' ').replace('-', ' ').title()}: {_status(status)}"
                        )
        return details


def compatibility_details(
        compatibility: Mapping[str, Mapping[str, str]],
        variables: Mapping[str, str],
) -> list[str]:
        """Describe current desktop/display support, followed by other declared targets."""
        details: list[str] = []
        current: dict[str, set[str]] = {
                "desktop_environments": set(),
                "display_servers": set(),
        }
        desktop = (
                variables.get("XDG_CURRENT_DESKTOP")
                or variables.get("XDG_SESSION_DESKTOP")
                or variables.get("DESKTOP_SESSION")
                or ""
        )
        desktop_names = [
                name.strip() for name in re.split(r"[:;,]", desktop) if name.strip()
        ]
        if desktop_names:
                for name in desktop_names:
                        key = _key(name)
                        current["desktop_environments"].add(key)
                        status = compatibility.get("desktop_environments", {}).get(key)
                        details.append(
                                f"Desktop environment · {name}: {_status(status)}"
                        )
        else:
                details.append("Desktop environment: Not detected")

        display_server = variables.get("XDG_SESSION_TYPE")
        if not display_server:
                display_server = (
                        "wayland"
                        if variables.get("WAYLAND_DISPLAY")
                        else "x11"
                        if variables.get("DISPLAY")
                        else None
                )
        if display_server:
                key = _key(display_server)
                current["display_servers"].add(key)
                status = compatibility.get("display_servers", {}).get(key)
                details.append(
                        f"Display server · {display_server.title()}: {_status(status)}"
                )
        else:
                details.append("Display server: Not detected")

        for layer, label in (
                ("desktop_environments", "Desktop environment"),
                ("display_servers", "Display server"),
        ):
                for name, status in sorted(compatibility.get(layer, {}).items()):
                        if _key(name) in current[layer]:
                                continue
                        details.append(
                                f"{name.replace('_', ' ').replace('-', ' ').title()} {label.lower()}: {_status(status)}"
                        )
        return details
