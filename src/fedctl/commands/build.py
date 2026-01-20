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


def run_build(
    *,
    path: str = ".",
    flwr_version: str = "1.26.0",
    image: str | None = None,
    no_cache: bool = False,
    platform: str | None = None,
    context: str | None = None,
    push: bool = False,
) -> int:
    try:
        info = inspect_project(Path(path))
    except (ProjectError, ValueError) as exc:
        console.print(f"[red]✗ Project error:[/red] {exc}")
        return 1

    image_tag = image or default_image_tag(info.project_name, repo_root=info.root)
    dockerfile = render_dockerfile(flwr_version)
    context_dir = Path(context) if context else info.root

    try:
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
        )
        path = write_latest_build(metadata)
        console.print(f"[green]✓ Built image:[/green] {image_tag}")
        console.print(f"[green]✓ Build metadata:[/green] {path}")
        return 0

    except BuildError as exc:
        console.print(f"[red]✗ Build error:[/red] {exc}")
        return 1
