from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class SubmitRepoConfig:
    node_class: str | None = None
    image: str | None = None
    artifact_store: str | None = None
    endpoint: str | None = None
    token: str | None = None
    user: str | None = None


def parse_submit_repo_config(repo_cfg: dict[str, Any]) -> SubmitRepoConfig:
    submit = repo_cfg.get("submit", {}) if isinstance(repo_cfg.get("submit"), dict) else {}
    node_class = submit.get("node_class")
    image = submit.get("image")
    artifact_store = submit.get("artifact_store")
    endpoint = submit.get("endpoint")
    token = submit.get("token")
    user = submit.get("user")
    return SubmitRepoConfig(
        node_class=str(node_class) if isinstance(node_class, str) and node_class else None,
        image=str(image) if isinstance(image, str) and image else None,
        artifact_store=(
            str(artifact_store) if isinstance(artifact_store, str) and artifact_store else None
        ),
        endpoint=str(endpoint) if isinstance(endpoint, str) and endpoint else None,
        token=str(token) if isinstance(token, str) and token else None,
        user=str(user) if isinstance(user, str) and user else None,
    )


def get_image_registry(repo_cfg: dict[str, Any]) -> str | None:
    value = repo_cfg.get("image_registry")
    if isinstance(value, str) and value.strip():
        return value.strip().rstrip("/")
    build_cfg = repo_cfg.get("build", {})
    if isinstance(build_cfg, dict):
        value = build_cfg.get("image_registry")
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip("/")
    return None


def _find_repo_config(base: Path) -> Path | None:
    base = base.resolve()
    if base.is_file():
        base = base.parent
    candidate = base / ".fedctl" / "fedctl.yaml"
    return candidate if candidate.exists() else None
