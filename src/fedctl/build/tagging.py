from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess


def default_image_tag(
    project_name: str,
    *,
    repo_root: Path | None = None,
    registry: str | None = None,
) -> str:
    suffix = _git_sha(repo_root) or _timestamp()
    base = project_name.strip() or "superexec"
    tag = f"{base}-superexec:{suffix}"
    return _apply_registry(tag, registry or _image_registry())


def supernode_netem_image_tag(flwr_version: str, *, registry: str | None = None) -> str:
    tag = f"flwr-supernode-netem:{flwr_version}"
    return _apply_registry(tag, registry or _image_registry())


def _image_registry() -> str | None:
    import os

    value = os.environ.get("FEDCTL_IMAGE_REGISTRY", "").strip()
    return value.rstrip("/") if value else None


def _apply_registry(tag: str, registry: str | None) -> str:
    return f"{registry}/{tag}" if registry else tag


def _git_sha(repo_root: Path | None) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root) if repo_root else None,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    sha = result.stdout.strip()
    return sha if sha else None


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
