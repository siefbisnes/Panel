"""Data model shared by the loader, detectors and interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
        FOUND = "found"
        NOT_FOUND = "not_found"
        UNKNOWN = "unknown"


@dataclass(frozen=True)
class ConfigSetting:
        key: str
        label: str
        kind: str
        default: Any = None
        minimum: float | None = None
        maximum: float | None = None
        step: float | None = None
        choices: tuple[str, ...] = ()
        description: str | None = None
        group: str | None = None


@dataclass(frozen=True)
class ConfigFile:
        path: str
        format: str | None = None
        syntax: str | None = None
        settings: tuple[ConfigSetting, ...] = ()


@dataclass(frozen=True)
class Application:
        id: str
        name: str
        category: str
        executables: tuple[str, ...] = ()
        config_paths: tuple[str, ...] = ()
        desktop_entries: tuple[str, ...] = ()
        processes: tuple[str, ...] = ()
        user_services: tuple[str, ...] = ()
        system_services: tuple[str, ...] = ()
        packages: dict[str, tuple[str, ...]] = field(default_factory=dict)
        config_files: tuple[ConfigFile, ...] = ()
        documentation: dict[str, str] = field(default_factory=dict)
        weights: dict[str, int] = field(default_factory=dict)
        compatibility: dict[str, dict[str, str]] = field(default_factory=dict)

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> Application:
                """Build from a definition that already passed schema validation."""
                detection = data["detection"]
                services = detection.get("services", {})
                files = tuple(
                        ConfigFile(item)
                        if isinstance(item, str)
                        else ConfigFile(
                                path=item["path"],
                                format=item.get("format"),
                                syntax=item.get("syntax"),
                                settings=tuple(
                                        ConfigSetting(
                                                key=setting["key"],
                                                label=setting.get(
                                                        "label",
                                                        setting["key"]
                                                        .replace("_", " ")
                                                        .title(),
                                                ),
                                                kind=setting["type"],
                                                group=setting.get("group"),
                                                default=setting.get("default"),
                                                minimum=setting.get("minimum"),
                                                maximum=setting.get("maximum"),
                                                step=setting.get("step"),
                                                choices=tuple(
                                                        setting.get("choices", ())
                                                ),
                                                description=setting.get("description"),
                                        )
                                        for setting in item.get("settings", ())
                                ),
                        )
                        for item in data.get("configuration", {}).get("files", [])
                )
                return cls(
                        id=data["id"],
                        name=data["name"],
                        category=data["category"],
                        executables=tuple(detection.get("executables", ())),
                        config_paths=tuple(detection.get("config_paths", ())),
                        desktop_entries=tuple(detection.get("desktop_entries", ())),
                        processes=tuple(detection.get("processes", ())),
                        user_services=tuple(services.get("user", ())),
                        system_services=tuple(services.get("system", ())),
                        packages={
                                key: tuple(names)
                                for key, names in data.get("packages", {}).items()
                        },
                        config_files=files,
                        documentation=dict(data.get("documentation", {})),
                        weights=dict(detection.get("weights", {})),
                        compatibility={
                                layer: dict(statuses)
                                for layer, statuses in data.get(
                                        "compatibility", {}
                                ).items()
                        },
                )


@dataclass(frozen=True)
class ServiceState:
        scope: str  # "user" or "system"
        unit: str
        loaded: bool
        active: bool
        enabled: bool

        def describe(self) -> str:
                active = "active" if self.active else "inactive"
                enabled = "enabled" if self.enabled else "disabled"
                return f"{self.scope}:{self.unit} ({active}, {enabled})"


@dataclass
class Signal:
        """Outcome of one detection method for one application."""

        status: Status
        evidence: list[str] = field(default_factory=list)
        version: str | None = None
        units: tuple[ServiceState, ...] = ()


INSTALL_SIGNALS = ("package", "executable", "desktop_entry")


@dataclass
class AppResult:
        app: Application
        signals: dict[str, Signal]
        score: int
        confidence: str  # "high" | "medium" | "low" | "none"

        def _found(self, name: str) -> bool:
                signal = self.signals.get(name)
                return signal is not None and signal.status is Status.FOUND

        @property
        def installed(self) -> bool:
                return any(self._found(name) for name in INSTALL_SIGNALS)

        @property
        def configured(self) -> bool:
                return self._found("config")

        @property
        def detected(self) -> bool:
                """Installed, or at least leftover configuration was found."""
                return self.installed or self.configured

        @property
        def version(self) -> str | None:
                signal = self.signals.get("package")
                return signal.version if signal else None

        @property
        def running(self) -> bool | None:
                signal = self.signals.get("process")
                if signal is None or signal.status is Status.UNKNOWN:
                        return None
                return signal.status is Status.FOUND

        @property
        def service_enabled(self) -> bool | None:
                signal = self.signals.get("service")
                if signal is None or signal.status is Status.UNKNOWN:
                        return None
                return any(unit.enabled for unit in signal.units if unit.loaded)

        def to_dict(self) -> dict[str, Any]:
                return {
                        "id": self.app.id,
                        "name": self.app.name,
                        "category": self.app.category,
                        "installed": self.installed,
                        "configured": self.configured,
                        "running": self.running,
                        "service_enabled": self.service_enabled,
                        "version": self.version,
                        "confidence": self.confidence,
                        "score": self.score,
                        "signals": {
                                name: {
                                        "status": signal.status.value,
                                        "evidence": signal.evidence,
                                }
                                for name, signal in self.signals.items()
                        },
                }
