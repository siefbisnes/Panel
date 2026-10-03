import pytest

from linux_system.installer import (
        InstallTarget,
        install_command,
        select_install_target,
        select_installed_target,
        uninstall_command,
)


def test_native_target_uses_first_supported_package_choice():
        target = select_install_target(
                {"fedora": ("rofi", "rofi-wayland"), "flatpak": ("org.example.Rofi",)},
                "fedora",
                native_available=True,
                flatpak_available=True,
        )
        assert target == InstallTarget("fedora", "rofi")


def test_flatpak_fallback_requires_a_queryable_flatpak_backend():
        packages = {"flatpak": ("org.mozilla.firefox",)}
        assert select_install_target(
                packages, "fedora", native_available=False, flatpak_available=True
        ) == InstallTarget("flatpak", "org.mozilla.firefox")
        assert (
                select_install_target(
                        packages,
                        "fedora",
                        native_available=False,
                        flatpak_available=False,
                )
                is None
        )


def test_installed_target_matches_the_actual_alternative_package():
        assert select_installed_target(
                {"debian": ("firefox", "firefox-esr")},
                "debian",
                native_packages={"firefox-esr": "128"},
                flatpak_packages=None,
        ) == InstallTarget("debian", "firefox-esr")


def test_installed_flatpak_is_selected_when_no_native_package_is_installed():
        assert select_installed_target(
                {"fedora": ("firefox",), "flatpak": ("org.mozilla.firefox",)},
                "fedora",
                native_packages={},
                flatpak_packages={"org.mozilla.firefox": "128"},
        ) == InstallTarget("flatpak", "org.mozilla.firefox")


@pytest.mark.parametrize(
        ("source", "expected"),
        [
                (
                        "fedora",
                        ["pkexec", "dnf", "install", "--assumeyes", "--", "firefox"],
                ),
                (
                        "opensuse",
                        [
                                "pkexec",
                                "zypper",
                                "--non-interactive",
                                "install",
                                "--",
                                "firefox",
                        ],
                ),
                (
                        "arch",
                        [
                                "pkexec",
                                "pacman",
                                "--noconfirm",
                                "-S",
                                "--needed",
                                "--",
                                "firefox",
                        ],
                ),
                (
                        "debian",
                        [
                                "pkexec",
                                "apt-get",
                                "install",
                                "--assume-yes",
                                "--",
                                "firefox",
                        ],
                ),
        ],
)
def test_native_install_commands_use_polkit_and_argument_arrays(source, expected):
        assert install_command(InstallTarget(source, "firefox")) == expected


def test_flatpak_install_is_user_scoped():
        assert install_command(InstallTarget("flatpak", "org.mozilla.firefox")) == [
                "flatpak",
                "install",
                "--user",
                "--assumeyes",
                "flathub",
                "org.mozilla.firefox",
        ]


def test_install_command_rejects_shell_metacharacters():
        with pytest.raises(ValueError, match="invalid package name"):
                install_command(InstallTarget("fedora", "firefox;touch /tmp/pwned"))


def test_install_command_can_skip_polkit_when_already_root():
        assert install_command(
                InstallTarget("fedora", "firefox"), use_polkit=False
        ) == ["dnf", "install", "--assumeyes", "--", "firefox"]


@pytest.mark.parametrize(
        ("source", "expected"),
        [
                ("fedora", ["pkexec", "dnf", "remove", "--assumeyes", "--", "firefox"]),
                (
                        "opensuse",
                        [
                                "pkexec",
                                "zypper",
                                "--non-interactive",
                                "remove",
                                "--",
                                "firefox",
                        ],
                ),
                ("arch", ["pkexec", "pacman", "--noconfirm", "-R", "--", "firefox"]),
                (
                        "debian",
                        [
                                "pkexec",
                                "apt-get",
                                "remove",
                                "--assume-yes",
                                "--",
                                "firefox",
                        ],
                ),
        ],
)
def test_native_uninstall_commands_remove_only_the_selected_package(source, expected):
        assert uninstall_command(InstallTarget(source, "firefox")) == expected


def test_flatpak_uninstall_keeps_user_data_by_default():
        assert uninstall_command(InstallTarget("flatpak", "org.mozilla.firefox")) == [
                "flatpak",
                "uninstall",
                "--user",
                "--assumeyes",
                "org.mozilla.firefox",
        ]
