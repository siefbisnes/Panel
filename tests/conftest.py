import os
from pathlib import Path

import pytest

from linux_system.environment import Environment
from linux_system.packages import BACKENDS, FLATPAK


class FakeSystem:
        """A throwaway Linux layout: fake root, home, PATH, XDG data dirs, /proc and command outputs."""

        def __init__(self, tmp_path: Path):
                self.root = tmp_path / "root"
                self.home = tmp_path / "home"
                self.bin = tmp_path / "bin"
                self.share = tmp_path / "share"
                for directory in (
                        self.root / "etc",
                        self.root / "proc",
                        self.home / ".config",
                        self.bin,
                        self.share,
                ):
                        directory.mkdir(parents=True)
                self.outputs: dict[tuple[str, ...], str] = {}
                self.variables = {
                        "PATH": str(self.bin),
                        "XDG_DATA_DIRS": str(self.share),
                        "XDG_DATA_HOME": str(tmp_path / "data"),
                        "XDG_CONFIG_HOME": str(self.home / ".config"),
                }
                self.set_os("fedora", pretty="Fedora Linux 44")

        def set_os(self, os_id, like="", pretty="Test OS"):
                (self.root / "etc" / "os-release").write_text(
                        f'ID={os_id}\nID_LIKE="{like}"\nPRETTY_NAME="{pretty}"\n'
                )

        def add_executable(self, name):
                path = self.bin / name
                path.write_text("#!/bin/sh\n")
                path.chmod(0o755)

        def add_config(self, relative, content="x"):
                path = self.home / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)

        def add_desktop(self, name, sub="applications"):
                directory = self.share / sub
                directory.mkdir(exist_ok=True)
                (directory / f"{name}.desktop").write_text("[Desktop Entry]\n")

        def add_process(self, name, pid="123"):
                directory = self.root / "proc" / pid
                directory.mkdir(parents=True)
                (directory / "comm").write_text(name + "\n")
                (directory / "cmdline").write_bytes(f"/usr/bin/{name}\0".encode())

        def set_packages(self, distro, text):
                self.outputs[BACKENDS[distro].command] = text

        def set_flatpaks(self, text):
                self.outputs[FLATPAK.command] = text

        def set_service(self, scope, unit, output):
                cmd = [
                        "systemctl",
                        *(["--user"] if scope == "user" else []),
                        "show",
                        unit,
                        "--property=LoadState,ActiveState,UnitFileState",
                ]
                self.outputs[tuple(cmd)] = output

        @property
        def env(self) -> Environment:
                return Environment(
                        root=self.root,
                        home=self.home,
                        variables=self.variables,
                        run=lambda cmd: self.outputs.get(tuple(cmd)),
                )


@pytest.fixture
def fake(tmp_path):
        return FakeSystem(tmp_path)
