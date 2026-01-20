from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fedctl.config.paths import user_config_dir
from .errors import BuildError


@dataclass(frozen=True)
class BuildMetadata:
    image: str
    project: str
    flwr_version: str
    timestamp: str

    def to_dict(self) -> dict[str, str]:
        return {
            "image": self.image,
            "project": self.project,
            "flwr_version": self.flwr_version,
            "timestamp": self.timestamp,
        }


def new_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_build_path() -> Path:
    return user_config_dir() / "builds" / "latest.json"


def write_latest_build(metadata: BuildMetadata) -> Path:
    path = latest_build_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(metadata.to_dict(), indent=2, sort_keys=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError as exc:
        raise BuildError(f"Failed to write build metadata: {exc}") from exc
    return path


def load_latest_build() -> BuildMetadata:
    path = latest_build_path()
    if not path.exists():
        raise BuildError(f"No build metadata found at {path}.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildError(f"Build metadata at {path} is invalid JSON.") from exc

    image = raw.get("image")
    project = raw.get("project")
    flwr_version = raw.get("flwr_version")
    timestamp = raw.get("timestamp")
    if not all(isinstance(val, str) and val for val in [image, project, flwr_version, timestamp]):
        raise BuildError(f"Build metadata at {path} is missing required fields.")
    return BuildMetadata(
        image=image,
        project=project,
        flwr_version=flwr_version,
        timestamp=timestamp,
    )
