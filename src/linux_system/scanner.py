"""Runs every detector for every application and scores the evidence."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .detector import DETECTORS, SystemProbe
from .models import AppResult, Application, Signal, Status

DEFAULT_WEIGHTS = {"package": 3, "executable": 3, "desktop_entry": 2, "config": 1}
HIGH, MEDIUM = 5, 3


def scan_app(app: Application, probe: SystemProbe) -> AppResult:
        signals: dict[str, Signal] = {}
        for name, detect in DETECTORS.items():
                signal = detect(app, probe)
                if signal is not None:
                        signals[name] = signal
        weights = {**DEFAULT_WEIGHTS, **app.weights}
        score = sum(
                weight
                for name, weight in weights.items()
                if name in signals and signals[name].status is Status.FOUND
        )
        result = AppResult(app, signals, score, "none")
        if result.detected:
                result.confidence = (
                        "high"
                        if score >= HIGH
                        else "medium"
                        if score >= MEDIUM
                        else "low"
                )
        return result


def scan(apps: Iterable[Application], probe: SystemProbe) -> list[AppResult]:
        return [scan_app(app, probe) for app in apps]


def system_overview(probe: SystemProbe, results: list[AppResult]) -> dict[str, str]:
        variables = probe.env.variables
        detected = [r for r in results if r.detected]
        overview = {"Distribution": probe.os_release.pretty_name}
        shell = variables.get("SHELL")
        for label, value in (
                ("Desktop", variables.get("XDG_CURRENT_DESKTOP")),
                ("Display server", variables.get("XDG_SESSION_TYPE")),
                ("Shell", Path(shell).name if shell else None),
        ):
                if value:
                        overview[label] = value
        overview["Applications"] = f"{len(detected)} detected ({len(results)} known)"
        overview["Configured"] = str(sum(r.configured for r in detected))
        overview["Running"] = str(sum(r.running is True for r in detected))
        overview["Services enabled"] = str(
                sum(r.service_enabled is True for r in detected)
        )
        return overview
