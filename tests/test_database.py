import textwrap

import pytest
import yaml

from linux_system.database import (
        bundled_root,
        definition_files,
        load_database,
        load_files,
        make_validator,
)

VALID = {
        "schema_version": 1,
        "id": "demo",
        "name": "Demo",
        "category": "tool",
        "detection": {"executables": ["demo"]},
}


def write(tmp_path, name, data):
        path = tmp_path / f"{name}.yaml"
        path.write_text(yaml.safe_dump(data))
        return path


def test_bundled_database_is_valid():
        result = load_files(definition_files(bundled_root()))
        assert result.errors == []
        assert {
                "rofi",
                "waybar",
                "kitty",
                "fish",
                "firefox",
                "git",
                "neovim",
                "hyprland",
        } <= set(result.apps)
        kitty_settings = result.apps["kitty"].config_files[0].settings
        assert len(kitty_settings) >= 140
        assert {
                "font_size",
                "background_opacity",
                "scrollback_lines",
                "tab_bar_style",
        } <= {setting.key for setting in kitty_settings}


def test_valid_definition_loads(tmp_path):
        result = load_files([write(tmp_path, "demo", VALID)])
        assert result.errors == [] and result.apps["demo"].executables == ("demo",)


def test_compatibility_metadata_loads(tmp_path):
        payload = {
                **VALID,
                "compatibility": {
                        "desktop_environments": {"hyprland": "supported"},
                        "display_servers": {"wayland": "supported"},
                },
        }
        result = load_files([write(tmp_path, "demo", payload)])
        assert result.errors == []
        assert result.apps["demo"].compatibility == payload["compatibility"]


@pytest.mark.parametrize(
        "change",
        [
                {"detction": {}},  # unknown key
                {"category": "nonsense"},
                {"detection": {}},  # no rule
                {
                        "detection": {"executables": ["../bin/evil"]}
                },  # path in executable name
                {"detection": {"config_paths": ["relative/path"]}},
                {"detection": {"services": {"user": ["not-a-unit"]}}},
                {"packages": {"gentoo": ["x"]}},
                {"documentation": {"home": "javascript:alert(1)"}},
                {"compatibility": {"desktop_environments": {"hyprland": "maybe"}}},
                {"schema_version": 2},
        ],
)
def test_invalid_definitions_are_rejected(tmp_path, change):
        result = load_files([write(tmp_path, "demo", {**VALID, **change})])
        assert result.errors and not result.apps


def test_id_must_match_file_name(tmp_path):
        result = load_files([write(tmp_path, "other", VALID)])
        assert "must match the file name" in result.errors[0]


def test_malformed_yaml_is_reported(tmp_path):
        path = tmp_path / "demo.yaml"
        path.write_text("id: [unclosed")
        assert "cannot read" in load_files([path]).errors[0]


def test_config_files_accept_plain_paths_and_objects(tmp_path):
        data = {
                **VALID,
                "configuration": {"files": ["~/.a", {"path": "~/.b", "format": "ini"}]},
        }
        app = load_files([write(tmp_path, "demo", data)]).apps["demo"]
        assert [(f.path, f.format) for f in app.config_files] == [
                ("~/.a", None),
                ("~/.b", "ini"),
        ]


def test_config_file_settings_load_as_typed_metadata(tmp_path):
        data = {
                **VALID,
                "configuration": {
                        "files": [
                                {
                                        "path": "~/.config/demo/init.lua",
                                        "format": "lua",
                                        "syntax": "lua",
                                        "settings": [
                                                {
                                                        "key": "Brightness",
                                                        "type": "integer",
                                                        "minimum": 0,
                                                        "maximum": 100,
                                                        "default": 70,
                                                }
                                        ],
                                }
                        ],
                },
        }
        app = load_files([write(tmp_path, "demo", data)]).apps["demo"]
        config_file = app.config_files[0]
        assert config_file.syntax == "lua"
        assert config_file.settings[0].key == "Brightness"
        assert config_file.settings[0].kind == "integer"
        assert config_file.settings[0].default == 70


def test_later_roots_override_earlier_by_id(tmp_path):
        for name, display in (("low", "Low"), ("high", "High")):
                (tmp_path / name / "applications").mkdir(parents=True)
                write(
                        tmp_path / name / "applications",
                        "demo",
                        {**VALID, "name": display},
                )
        result = load_database([tmp_path / "low", tmp_path / "high"])
        assert result.apps["demo"].name == "High"
