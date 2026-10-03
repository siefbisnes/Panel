from pathlib import Path

import pytest

from linux_system.config_editor import (
        ConfigEditorError,
        load_setting_values,
        save_setting_values,
)
from linux_system.models import ConfigFile, ConfigSetting


def test_lua_setting_round_trip_preserves_comments_and_other_lines(tmp_path: Path):
        path = tmp_path / "init.lua"
        path.write_text(
                "-- keep this\nBrightness=70 -- keep inline\nOtherOption = true\n"
        )
        setting = ConfigSetting("Brightness", "Brightness", "integer", 70, 0, 100)
        config = ConfigFile(str(path), "lua", settings=(setting,))

        assert load_setting_values(path, config) == {"Brightness": 70}
        save_setting_values(path, config, {"Brightness": 82})
        assert (
                path.read_text()
                == "-- keep this\nBrightness=82 -- keep inline\nOtherOption = true\n"
        )


def test_missing_lua_setting_uses_default_and_is_added_on_save(tmp_path: Path):
        path = tmp_path / "init.lua"
        path.write_text("-- user config\n")
        setting = ConfigSetting("Brightness", "Brightness", "integer", 70, 0, 100)
        config = ConfigFile(str(path), "lua", settings=(setting,))

        assert load_setting_values(path, config) == {"Brightness": 70}
        save_setting_values(path, config, {"Brightness": 65})
        assert "Brightness = 65" in path.read_text()


def test_ini_settings_stay_in_their_section(tmp_path: Path):
        path = tmp_path / "settings.ini"
        path.write_text("[user]\nname = Ada\n[display]\nwidth = 1200\n")
        settings = (
                ConfigSetting("user.name", "Name", "string", "Ada"),
                ConfigSetting(
                        "user.theme",
                        "Theme",
                        "choice",
                        "dark",
                        choices=("dark", "light"),
                ),
        )
        config = ConfigFile(str(path), "ini", settings=settings)

        save_setting_values(path, config, {"user.name": "Grace", "user.theme": "light"})
        text = path.read_text()
        assert "[user]\nname = Grace\ntheme = light\n[display]" in text
        assert load_setting_values(path, config) == {
                "user.name": "Grace",
                "user.theme": "light",
        }


def test_space_delimited_config_value_is_updated_in_place(tmp_path: Path):
        path = tmp_path / "kitty.conf"
        path.write_text("font_size 11.0\nbackground_opacity 1.0 # keep\n")
        setting = ConfigSetting(
                "background_opacity", "Background opacity", "number", 1, 0, 1, 0.05
        )
        config = ConfigFile(str(path), "conf", syntax="space", settings=(setting,))

        save_setting_values(path, config, {"background_opacity": 0.8})
        assert path.read_text() == "font_size 11.0\nbackground_opacity 0.8 # keep\n"


def test_fish_setting_round_trip_preserves_comments(tmp_path: Path):
        path = tmp_path / "config.fish"
        path.write_text("set -g Brightness 70 # keep\n")
        setting = ConfigSetting("Brightness", "Brightness", "integer", 70, 0, 100)
        config = ConfigFile(str(path), "fish", settings=(setting,))

        assert load_setting_values(path, config) == {"Brightness": 70}
        save_setting_values(path, config, {"Brightness": 82})
        assert path.read_text() == "set -g Brightness 82 # keep\n"


def test_vim_boolean_updates_set_and_nonset_without_touching_comments(tmp_path: Path):
        path = tmp_path / "init.vim"
        path.write_text('set number " keep comment\n')
        setting = ConfigSetting("number", "Show line numbers", "boolean", True)
        config = ConfigFile(str(path), "vim", settings=(setting,))

        assert load_setting_values(path, config) == {"number": True}
        save_setting_values(path, config, {"number": False})
        assert path.read_text() == 'set nonumber " keep comment\n'


def test_hyprlang_setting_updates_inside_its_block(tmp_path: Path):
        path = tmp_path / "hyprland.conf"
        path.write_text("general {\n    gaps_in = 5\n    border_size = 2\n}\n")
        setting = ConfigSetting("general.gaps_in", "Inner gaps", "integer", 5, 0, 30)
        config = ConfigFile(str(path), "hyprlang", settings=(setting,))

        assert load_setting_values(path, config) == {"general.gaps_in": 5}
        save_setting_values(path, config, {"general.gaps_in": 8})
        assert (
                path.read_text()
                == "general {\n    gaps_in = 8\n    border_size = 2\n}\n"
        )


def test_rasi_setting_updates_and_preserves_trailing_comment(tmp_path: Path):
        path = tmp_path / "config.rasi"
        path.write_text('configuration {\n    font: "Iosevka 11"; /* keep */\n}\n')
        setting = ConfigSetting("configuration.font", "Font", "string", "Iosevka 11")
        config = ConfigFile(str(path), "rasi", settings=(setting,))

        assert load_setting_values(path, config) == {"configuration.font": "Iosevka 11"}
        save_setting_values(path, config, {"configuration.font": "Iosevka 12"})
        assert 'font: "Iosevka 12"; /* keep */' in path.read_text()


def test_json_nested_setting_preserves_other_values(tmp_path: Path):
        path = tmp_path / "config.json"
        path.write_text('{"appearance": {"brightness": 70}, "enabled": true}\n')
        setting = ConfigSetting(
                "appearance.brightness", "Brightness", "integer", 70, 0, 100
        )
        config = ConfigFile(str(path), "json", settings=(setting,))

        save_setting_values(path, config, {"appearance.brightness": 85})
        assert load_setting_values(path, config) == {"appearance.brightness": 85}
        assert '"enabled": true' in path.read_text()


def test_setting_bounds_are_enforced_on_save(tmp_path: Path):
        path = tmp_path / "settings.lua"
        setting = ConfigSetting("Brightness", "Brightness", "integer", 70, 0, 100)
        config = ConfigFile(str(path), "lua", settings=(setting,))
        with pytest.raises(ConfigEditorError, match="at most 100"):
                save_setting_values(path, config, {"Brightness": 120})


def test_string_setting_keeps_boolean_like_words_as_text(tmp_path: Path):
        path = tmp_path / "kitty.conf"
        path.write_text("tab_activity_symbol true\n")
        setting = ConfigSetting(
                "tab_activity_symbol", "Tab activity symbol", "string", ""
        )
        config = ConfigFile(str(path), "conf", syntax="space", settings=(setting,))
        assert load_setting_values(path, config) == {"tab_activity_symbol": "true"}


def test_unchanged_metadata_defaults_do_not_create_config_file(tmp_path: Path):
        path = tmp_path / "kitty.conf"
        setting = ConfigSetting("font_size", "Font size", "number", 11)
        config = ConfigFile(str(path), "conf", syntax="space", settings=(setting,))

        save_setting_values(path, config, {"font_size": 11})
        assert not path.exists()


def test_comment_syntax_is_rejected_instead_of_rewritten(tmp_path: Path):
        path = tmp_path / "config.jsonc"
        path.write_text('{ /* keep comment */ "brightness": 70 }\n')
        setting = ConfigSetting("brightness", "Brightness", "integer", 70, 0, 100)
        config = ConfigFile(str(path), "jsonc", settings=(setting,))
        with pytest.raises(ConfigEditorError, match="no GUI settings adapter"):
                load_setting_values(path, config)
