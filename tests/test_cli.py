import json
import os
import shutil
import subprocess

import pytest

from linux_system import gui as gui_module
from linux_system.cli import build_parser, main
from linux_system.database import (
        community_root,
        load_database,
        default_roots,
        update_community_db,
        DatabaseUpdateError,
)


@pytest.fixture
def system(fake):
        fake.set_packages("fedora", "rofi\t2.0.0\nbash\t5.2\n")
        fake.add_executable("rofi")
        fake.add_config(".config/rofi/config.rasi")
        return fake


def run(system, capsys, *args):
        code = main(["--no-color", *args], env=system.env)
        captured = capsys.readouterr()
        return code, captured.out, captured.err


def test_default_command_lists_detected(system, capsys):
        code, out, _ = run(system, capsys)
        assert code == 0 and "✓ Rofi" in out and "1 application detected." in out


def test_parser_uses_panel_name():
        assert build_parser().prog == "panel"


def test_info(system, capsys):
        code, out, _ = run(system, capsys, "info", "Rofi")
        assert code == 0 and "2.0.0" in out and "High" in out and "config.rasi" in out


def test_info_json(system, capsys):
        _, out, _ = run(system, capsys, "info", "rofi", "--json")
        data = json.loads(out)
        assert data["installed"] and data["configured"] and data["confidence"] == "high"


def test_unknown_app_suggests_close_match(system, capsys):
        code, _, err = run(system, capsys, "info", "rofii")
        assert code == 2 and "rofi" in err


def test_list_all_includes_undetected(system, capsys):
        _, out, _ = run(system, capsys, "list", "--all")
        assert "✗ Waybar" in out and "not detected" in out


def test_scan_json(system, capsys):
        _, out, _ = run(system, capsys, "scan", "--json")
        data = json.loads(out)
        assert data["overview"]["Distribution"] == "Fedora Linux 44"
        assert [a["id"] for a in data["applications"]] == ["rofi"]


def test_config_listing(system, capsys):
        _, out, _ = run(system, capsys, "config", "rofi")
        assert "config.rasi" in out and "[rasi]" in out


def test_config_edit_opens_first_existing_file(system, capsys, tmp_path):
        marker = tmp_path / "opened"
        editor = tmp_path / "editor.sh"
        editor.write_text(f'#!/bin/sh\necho "$1" > {marker}\n')
        editor.chmod(0o755)
        system.variables["EDITOR"] = str(editor)
        assert run(system, capsys, "config", "rofi", "--edit")[0] == 0
        assert marker.read_text().strip() == str(
                system.home / ".config/rofi/config.rasi"
        )


def test_config_edit_without_file_fails(system, capsys):
        assert run(system, capsys, "config", "waybar", "--edit")[0] == 1


def test_validate(system, capsys, tmp_path):
        assert run(system, capsys, "validate")[0] == 0
        bad = tmp_path / "bad.yaml"
        bad.write_text("id: bad\n")
        code, _, err = run(system, capsys, "validate", str(bad))
        assert code == 1 and "problem(s) found" in err


def test_doctor_reports_definition_problems(system, capsys, tmp_path):
        (tmp_path / "extra" / "applications").mkdir(parents=True)
        (tmp_path / "extra" / "applications" / "bad.yaml").write_text("id: bad\n")
        code, out, _ = run(system, capsys, "--db", str(tmp_path / "extra"), "doctor")
        assert code == 1 and "bad.yaml" in out


def test_user_definitions_extend_the_database(system, capsys, tmp_path):
        directory = system.home / ".config" / "panel" / "database" / "applications"
        directory.mkdir(parents=True)
        (directory / "mytool.yaml").write_text(
                "schema_version: 1\nid: mytool\nname: MyTool\ncategory: tool\ndetection:\n  executables: [mytool]\n"
        )
        system.add_executable("mytool")
        assert "MyTool" in run(system, capsys, "list")[1]


def test_backup_creates_a_manifest_and_copies_config(system, capsys):
        code, out, _ = run(system, capsys, "backup", "rofi")
        assert code == 0 and "Backup created" in out
        backups = sorted((system.env.data_home / "panel" / "backups").glob("*"))
        assert backups
        manifest = json.loads((backups[-1] / "manifest.json").read_text())
        assert manifest["applications"] == ["rofi"]
        assert any(
                path.name == "config.rasi"
                for path in (backups[-1] / "files").rglob("config.rasi")
        )


