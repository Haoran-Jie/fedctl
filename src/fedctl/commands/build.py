from __future__ import annotations

import tempfile
from pathlib import Path

from rich.console import Console

from fedctl.build.build import build_image
from fedctl.build.dockerfile import render_dockerfile
from fedctl.build.errors import BuildError
from fedctl.build.inspect import inspect_project
from fedctl.build.push import push_image
from fedctl.build.state import BuildMetadata, new_timestamp, write_latest_build
from fedctl.build.tagging import default_image_tag
from fedctl.project.errors import ProjectError

console = Console()


def build_and_record(
    *,
    path: str = ".",
    flwr_version: str = "1.23.0",
    image: str | None = None,
    no_cache: bool = False,
    platform: str | None = None,
    context: str | None = None,
    push: bool = False,
    verbose: bool = False,
) -> str:
    try:
        info = inspect_project(Path(path))
    except (ProjectError, ValueError) as exc:
        raise BuildError(str(exc)) from exc

    image_tag = image or default_image_tag(info.project_name, repo_root=info.root)
    dockerfile = render_dockerfile(flwr_version)
    context_dir = Path(context) if context else info.root

    with tempfile.TemporaryDirectory() as tmp_dir:
        dockerfile_path = Path(tmp_dir) / "Dockerfile"
        dockerfile_path.write_text(dockerfile, encoding="utf-8")

        build_image(
            image=image_tag,
            dockerfile_path=dockerfile_path,
            context_dir=context_dir,
            no_cache=no_cache,
            platform=platform,
            quiet=not verbose,
        )

    if push:
        push_image(image_tag)

    metadata = BuildMetadata(
        image=image_tag,
        project=info.project_name,
        flwr_version=flwr_version,
        timestamp=new_timestamp(),
    )
    write_latest_build(metadata)
    return image_tag


def run_build(
    *,
    path: str = ".",
    flwr_version: str = "1.23.0",
    image: str | None = None,
    no_cache: bool = False,
    platform: str | None = None,
    context: str | None = None,
    push: bool = False,
    verbose: bool = False,
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
            verbose=verbose,
        )
        console.print(f"[green]✓ Built image:[/green] {image_tag}")
        return 0
    except BuildError as exc:
        console.print(f"[red]✗ Build error:[/red] {exc}")
        return 1
