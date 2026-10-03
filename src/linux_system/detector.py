"""Detection methods. Each returns a Signal, or None when a definition has no rule for it."""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path

from .environment import Environment, OsRelease
from .models import Application, ServiceState, Signal, Status
from .packages import BACKENDS, FLATPAK, load_index

DESKTOP_SUBDIRS = ("applications", "wayland-sessions", "xsessions")
DISTRO_KEYS = ("fedora", "arch", "debian", "opensuse")


class SystemProbe:
        """Lazily gathers system-wide facts once, so scanning many applications stays cheap."""

        def __init__(self, env: Environment | None = None):
                self.env = env or Environment()

        @cached_property
        def os_release(self) -> OsRelease:
                return self.env.os_release()

        @cached_property
        def package_key(self) -> str | None:
                tokens = [self.os_release.id, *self.os_release.id_like]
                for key in DISTRO_KEYS:
                        if any(
                                token == key or token.startswith(key + "-")
                                for token in tokens
                        ):
                                return key
                return None

        @cached_property
        def native_packages(self) -> dict[str, str] | None:
                return load_index(BACKENDS.get(self.package_key or ""), self.env.run)

        @cached_property
        def flatpak_packages(self) -> dict[str, str] | None:
                return load_index(FLATPAK, self.env.run)

        @cached_property
        def processes(self) -> set[str] | None:
                try:
                        entries = [
                                e
                                for e in self.env.rooted("/proc").iterdir()
                                if e.name.isdigit()
                        ]
                except OSError:
                        return None
                names: set[str] = set()
                for entry in entries:
                        try:
                                names.add((entry / "comm").read_text().strip())
                                argv0 = (
                                        (entry / "cmdline")
                                        .read_bytes()
                                        .split(b"\0", 1)[0]
                                        .decode(errors="replace")
                                )
                        except OSError:
                                continue
                        if argv0:
                                names.add(Path(argv0).name)
                return names

        @cached_property
        def desktop_entries(self) -> dict[str, Path]:
                env = self.env
                share_dirs = [
                        env.data_home,
                        *env.data_dirs,
                        env.data_home / "flatpak" / "exports" / "share",
                        env.rooted("/var/lib/flatpak/exports/share"),
                ]
                found: dict[str, Path] = {}
                for share in share_dirs:
                        for sub in DESKTOP_SUBDIRS:
                                try:
                                        for entry in (share / sub).glob("*.desktop"):
                                                found.setdefault(entry.stem, entry)
                                except OSError:
                                        continue
                return found

        def find_executable(self, name: str) -> Path | None:
                for directory in self.env.path_dirs:
                        candidate = directory / name
                        if candidate.is_file() and os.access(candidate, os.X_OK):
                                return candidate
                return None


def detect_package(app: Application, probe: SystemProbe) -> Signal:
        key = probe.package_key
        sources = (
                (
                        key or "",
                        app.packages.get(key, ()) if key else (),
                        probe.native_packages,
                ),
                ("flatpak", app.packages.get("flatpak", ()), probe.flatpak_packages),
        )
        evidence: list[str] = []
        version: str | None = None
        checked = False
        for label, names, index in sources:
                if not names or index is None:
                        continue
                checked = True
                for name in names:
                        if name in index:
                                evidence.append(
                                        f"{label}:{name}"
                                        + (f" {index[name]}" if index[name] else "")
                                )
                                version = version or index[name] or None
        if evidence:
                return Signal(Status.FOUND, evidence, version)
        return Signal(Status.NOT_FOUND if checked else Status.UNKNOWN)


def detect_executable(app: Application, probe: SystemProbe) -> Signal | None:
        if not app.executables:
                return None
        found = [
                str(path)
                for name in app.executables
                if (path := probe.find_executable(name))
        ]
        return Signal(Status.FOUND if found else Status.NOT_FOUND, found)


def detect_desktop_entry(app: Application, probe: SystemProbe) -> Signal | None:
        if not app.desktop_entries:
                return None
        entries = probe.desktop_entries
        found = [str(entries[name]) for name in app.desktop_entries if name in entries]
        return Signal(Status.FOUND if found else Status.NOT_FOUND, found)


def detect_config(app: Application, probe: SystemProbe) -> Signal | None:
        raw_paths = [*app.config_paths, *(f.path for f in app.config_files)]
        if not raw_paths:
                return None
        existing = [
                p
                for p in dict.fromkeys(probe.env.expand(raw) for raw in raw_paths)
                if p.exists()
        ]
        # A found directory already implies the files inside it.
        found = [
                str(p)
                for p in existing
                if not any(q != p and q in p.parents for q in existing)
        ]
        return Signal(Status.FOUND if found else Status.NOT_FOUND, found)


def detect_process(app: Application, probe: SystemProbe) -> Signal | None:
        names = app.processes or app.executables
        if not names:
                return None
        running = probe.processes
        if running is None:
                return Signal(Status.UNKNOWN)
        # The kernel truncates process names to 15 characters.
        matches = [name for name in names if name in running or name[:15] in running]
        return Signal(Status.FOUND if matches else Status.NOT_FOUND, matches)


def detect_service(app: Application, probe: SystemProbe) -> Signal | None:
        scopes = (("user", app.user_services), ("system", app.system_services))
        if not any(units for _, units in scopes):
                return None
        states: list[ServiceState] = []
        reachable = False
        for scope, units in scopes:
                for unit in units:
                        cmd = [
                                "systemctl",
                                *(["--user"] if scope == "user" else []),
                                "show",
                                unit,
                                "--property=LoadState,ActiveState,UnitFileState",
                        ]
                        output = probe.env.run(cmd)
                        if output is None:
                                continue
                        reachable = True
                        props = dict(
                                line.split("=", 1)
                                for line in output.splitlines()
                                if "=" in line
                        )
                        states.append(
                                ServiceState(
                                        scope=scope,
                                        unit=unit,
                                        loaded=props.get("LoadState") == "loaded",
                                        active=props.get("ActiveState") == "active",
                                        enabled=props.get(
                                                "UnitFileState", ""
                                        ).startswith("enabled"),
                                )
                        )
        if not reachable:
                return Signal(Status.UNKNOWN)
        loaded = [state for state in states if state.loaded]
        return Signal(
                Status.FOUND if loaded else Status.NOT_FOUND,
                [s.describe() for s in loaded],
                units=tuple(states),
        )


DETECTORS = {
        "package": detect_package,
        "executable": detect_executable,
        "desktop_entry": detect_desktop_entry,
        "config": detect_config,
        "process": detect_process,
        "service": detect_service,
}
