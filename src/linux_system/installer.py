"""Resolve safe package-manager commands for supported application definitions."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:@-]*$")
NATIVE_INSTALLERS = {
        "fedora": ("dnf", ("install", "--assumeyes")),
        "opensuse": ("zypper", ("--non-interactive", "install")),
        "arch": ("pacman", ("--noconfirm", "-S", "--needed")),
        "debian": ("apt-get", ("install", "--assume-yes")),
}
NATIVE_UNINSTALLERS = {
        "fedora": ("dnf", ("remove", "--assumeyes")),
        "opensuse": ("zypper", ("--non-interactive", "remove")),
        "arch": ("pacman", ("--noconfirm", "-R")),
        "debian": ("apt-get", ("remove", "--assume-yes")),
}


@dataclass(frozen=True)
class InstallTarget:
        source: str
        package: str


def select_install_target(
        packages: Mapping[str, Sequence[str]],
        package_key: str | None,
        *,
        native_available: bool,
        flatpak_available: bool,
) -> InstallTarget | None:
        """Choose one native package, then one Flatpak ID as a fallback."""
        if package_key and native_available and packages.get(package_key):
                return InstallTarget(package_key, packages[package_key][0])
        if flatpak_available and packages.get("flatpak"):
                return InstallTarget("flatpak", packages["flatpak"][0])
        return None


def select_installed_target(
        packages: Mapping[str, Sequence[str]],
        package_key: str | None,
        *,
        native_packages: Mapping[str, str] | None,
        flatpak_packages: Mapping[str, str] | None,
) -> InstallTarget | None:
        """Return a package target only when that exact package is in an installed index."""
        if package_key and native_packages is not None:
                for package in packages.get(package_key, ()):
                        if package in native_packages:
                                return InstallTarget(package_key, package)
        if flatpak_packages is not None:
                for package in packages.get("flatpak", ()):
                        if package in flatpak_packages:
                                return InstallTarget("flatpak", package)
        return None


def _validate_target(target: InstallTarget) -> None:
        if not PACKAGE_NAME.fullmatch(target.package):
                raise ValueError(f"invalid package name: {target.package!r}")


def install_command(target: InstallTarget, *, use_polkit: bool = True) -> list[str]:
        """Build an argv-only install command; native installs request graphical auth."""
        _validate_target(target)
        if target.source == "flatpak":
                return [
                        "flatpak",
                        "install",
                        "--user",
                        "--assumeyes",
                        "flathub",
                        target.package,
                ]
        try:
                manager, arguments = NATIVE_INSTALLERS[target.source]
        except KeyError:
                raise ValueError(
                        f"unsupported package source: {target.source!r}"
                ) from None
        prefix = ["pkexec"] if use_polkit else []
        return [*prefix, manager, *arguments, "--", target.package]


def uninstall_command(target: InstallTarget, *, use_polkit: bool = True) -> list[str]:
        """Build a package-only uninstall command, retaining per-user application data."""
        _validate_target(target)
        if target.source == "flatpak":
                return ["flatpak", "uninstall", "--user", "--assumeyes", target.package]
        try:
                manager, arguments = NATIVE_UNINSTALLERS[target.source]
        except KeyError:
                raise ValueError(
                        f"unsupported package source: {target.source!r}"
                ) from None
        prefix = ["pkexec"] if use_polkit else []
        return [*prefix, manager, *arguments, "--", target.package]
