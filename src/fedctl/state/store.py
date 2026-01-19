from __future__ import annotations

import json
import os
from pathlib import Path

from fedctl.config.paths import user_config_dir
from .errors import StateError
from .manifest import DeploymentManifest


def manifest_path(namespace: str = "default") -> Path:
    return user_config_dir() / "state" / namespace / "deploy.json"


def write_manifest(
    manifest: DeploymentManifest,
    *,
    namespace: str = "default",
    overwrite: bool = False,
) -> Path:
    path = manifest_path(namespace)
    if path.exists() and not overwrite:
        raise StateError(f"Manifest already exists at {path}.")

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)
    return path
