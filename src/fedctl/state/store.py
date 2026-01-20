from __future__ import annotations

import json
import os
from pathlib import Path

from fedctl.config.paths import user_config_dir
from .errors import StateError
from .manifest import DeploymentManifest


def manifest_path(namespace: str = "default", experiment: str = "default") -> Path:
    return user_config_dir() / "state" / namespace / experiment / "deploy.json"


def write_manifest(
    manifest: DeploymentManifest,
    *,
    namespace: str = "default",
    overwrite: bool = True,
    experiment: str = "default",
) -> Path:
    path = manifest_path(namespace, experiment)
    if path.exists() and not overwrite:
        raise StateError(f"Manifest already exists at {path}.")

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)
    return path


def load_manifest(namespace: str = "default", experiment: str = "default") -> dict[str, object]:
    path = manifest_path(namespace, experiment)
    if not path.exists():
        raise StateError(f"Manifest not found at {path}.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"Manifest at {path} is invalid JSON.") from exc