def test_restore_requires_explicit_force_for_existing_files(system, capsys):
        assert run(system, capsys, "backup", "rofi")[0] == 0
        backup_dir = sorted((system.env.data_home / "panel" / "backups").glob("*"))[-1]
        target = system.home / ".config" / "rofi" / "config.rasi"
        target.write_text("new")
        code, _, err = run(system, capsys, "restore", str(backup_dir))
        assert code == 1 and "overwrite" in err.lower()
        assert run(system, capsys, "restore", str(backup_dir), "--force")[0] == 0
        assert target.read_text() == "x"


def test_submit_writes_a_reviewable_definition(system, capsys):
        code, out, _ = run(
                system,
                capsys,
                "submit",
                "--id",
                "ghostty",
                "--name",
                "Ghostty",
                "--category",
                "terminal",
                "--executable",
                "ghostty",
                "--config",
                "~/.config/ghostty",
                "--package",
                "ghostty",
                "--docs",
                "https://ghostty.org",
        )
        assert code == 0 and "Submission created" in out
        submission = sorted(
                (system.env.data_home / "panel" / "submissions").glob("*.yaml")
        )[-1]
        assert "id: ghostty" in submission.read_text()
        assert run(system, capsys, "validate", str(submission))[0] == 0


def test_community_reports_pending_submissions(system, capsys):
        run(
                system,
                capsys,
                "submit",
                "--id",
                "ghostty",
                "--name",
                "Ghostty",
                "--category",
                "terminal",
                "--executable",
                "ghostty",
                "--config",
                "~/.config/ghostty",
                "--package",
                "ghostty",
                "--docs",
                "https://ghostty.org",
        )
        code, out, _ = run(system, capsys, "community")
        assert code == 0 and "pending submissions" in out.lower()


def test_gui_command_is_available(system, monkeypatch):
        calls = []
        env = system.env
        monkeypatch.setattr(
                "linux_system.cli.launch_gui", lambda env: calls.append(env) or 0
        )
        assert main(["gui"], env=env) == 0
        assert calls == [env]


@pytest.mark.skipif(gui_module.Gtk is None, reason="GTK 4 is not installed")
def test_gui_sidebar_navigation(system):
        if not gui_module.Gtk.init_check():
                pytest.skip("GTK display is unavailable")
        window = gui_module._build_window(system.env)
        try:
                layout = window.get_child()
                sidebar = layout.get_first_child()
                stack = sidebar.get_next_sibling()
                visited = []
                child = sidebar.get_first_child()
                while child is not None:
                        if isinstance(child, gui_module.Gtk.Button):
                                label = child.get_child().get_last_child().get_text()
                                child.emit("clicked")
                                assert stack.get_visible_child_name() == label
                                visited.append(label)
                        child = child.get_next_sibling()
        finally:
                window.destroy()
        assert visited == [
                "Overview",
                "Applications",
                "Store",
                "Configuration",
                "About",
        ]
        assert stack.get_child_by_name("Backups") is None
        about_page = stack.get_child_by_name("About")
        assert about_page is not None
        pending = [about_page]
        labels = []
        buttons = []
        while pending:
                widget = pending.pop()
                if isinstance(widget, gui_module.Gtk.Label):
                        labels.append(widget.get_text())
                if isinstance(widget, gui_module.Gtk.Button):
                        buttons.append(widget.get_label())
                child = widget.get_first_child()
                while child is not None:
                        pending.append(child)
                        child = child.get_next_sibling()
        assert "altftheoriginal" in labels
        assert "Open Discord profile" in buttons
        assert (
                gui_module.DISCORD_PROFILE_URL
                == "https://discord.com/users/896604385440829481"
        )


