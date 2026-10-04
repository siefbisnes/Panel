"""Create and restore backups of configuration files."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .configuration import config_entries
from .environment import Environment
from .models import Application


class BackupError(RuntimeError):
        """Raised when a backup or restore action fails."""


def backup_root(env: Environment) -> Path:
        return env.data_home / "panel" / "backups"


def _store_path(backup_dir: Path, source: Path) -> Path:
        return backup_dir / "files" / f"{abs(hash(str(source))):x}"


def create_backup(env: Environment, apps: list[Application]) -> Path:
        """Create a backup of every existing config path for the selected applications."""
        root = backup_root(env)
        root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_dir = root / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)
        files_dir = backup_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        entries: list[dict[str, str]] = []
        seen: set[Path] = set()
        for app in apps:
                for entry in config_entries(app, env):
                        path = entry.path
                        if not path.exists():
                                continue
                        if path in seen:
                                continue
                        seen.add(path)
                        if path.is_dir():
                                dest = _store_path(backup_dir, path)
                                shutil.copytree(path, dest, dirs_exist_ok=True)
                                kind = "directory"
                        elif path.is_file():
                                dest = _store_path(backup_dir, path)
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(path, dest)
                                kind = "file"
                        else:
                                continue
                        entries.append(
                                {
                                        "source": str(path),
                                        "stored": str(dest.relative_to(backup_dir)),
                                        "kind": kind,
                                }
                        )

        manifest = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "applications": [app.id for app in apps],
                "entries": entries,
        }
        (backup_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return backup_dir


def restore_backup(
        backup_dir: Path, env: Environment, overwrite: bool = False
) -> list[str]:
        """Restore files from a backup directory; overwrite requires an explicit flag."""
        manifest_path = backup_dir / "manifest.json"
        if not manifest_path.is_file():
                raise BackupError(f"not a valid backup: {backup_dir}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        restored: list[str] = []
        for entry in manifest.get("entries", []):
                target = Path(entry["source"])
                source = backup_dir / entry["stored"]
                if not source.exists():
                        raise BackupError(f"missing backup payload for {target}")
                if target.exists() and not overwrite:
                        raise BackupError(
                                f"refusing to overwrite existing configuration: {target}. Pass --force to replace it."
                        )
                if target.exists() and target.is_dir() and entry["kind"] == "file":
                        shutil.rmtree(target)
                elif (
                        target.exists()
                        and target.is_file()
                        and entry["kind"] == "directory"
                ):
                        target.unlink()
                target.parent.mkdir(parents=True, exist_ok=True)
                if entry["kind"] == "directory":
                        if target.exists():
                                shutil.rmtree(target)
                        shutil.copytree(source, target)
                else:
                        if target.exists() and target.is_dir():
                                shutil.rmtree(target)
                        shutil.copy2(source, target)
                restored.append(str(target))
        return restored
