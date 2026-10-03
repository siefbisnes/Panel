"""Read and update only metadata-declared scalar configuration settings."""

from __future__ import annotations

import ast
import json
import re
import shlex
from pathlib import Path
from typing import Any

from .models import ConfigFile, ConfigSetting

SYNTAX_BY_FORMAT = {
        "lua": "lua",
        "ini": "ini",
        "conf": "space",
        "json": "json",
        "fish": "fish",
        "vim": "vim",
        "hyprlang": "block",
        "rasi": "block",
        "css": "block",
}
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


class ConfigEditorError(ValueError):
        """Raised when declared editor settings do not match the file syntax."""


def syntax_for(config_file: ConfigFile) -> str | None:
        return config_file.syntax or SYNTAX_BY_FORMAT.get(config_file.format or "")


def default_value(setting: ConfigSetting) -> Any:
        if setting.default is not None:
                return setting.default
        if setting.kind == "boolean":
                return False
        if setting.kind == "integer":
                return int(setting.minimum or 0)
        if setting.kind == "number":
                return float(setting.minimum or 0)
        if setting.kind == "choice":
                return setting.choices[0] if setting.choices else ""
        return ""


def _coerce(value: Any, setting: ConfigSetting) -> Any:
        try:
                if setting.kind == "boolean":
                        if isinstance(value, bool):
                                result = value
                        elif str(value).strip().casefold() in (
                                "true",
                                "yes",
                                "on",
                                "1",
                        ):
                                result = True
                        elif str(value).strip().casefold() in (
                                "false",
                                "no",
                                "off",
                                "0",
                        ):
                                result = False
                        else:
                                raise ValueError
                elif setting.kind == "integer":
                        result = int(value)
                elif setting.kind == "number":
                        result = float(value)
                elif setting.kind in ("string", "choice"):
                        result = str(value)
                else:
                        raise ConfigEditorError(
                                f"unsupported setting type: {setting.kind}"
                        )
        except (TypeError, ValueError):
                raise ConfigEditorError(
                        f"{setting.label} has an invalid value"
                ) from None

        if setting.kind in ("integer", "number"):
                if setting.minimum is not None and result < setting.minimum:
                        raise ConfigEditorError(
                                f"{setting.label} must be at least {setting.minimum:g}"
                        )
                if setting.maximum is not None and result > setting.maximum:
                        raise ConfigEditorError(
                                f"{setting.label} must be at most {setting.maximum:g}"
                        )
        if setting.kind == "choice" and result not in setting.choices:
                raise ConfigEditorError(
                        f"{setting.label} must be one of: {', '.join(setting.choices)}"
                )
        return result


def _parse_scalar(raw: str, setting: ConfigSetting, syntax: str) -> Any:
        value = raw.strip()
        if setting.kind in ("string", "choice"):
                if value.startswith(("'", '"')):
                        try:
                                return _coerce(ast.literal_eval(value), setting)
                        except (SyntaxError, ValueError):
                                raise ConfigEditorError(
                                        f"cannot read {setting.label} from its config value"
                                ) from None
                return _coerce(value, setting)
        if syntax == "lua" and value == "nil":
                return None
        if value.casefold() in ("true", "yes", "on"):
                parsed: Any = True
        elif value.casefold() in ("false", "no", "off"):
                parsed = False
        elif _NUMBER.fullmatch(value):
                parsed = (
                        float(value)
                        if any(char in value for char in ".eE")
                        else int(value)
                )
        elif value.startswith(("'", '"')):
                try:
                        parsed = ast.literal_eval(value)
                except (SyntaxError, ValueError):
                        raise ConfigEditorError(
                                f"cannot read {setting.label} from its config value"
                        ) from None
        else:
                parsed = value
        return _coerce(parsed, setting)


def _comment_offset(value: str, syntax: str) -> int | None:
        markers = {
                "lua": ("--",),
                "vim": ('"',),
                "fish": ("#",),
                "block": ("/*", "//"),
        }.get(syntax, ("#", ";"))
        quote: str | None = None
        escaped = False
        index = 0
        while index < len(value):
                char = value[index]
                if quote:
                        if escaped:
                                escaped = False
                        elif char == "\\":
                                escaped = True
                        elif char == quote:
                                quote = None
                elif syntax != "vim" and char in ("'", '"'):
                        quote = char
                else:
                        marker = next(
                                (
                                        item
                                        for item in markers
                                        if value.startswith(item, index)
                                ),
                                None,
                        )
                        if marker and (
                                (syntax == "vim" and marker == '"' and index == 0)
                                or (index > 0 and value[index - 1].isspace())
                        ):
                                return index
                index += 1
        return None