@pytest.mark.skipif(gui_module.Gtk is None, reason="GTK 4 is not installed")
def test_application_details_show_hyprland_compatibility(system):
        if not gui_module.Gtk.init_check():
                pytest.skip("GTK display is unavailable")
        system.set_packages("fedora", "rofi\t2.0.0\nwaybar\t0.11.0\n")
        system.add_executable("waybar")
        window = gui_module._build_window(system.env)

        def descendants(root):
                pending = [root]
                while pending:
                        widget = pending.pop()
                        yield widget
                        child = widget.get_first_child()
                        while child is not None:
                                pending.append(child)
                                child = child.get_next_sibling()

        try:
                stack = window.get_child().get_last_child()
                applications = stack.get_child_by_name("Applications")
                app_list = next(
                        item
                        for item in descendants(applications)
                        if isinstance(item, gui_module.Gtk.ListBox)
                )
                waybar_row = next(
                        row
                        for row in descendants(app_list)
                        if isinstance(row, gui_module.Gtk.ListBoxRow)
                        and row.get_child().get_first_child().get_text() == "Waybar"
                )
                app_list.select_row(waybar_row)
                app_details = [
                        item.get_text()
                        for item in descendants(applications)
                        if isinstance(item, gui_module.Gtk.Label)
                ]
                assert any(
                        "Hyprland desktop environment: Supported" in text
                        for text in app_details
                )

                store = stack.get_child_by_name("Store")
                store_list = next(
                        item
                        for item in descendants(store)
                        if isinstance(item, gui_module.Gtk.ListBox)
                )
                store_row = next(
                        row
                        for row in descendants(store_list)
                        if isinstance(row, gui_module.Gtk.ListBoxRow)
                        and row.get_child()
                        .get_first_child()
                        .get_first_child()
                        .get_text()
                        == "Waybar"
                )
                store_subtitle = (
                        store_row.get_child()
                        .get_first_child()
                        .get_last_child()
                        .get_text()
                )
                assert "Hyprland: Supported" in store_subtitle
        finally:
                window.destroy()


@pytest.mark.skipif(gui_module.Gtk is None, reason="GTK 4 is not installed")
def test_config_editor_builds_and_saves_metadata_controls(system):
        if not gui_module.Gtk.init_check():
                pytest.skip("GTK display is unavailable")
        env = system.env
        app = load_database(default_roots(env)).apps["neovim"]
        parent = gui_module.Gtk.Window()
        editor = gui_module._build_config_editor(parent, app, env)
        try:
                pending = [editor]
                switches = {}
                save_button = None
                while pending:
                        widget = pending.pop()
                        if isinstance(widget, gui_module.Gtk.Switch):
                                label = (
                                        widget.get_parent()
                                        .get_first_child()
                                        .get_first_child()
                                        .get_text()
                                )
                                switches[label] = widget
                        if (
                                isinstance(widget, gui_module.Gtk.Button)
                                and widget.get_label() == "Save settings"
                        ):
                                save_button = widget
                        child = widget.get_first_child()
                        while child is not None:
                                pending.append(child)
                                child = child.get_next_sibling()
                assert set(switches) == {
                        "Show line numbers",
                        "Relative line numbers",
                        "Use spaces for indentation",
                        "Wrap long lines",
                        "Ignore case in search",
                        "Smart case in search",
                        "True color support",
                }
                switches["Show line numbers"].set_active(False)
                switches["Relative line numbers"].set_active(True)
                saved = (env.home / ".config/nvim/init.lua").read_text()
                assert "vim.opt.number = false" in saved
                assert "vim.opt.relativenumber = true" in saved
                assert save_button is not None
                save_button.emit("clicked")
                saved = (env.home / ".config/nvim/init.lua").read_text()
                assert "vim.opt.number = false" in saved
                assert "vim.opt.relativenumber = true" in saved
        finally:
                editor.destroy()
                parent.destroy()


