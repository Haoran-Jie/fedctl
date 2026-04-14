from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess


def default_image_tag(
    project_name: str,
    *,
    repo_root: Path | None = None,
    context_root: Path | None = None,
    dockerfile_contents: str | None = None,
    flwr_version: str | None = None,
    registry: str | None = None,
) -> str:
    context_hash = _context_hash(
        context_root=context_root,
        dockerfile_contents=dockerfile_contents,
        flwr_version=flwr_version,
    )
    suffix = f"ctx-{context_hash}" if context_hash else (_git_sha(repo_root) or _timestamp())
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


def _context_hash(
    *,
    context_root: Path | None,
    dockerfile_contents: str | None,
    flwr_version: str | None,
) -> str | None:
    if context_root is None or dockerfile_contents is None or flwr_version is None:
        return None
    if not context_root.exists() or not context_root.is_dir():
        return None

    digest = hashlib.sha256()
    digest.update(b"flwr-version\0")
    digest.update(flwr_version.encode("utf-8"))
    digest.update(b"\0dockerfile\0")
    digest.update(dockerfile_contents.encode("utf-8"))

    for path in sorted(_walk_context_files(context_root)):
        rel = path.relative_to(context_root).as_posix()
        digest.update(b"\0file\0")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)

    return digest.hexdigest()[:12]


def _walk_context_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file():
            files.append(path)
    return files