def _split_comment(value: str, syntax: str) -> tuple[str, str]:
        offset = _comment_offset(value, syntax)
        if offset is None:
                return value.rstrip(), ""
        start = offset
        while start and value[start - 1].isspace():
                start -= 1
        return value[:start].rstrip(), value[start:]


def _syntax_pattern(
        setting: ConfigSetting, syntax: str, key: str | None = None
) -> re.Pattern[str]:
        name = re.escape(key or setting.key)
        if syntax == "lua":
                separator = r"\s*=\s*"
                prefix = rf"\s*(?:local\s+)?{name}{separator}"
        elif syntax == "fish":
                prefix = rf"\s*set\s+(?:-[A-Za-z]+\s+)*{name}\s+"
        elif syntax == "vim":
                prefix = rf"\s*set\s+(?:no)?{name}(?:=|\s+)?"
        elif syntax == "block":
                prefix = rf"\s*{name}\s*[:=]\s*"
        elif syntax == "space":
                prefix = rf"\s*{name}\s+"
        else:
                prefix = rf"\s*{name}\s*=\s*"
        return re.compile(rf"^(?P<prefix>{prefix})(?P<value>.*)$")


def _ini_key(setting: ConfigSetting) -> tuple[str | None, str]:
        if "." in setting.key:
                section, key = setting.key.rsplit(".", 1)
                return section, key
        return None, setting.key


def _block_matches(
        lines: list[str], setting: ConfigSetting
) -> list[tuple[int, re.Match[str]]]:
        matches = []
        section, key = _ini_key(setting)
        pattern = _syntax_pattern(setting, "block", key)
        sections: list[str] = []
        for index, line in enumerate(lines):
                original = line.rstrip("\r\n")
                content, _comment = _split_comment(original, "block")
                closing = re.match(r"^\s*(}+)", content)
                if closing:
                        close_count = len(closing.group(1))
                        for _ in range(min(close_count, len(sections))):
                                sections.pop()
                        continue
                header = re.match(r"^\s*([^{}]+?)\s*\{\s*$", content)
                if header:
                        sections.append(header.group(1).strip())
                        continue
                current_section = ".".join(sections) or None
                if current_section != section:
                        continue
                match = pattern.match(original)
                if match:
                        matches.append((index, match))
        return matches


def _line_matches(
        lines: list[str], setting: ConfigSetting, syntax: str
) -> list[tuple[int, re.Match[str]]]:
        if syntax == "block":
                return _block_matches(lines, setting)
        matches = []
        current_section: str | None = None
        section, key = _ini_key(setting) if syntax == "ini" else (None, setting.key)
        pattern = _syntax_pattern(setting, syntax, key)
        for index, line in enumerate(lines):
                content = line.rstrip("\r\n")
                if syntax == "ini":
                        section_match = re.match(
                                r"^\s*\[([^]]+)\]\s*(?:[;#].*)?$", content
                        )
                        if section_match:
                                current_section = section_match.group(1).strip()
                                continue
                        if current_section != section and not (
                                section == "main" and current_section is None
                        ):
                                continue
                match = pattern.match(content)
                if match:
                        if syntax == "vim" and setting.kind == "boolean":
                                value, _comment = _split_comment(
                                        match.group("value"), syntax
                                )
                                if value.strip() and not value.lstrip().startswith('"'):
                                        continue
                        matches.append((index, match))
        return matches


def _line_value(match: re.Match[str], setting: ConfigSetting, syntax: str) -> str:
        if syntax == "vim" and setting.kind == "boolean":
                token = match.group("prefix").strip().split()[-1]
                return "false" if token == f"no{setting.key}" else "true"
        value, _comment = _split_comment(match.group("value"), syntax)
        if syntax == "block" and value.rstrip().endswith(";"):
                value = value.rstrip()[:-1].rstrip()
        return value


def _parse_json(path: Path) -> Any:
        if not path.exists():
                return {}
        try:
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
                raise ConfigEditorError(
                        f"cannot parse JSON config {path}: {exc}"
                ) from None