@pytest.mark.skipif(gui_module.Gtk is None, reason="GTK 4 is not installed")
def test_selected_application_opens_its_config_editor(system):
        if not gui_module.Gtk.init_check():
                pytest.skip("GTK display is unavailable")
        window = gui_module._build_window(system.env)
        editor = None

        def descendants(root):
                pending = [root]
                while pending:
                        widget = pending.pop()
                        yield widget
                        child = widget.get_first_child()
                        while child is not None:
                                pending.append(child)
                                child = child.get_next_sibling()

        try:
                stack = window.get_child().get_last_child()
                applications = stack.get_child_by_name("Applications")
                app_list = next(
                        item
                        for item in descendants(applications)
                        if isinstance(item, gui_module.Gtk.ListBox)
                )
                row = next(
                        row
                        for row in descendants(app_list)
                        if isinstance(row, gui_module.Gtk.ListBoxRow)
                        and row.get_child().get_first_child().get_text() == "Rofi"
                )
                app_list.select_row(row)
                edit_button = next(
                        item
                        for item in descendants(applications)
                        if isinstance(item, gui_module.Gtk.Button)
                        and item.get_label() == "Edit config"
                )
                assert edit_button.get_sensitive()
                edit_button.emit("clicked")
                windows = gui_module.Gtk.Window.get_toplevels()
                editor = next(
                        windows.get_item(index)
                        for index in range(windows.get_n_items())
                        if windows.get_item(index).get_title() == "Rofi Configuration"
                )
                assert editor is not None
        finally:
                if editor is not None:
                        editor.destroy()
                window.destroy()


@pytest.mark.skipif(gui_module.Gtk is None, reason="GTK 4 is not installed")
def test_configuration_row_opens_installed_app_details(system):
        if not gui_module.Gtk.init_check():
                pytest.skip("GTK display is unavailable")
        window = gui_module._build_window(system.env)

        def descendants(root):
                pending = [root]
                while pending:
                        widget = pending.pop()
                        yield widget
                        child = widget.get_first_child()
                        while child is not None:
                                pending.append(child)
                                child = child.get_next_sibling()

        try:
                stack = window.get_child().get_last_child()
                configuration = stack.get_child_by_name("Configuration")
                pending = [configuration]
                listing = None
                scrollers = 0
                while pending:
                        widget = pending.pop()
                        if isinstance(widget, gui_module.Gtk.ScrolledWindow):
                                scrollers += 1
                        if isinstance(widget, gui_module.Gtk.ListBox):
                                listing = widget
                        child = widget.get_first_child()
                        while child is not None:
                                pending.append(child)
                                child = child.get_next_sibling()
                assert listing is not None and scrollers == 1
                row = listing.get_first_child()
                while row is not None:
                        row_name = (
                                row.get_child()
                                .get_first_child()
                                .get_first_child()
                                .get_text()
                        )
                        if row_name == "Rofi":
                                break
                        row = row.get_next_sibling()
                assert row is not None
                listing.select_row(row)
                assert stack.get_visible_child_name() == "Applications"
                applications = stack.get_child_by_name("Applications")
                selected_name = next(
                        item.get_text()
                        for item in descendants(applications)
                        if isinstance(item, gui_module.Gtk.Label)
                        and "title-2" in item.get_css_classes()
                )
                assert selected_name == "Rofi"
                app_rows = [
                        item
                        for item in descendants(applications)
                        if isinstance(item, gui_module.Gtk.ListBoxRow)
                ]
                app_names = [
                        row.get_child().get_first_child().get_text() for row in app_rows
                ]
                assert app_names == ["Rofi"]
                assert any(
                        isinstance(item, gui_module.Gtk.LinkButton)
                        for item in descendants(applications)
                )
                assert any(
                        isinstance(item, gui_module.Gtk.Button)
                        and item.get_label() == "Edit config"
                        for item in descendants(applications)
                )
        finally:
                window.destroy()


@pytest.mark.skipif(gui_module.Gtk is None, reason="GTK 4 is not installed")
def test_kitty_editor_builds_full_form_without_writing_defaults(system):
        if not gui_module.Gtk.init_check():
                pytest.skip("GTK display is unavailable")
        env = system.env
        app = load_database(default_roots(env)).apps["kitty"]
        config_path = env.expand(app.config_files[0].path)
        parent = gui_module.Gtk.Window()
        editor = gui_module._build_config_editor(parent, app, env)
        try:
                pending = [editor]
                controls = 0
                save_button = None
                while pending:
                        widget = pending.pop()
                        if isinstance(
                                widget,
                                (
                                        gui_module.Gtk.Switch,
                                        gui_module.Gtk.SpinButton,
                                        gui_module.Gtk.DropDown,
                                        gui_module.Gtk.Entry,
                                ),
                        ):
                                controls += 1
                        if (
                                isinstance(widget, gui_module.Gtk.Button)
                                and widget.get_label() == "Save settings"
                        ):
                                save_button = widget
                        child = widget.get_first_child()
                        while child is not None:
                                pending.append(child)
                                child = child.get_next_sibling()
                assert controls == len(app.config_files[0].settings)
                assert save_button is not None and save_button.get_sensitive()
                save_button.emit("clicked")
                assert not config_path.exists()
        finally:
                editor.destroy()
                parent.destroy()


