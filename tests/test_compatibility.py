from linux_system.compatibility import compatibility_details, declared_compatibility


def test_compatibility_details_compare_hyprland_and_wayland():
        compatibility = {
                "desktop_environments": {
                        "hyprland": "supported",
                        "gnome": "unsupported",
                },
                "display_servers": {"wayland": "partial"},
        }
        details = compatibility_details(
                compatibility,
                {"XDG_CURRENT_DESKTOP": "Hyprland", "XDG_SESSION_TYPE": "wayland"},
        )
        assert "Desktop environment · Hyprland: Supported" in details
        assert "Display server · Wayland: Partial support" in details
        assert "Gnome desktop environment: Unsupported" in details


def test_compatibility_details_mark_missing_metadata_as_not_specified():
        details = compatibility_details(
                {},
                {"XDG_CURRENT_DESKTOP": "Hyprland", "WAYLAND_DISPLAY": "wayland-1"},
        )
        assert "Desktop environment · Hyprland: Not specified" in details
        assert "Display server · Wayland: Not specified" in details


def test_compatibility_details_handles_missing_session_variables():
        assert compatibility_details({}, {}) == [
                "Desktop environment: Not detected",
                "Display server: Not detected",
        ]


def test_declared_compatibility_is_suitable_for_store_rows():
        assert declared_compatibility(
                {
                        "desktop_environments": {"hyprland": "supported"},
                        "display_servers": {"wayland": "supported"},
                }
        ) == ["Hyprland: Supported", "Wayland: Supported"]
