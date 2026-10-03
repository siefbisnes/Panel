"""Minimal GNOME-style desktop window for the Linux System overview."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable

from .backup import backup_root, create_backup
from .compatibility import compatibility_details, declared_compatibility
from .config_editor import (
        ConfigEditorError,
        default_value,
        load_setting_values,
        save_setting_values,
)
from .configuration import config_entries
from .database import default_roots, load_database
from .detector import SystemProbe
from .environment import Environment
from .installer import (
        InstallTarget,
        install_command,
        select_install_target,
        select_installed_target,
        uninstall_command,
)
from .models import AppResult, Application, ConfigFile, ConfigSetting
from .scanner import scan, system_overview

try:  # pragma: no cover - optional runtime dependency
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, GLib, Gtk, Pango
except Exception:  # pragma: no cover - handled in runtime message
        gi = None
        Gio = None
        GLib = None
        Gtk = None
        Pango = None

DISCORD_PROFILE_URL = "https://discord.com/users/896604385440829481"


def _make_nav_button(label: str, active: bool = False) -> Gtk.Widget:
        icons = {
                "Overview": "view-dashboard-symbolic",
                "Applications": "application-x-executable-symbolic",
                "Store": "system-software-install-symbolic",
                "Configuration": "folder-documents-symbolic",
                "Backups": "document-save-symbolic",
                "About": "help-about-symbolic",
        }
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        image = Gtk.Image.new_from_icon_name(icons[label])
        image.set_pixel_size(16)
        text = Gtk.Label(label=label)
        text.set_xalign(0)
        content.append(image)
        content.append(text)
        button = Gtk.Button(child=content)
        button.set_halign(Gtk.Align.FILL)
        button.set_margin_top(2)
        button.set_margin_bottom(2)
        button.set_margin_start(8)
        button.set_margin_end(8)
        button.add_css_class("flat")
        if active:
                button.add_css_class("selected")
        return button


def _make_summary_card(title: str, value: str) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("card")
        card.set_size_request(150, 86)
        card.set_margin_top(4)
        card.set_margin_bottom(4)
        card.set_margin_start(4)
        card.set_margin_end(4)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(14)
        box.set_margin_end(14)
        title_label = Gtk.Label(label=title)
        title_label.set_xalign(0)
        title_label.add_css_class("dim-label")
        value_label = Gtk.Label(label=value)
        value_label.set_xalign(0)
        value_label.set_ellipsize(Pango.EllipsizeMode.END)
        value_label.add_css_class("title-2")
        box.append(title_label)
        box.append(value_label)
        card.append(box)
        return card


def _make_page(title: str, subtitle: str = "") -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        page.set_margin_start(28)
        page.set_margin_end(28)
        heading = Gtk.Label(label=title)
        heading.add_css_class("title-1")
        heading.set_halign(Gtk.Align.START)
        page.append(heading)
        if subtitle:
                detail = Gtk.Label(label=subtitle)
                detail.add_css_class("dim-label")
                detail.set_halign(Gtk.Align.START)
                detail.set_xalign(0)
                detail.set_wrap(True)
                page.append(detail)
        return page


def _scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.set_child(child)
        return scroll


def _append_list_row(
        parent: Gtk.Widget, title: str, subtitle: str, status: str = ""
) -> Gtk.Widget:
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row_box.set_margin_top(10)
        row_box.set_margin_bottom(10)
        row_box.set_margin_start(12)
        row_box.set_margin_end(12)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        name = Gtk.Label(label=title)
        name.set_halign(Gtk.Align.START)
        name.set_xalign(0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        description = Gtk.Label(label=subtitle)
        description.set_halign(Gtk.Align.START)
        description.set_xalign(0)
        description.set_ellipsize(Pango.EllipsizeMode.END)
        description.add_css_class("dim-label")
        labels.append(name)
        labels.append(description)
        labels.set_hexpand(True)
        row_box.append(labels)
        if status:
                state = Gtk.Label(label=status)
                state.add_css_class("dim-label")
                row_box.append(state)
        if isinstance(parent, Gtk.ListBox):
                row = Gtk.ListBoxRow(child=row_box)
                parent.append(row)
                return row
        else:
                parent.append(row_box)
                return row_box


def _backup_lines(env: Environment) -> list[str]:
        lines = []
        for manifest_path in sorted(
                backup_root(env).glob("*/manifest.json"), reverse=True
        ):
                try:
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        lines.append(
                                f"{manifest.get('created_at', manifest_path.parent.name)} · "
                                f"{len(manifest.get('applications', []))} apps · "
                                f"{len(manifest.get('entries', []))} files"
                        )
                except (OSError, json.JSONDecodeError):
                        lines.append(
                                f"Unreadable backup manifest · {manifest_path.name}"
                        )
        return lines


def _setting_control(setting: ConfigSetting, value: object) -> Gtk.Widget:
        if setting.kind == "boolean":
                return Gtk.Switch(active=bool(value))
        if setting.kind in ("integer", "number"):
                minimum = setting.minimum if setting.minimum is not None else -1_000_000
                maximum = setting.maximum if setting.maximum is not None else 1_000_000
                step = setting.step if setting.step is not None else 1
                control = Gtk.SpinButton.new_with_range(minimum, maximum, step)
                control.set_digits(0 if setting.kind == "integer" else 2)
                control.set_value(float(value))
                return control
        if setting.kind == "choice":
                control = Gtk.DropDown.new_from_strings(list(setting.choices))
                selected = (
                        setting.choices.index(value) if value in setting.choices else 0
                )
                control.set_selected(selected)
                return control
        control = Gtk.Entry()
        control.set_text(str(value))
        return control


def _setting_control_value(setting: ConfigSetting, control: Gtk.Widget):
        if setting.kind == "boolean":
                return control.get_active()
        if setting.kind == "integer":
                return control.get_value_as_int()
        if setting.kind == "number":
                return control.get_value()
        if setting.kind == "choice":
                index = control.get_selected()
                return setting.choices[index]
        return control.get_text()


def _setting_group(setting: ConfigSetting) -> str:
        if setting.group:
                return setting.group
        key = setting.key
        groups = (
                (
                        "Typography",
                        (
                                "font_",
                                "bold_font",
                                "italic_font",
                                "box_drawing_scale",
                                "force_ltr",
                                "text_composition",
                        ),
                ),
                ("Cursor", ("cursor_",)),
                (
                        "Scrollback",
                        (
                                "scrollback_",
                                "scrollbar_",
                                "wheel_",
                                "touch_scroll",
                                "momentum_scroll",
                                "pixel_scroll",
                        ),
                ),
                (
                        "Mouse",
                        (
                                "mouse_",
                                "click_interval",
                                "copy_on_select",
                                "detect_urls",
                                "drag_threshold",
                                "focus_follows_mouse",
                                "pointer_shape",
                                "select_by_word",
                                "url_",
                                "show_hyperlink",
                                "underline_hyperlinks",
                                "paste_actions",
                        ),
                ),
                (
                        "Window",
                        (
                                "window_",
                                "single_window_",
                                "remember_window",
                                "placement_strategy",
                                "resize_",
                                "draw_",
                                "hide_window",
                                "inactive_text_alpha",
                        ),
                ),
                ("Tabs", ("tab_", "active_tab_", "inactive_tab_")),
                (
                        "Appearance",
                        (
                                "background",
                                "foreground",
                                "selection_",
                                "active_border",
                                "inactive_border",
                                "bell_border",
                                "dim_opacity",
                                "color",
                        ),
                ),
                (
                        "Bell",
                        (
                                "bell_",
                                "enable_audio_bell",
                                "visual_bell",
                                "window_alert_on_bell",
                                "command_on_bell",
                        ),
                ),
                (
                        "Performance",
                        (
                                "repaint_delay",
                                "input_delay",
                                "sync_to_monitor",
                                "update_check_interval",
                                "auto_reload_config",
                        ),
                ),
                ("Platform", ("macos_", "wayland_", "linux_")),
                (
                        "Integration",
                        (
                                "shell",
                                "editor",
                                "term",
                                "terminfo_",
                                "clipboard_",
                                "allow_",
                                "file_transfer",
                                "forward_stdio",
                                "kitty_mod",
                                "listen_on",
                                "map_timeout",
                        ),
                ),
        )
        return next(
                (
                        group
                        for group, prefixes in groups
                        if any(key.startswith(prefix) for prefix in prefixes)
                ),
                "General",
        )


def _build_config_editor(
        parent: Gtk.Window, app: Application, env: Environment
) -> Gtk.Window:
        editor = Gtk.Window(title=f"{app.name} Configuration", transient_for=parent)
        editor.set_default_size(720, 620)
        header = Gtk.HeaderBar()
        heading = Gtk.Label(label=f"{app.name} Configuration")
        heading.add_css_class("title")
        header.set_title_widget(heading)
        editor.set_titlebar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(24)
        content.set_margin_end(24)
        status = Gtk.Label(label="", xalign=0)
        status.set_wrap(True)
        file_controls: list[tuple[ConfigFile, Path, dict[str, Gtk.Widget]]] = []

        def save(_widget: Gtk.Widget, *_args: object) -> None:
                saved = 0
                try:
                        for config_file, path, controls in file_controls:
                                values = {
                                        setting.key: _setting_control_value(
                                                setting, controls[setting.key]
                                        )
                                        for setting in config_file.settings
                                        if setting.key in controls
                                }
                                save_setting_values(path, config_file, values)
                                saved += 1
                except ConfigEditorError as exc:
                        status.set_text(f"Could not save settings: {exc}")
                        return
                status.set_text(f"Saved settings in {saved} configuration file(s).")

        def open_text(_button: Gtk.Button, path: Path) -> None:
                try:
                        Gio.AppInfo.launch_default_for_uri(
                                path.resolve().as_uri(), None
                        )
                except GLib.Error as exc:
                        status.set_text(f"Could not open text editor: {exc.message}")

        if not app.config_files:
                empty = Gtk.Label(
                        label="No configuration files are declared for this application.",
                        xalign=0,
                )
                empty.add_css_class("dim-label")
                content.append(empty)

        for config_file in app.config_files:
                path = env.expand(config_file.path)
                file_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                file_box.add_css_class("card")
                file_box.set_margin_top(4)
                file_box.set_margin_bottom(4)
                file_box.set_margin_start(4)
                file_box.set_margin_end(4)
                file_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                file_content.set_margin_top(14)
                file_content.set_margin_bottom(14)
                file_content.set_margin_start(16)
                file_content.set_margin_end(16)
                file_heading = Gtk.Label(label=path.name, xalign=0)
                file_heading.add_css_class("heading")
                file_path_label = Gtk.Label(label=env.tilde(str(path)), xalign=0)
                file_path_label.add_css_class("dim-label")
                file_content.append(file_heading)
                file_content.append(file_path_label)
                open_button = Gtk.Button(label="Open as text")
                open_button.set_halign(Gtk.Align.START)
                open_button.set_sensitive(path.is_file())
                open_button.connect("clicked", open_text, path)
                file_content.append(open_button)

                controls: dict[str, Gtk.Widget] = {}
                if config_file.settings:
                        try:
                                values = load_setting_values(path, config_file)
                        except ConfigEditorError as exc:
                                warning = Gtk.Label(
                                        label=f"Structured controls unavailable: {exc}",
                                        xalign=0,
                                )
                                warning.set_wrap(True)
                                warning.add_css_class("error")
                                file_content.append(warning)
                        else:
                                current_group = None
                                for setting in config_file.settings:
                                        group = _setting_group(setting)
                                        if group != current_group:
                                                group_heading = Gtk.Label(
                                                        label=group, xalign=0
                                                )
                                                group_heading.add_css_class("heading")
                                                group_heading.set_margin_top(8)
                                                file_content.append(group_heading)
                                                current_group = group
                                        row = Gtk.Box(
                                                orientation=Gtk.Orientation.HORIZONTAL,
                                                spacing=16,
                                        )
                                        labels = Gtk.Box(
                                                orientation=Gtk.Orientation.VERTICAL,
                                                spacing=3,
                                        )
                                        label = Gtk.Label(label=setting.label, xalign=0)
                                        description = Gtk.Label(
                                                label=setting.description or "",
                                                xalign=0,
                                        )
                                        description.set_wrap(True)
                                        description.add_css_class("dim-label")
                                        labels.append(label)
                                        if setting.description:
                                                labels.append(description)
                                        labels.set_hexpand(True)
                                        control = _setting_control(
                                                setting,
                                                values.get(
                                                        setting.key,
                                                        default_value(setting),
                                                ),
                                        )
                                        control.set_valign(Gtk.Align.CENTER)
                                        change_signal = {
                                                "boolean": "notify::active",
                                                "integer": "value-changed",
                                                "number": "value-changed",
                                                "choice": "notify::selected",
                                                "string": "changed",
                                        }[setting.kind]
                                        control.connect(change_signal, save)
                                        row.append(labels)
                                        row.append(control)
                                        file_content.append(row)
                                        controls[setting.key] = control
                                file_controls.append((config_file, path, controls))
                else:
                        no_settings = Gtk.Label(
                                label="No graphical options are declared for this file.",
                                xalign=0,
                        )
                        no_settings.add_css_class("dim-label")
                        file_content.append(no_settings)
                file_box.append(file_content)
                content.append(file_box)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        save_button = Gtk.Button(label="Save settings")
        save_button.add_css_class("suggested-action")
        save_button.set_sensitive(bool(file_controls))
        save_button.connect("clicked", save)
        footer.append(save_button)
        footer.append(status)
        content.append(footer)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(content)
        editor.set_child(scroll)
        return editor


def _build_window(env: Environment | None = None) -> Gtk.Window:
        window = Gtk.Window()
        window.set_title("Linux System")
        window.set_default_size(1100, 720)
        window.set_size_request(760, 520)

        env = env or Environment()

        header = Gtk.HeaderBar()
        title = Gtk.Label(label="Linux System")
        title.add_css_class("title")
        header.set_title_widget(title)
        refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_button.set_tooltip_text("Refresh system scan")
        refresh_button.add_css_class("flat")
        header.pack_end(refresh_button)
        window.set_titlebar(header)

        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sidebar.add_css_class("navigation-sidebar")
        sidebar.set_size_request(220, -1)
        sidebar.set_margin_top(16)
        sidebar.set_margin_bottom(12)
        sidebar.set_margin_start(4)
        sidebar.set_margin_end(4)
        nav_items = (
                "Overview",
                "Applications",
                "Store",
                "Configuration",
                "Backups",
                "About",
        )
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(100)
        stack.set_hexpand(True)
        stack.set_vexpand(True)
        nav_buttons: dict[str, Gtk.Widget] = {}
        for index, label in enumerate(nav_items):
                button = _make_nav_button(label, active=index == 0)
                button.connect(
                        "clicked",
                        lambda _button, page=label: stack.set_visible_child_name(page),
                )
                sidebar.append(button)
                nav_buttons[label] = button

        sidebar.append(Gtk.Box(vexpand=True))
        scan_status = Gtk.Label(label="Scanning system")
        scan_status.add_css_class("dim-label")
        scan_status.set_margin_start(16)
        scan_status.set_margin_bottom(12)
        scan_status.set_halign(Gtk.Align.START)
        sidebar.append(scan_status)

        def show_page(_stack: Gtk.Stack, _param: object) -> None:
                active_page = stack.get_visible_child_name()
                for label, button in nav_buttons.items():
                        if label == active_page:
                                button.add_css_class("selected")
                        else:
                                button.remove_css_class("selected")

        stack.connect("notify::visible-child-name", show_page)
        install_notice = ""
        app_navigation: dict[str, Callable[[str], None]] = {}

        def build_overview(probe: SystemProbe, results: list[AppResult]) -> Gtk.Widget:
                overview_data = system_overview(probe, results)
                detected = sorted(
                        (item for item in results if item.detected),
                        key=lambda item: item.app.name.casefold(),
                )
                page = _make_page(
                        overview_data.get("Distribution", "Linux"),
                        "Current system scan",
                )
                metrics = Gtk.Grid(column_spacing=12, row_spacing=12)
                metrics.set_halign(Gtk.Align.START)
                values = (
                        ("Detected", str(len(detected))),
                        ("Known applications", str(len(results))),
                        ("Configured", overview_data.get("Configured", "0")),
                        ("Running", overview_data.get("Running", "0")),
                )
                for index, (label, value) in enumerate(values):
                        metrics.attach(
                                _make_summary_card(label, value),
                                index % 2,
                                index // 2,
                                1,
                                1,
                        )
                page.append(metrics)
                system_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                system_box.add_css_class("card")
                system_box.set_margin_top(8)
                system_box.set_margin_bottom(8)
                system_box.set_margin_start(4)
                system_box.set_margin_end(4)
                for label in ("Desktop", "Display server", "Shell"):
                        value = overview_data.get(label)
                        if value:
                                _append_list_row(system_box, label, value)
                page.append(system_box)
                installed = [item for item in detected if item.installed]
                if installed:
                        page.append(
                                Gtk.Label(
                                        label=f"Installed applications ({len(installed)})",
                                        xalign=0,
                                )
                        )
                        detected_box = Gtk.ListBox()
                        detected_box.add_css_class("boxed-list")
                        detected_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
                        overview_rows: dict[Gtk.ListBoxRow, str] = {}
                        for result in installed[:10]:
                                row = _append_list_row(
                                        detected_box,
                                        result.app.name,
                                        result.app.category,
                                        "Installed",
                                )
                                overview_rows[row] = result.app.id

                        def open_overview_app(
                                _list: Gtk.ListBox, row: Gtk.ListBoxRow | None
                        ) -> None:
                                if row is not None and row in overview_rows:
                                        callback = app_navigation.get("select")
                                        if callback:
                                                callback(overview_rows[row])

                        detected_box.connect("row-selected", open_overview_app)
                        page.append(detected_box)
                else:
                        empty = Gtk.Label(
                                label="No applications detected yet.", xalign=0
                        )
                        empty.add_css_class("dim-label")
                        page.append(empty)
                return _scrolled(page)

        def build_applications(
                results: list[AppResult], probe: SystemProbe
        ) -> Gtk.Widget:
                installed_results = sorted(
                        (result for result in results if result.installed),
                        key=lambda result: result.app.name.casefold(),
                )
                page = _make_page(
                        "Applications",
                        f"{len(installed_results)} installed applications · select one for local evidence and documentation.",
                )
                search = Gtk.SearchEntry()
                search.set_placeholder_text("Search by name, category, or ID")
                list_box = Gtk.ListBox()
                list_box.add_css_class("boxed-list")
                list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
                list_box.set_vexpand(True)
                row_results: dict[Gtk.ListBoxRow, AppResult] = {}
                search_terms: dict[Gtk.ListBoxRow, str] = {}
                details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                detail_title = Gtk.Label(label="Select an application", xalign=0)
                detail_title.add_css_class("title-2")
                details.append(detail_title)
                detail_body = Gtk.Label(
                        label="Detection signals and evidence will appear here.",
                        xalign=0,
                )
                detail_body.set_wrap(True)
                detail_body.set_selectable(True)
                details.append(detail_body)
                documentation_heading = Gtk.Label(
                        label="Official documentation", xalign=0
                )
                documentation_heading.add_css_class("heading")
                documentation_box = Gtk.Box(
                        orientation=Gtk.Orientation.VERTICAL, spacing=4
                )
                details.append(documentation_heading)
                details.append(documentation_box)
                selected_result: dict[str, AppResult] = {}
                edit_config_button = Gtk.Button(label="Edit config")
                edit_config_button.add_css_class("suggested-action")
                edit_config_button.set_sensitive(False)
                details.append(edit_config_button)

                def open_selected_config(_button: Gtk.Button) -> None:
                        result = selected_result.get("result")
                        if result is not None and result.app.config_files:
                                _build_config_editor(
                                        window, result.app, probe.env
                                ).present()

                edit_config_button.connect("clicked", open_selected_config)

                def show_result(_list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
                        if row is None or row not in row_results:
                                return
                        result = row_results[row]
                        selected_result["result"] = result
                        edit_config_button.set_sensitive(bool(result.app.config_files))
                        detail_title.set_text(result.app.name)
                        lines = [
                                f"ID: {result.app.id}",
                                f"Category: {result.app.category}",
                                "State: Installed",
                        ]
                        lines.append(f"Confidence: {result.confidence.title()}")
                        if result.version:
                                lines.append(f"Version: {result.version}")
                        lines.append("\nLocal detection evidence")
                        for name, signal in result.signals.items():
                                label = name.replace("_", " ").title()
                                if signal.status.value == "unknown":
                                        lines.append(
                                                f"{label}: Unavailable (source could not be queried)"
                                        )
                                else:
                                        state_label = (
                                                "Detected"
                                                if signal.status.value == "found"
                                                else "No match"
                                        )
                                        lines.append(f"{label}: {state_label}")
                                        if signal.evidence:
                                                lines.append(
                                                        f"  Evidence: {', '.join(signal.evidence)}"
                                                )
                        lines.extend(
                                (
                                        "",
                                        "Compatibility",
                                        *compatibility_details(
                                                result.app.compatibility,
                                                probe.env.variables,
                                        ),
                                )
                        )
                        detail_body.set_text("\n".join(lines))
                        while (link := documentation_box.get_first_child()) is not None:
                                documentation_box.remove(link)
                        documentation_heading.set_visible(
                                bool(result.app.documentation)
                        )
                        for name, url in result.app.documentation.items():
                                link = Gtk.LinkButton(
                                        uri=url, label=name.replace("_", " ").title()
                                )
                                link.set_halign(Gtk.Align.START)
                                link.set_tooltip_text(url)
                                documentation_box.append(link)

                list_box.connect("row-selected", show_result)

                def activate_application(
                        _list: Gtk.ListBox, row: Gtk.ListBoxRow
                ) -> None:
                        result = row_results.get(row)
                        if result is not None and result.app.config_files:
                                _build_config_editor(
                                        window, result.app, probe.env
                                ).present()

                list_box.connect("row-activated", activate_application)
                list_box.set_filter_func(
                        lambda row: search.get_text().casefold() in search_terms[row]
                )
                search.connect(
                        "search-changed", lambda _entry: list_box.invalidate_filter()
                )
                for result in installed_results:
                        row = Gtk.ListBoxRow()
                        label = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                        label.set_margin_top(9)
                        label.set_margin_bottom(9)
                        label.set_margin_start(12)
                        label.set_margin_end(12)
                        name = Gtk.Label(label=result.app.name, xalign=0)
                        subtitle = Gtk.Label(
                                label=f"{result.app.category} · Installed", xalign=0
                        )
                        subtitle.add_css_class("dim-label")
                        label.append(name)
                        label.append(subtitle)
                        row.set_child(label)
                        row_results[row] = result
                        search_terms[row] = (
                                f"{result.app.name} {result.app.id} {result.app.category}".casefold()
                        )
                        list_box.append(row)

                left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                left.set_size_request(260, -1)
                left.append(search)
                left.append(_scrolled(list_box))
                right_page = _make_page("Application details")
                right_page.append(details)
                pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
                pane.set_wide_handle(True)
                pane.set_position(360)
                pane.set_start_child(left)
                pane.set_end_child(_scrolled(right_page))
                page.append(pane)

                def select_application(app_id: str) -> None:
                        stack.set_visible_child_name("Applications")
                        row = next(
                                (
                                        row
                                        for row, result in row_results.items()
                                        if result.app.id == app_id
                                ),
                                None,
                        )
                        if row is not None:
                                list_box.select_row(row)

                app_navigation["select"] = select_application
                if installed_results:
                        list_box.select_row(list_box.get_row_at_index(0))
                else:
                        detail_title.set_text("No installed applications")
                        detail_body.set_text(
                                "The scanner did not find any installed applications in the loaded definitions."
                        )
                        documentation_heading.set_visible(False)
                        edit_config_button.set_sensitive(False)
                return page

        def build_configuration(results: list[AppResult]) -> Gtk.Widget:
                entries = [
                        (result, entry)
                        for result in results
                        if result.installed
                        for entry in config_entries(result.app, env)
                ]
                present_count = sum(entry.exists for _, entry in entries)
                page = _make_page(
                        "Configuration",
                        f"{present_count} of {len(entries)} declared locations for installed applications currently exist. Select an application to view its details.",
                )
                listing = Gtk.ListBox()
                listing.add_css_class("boxed-list")
                listing.set_selection_mode(Gtk.SelectionMode.SINGLE)
                row_app_ids: dict[Gtk.Widget, str] = {}
                for result, entry in entries:
                        row = _append_list_row(
                                listing,
                                result.app.name,
                                env.tilde(str(entry.path)),
                                "Present" if entry.exists else "Missing",
                        )
                        row_app_ids[row] = result.app.id

                def open_configuration_app(
                        _list: Gtk.ListBox, row: Gtk.ListBoxRow | None
                ) -> None:
                        if row is not None and row in row_app_ids:
                                callback = app_navigation.get("select")
                                if callback:
                                        callback(row_app_ids[row])

                listing.connect("row-selected", open_configuration_app)
                if not entries:
                        empty = Gtk.Label(
                                label="No configuration paths are declared for installed applications.",
                                xalign=0,
                        )
                        empty.add_css_class("dim-label")
                        page.append(empty)
                else:
                        page.append(listing)
                return _scrolled(page)

        def build_store(results: list[AppResult], probe: SystemProbe) -> Gtk.Widget:
                nonlocal install_notice
                store_items = []
                installable_count = 0
                for result in results:
                        installed_target = select_installed_target(
                                result.app.packages,
                                probe.package_key,
                                native_packages=probe.native_packages,
                                flatpak_packages=probe.flatpak_packages,
                        )
                        install_target = select_install_target(
                                result.app.packages,
                                probe.package_key,
                                native_available=probe.native_packages is not None,
                                flatpak_available=probe.flatpak_packages is not None,
                        )
                        if install_target is not None:
                                installable_count += 1
                        if installed_target is not None:
                                store_items.append(
                                        (result, installed_target, "uninstall")
                                )
                        elif result.installed:
                                store_items.append((result, None, "external"))
                        elif install_target is not None:
                                store_items.append((result, install_target, "install"))

                distro = probe.os_release.pretty_name
                page = _make_page(
                        "Store",
                        f"{installable_count} of {len(results)} definitions have install packages for {distro} or Flatpak.",
                )
                search = Gtk.SearchEntry()
                search.set_placeholder_text("Search installable applications")
                page.append(search)
                feedback = Gtk.Label(label=install_notice, xalign=0)
                feedback.set_wrap(True)
                page.append(feedback)
                listing = Gtk.ListBox()
                listing.add_css_class("boxed-list")
                listing.set_selection_mode(Gtk.SelectionMode.NONE)
                search_terms: dict[Gtk.ListBoxRow, str] = {}
                listing.set_filter_func(
                        lambda row: search.get_text().casefold() in search_terms[row]
                )
                search.connect(
                        "search-changed", lambda _entry: listing.invalidate_filter()
                )
                if not store_items:
                        empty = Gtk.Label(
                                label="No installed or installable applications are available for this distribution.",
                                xalign=0,
                        )
                        empty.set_wrap(True)
                        empty.add_css_class("dim-label")
                        page.append(empty)
                        return _scrolled(page)

                def start_package_action(
                        button: Gtk.Button,
                        app_name: str,
                        target: InstallTarget,
                        action: str,
                ) -> None:
                        use_polkit = os.geteuid() != 0 and target.source != "flatpak"
                        command = (
                                install_command(target, use_polkit=use_polkit)
                                if action == "install"
                                else uninstall_command(target, use_polkit=use_polkit)
                        )
                        verb = "install" if action == "install" else "remove"
                        button.set_sensitive(False)
                        button.set_label(
                                "Installing…" if action == "install" else "Removing…"
                        )
                        feedback.set_text(
                                f"Waiting for authentication and package manager to {verb} {app_name}…"
                        )
                        try:
                                process = Gio.Subprocess.new(
                                        command,
                                        Gio.SubprocessFlags.STDOUT_PIPE
                                        | Gio.SubprocessFlags.STDERR_MERGE,
                                )
                        except GLib.Error as exc:
                                button.set_sensitive(True)
                                button.set_label("Try again")
                                feedback.set_text(
                                        f"Could not start installer: {exc.message}"
                                )
                                return

                        def finished(child_process, async_result, _user_data) -> None:
                                nonlocal install_notice
                                try:
                                        _communicated, output, _error = (
                                                child_process.communicate_utf8_finish(
                                                        async_result
                                                )
                                        )
                                except GLib.Error as exc:
                                        button.set_sensitive(True)
                                        button.set_label(
                                                "Install"
                                                if action == "install"
                                                else "Uninstall"
                                        )
                                        feedback.set_text(
                                                f"Installer failed: {exc.message}"
                                        )
                                        return
                                if child_process.get_successful():
                                        result = (
                                                "Installed"
                                                if action == "install"
                                                else "Removed"
                                        )
                                        install_notice = f"{result} {app_name}. The system scan has been refreshed."
                                        rebuild_pages("Store")
                                        return
                                button.set_sensitive(True)
                                button.set_label(
                                        "Install"
                                        if action == "install"
                                        else "Uninstall"
                                )
                                details = (output or "").strip()
                                feedback.set_text(
                                        f"Could not {verb} {app_name}.\n{details[-1200:] or 'The package manager returned an error.'}"
                                )

                        process.communicate_utf8_async(None, None, finished, None)

                def confirm_package_action(
                        button: Gtk.Button,
                        app_name: str,
                        target: InstallTarget,
                        action: str,
                ) -> None:
                        installing = action == "install"
                        verb = "Install" if installing else "Remove"
                        dialog = Gtk.Dialog(
                                title=f"{verb} {app_name}?",
                                transient_for=window,
                                modal=True,
                        )
                        source_name = (
                                "Flatpak"
                                if target.source == "flatpak"
                                else f"{target.source.title()} package"
                        )
                        message = Gtk.Label(
                                label=(
                                        f"This will {verb.lower()} {target.package} from the {source_name} source."
                                        + (
                                                " User data and configuration are left in place."
                                                if not installing
                                                else ""
                                        )
                                        + (
                                                " The system will request administrator authentication."
                                                if target.source != "flatpak"
                                                and os.geteuid() != 0
                                                else ""
                                        )
                                ),
                                wrap=True,
                        )
                        message.set_margin_top(18)
                        message.set_margin_bottom(18)
                        message.set_margin_start(18)
                        message.set_margin_end(18)
                        dialog.get_content_area().append(message)
                        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
                        dialog.add_button(verb, Gtk.ResponseType.ACCEPT)

                        def response(current_dialog, response_id: int) -> None:
                                current_dialog.close()
                                if response_id == Gtk.ResponseType.ACCEPT:
                                        start_package_action(
                                                button, app_name, target, action
                                        )

                        dialog.connect("response", response)
                        dialog.present()

                for result, target, action in store_items:
                        row = Gtk.ListBoxRow()
                        row_box = Gtk.Box(
                                orientation=Gtk.Orientation.HORIZONTAL, spacing=12
                        )
                        row_box.set_margin_top(8)
                        row_box.set_margin_bottom(8)
                        row_box.set_margin_start(12)
                        row_box.set_margin_end(12)
                        labels = Gtk.Box(
                                orientation=Gtk.Orientation.VERTICAL, spacing=4
                        )
                        name = Gtk.Label(label=result.app.name, xalign=0)
                        package_source = (
                                "Installed outside package manager"
                                if target is None
                                else "Flatpak"
                                if target.source == "flatpak"
                                else target.source.title()
                        )
                        package_detail = Gtk.Label(
                                label=(
                                        f"{result.app.category.title()} · {package_source}"
                                        if target is None
                                        else f"{result.app.category.title()} · {package_source}: {target.package}"
                                )
                                + (
                                        " · "
                                        + ", ".join(
                                                declared_compatibility(
                                                        result.app.compatibility
                                                )
                                        )
                                        if result.app.compatibility
                                        else ""
                                ),
                                xalign=0,
                        )
                        package_detail.add_css_class("dim-label")
                        labels.append(name)
                        labels.append(package_detail)
                        labels.set_hexpand(True)
                        row_box.append(labels)
                        button_label = {
                                "install": "Install",
                                "uninstall": "Uninstall",
                                "external": "Installed",
                        }[action]
                        button = Gtk.Button(label=button_label)
                        button.set_sensitive(action != "external")
                        if action == "install":
                                button.add_css_class("suggested-action")
                        elif action == "uninstall":
                                button.add_css_class("destructive-action")
                        if target is not None:
                                button.connect(
                                        "clicked",
                                        confirm_package_action,
                                        result.app.name,
                                        target,
                                        action,
                                )
                        row_box.append(button)
                        row.set_child(row_box)
                        target_name = target.package if target is not None else ""
                        search_terms[row] = (
                                f"{result.app.name} {result.app.id} {result.app.category} {target_name}".casefold()
                        )
                        listing.append(row)
                page.append(listing)
                return _scrolled(page)

        def build_backups(results: list[AppResult]) -> Gtk.Widget:
                configured_apps = [
                        result.app for result in results if result.configured
                ]
                page = _make_page(
                        "Backups",
                        "Snapshots of the configuration files found on this system.",
                )
                action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                app_count = len(configured_apps)
                app_label = "application" if app_count == 1 else "applications"
                create_button = Gtk.Button(
                        label=f"Back up {app_count} configured {app_label}"
                )
                create_button.add_css_class("suggested-action")
                create_button.set_sensitive(bool(configured_apps))
                action_row.append(create_button)
                page.append(action_row)
                feedback = Gtk.Label(label="", xalign=0)
                feedback.set_wrap(True)
                page.append(feedback)

                included_title = Gtk.Label(label="Apps ready to back up", xalign=0)
                included_title.add_css_class("heading")
                page.append(included_title)
                if configured_apps:
                        included_apps = Gtk.ListBox()
                        included_apps.add_css_class("boxed-list")
                        included_apps.set_selection_mode(Gtk.SelectionMode.NONE)
                        for app in configured_apps:
                                existing_paths = [
                                        entry
                                        for entry in config_entries(app, env)
                                        if entry.exists
                                ]
                                path_count = len(existing_paths)
                                path_label = (
                                        "configuration path"
                                        if path_count == 1
                                        else "configuration paths"
                                )
                                _append_list_row(
                                        included_apps,
                                        app.name,
                                        f"{path_count} existing {path_label}",
                                )
                        page.append(included_apps)
                else:
                        no_config = Gtk.Label(
                                label=(
                                        "No supported application configuration paths were found. "
                                        "The backup action is available once a declared config path exists."
                                ),
                                xalign=0,
                        )
                        no_config.set_wrap(True)
                        no_config.add_css_class("dim-label")
                        page.append(no_config)

                history_title = Gtk.Label(label="Backup history", xalign=0)
                history_title.add_css_class("heading")
                page.append(history_title)
                history = Gtk.ListBox()
                history.add_css_class("boxed-list")
                history.set_selection_mode(Gtk.SelectionMode.NONE)
                history_lines = _backup_lines(env)
                for line in history_lines:
                        _append_list_row(history, line, str(backup_root(env)))
                empty = Gtk.Label(
                        label="No backups yet. Create a snapshot above to see it here.",
                        xalign=0,
                )
                empty.add_css_class("dim-label")
                empty.set_visible(not history_lines)
                page.append(empty)
                page.append(_scrolled(history))

                def make_backup(_button: Gtk.Button) -> None:
                        try:
                                created = create_backup(env, configured_apps)
                        except OSError as exc:
                                feedback.set_text(f"Backup failed: {exc}")
                                return
                        feedback.set_text(f"Backup created at {created}")
                        _append_list_row(history, created.name, str(backup_root(env)))
                        empty.set_visible(False)

                create_button.connect("clicked", make_backup)
                return _scrolled(page)

        def build_about() -> Gtk.Widget:
                page = _make_page(
                        "About Linux System",
                        "A community project from Egypt, still early and growing.",
                )
                story = Gtk.Label(
                        label=(
                                "I work at a local coding company in Egypt, where I see how much "
                                "ambition there is across the Linux community. I believe people "
                                "from different distros and projects can meet, share what they "
                                "know, and build something real together. Linux System is my "
                                "small starting point for that collaboration."
                        ),
                        xalign=0,
                )
                story.set_wrap(True)
                page.append(story)

                profile_title = Gtk.Label(label="Find me on Discord", xalign=0)
                profile_title.add_css_class("heading")
                profile_name = Gtk.Label(label="altftheoriginal", xalign=0)
                profile_name.add_css_class("dim-label")
                page.append(profile_title)
                page.append(profile_name)

                profile_status = Gtk.Label(label="", xalign=0)
                profile_status.set_wrap(True)
                open_profile = Gtk.Button(label="Open Discord profile")
                open_profile.set_halign(Gtk.Align.START)

                def launch_profile(_button: Gtk.Button) -> None:
                        try:
                                Gio.AppInfo.launch_default_for_uri(
                                        DISCORD_PROFILE_URL, None
                                )
                        except GLib.Error as exc:
                                profile_status.set_text(
                                        f"Could not open Discord profile: {exc.message}"
                                )

                open_profile.connect("clicked", launch_profile)
                page.append(open_profile)
                page.append(profile_status)
                return _scrolled(page)

        def rebuild_pages(visible_page: str = "Overview") -> None:
                env_local = env
                database = load_database(default_roots(env_local))
                probe = SystemProbe(env_local)
                results = scan(database.apps.values(), probe)
                scan_status.set_text(
                        f"{sum(result.detected for result in results)} detected · {len(results)} known"
                )
                while (child := stack.get_first_child()) is not None:
                        stack.remove(child)
                stack.add_named(build_overview(probe, results), "Overview")
                stack.add_named(build_applications(results, probe), "Applications")
                stack.add_named(build_store(results, probe), "Store")
                stack.add_named(build_configuration(results), "Configuration")
                stack.add_named(build_backups(results), "Backups")
                stack.add_named(build_about(), "About")
                stack.set_visible_child_name(
                        visible_page if visible_page in nav_items else "Overview"
                )

        def refresh_scan(_button: Gtk.Button) -> None:
                refresh_button.set_sensitive(False)
                try:
                        rebuild_pages(stack.get_visible_child_name() or "Overview")
                finally:
                        refresh_button.set_sensitive(True)

        refresh_button.connect("clicked", refresh_scan)
        rebuild_pages()

        main_box.append(sidebar)
        main_box.append(stack)
        window.set_child(main_box)
        return window


def launch_gui(env: Environment | None = None) -> int:
        """Launch the GNOME-style desktop overview; returns 1 when GTK is unavailable."""
        if Gtk is None:
                print(
                        "error: GTK/GNOME support is not installed. Install the GTK 4 / PyGObject stack first.",
                        file=sys.stderr,
                )
                print(
                        "hint: Fedora: sudo dnf install gtk4 gobject-introspection-devel python3-gobject",
                        file=sys.stderr,
                )
                return 1

        print("Launching GTK/GNOME overview window...")
        app = Gtk.Application(application_id="org.linux_system.Overview")

        def activate(application: Gtk.Application) -> None:
                window = _build_window(env)
                window.set_application(application)
                window.present()

        app.connect("activate", activate)
        try:
                return app.run()
        except KeyboardInterrupt:
                print("Window closed.")
                return 0
