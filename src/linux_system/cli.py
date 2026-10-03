"""Command line interface."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

from . import __version__
from .backup import BackupError, create_backup, restore_backup
from .community import build_submission, community_summary, submit_definition
from .configuration import edit_target, open_in_editor
from .database import (
        DatabaseUpdateError,
        LoadResult,
        bundled_root,
        default_roots,
        definition_files,
        load_database,
        load_files,
        make_validator,
        update_community_db,
)
from .detector import SystemProbe
from .environment import Environment
from .gui import launch_gui
from .models import Application, Status
from .render import (
        Style,
        mark,
        render_brief,
        render_config,
        render_info,
        render_list,
        render_scan,
)
from .scanner import scan, scan_app, system_overview


def _load(args: argparse.Namespace, env: Environment) -> LoadResult:
        result = load_database(default_roots(env, args.db))
        if result.errors:
                print(
                        f"warning: {len(result.errors)} definition problem(s) found; run 'linux-system doctor' for details",
                        file=sys.stderr,
                )
        return result


def _find_app(apps: dict[str, Application], query: str) -> Application | None:
        wanted = query.lower()
        for app in apps.values():
                if wanted in (app.id, app.name.lower()):
                        return app
        close = difflib.get_close_matches(wanted, list(apps), n=3)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        print(f"error: unknown application '{query}'.{hint}", file=sys.stderr)
        return None


def _json(data: object) -> None:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def _scan_all(args: argparse.Namespace, env: Environment):
        db = _load(args, env)
        probe = SystemProbe(env)
        return probe, scan(db.apps.values(), probe)


def cmd_brief(args, env, style) -> int:
        print("Scanning system...\n")
        _, results = _scan_all(args, env)
        print(render_brief(results, style))
        return 0


def cmd_scan(args, env, style) -> int:
        probe, results = _scan_all(args, env)
        overview = system_overview(probe, results)
        if args.json:
                _json(
                        {
                                "overview": overview,
                                "applications": [
                                        r.to_dict() for r in results if r.detected
                                ],
                        }
                )
        else:
                print(render_scan(overview, results, style))
        return 0


def cmd_list(args, env, style) -> int:
        _, results = _scan_all(args, env)
        if args.json:
                _json([r.to_dict() for r in results if args.all or r.detected])
        else:
                print(render_list(results, style, args.all))
        return 0


def cmd_info(args, env, style) -> int:
        db = _load(args, env)
        app = _find_app(db.apps, args.app)
        if app is None:
                return 2
        result = scan_app(app, SystemProbe(env))
        if args.json:
                _json(result.to_dict())
        else:
                print(render_info(result, env, style))
        return 0


def cmd_config(args, env, style) -> int:
        db = _load(args, env)
        app = _find_app(db.apps, args.app)
        if app is None:
                return 2
        if args.edit:
                target = edit_target(app, env)
                if target is None:
                        print(
                                f"error: no existing configuration file found for {app.name}",
                                file=sys.stderr,
                        )
                        return 1
                return open_in_editor(target, env)
        print(render_config(scan_app(app, SystemProbe(env)), env, style))
        return 0


def cmd_doctor(args, env, style) -> int:
        probe = SystemProbe(env)
        db = load_database(default_roots(env, args.db))
        key = probe.package_key
        checks = [
                (Status.FOUND, "Distribution", probe.os_release.pretty_name),
                (
                        Status.FOUND if key else Status.UNKNOWN,
                        "Package backend",
                        key or "unsupported distribution; package checks will show '?'",
                ),
                (
                        Status.FOUND
                        if probe.native_packages is not None
                        else Status.UNKNOWN,
                        "Package database",
                        f"{len(probe.native_packages)} packages"
                        if probe.native_packages is not None
                        else "cannot be queried",
                ),
                (
                        Status.FOUND
                        if probe.flatpak_packages is not None
                        else Status.UNKNOWN,
                        "Flatpak",
                        "available"
                        if probe.flatpak_packages is not None
                        else "not available",
                ),
                (
                        Status.FOUND if probe.processes is not None else Status.UNKNOWN,
                        "Process list",
                        "readable"
                        if probe.processes is not None
                        else "cannot read /proc",
                ),
                (
                        Status.FOUND
                        if env.run(
                                ["systemctl", "--user", "show", "--property=Version"]
                        )
                        is not None
                        else Status.UNKNOWN,
                        "systemd (user)",
                        "reachable"
                        if env.run(
                                ["systemctl", "--user", "show", "--property=Version"]
                        )
                        is not None
                        else "not reachable",
                ),
                (
                        Status.NOT_FOUND if db.errors else Status.FOUND,
                        "Definitions",
                        f"{len(db.apps)} loaded, {len(db.errors)} problem(s)",
                ),
        ]
        for status, label, detail in checks:
                print(f"{mark(status, style)} {label:<17} {detail}")
        for error in db.errors:
                print(f"  {error}")
        return 1 if db.errors else 0


def cmd_validate(args, env, style) -> int:
        files = [
                f
                for path in (args.paths or [bundled_root()])
                for f in definition_files(path)
        ]
        result = load_files(files, make_validator())
        for error in result.errors:
                print(error, file=sys.stderr)
        if result.errors:
                print(f"{len(result.errors)} problem(s) found", file=sys.stderr)
                return 1
        print(f"{len(result.apps)} definitions valid")
        return 0


def cmd_backup(args, env, style) -> int:
        db = _load(args, env)
        probe = SystemProbe(env)
        if args.all:
                apps = [r.app for r in scan(db.apps.values(), probe) if r.detected]
        elif args.apps:
                apps = []
                for name in args.apps:
                        app = _find_app(db.apps, name)
                        if app is None:
                                return 2
                        apps.append(app)
        else:
                apps = [r.app for r in scan(db.apps.values(), probe) if r.configured]
        if not apps:
                print(
                        "error: no configured applications available to back up",
                        file=sys.stderr,
                )
                return 1
        backup_dir = create_backup(env, apps)
        print(f"Backup created: {backup_dir}")
        print(f"{len(apps)} application(s) backed up")
        return 0


def cmd_restore(args, env, style) -> int:
        backup_dir = Path(args.backup)
        try:
                restored = restore_backup(backup_dir, env, overwrite=args.force)
        except BackupError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        print(f"Restored {len(restored)} file(s) from {backup_dir}")
        return 0


def cmd_submit(args, env, style) -> int:
        payload = build_submission(
                app_id=args.id,
                name=args.name,
                category=args.category,
                executable=args.executable,
                config=args.config,
                distro=args.distro,
                package=args.package,
                docs=args.docs,
        )
        try:
                path = submit_definition(env, payload)
        except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        print(f"Submission created: {path}")
        print("Submission is pending maintainer review.")
        return 0


def cmd_community(args, env, style) -> int:
        db = load_database(default_roots(env, args.db))
        summary = community_summary(env, len(db.apps))
        print("Community")
        print(f"Supported applications: {summary['supported_applications']}")
        print(f"Pending submissions: {summary['pending_submissions']}")
        print("Trusted database: bundled definitions + reviewed community entries")
        return 0


def cmd_gui(args, env, style) -> int:
        return launch_gui(env)


def cmd_update_db(args, env, style) -> int:
        try:
                print(update_community_db(env, args.source))
        except DatabaseUpdateError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        return 0


def build_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
                prog="linux-system",
                description="Discover, understand, and manage the software and configuration of a Linux system.",
        )
        parser.add_argument(
                "-V", "--version", action="version", version=f"%(prog)s {__version__}"
        )
        parser.add_argument(
                "--db",
                action="append",
                default=[],
                type=Path,
                metavar="DIR",
                help="extra definition directory (highest priority; repeatable)",
        )
        parser.add_argument(
                "--no-color", action="store_true", help="disable colored output"
        )
        sub = parser.add_subparsers(dest="command", metavar="COMMAND")

        scan_p = sub.add_parser(
                "scan", help="show a system overview and every detected application"
        )
        scan_p.add_argument("--json", action="store_true")
        list_p = sub.add_parser("list", help="list detected applications")
        list_p.add_argument(
                "--all",
                action="store_true",
                help="include applications that were not detected",
        )
        list_p.add_argument("--json", action="store_true")
        info_p = sub.add_parser(
                "info", help="show everything known about one application"
        )
        info_p.add_argument("app")
        info_p.add_argument("--json", action="store_true")
        config_p = sub.add_parser(
                "config", help="show an application's configuration locations"
        )
        config_p.add_argument("app")
        config_p.add_argument(
                "--edit",
                action="store_true",
                help="open its first configuration file in $EDITOR",
        )
        sub.add_parser(
                "doctor",
                help="check what this system lets the scanner see, and the definitions",
        )
        validate_p = sub.add_parser(
                "validate",
                help="validate definition files (default: the bundled database)",
        )
        validate_p.add_argument("paths", nargs="*", type=Path)
        backup_p = sub.add_parser(
                "backup", help="create a backup of application configuration"
        )
        backup_p.add_argument(
                "apps", nargs="*", help="application ids or names to back up"
        )
        backup_p.add_argument(
                "--all",
                action="store_true",
                help="back up every configured application",
        )
        restore_p = sub.add_parser(
                "restore", help="restore a backup of application configuration"
        )
        restore_p.add_argument("backup", type=Path, help="path to the backup directory")
        restore_p.add_argument(
                "--force",
                action="store_true",
                help="replace existing files without prompting",
        )
        submit_p = sub.add_parser(
                "submit", help="create a reviewable application definition submission"
        )
        submit_p.add_argument(
                "--id", required=True, help="application id (lowercase, digits, dashes)"
        )
        submit_p.add_argument("--name", required=True, help="display name")
        submit_p.add_argument(
                "--category",
                required=True,
                choices=[
                        "desktop",
                        "bar",
                        "terminal",
                        "shell",
                        "launcher",
                        "editor",
                        "browser",
                        "tool",
                        "audio",
                        "media",
                        "notification",
                        "file-manager",
                        "network",
                        "other",
                ],
        )
        submit_p.add_argument("--executable", help="main executable name")
        submit_p.add_argument(
                "--config",
                action="append",
                default=[],
                help="configuration path to include, repeatable",
        )
        submit_p.add_argument(
                "--distro",
                default="fedora",
                help="package distribution name to associate with --package",
        )
        submit_p.add_argument(
                "--package", help="package name for the selected distribution"
        )
        submit_p.add_argument("--docs", help="official documentation URL")
        community_p = sub.add_parser(
                "community",
                help="show the trusted database and pending community submissions",
        )
        gui_p = sub.add_parser("gui", help="launch the GNOME-style overview window")
        update_p = sub.add_parser(
                "update-db", help="fetch or update the community database"
        )
        update_p.add_argument("--source", help="git repository to clone the first time")
        return parser


COMMANDS = {
        None: cmd_brief,
        "scan": cmd_scan,
        "list": cmd_list,
        "info": cmd_info,
        "config": cmd_config,
        "doctor": cmd_doctor,
        "validate": cmd_validate,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "submit": cmd_submit,
        "community": cmd_community,
        "gui": cmd_gui,
        "update-db": cmd_update_db,
}


def main(argv: list[str] | None = None, env: Environment | None = None) -> int:
        args = build_parser().parse_args(argv)
        env = env or Environment()
        style = Style(
                not args.no_color
                and sys.stdout.isatty()
                and "NO_COLOR" not in env.variables
        )
        try:
                return COMMANDS[args.command](args, env, style)
        except BrokenPipeError:  # e.g. `linux-system list | head`
                os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
                return 1
