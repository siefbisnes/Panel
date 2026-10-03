"""Inspecting and opening an application's configuration."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .environment import Environment
from .models import Application


@dataclass(frozen=True)
class ConfigEntry:
        path: Path
        exists: bool
        is_file: bool
        format: str | None = None


def config_entries(app: Application, env: Environment) -> list[ConfigEntry]:
        formats = {env.expand(f.path): f.format for f in app.config_files}
        raw_paths = [*app.config_paths, *(f.path for f in app.config_files)]
        entries = []
        for path in dict.fromkeys(env.expand(raw) for raw in raw_paths):
                entries.append(
                        ConfigEntry(
                                path, path.exists(), path.is_file(), formats.get(path)
                        )
                )
        return entries


def edit_target(app: Application, env: Environment) -> Path | None:
        """First existing declared configuration file."""
        for config_file in app.config_files:
                path = env.expand(config_file.path)
                if path.is_file():
                        return path
        return None


def open_in_editor(path: Path, env: Environment) -> int:
        editor = env.variables.get("VISUAL") or env.variables.get("EDITOR") or "vi"
        try:
                return subprocess.call([*shlex.split(editor), str(path)])
        except OSError as exc:
                print(f"error: cannot start editor '{editor}': {exc}")
                return 1