@pytest.mark.skipif(gui_module.Gtk is None, reason="GTK 4 is not installed")
def test_store_install_requires_confirmation(system):
        if not gui_module.Gtk.init_check():
                pytest.skip("GTK display is unavailable")
        window = gui_module._build_window(system.env)
        try:
                stack = window.get_child().get_last_child()
                store = stack.get_child_by_name("Store")
                pending = [store]
                install_button = None
                while pending:
                        widget = pending.pop()
                        if (
                                isinstance(widget, gui_module.Gtk.Button)
                                and widget.get_label() == "Install"
                        ):
                                install_button = widget
                                break
                        child = widget.get_first_child()
                        while child is not None:
                                pending.append(child)
                                child = child.get_next_sibling()
                assert install_button is not None
                install_button.emit("clicked")
                dialogs = gui_module.Gtk.Window.get_toplevels()
                confirmation = next(
                        (
                                dialogs.get_item(index)
                                for index in range(dialogs.get_n_items())
                                if isinstance(
                                        dialogs.get_item(index), gui_module.Gtk.Dialog
                                )
                                and dialogs.get_item(index).get_transient_for()
                                is window
                        ),
                        None,
                )
                assert confirmation is not None
                confirmation.emit("response", gui_module.Gtk.ResponseType.CANCEL)
                assert install_button.get_label() == "Install"
        finally:
                window.destroy()


@pytest.mark.skipif(gui_module.Gtk is None, reason="GTK 4 is not installed")
def test_store_search_filters_and_uses_one_scroller(system):
        if not gui_module.Gtk.init_check():
                pytest.skip("GTK display is unavailable")
        window = gui_module._build_window(system.env)
        try:
                stack = window.get_child().get_last_child()
                store = stack.get_child_by_name("Store")
                pending = [store]
                search = listing = None
                scroller_count = 0
                while pending:
                        widget = pending.pop()
                        if isinstance(widget, gui_module.Gtk.ScrolledWindow):
                                scroller_count += 1
                        elif isinstance(widget, gui_module.Gtk.SearchEntry):
                                search = widget
                        elif isinstance(widget, gui_module.Gtk.ListBox):
                                listing = widget
                        child = widget.get_first_child()
                        while child is not None:
                                pending.append(child)
                                child = child.get_next_sibling()
                assert search is not None and listing is not None
                assert scroller_count == 1
                search.set_text("kitty")
                search.emit("search-changed")
                visible_names = []
                row = listing.get_first_child()
                while row is not None:
                        if row.get_child_visible():
                                visible_names.append(
                                        row.get_child()
                                        .get_first_child()
                                        .get_first_child()
                                        .get_text()
                                )
                        row = row.get_next_sibling()
                assert visible_names == ["Kitty"]
        finally:
                window.destroy()


@pytest.mark.skipif(gui_module.Gtk is None, reason="GTK 4 is not installed")
def test_store_offers_uninstall_for_the_detected_package(system):
        if not gui_module.Gtk.init_check():
                pytest.skip("GTK display is unavailable")
        window = gui_module._build_window(system.env)
        try:
                stack = window.get_child().get_last_child()
                store = stack.get_child_by_name("Store")
                pending = [store]
                listing = None
                while pending:
                        widget = pending.pop()
                        if isinstance(widget, gui_module.Gtk.ListBox):
                                listing = widget
                                break
                        child = widget.get_first_child()
                        while child is not None:
                                pending.append(child)
                                child = child.get_next_sibling()
                assert listing is not None
                row = listing.get_first_child()
                uninstall_button = None
                while row is not None:
                        row_box = row.get_child()
                        labels = row_box.get_first_child()
                        if labels.get_first_child().get_text() == "Rofi":
                                uninstall_button = row_box.get_last_child()
                                break
                        row = row.get_next_sibling()
                assert uninstall_button is not None
                assert uninstall_button.get_label() == "Uninstall"
                uninstall_button.emit("clicked")
                dialogs = gui_module.Gtk.Window.get_toplevels()
                confirmation = next(
                        (
                                dialogs.get_item(index)
                                for index in range(dialogs.get_n_items())
                                if isinstance(
                                        dialogs.get_item(index), gui_module.Gtk.Dialog
                                )
                                and dialogs.get_item(index).get_transient_for()
                                is window
                        ),
                        None,
                )
                assert confirmation is not None
                confirmation.emit("response", gui_module.Gtk.ResponseType.CANCEL)
                assert uninstall_button.get_label() == "Uninstall"
                assert uninstall_button.get_sensitive()
        finally:
                window.destroy()


