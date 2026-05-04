from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - fcntl is available on supported hosts.
    fcntl = None

from rich.console import Console

from fedctl.build.build import build_image, image_exists
from fedctl.build.dockerfile import render_dockerfile
from fedctl.build.errors import BuildError
from fedctl.build.inspect import inspect_project
from fedctl.build.push import push_image
from fedctl.build.state import (
    BuildMetadata,
    new_timestamp,
    write_latest_build,
    write_project_build,
)
from fedctl.build.tagging import default_image_tag
from fedctl.constants import DEFAULT_FLWR_VERSION
from fedctl.project.errors import ProjectError
from fedctl.config.deploy import get_image_registry, resolve_deploy_config

console = Console()


def _env_image_registry() -> str | None:
    value = os.environ.get("FEDCTL_IMAGE_REGISTRY", "").strip()
    return value.rstrip("/") if value else None


def build_and_record(
    *,
    path: str = ".",
    flwr_version: str = DEFAULT_FLWR_VERSION,
    image: str | None = None,
    no_cache: bool = False,
    platform: str | None = None,
    context: str | None = None,
    push: bool = False,
) -> str:
    try:
        info = inspect_project(Path(path))
    except (ProjectError, ValueError) as exc:
        raise BuildError(str(exc)) from exc

    deploy_cfg = resolve_deploy_config(
        project_root=info.root,
        include_project_local=True,
        include_profile=True,
    ).data
    registry = _env_image_registry() or get_image_registry(deploy_cfg)
    dockerfile = render_dockerfile(flwr_version)
    context_dir = Path(context) if context else info.root
    image_tag = image or default_image_tag(
        info.project_name,
        repo_root=info.root,
        context_root=context_dir,
        dockerfile_contents=dockerfile,
        flwr_version=flwr_version,
        registry=registry,
    )
    reuse_existing_tag = image is None and not no_cache

    with _image_build_lock(image_tag) if reuse_existing_tag else _unlocked():
        if not reuse_existing_tag or not image_exists(image_tag):
            with tempfile.TemporaryDirectory() as tmp_dir:
                dockerfile_path = Path(tmp_dir) / "Dockerfile"
                dockerfile_path.write_text(dockerfile, encoding="utf-8")

                build_image(
                    image=image_tag,
                    dockerfile_path=dockerfile_path,
                    context_dir=context_dir,
                    no_cache=no_cache,
                    platform=platform,
                )

    if push:
        push_image(image_tag)

    metadata = BuildMetadata(
        image=image_tag,
        project=info.project_name,
        flwr_version=flwr_version,
        timestamp=new_timestamp(),
        project_root=str(info.root),
    )
    write_latest_build(metadata)
    write_project_build(metadata, info.root)
    return image_tag


def run_build(
    *,
    path: str = ".",
    flwr_version: str = DEFAULT_FLWR_VERSION,
    image: str | None = None,
    no_cache: bool = False,
    platform: str | None = None,
    context: str | None = None,
    push: bool = False,
) -> int:
    try:
        image_tag = build_and_record(
            path=path,
            flwr_version=flwr_version,
            image=image,
            no_cache=no_cache,
            platform=platform,
            context=context,
            push=push,
        )
        console.print(f"[green]✓ Built image:[/green] {image_tag}")
        return 0
    except BuildError as exc:
        console.print(f"[red]✗ Build error:[/red] {exc}")
        return 1


@contextmanager
def _unlocked() -> Iterator[None]:
    yield


@contextmanager
def _image_build_lock(image_tag: str) -> Iterator[None]:
    if fcntl is None:
        yield
        return

    lock_dir = Path(tempfile.gettempdir()) / "fedctl-build-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_name = hashlib.sha256(image_tag.encode("utf-8")).hexdigest()
    lock_path = lock_dir / f"{lock_name}.lock"
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
