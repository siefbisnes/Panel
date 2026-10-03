"""Package manager backends. Each lists every installed package once, as name -> version."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .environment import Runner


def _pairs(output: str, sep: str) -> dict[str, str]:
        index = {}
        for line in output.splitlines():
                name, _, version = line.partition(sep)
                if name:
                        index[name] = version.strip()
        return index


def parse_rpm(output: str) -> dict[str, str]:
        return _pairs(output, "\t")


def parse_pacman(output: str) -> dict[str, str]:
        return _pairs(output, " ")


def parse_flatpak(output: str) -> dict[str, str]:
        return _pairs(output, "\t")


def parse_dpkg(output: str) -> dict[str, str]:
        index = {}
        for line in output.splitlines():
                parts = line.split("\t")
                if len(parts) == 3 and parts[2].endswith(" installed"):
                        index[parts[0]] = parts[1]
        return index


@dataclass(frozen=True)
class Backend:
        command: tuple[str, ...]
        parse: Callable[[str], dict[str, str]]


RPM = Backend(("rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}\n"), parse_rpm)

BACKENDS: dict[str, Backend] = {
        "fedora": RPM,
        "opensuse": RPM,
        "arch": Backend(("pacman", "-Q"), parse_pacman),
        "debian": Backend(
                ("dpkg-query", "-W", "-f=${Package}\t${Version}\t${Status}\n"),
                parse_dpkg,
        ),
}

FLATPAK = Backend(
        ("flatpak", "list", "--app", "--columns=application,version"), parse_flatpak
)


def load_index(backend: Backend | None, run: Runner) -> dict[str, str] | None:
        """Installed packages, or None when the package manager is unavailable."""
        if backend is None:
                return None
        output = run(backend.command)
        return None if output is None else backend.parse(output)
