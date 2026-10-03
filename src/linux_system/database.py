"""Loading, validating and updating application definitions."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from .environment import Environment
from .models import Application

SCHEMA_NAME = "application.schema.json"


class DatabaseUpdateError(Exception):
        pass


@dataclass
class LoadResult:
        apps: dict[str, Application] = field(default_factory=dict)
        errors: list[str] = field(default_factory=list)


def bundled_root() -> Path:
        package_dir = Path(__file__).resolve().parent
        for candidate in (
                package_dir / "database",
                package_dir.parents[1] / "database",
        ):
                if (candidate / "applications").is_dir():
                        return candidate
        raise FileNotFoundError("bundled application database not found")


def community_root(env: Environment) -> Path:
        return env.data_home / "linux-system" / "community-db"


def default_roots(env: Environment, extra: list[Path] | None = None) -> list[Path]:
        """Database roots from lowest to highest priority; later roots override earlier ones by id."""
        return [
                bundled_root(),
                community_root(env),
                env.config_home / "linux-system" / "database",
                *(extra or []),
        ]


def make_validator() -> Draft202012Validator:
        schema = json.loads(
                (bundled_root() / "schemas" / SCHEMA_NAME).read_text(encoding="utf-8")
        )
        return Draft202012Validator(schema)


def applications_dir(root: Path) -> Path | None:
        for candidate in (root / "applications", root / "database" / "applications"):
                if candidate.is_dir():
                        return candidate
        return None


def definition_files(path: Path) -> list[Path]:
        """A single file, or every *.yaml in a database root or applications directory."""
        if path.is_file():
                return [path]
        return sorted((applications_dir(path) or path).glob("*.yaml"))


def load_files(
        files: list[Path], validator: Draft202012Validator | None = None
) -> LoadResult:
        validator = validator or make_validator()
        result = LoadResult()
        for file in files:
                try:
                        data = yaml.safe_load(file.read_text(encoding="utf-8"))
                except (OSError, yaml.YAMLError) as exc:
                        result.errors.append(f"{file}: cannot read: {exc}")
                        continue
                problems = [
                        f"{file}: {'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
                        for e in sorted(
                                validator.iter_errors(data),
                                key=lambda e: list(map(str, e.path)),
                        )
                ]
                if not problems:
                        if data["id"] != file.stem:
                                problems.append(
                                        f"{file}: id '{data['id']}' must match the file name '{file.stem}'"
                                )
                        elif data["id"] in result.apps:
                                problems.append(f"{file}: duplicate id '{data['id']}'")
                if problems:
                        result.errors.extend(problems)
                else:
                        result.apps[data["id"]] = Application.from_dict(data)
        return result


def load_database(roots: list[Path]) -> LoadResult:
        validator = make_validator()
        merged = LoadResult()
        for root in roots:
                directory = applications_dir(root)
                if directory is None:
                        continue
                loaded = load_files(sorted(directory.glob("*.yaml")), validator)
                merged.apps.update(loaded.apps)
                merged.errors.extend(loaded.errors)
        return merged


def update_community_db(env: Environment, source: str | None = None) -> str:
        """Clone the community database on first use, fast-forward it afterwards."""
        target = community_root(env)
        if (target / ".git").is_dir():
                args, action = ["-C", str(target), "pull", "--ff-only"], "updated"
        elif source:
                target.parent.mkdir(parents=True, exist_ok=True)
                args, action = (
                        ["clone", "--depth", "1", "--", source, str(target)],
                        "cloned",
                )
        else:
                raise DatabaseUpdateError(
                        "no community database configured yet; pass --source <git repository>"
                )
        try:
                proc = subprocess.run(
                        ["git", *args],
                        capture_output=True,
                        text=True,
                        timeout=300,
                        check=False,
                )
        except FileNotFoundError:
                raise DatabaseUpdateError("git is not installed") from None
        except subprocess.TimeoutExpired:
                raise DatabaseUpdateError("git timed out") from None
        if proc.returncode != 0:
                raise DatabaseUpdateError(proc.stderr.strip() or "git failed")
        return f"Community database {action}: {target}"
