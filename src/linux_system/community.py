"""Create reviewable application submissions without executing arbitrary code."""

from __future__ import annotations

from pathlib import Path

import yaml

from .database import load_files, make_validator
from .environment import Environment


def submissions_root(env: Environment) -> Path:
        return env.data_home / "panel" / "submissions"


def build_submission(
        *,
        app_id: str,
        name: str,
        category: str,
        executable: str | None = None,
        config: str | list[str] | None = None,
        distro: str = "fedora",
        package: str | None = None,
        docs: str | None = None,
) -> dict[str, object]:
        config_list = [config] if isinstance(config, str) else list(config or [])
        detection: dict[str, object] = {}
        if executable:
                detection["executables"] = [executable]
        if config_list:
                detection["config_paths"] = config_list
        packages: dict[str, list[str]] = {}
        if package:
                packages[distro] = [package]

        payload: dict[str, object] = {
                "schema_version": 1,
                "id": app_id,
                "name": name,
                "category": category,
                "detection": detection,
        }
        if packages:
                payload["packages"] = packages
        if config_list:
                payload["configuration"] = {"files": config_list}
        if docs:
                payload["documentation"] = {"official": docs}
        return payload


def submit_definition(env: Environment, payload: dict[str, object]) -> Path:
        root = submissions_root(env)
        root.mkdir(parents=True, exist_ok=True)
        app_id = str(payload["id"])
        path = root / f"{app_id}.yaml"
        path.write_text(
                yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
        )
        result = load_files([path], make_validator())
        if result.errors:
                path.unlink(missing_ok=True)
                raise ValueError("; ".join(result.errors))
        return path


def community_summary(env: Environment, app_count: int) -> dict[str, int]:
        pending = len(list(submissions_root(env).glob("*.yaml")))
        return {"supported_applications": app_count, "pending_submissions": pending}
