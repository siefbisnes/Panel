"""Plain-text output for the CLI."""

from __future__ import annotations

from .configuration import config_entries
from .environment import Environment
from .models import AppResult, Status

CATEGORY_ORDER = (
        "desktop",
        "bar",
        "terminal",
        "shell",
        "launcher",
        "editor",
        "browser",
        "tool",
        "audio",
        "media",
        "notification",
        "file-manager",
        "network",
        "other",
)
CATEGORY_TITLES = {
        "desktop": "Desktop Environment",
        "tool": "Tools",
        "file-manager": "File Manager",
        "notification": "Notifications",
}
SIGNAL_LABELS = {
        "package": "Package",
        "executable": "Executable",
        "desktop_entry": "Desktop entry",
        "config": "Configuration",
        "process": "Running",
        "service": "Service",
}


class Style:
        def __init__(self, enabled: bool):
                self.enabled = enabled

        def _wrap(self, code: str, text: str) -> str:
                return f"\033[{code}m{text}\033[0m" if self.enabled else text

        def green(self, text: str) -> str:
                return self._wrap("32", text)

        def red(self, text: str) -> str:
                return self._wrap("31", text)

        def yellow(self, text: str) -> str:
                return self._wrap("33", text)

        def dim(self, text: str) -> str:
                return self._wrap("2", text)

        def bold(self, text: str) -> str:
                return self._wrap("1", text)


def mark(status: Status, style: Style) -> str:
        return {
                Status.FOUND: style.green("✓"),
                Status.NOT_FOUND: style.red("✗"),
                Status.UNKNOWN: style.yellow("?"),
        }[status]


def state_mark(result: AppResult, style: Style) -> str:
        if result.installed:
                return style.green("✓")
        return style.yellow("~") if result.detected else style.red("✗")


def sort_results(results: list[AppResult]) -> list[AppResult]:
        def key(result: AppResult) -> tuple[int, str]:
                category = result.app.category
                rank = (
                        CATEGORY_ORDER.index(category)
                        if category in CATEGORY_ORDER
                        else len(CATEGORY_ORDER)
                )
                return rank, result.app.name.lower()

        return sorted(results, key=key)


def flags(result: AppResult) -> str:
        items = []
        if result.detected and not result.installed:
                items.append("config only")
        if result.configured and result.installed:
                items.append("configured")
        if result.running:
                items.append("running")
        if result.service_enabled:
                items.append("service enabled")
        return ", ".join(items)


def render_brief(results: list[AppResult], style: Style) -> str:
        detected = sort_results([r for r in results if r.detected])
        lines = [
                f"{state_mark(r, style)} {r.app.name}"
                + (style.dim(" (config only)") if not r.installed else "")
                for r in detected
        ]
        noun = "application" if len(detected) == 1 else "applications"
        return "\n".join([*lines, "", f"{len(detected)} {noun} detected."])


def render_scan(
        overview: dict[str, str], results: list[AppResult], style: Style
) -> str:
        width = max(len(key) for key in overview)
        lines = [style.bold("SYSTEM OVERVIEW"), "─" * 28]
        lines += [f"{key:<{width}}  {value}" for key, value in overview.items()]
        detected = sort_results([r for r in results if r.detected])
        name_width = max((len(r.app.name) for r in detected), default=0)
        current = None
        for result in detected:
                category = result.app.category
                if category != current:
                        current = category
                        title = CATEGORY_TITLES.get(
                                category, category.replace("-", " ").title()
                        )
                        lines += ["", style.bold(title)]
                lines.append(
                        f"  {state_mark(result, style)} {result.app.name:<{name_width}}  "
                        f"{result.confidence:<6}  {style.dim(flags(result))}".rstrip()
                )
        return "\n".join(lines)


def render_list(results: list[AppResult], style: Style, show_all: bool) -> str:
        rows = sort_results(results if show_all else [r for r in results if r.detected])
        if not rows:
                return "No applications detected."
        name_width = max(len(r.app.name) for r in rows)
        cat_width = max(len(r.app.category) for r in rows)
        lines = []
        for r in rows:
                detail = flags(r) if r.detected else "not detected"
                lines.append(
                        f"{state_mark(r, style)} {r.app.name:<{name_width}}  {r.app.category:<{cat_width}}  "
                        f"{r.confidence:<6}  {style.dim(detail)}".rstrip()
                )
        return "\n".join(lines)


def render_info(result: AppResult, env: Environment, style: Style) -> str:
        app = result.app
        lines = [
                f"{style.bold(app.name)}  {style.dim('(' + app.category + ')')}",
                "─" * 28,
                "",
        ]
        for name, label in SIGNAL_LABELS.items():
                signal = result.signals.get(name)
                if signal is None:
                        continue
                detail = "; ".join(env.tilde(item) for item in signal.evidence)
                lines.append(
                        f"{label:<15} {mark(signal.status, style)}  {detail}".rstrip()
                )
        lines.append("")
        if result.version:
                lines.append(f"{'Version':<15} {result.version}")
        lines.append(f"{'Confidence':<15} {result.confidence.capitalize()}")
        files = [e for e in config_entries(app, env) if e.exists and e.is_file]
        if files:
                lines += ["", "Configuration files"]
                lines += [
                        f"  {style.green('✓')} {env.tilde(str(e.path))}" for e in files
                ]
        if app.documentation:
                lines += ["", "Documentation"]
                lines += [
                        f"  {key.replace('_', ' '):<14} {url}"
                        for key, url in app.documentation.items()
                ]
        return "\n".join(lines)


def render_config(result: AppResult, env: Environment, style: Style) -> str:
        entries = config_entries(result.app, env)
        if not entries:
                return f"{result.app.name} has no known configuration locations."
        lines = [style.bold(f"{result.app.name} configuration"), "─" * 28]
        for entry in entries:
                status = Status.FOUND if entry.exists else Status.NOT_FOUND
                kind = "" if not entry.exists else "/" if not entry.is_file else ""
                fmt = style.dim(f"  [{entry.format}]") if entry.format else ""
                lines.append(
                        f"{mark(status, style)} {env.tilde(str(entry.path))}{kind}{fmt}"
                )
        return "\n".join(lines)