def _json_get(document: Any, key: str) -> Any:
        current = document
        for part in key.split("."):
                if not isinstance(current, dict) or part not in current:
                        raise KeyError(key)
                current = current[part]
        return current


def _json_set(document: dict[str, Any], key: str, value: Any) -> None:
        parts = key.split(".")
        current = document
        for part in parts[:-1]:
                nested = current.setdefault(part, {})
                if not isinstance(nested, dict):
                        raise ConfigEditorError(
                                f"cannot create nested JSON setting {key}"
                        )
                current = nested
        current[parts[-1]] = value


def load_setting_values(path: Path, config_file: ConfigFile) -> dict[str, Any]:
        """Load declared values, using metadata defaults when a key is absent."""
        syntax = syntax_for(config_file)
        if not config_file.settings:
                return {}
        if syntax is None:
                raise ConfigEditorError(
                        f"no GUI settings adapter is available for {config_file.format or path.suffix}"
                )
        if syntax == "json":
                document = _parse_json(path)
                values = {}
                for setting in config_file.settings:
                        try:
                                raw = _json_get(document, setting.key)
                        except KeyError:
                                raw = default_value(setting)
                        values[setting.key] = _coerce(raw, setting)
                return values
        if syntax not in ("lua", "equals", "space", "ini", "fish", "vim", "block"):
                raise ConfigEditorError(f"unsupported GUI settings syntax: {syntax}")

        try:
                lines = (
                        path.read_text(encoding="utf-8").splitlines(keepends=True)
                        if path.exists()
                        else []
                )
        except OSError as exc:
                raise ConfigEditorError(f"cannot read config {path}: {exc}") from None
        values = {}
        for setting in config_file.settings:
                matches = _line_matches(lines, setting, syntax)
                if not matches:
                        values[setting.key] = default_value(setting)
                        continue
                _, match = matches[-1]
                raw_value = _line_value(match, setting, syntax)
                values[setting.key] = _parse_scalar(raw_value, setting, syntax)
        return values


def _serialize_scalar(value: Any, syntax: str) -> str:
        if isinstance(value, bool):
                return "true" if value else "false"
        if isinstance(value, str):
                if syntax == "fish":
                        return shlex.quote(value)
                if (
                        syntax == "lua"
                        or any(char.isspace() for char in value)
                        or not value
                ):
                        return json.dumps(value, ensure_ascii=False)
                return value
        if value is None:
                if syntax == "lua":
                        return "nil"
                return "null"
        return str(value)


def _line_assignment(setting: ConfigSetting, value: Any, syntax: str) -> str:
        serialized = _serialize_scalar(value, syntax)
        if syntax == "fish":
                return f"set -g {setting.key} {serialized}"
        if syntax == "vim":
                if setting.kind == "boolean":
                        return f"set {'no' if not value else ''}{setting.key}"
                return f"set {setting.key}={serialized}"
        separator = " = " if syntax in ("lua", "equals", "ini") else " "
        key = _ini_key(setting)[1] if syntax == "ini" else setting.key
        return f"{key}{separator}{serialized}"


def _append_ini(lines: list[str], setting: ConfigSetting, value: Any) -> None:
        section, _key = _ini_key(setting)
        assignment = _line_assignment(setting, value, "ini") + "\n"
        if section is None:
                if lines and not lines[-1].endswith(("\n", "\r")):
                        lines[-1] += "\n"
                lines.append(assignment)
                return

        current_section: str | None = None
        insert_at = None
        for index, line in enumerate(lines):
                match = re.match(r"^\s*\[([^]]+)\]\s*(?:[;#].*)?$", line.rstrip("\r\n"))
                if match:
                        if current_section == section:
                                insert_at = index
                        current_section = match.group(1).strip()
        if current_section == section:
                insert_at = len(lines)
        if insert_at is not None:
                lines.insert(insert_at, assignment)
                return
        if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += "\n"
        if lines and lines[-1].strip():
                lines.append("\n")
        lines.extend((f"[{section}]\n", assignment))


