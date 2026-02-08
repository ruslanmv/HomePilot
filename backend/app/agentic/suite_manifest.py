from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


Json = Dict[str, Any]


def _default_suite_dir() -> Path:
    """Locate the repo-local agentic suite directory.

    This remains additive: if the folder is absent in some deployments,
    suite endpoints will return empty manifests.
    """

    # backend/app/agentic -> backend/app -> backend -> repo root
    root = Path(__file__).resolve().parents[3]
    return root / "agentic" / "suite"


def _suite_dir() -> Path:
    override = os.environ.get("HOMEPILOT_AGENTIC_SUITE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return _default_suite_dir()


def read_suite(name: str) -> Json:
    """Read `agentic/suite/<name>.yaml` and return parsed YAML as JSON."""

    suite_dir = _suite_dir()
    path = suite_dir / f"{name}.yaml"
    if not path.exists():
        return {"error": f"suite manifest not found: {name}", "name": name, "path": str(path)}

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {"error": f"invalid suite manifest: {name}", "name": name}
        return data


def list_suites() -> Json:
    """Return known suite manifests if present."""

    return {
        "default_home": read_suite("default_home"),
        "default_pro": read_suite("default_pro"),
        "optional_addons": read_suite("optional_addons"),
    }
