"""Access to the host: filesystem root, XDG locations, variables and commands."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

Runner = Callable[[Sequence[str]], "str | None"]


def run_command(cmd: Sequence[str], timeout: float = 15) -> str | None:
        """Return stdout of a successful command, or None if it is missing or failed."""
        try:
                proc = subprocess.run(
                        list(cmd),
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        check=False,
                )
        except (OSError, subprocess.TimeoutExpired):
                return None
        return proc.stdout if proc.returncode == 0 else None


@dataclass
class OsRelease:
        id: str = ""
        id_like: tuple[str, ...] = ()
        pretty_name: str = "Linux"


@dataclass
class Environment:
        """The system being inspected. Tests substitute a fake root, variables and runner."""

        root: Path = Path("/")
        home: Path = field(default_factory=Path.home)
        variables: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
        run: Runner = run_command

        def rooted(self, path: str | Path) -> Path:
                return self.root / str(path).lstrip("/")

        @property
        def config_home(self) -> Path:
                return Path(
                        self.variables.get("XDG_CONFIG_HOME") or self.home / ".config"
                )

        @property
        def data_home(self) -> Path:
                return Path(
                        self.variables.get("XDG_DATA_HOME")
                        or self.home / ".local" / "share"
                )

        @property
        def path_dirs(self) -> list[Path]:
                return [Path(p) for p in self.variables.get("PATH", "").split(":") if p]

        @property
        def data_dirs(self) -> list[Path]:
                raw = self.variables.get("XDG_DATA_DIRS")
                if raw:
                        return [Path(p) for p in raw.split(":") if p]
                return [self.rooted("/usr/local/share"), self.rooted("/usr/share")]

        def expand(self, raw: str) -> Path:
                """Expand ~ and the XDG variables allowed by the schema; absolute paths follow the root."""
                if raw.startswith("/"):
                        return self.rooted(raw)
                values = {
                        "HOME": str(self.home),
                        "XDG_CONFIG_HOME": str(self.config_home),
                        "XDG_DATA_HOME": str(self.data_home),
                        "XDG_STATE_HOME": self.variables.get("XDG_STATE_HOME")
                        or str(self.home / ".local" / "state"),
                        "XDG_CACHE_HOME": self.variables.get("XDG_CACHE_HOME")
                        or str(self.home / ".cache"),
                }
                if raw == "~" or raw.startswith("~/"):
                        raw = "$HOME" + raw[1:]
                for name, value in values.items():
                        raw = raw.replace("${" + name + "}", value).replace(
                                "$" + name, value
                        )
                return Path(raw)

        def tilde(self, text: str) -> str:
                home = str(self.home)
                if text == home or text.startswith(home + "/"):
                        return "~" + text[len(home) :]
                return text

        def os_release(self) -> OsRelease:
                for candidate in ("/etc/os-release", "/usr/lib/os-release"):
                        try:
                                text = self.rooted(candidate).read_text(
                                        encoding="utf-8"
                                )
                        except OSError:
                                continue
                        fields = {}
                        for line in text.splitlines():
                                key, sep, value = line.partition("=")
                                if sep:
                                        fields[key.strip()] = value.strip().strip("\"'")
                        return OsRelease(
                                id=fields.get("ID", ""),
                                id_like=tuple(fields.get("ID_LIKE", "").split()),
                                pretty_name=fields.get("PRETTY_NAME")
                                or fields.get("NAME")
                                or "Linux",
                        )
                return OsRelease()
