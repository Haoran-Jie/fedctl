from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess


def default_image_tag(project_name: str, *, repo_root: Path | None = None) -> str:
    suffix = _git_sha(repo_root) or _timestamp()
    base = project_name.strip() or "superexec"
    return f"{base}-superexec:{suffix}"


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