def _append_block(
        lines: list[str], config_file: ConfigFile, setting: ConfigSetting, value: Any
) -> None:
        section, key = _ini_key(setting)
        format_name = config_file.format or ""
        separator = ": " if format_name in ("rasi", "css") else " = "
        terminator = ";" if format_name in ("rasi", "css") else ""
        property_line = (
                f"    {key}{separator}{_serialize_scalar(value, 'block')}{terminator}\n"
        )
        if section is None:
                lines.append(property_line)
                return

        sections: list[str] = []
        insert_at = None
        for index, line in enumerate(lines):
                content, _comment = _split_comment(line.rstrip("\r\n"), "block")
                closing = re.match(r"^\s*(}+)", content)
                if closing:
                        if ".".join(sections) == section:
                                insert_at = index
                        for _ in range(min(len(closing.group(1)), len(sections))):
                                sections.pop()
                        continue
                header = re.match(r"^\s*([^{}]+?)\s*\{\s*$", content)
                if header:
                        sections.append(header.group(1).strip())
        if insert_at is not None:
                lines.insert(insert_at, property_line)
                return
        if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += "\n"
        if lines and lines[-1].strip():
                lines.append("\n")
        lines.extend((f"{section} {{\n", property_line, "}\n"))


def _update_lines(
        text: str, config_file: ConfigFile, values: dict[str, Any], syntax: str
) -> str:
        lines = text.splitlines(keepends=True)
        for setting in config_file.settings:
                value = _coerce(values[setting.key], setting)
                matches = _line_matches(lines, setting, syntax)
                if matches:
                        index, match = matches[-1]
                        content = lines[index].rstrip("\r\n")
                        newline = lines[index][len(content) :]
                        raw_value, comment = _split_comment(
                                match.group("value"), syntax
                        )
                        if syntax == "vim" and setting.kind == "boolean":
                                indentation = re.match(r"^\s*", content).group()
                                replacement = indentation + _line_assignment(
                                        setting, value, syntax
                                )
                        else:
                                raw_value, _comment = _split_comment(
                                        match.group("value"), syntax
                                )
                                terminator = (
                                        ";"
                                        if syntax == "block"
                                        and raw_value.rstrip().endswith(";")
                                        else ""
                                )
                                replacement = (
                                        match.group("prefix")
                                        + _serialize_scalar(value, syntax)
                                        + terminator
                                )
                        if comment:
                                if not comment[0].isspace():
                                        replacement += " "
                                replacement += comment
                        lines[index] = replacement + newline
                elif syntax == "ini":
                        _append_ini(lines, setting, value)
                elif syntax == "block":
                        _append_block(lines, config_file, setting, value)
                else:
                        if lines and not lines[-1].endswith(("\n", "\r")):
                                lines[-1] += "\n"
                        lines.append(_line_assignment(setting, value, syntax) + "\n")
        return "".join(lines)


def _update_json(
        document: dict[str, Any], config_file: ConfigFile, values: dict[str, Any]
) -> str:
        for setting in config_file.settings:
                _json_set(document, setting.key, _coerce(values[setting.key], setting))
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def save_setting_values(
        path: Path, config_file: ConfigFile, values: dict[str, Any]
) -> None:
        """Write declared values while leaving unrelated text lines intact."""
        syntax = syntax_for(config_file)
        if syntax is None:
                raise ConfigEditorError(
                        f"no GUI settings adapter is available for {config_file.format or path.suffix}"
                )
        current_values = load_setting_values(path, config_file)
        changed = {
                setting.key: _coerce(values[setting.key], setting)
                for setting in config_file.settings
                if setting.key in values
                and _coerce(values[setting.key], setting) != current_values[setting.key]
        }
        if not changed:
                return
        active_file = ConfigFile(
                path=config_file.path,
                format=config_file.format,
                syntax=config_file.syntax,
                settings=tuple(
                        setting
                        for setting in config_file.settings
                        if setting.key in changed
                ),
        )
        if syntax == "json":
                text = _update_json(_parse_json(path), active_file, changed)
        elif syntax in ("lua", "equals", "space", "ini", "fish", "vim", "block"):
                try:
                        current_text = (
                                path.read_text(encoding="utf-8")
                                if path.exists()
                                else ""
                        )
                except OSError as exc:
                        raise ConfigEditorError(
                                f"cannot read config {path}: {exc}"
                        ) from None
                text = _update_lines(current_text, active_file, changed, syntax)
        else:
                raise ConfigEditorError(f"unsupported GUI settings syntax: {syntax}")
        try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        except OSError as exc:
                raise ConfigEditorError(f"cannot save config {path}: {exc}") from None
