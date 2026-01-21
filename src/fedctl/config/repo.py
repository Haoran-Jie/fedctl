from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_repo_config(base: Path | None = None, config_path: Path | None = None) -> dict[str, Any]:
    if config_path:
        path = config_path
        if not path.is_absolute():
            path = (base or Path.cwd()) / path
    else:
        path = _find_repo_config(base or Path.cwd())
    if not path:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _find_repo_config(base: Path) -> Path | None:
    base = base.resolve()
    if base.is_file():
        base = base.parent
    candidate = base / ".fedctl" / "fedctl.yaml"
    return candidate if candidate.exists() else None