@pytest.mark.skipif(gui_module.Gtk is None, reason="GTK 4 is not installed")
def test_confirmed_uninstall_runs_the_selected_package_command(system, monkeypatch):
        if not gui_module.Gtk.init_check():
                pytest.skip("GTK display is unavailable")
        commands = []

        class FakeProcess:
                def communicate_utf8_async(
                        self, _stdin, _cancellable, callback, user_data
                ):
                        callback(self, object(), user_data)

                def communicate_utf8_finish(self, _result):
                        return True, "", ""

                def get_successful(self):
                        return True

        class FakeSubprocess:
                @staticmethod
                def new(command, _flags):
                        commands.append(command)
                        return FakeProcess()

        class FakeFlags:
                STDOUT_PIPE = 1
                STDERR_MERGE = 2

        class FakeGio:
                Subprocess = FakeSubprocess
                SubprocessFlags = FakeFlags

        monkeypatch.setattr(gui_module, "Gio", FakeGio)
        window = gui_module._build_window(system.env)
        try:
                store = window.get_child().get_last_child().get_child_by_name("Store")
                pending = [store]
                uninstall_button = None
                while pending:
                        widget = pending.pop()
                        if (
                                isinstance(widget, gui_module.Gtk.Button)
                                and widget.get_label() == "Uninstall"
                        ):
                                uninstall_button = widget
                                break
                        child = widget.get_first_child()
                        while child is not None:
                                pending.append(child)
                                child = child.get_next_sibling()
                assert uninstall_button is not None
                uninstall_button.emit("clicked")
                dialogs = gui_module.Gtk.Window.get_toplevels()
                confirmation = next(
                        (
                                dialogs.get_item(index)
                                for index in range(dialogs.get_n_items())
                                if isinstance(
                                        dialogs.get_item(index), gui_module.Gtk.Dialog
                                )
                                and dialogs.get_item(index).get_transient_for()
                                is window
                        ),
                        None,
                )
                assert confirmation is not None
                confirmation.emit("response", gui_module.Gtk.ResponseType.ACCEPT)
                expected = ["dnf", "remove", "--assumeyes", "--", "rofi"]
                if os.geteuid() != 0:
                        expected.insert(0, "pkexec")
                assert commands == [expected]
        finally:
                window.destroy()


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@needs_git
def test_update_db_clones_then_pulls(fake, tmp_path):
        repo = tmp_path / "community"
        (repo / "applications").mkdir(parents=True)

        def commit(name):
                (repo / "applications" / f"{name}.yaml").write_text(
                        f"schema_version: 1\nid: {name}\nname: {name}\ncategory: tool\ndetection:\n  executables: [{name}]\n"
                )
                git = [
                        "git",
                        "-C",
                        str(repo),
                        "-c",
                        "user.name=t",
                        "-c",
                        "user.email=t@t",
                ]
                subprocess.run([*git, "add", "."], check=True, capture_output=True)
                subprocess.run(
                        [*git, "commit", "-m", name], check=True, capture_output=True
                )

        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        commit("alpha")
        env = fake.env
        assert "cloned" in update_community_db(env, repo.as_uri())
        assert "alpha" in load_database(default_roots(env)).apps
        commit("beta")
        assert "updated" in update_community_db(env)
        assert {"alpha", "beta"} <= set(load_database(default_roots(env)).apps)
        assert (community_root(env) / ".git").is_dir()


def test_update_db_needs_a_source_first(fake):
        with pytest.raises(DatabaseUpdateError, match="--source"):
                update_community_db(fake.env)
