from linux_system.detector import SystemProbe
from linux_system.models import Application, Status
from linux_system.scanner import scan_app, system_overview

ROFI = Application(
        id="rofi",
        name="Rofi",
        category="launcher",
        executables=("rofi",),
        config_paths=("~/.config/rofi",),
        desktop_entries=("rofi",),
        packages={"fedora": ("rofi",), "arch": ("rofi",)},
)


def scan_rofi(fake, app=ROFI):
        return scan_app(app, SystemProbe(fake.env))


def test_full_evidence_is_high_confidence(fake):
        fake.set_packages("fedora", "rofi\t2.0.0\nbash\t5.2\n")
        fake.add_executable("rofi")
        fake.add_config(".config/rofi/config.rasi")
        result = scan_rofi(fake)
        assert result.installed and result.configured
        assert result.confidence == "high" and result.version == "2.0.0"
        assert result.signals["config"].evidence == [str(fake.home / ".config/rofi")]


def test_unknown_package_state_gives_medium_confidence(fake):
        fake.add_executable("rofi")  # no rpm output: package manager unreachable
        result = scan_rofi(fake)
        assert result.signals["package"].status is Status.UNKNOWN
        assert result.signals["config"].status is Status.NOT_FOUND
        assert result.confidence == "medium"


def test_missing_package_name_for_distro_is_unknown_not_absent(fake):
        fake.set_os("debian")
        fake.set_packages("debian", "")
        assert (
                scan_rofi(fake, Application("x", "X", "tool", executables=("x",)))
                .signals["package"]
                .status
                is Status.UNKNOWN
        )


def test_config_alone_is_detected_but_not_installed(fake):
        fake.set_packages("fedora", "bash\t5.2\n")
        fake.add_config(".config/rofi/config.rasi")
        result = scan_rofi(fake)
        assert result.detected and not result.installed and result.confidence == "low"


def test_nothing_found(fake):
        fake.set_packages("fedora", "bash\t5.2\n")
        result = scan_rofi(fake)
        assert not result.detected and result.confidence == "none" and result.score == 0


def test_non_executable_file_in_path_is_ignored(fake):
        (fake.bin / "rofi").write_text("data")
        assert not scan_rofi(fake).signals["executable"].evidence


def test_desktop_entries_include_session_files(fake):
        fake.add_desktop("hyprland", sub="wayland-sessions")
        app = Application(
                "hyprland", "Hyprland", "desktop", desktop_entries=("hyprland",)
        )
        assert scan_rofi(fake, app).signals["desktop_entry"].status is Status.FOUND


def test_flatpak_package_is_detected_on_any_distro(fake):
        fake.set_packages("fedora", "bash\t5.2\n")
        fake.set_flatpaks("org.mozilla.firefox\t140.0\n")
        app = Application(
                "firefox",
                "Firefox",
                "browser",
                packages={"flatpak": ("org.mozilla.firefox",)},
        )
        signal = scan_rofi(fake, app).signals["package"]
        assert signal.status is Status.FOUND and signal.version == "140.0"


def test_dpkg_ignores_removed_packages(fake):
        fake.set_os("ubuntu", like="debian")
        fake.set_packages(
                "debian",
                "git\t1:2.43\tinstall ok installed\nrofi\t1.7\tdeinstall ok config-files\n",
        )
        app = Application("rofi", "Rofi", "launcher", packages={"debian": ("rofi",)})
        assert scan_rofi(fake, app).signals["package"].status is Status.NOT_FOUND


def test_process_detection_uses_comm_and_argv0(fake):
        fake.add_process("rofi")
        assert scan_rofi(fake).running is True
        assert (
                scan_rofi(
                        fake, Application("x", "X", "tool", executables=("waybar",))
                ).running
                is False
        )


def test_process_state_unknown_without_proc(fake):
        (fake.root / "proc").rmdir()
        assert scan_rofi(fake).running is None


def test_long_process_names_match_truncated_comm(fake):
        fake.add_process("a-very-long-pro")  # kernel keeps 15 characters
        app = Application("x", "X", "tool", processes=("a-very-long-process",))
        assert scan_rofi(fake, app).running is True


def test_services(fake):
        fake.set_service(
                "user",
                "pipewire.service",
                "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n",
        )
        fake.set_service(
                "user",
                "wireplumber.service",
                "LoadState=not-found\nActiveState=inactive\nUnitFileState=\n",
        )
        app = Application(
                "pipewire",
                "PipeWire",
                "audio",
                user_services=("pipewire.service", "wireplumber.service"),
        )
        result = scan_rofi(fake, app)
        assert result.service_enabled is True
        assert result.signals["service"].evidence == [
                "user:pipewire.service (active, enabled)"
        ]


def test_service_state_unknown_when_systemd_unreachable(fake):
        app = Application(
                "pipewire", "PipeWire", "audio", user_services=("pipewire.service",)
        )
        assert scan_rofi(fake, app).service_enabled is None


def test_weights_can_be_overridden_by_definitions(fake):
        fake.add_config(".config/rofi/config.rasi")
        app = Application(
                "rofi",
                "Rofi",
                "launcher",
                config_paths=("~/.config/rofi",),
                weights={"config": 5},
        )
        assert scan_rofi(fake, app).confidence == "high"


def test_absolute_config_paths_follow_the_root(fake):
        (fake.root / "etc").joinpath("gitconfig").write_text("[user]\n")
        app = Application("git", "Git", "tool", config_paths=("/etc/gitconfig",))
        assert scan_rofi(fake, app).configured


def test_overview(fake):
        fake.add_executable("rofi")
        fake.variables["XDG_SESSION_TYPE"] = "wayland"
        probe = SystemProbe(fake.env)
        overview = system_overview(probe, [scan_app(ROFI, probe)])
        assert overview["Distribution"] == "Fedora Linux 44"
        assert overview["Display server"] == "wayland"
        assert overview["Applications"] == "1 detected (1 known)"
