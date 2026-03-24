from __future__ import annotations

import os
import subprocess
from pathlib import Path

from typing import Callable

from fedctl.commands.build import build_and_record
from fedctl.commands.configure import run_configure
from fedctl.commands.deploy import run_deploy
from fedctl.commands.destroy import run_destroy
from fedctl.project.errors import ProjectError
from datetime import datetime, timezone

from fedctl.deploy.spec import normalize_experiment_name
from fedctl.project.flwr_inspect import inspect_flwr_project
from fedctl.build.state import load_project_build
from fedctl.build.build import image_exists, pull_image
from fedctl.build.errors import BuildError
from fedctl.config.repo import resolve_repo_config_path
from fedctl.util.console import console


def _print_step(idx: int, total: int, title: str) -> None:
    if idx > 1:
        console.print()
    console.print(f"[bold cyan]Step {idx}/{total}[/bold cyan] [bold]-[/bold] {title}")


def _print_ok(message: str) -> None:
    console.print(f"[green]✓[/green] {message}")


def run_run(
    *,
    path: str = ".",
    flwr_version: str = "1.25.0",
    image: str | None = None,
    no_cache: bool = False,
    platform: str | None = None,
    context: str | None = None,
    push: bool = False,
    num_supernodes: int = 2,
    auto_supernodes: bool = False,
    supernodes: list[str] | None = None,
    net: list[str] | None = None,
    allow_oversubscribe: bool | None = None,
    repo_config: str | None = None,
    experiment: str | None = None,
    timeout_seconds: int = 120,
    no_wait: bool = False,
    namespace: str | None = None,
    profile: str | None = None,
    endpoint: str | None = None,
    token: str | None = None,
    federation: str = "remote-deployment",
    stream: bool = True,
    verbose: bool = False,
    pre_cleanup: Callable[[], None] | None = None,
    destroy: bool = True,
) -> int:
    project_path = Path(path)
    _print_step(1, 5, "Inspect project")
    try:
        info = inspect_flwr_project(project_path)
    except ProjectError as exc:
        console.print(f"[red]✗ Project error:[/red] {exc}")
        return 1

    project_name = info.project_name or "project"
    if not supernodes and auto_supernodes and info.local_sim_num_supernodes:
        num_supernodes = info.local_sim_num_supernodes
        _print_ok(f"Using num-supernodes={num_supernodes}")

    exp_name = normalize_experiment_name(
        experiment or f"{project_name}-{_timestamp_compact()}"
    )
    _print_ok(f"Experiment: {exp_name}")

    _print_step(2, 5, "Build SuperExec image")
    image_tag = None
    reuse_allowed = not no_cache and image is None and context is None
    pull_cached = os.environ.get("FEDCTL_PULL_CACHED_IMAGE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if reuse_allowed:
        try:
            cached = load_project_build(info.root)
            if cached.flwr_version != flwr_version:
                console.print(
                    f"[yellow]Note:[/yellow] Cached image flwr_version "
                    f"{cached.flwr_version} does not match {flwr_version}."
                )
            else:
                if image_exists(cached.image):
                    image_tag = cached.image
                    _print_ok(f"Reusing cached image: {image_tag}")
                elif pull_cached:
                    console.print(
                        f"[yellow]Note:[/yellow] Cached image not local, attempting pull: {cached.image}"
                    )
                    if pull_image(cached.image) and image_exists(cached.image):
                        image_tag = cached.image
                        _print_ok(f"Pulled cached image: {image_tag}")
                    else:
                        console.print(
                            f"[yellow]Note:[/yellow] Failed to pull cached image {cached.image}."
                        )
                else:
                    console.print(
                        f"[yellow]Note:[/yellow] Cached image not found locally. "
                        f"Set FEDCTL_PULL_CACHED_IMAGE=1 to pull {cached.image}."
                    )
        except BuildError:
            pass

    if not image_tag:
        try:
            image_tag = build_and_record(
                path=str(info.root),
                flwr_version=flwr_version,
                image=image,
                no_cache=no_cache,
                platform=platform,
                context=context,
                push=push,
                verbose=verbose,
            )
            _print_ok(f"Built image: {image_tag}")
        except BuildError as exc:
            console.print(f"[red]✗ Build error:[/red] {exc}")
            return 1

    deploy_num_supernodes = None if supernodes else num_supernodes

    _print_step(3, 5, "Deploy to Nomad")
    resolved_repo_config = _resolve_run_repo_config(
        repo_config=repo_config,
        project_root=info.root,
    )
    deploy_status = run_deploy(
        dry_run=False,
        out=None,
        fmt="json",
        num_supernodes=deploy_num_supernodes,
        supernodes=supernodes,
        net=net,
        allow_oversubscribe=allow_oversubscribe,
        repo_config=resolved_repo_config,
        image=image_tag,
        experiment=exp_name,
        timeout_seconds=timeout_seconds,
        no_wait=no_wait,
        profile=profile,
        endpoint=endpoint,
        namespace=namespace,
        token=token,
    )
    if deploy_status != 0:
        return deploy_status

    _print_step(4, 5, "Configure project federation")
    configure_status = run_configure(
        path=str(info.root),
        namespace=namespace,
        backup=True,
        show_next=False,
        experiment=exp_name,
        profile=profile,
        endpoint=endpoint,
        token=token,
    )
    if configure_status != 0:
        return configure_status

    _print_step(5, 5, "Run Flower")
    cmd = ["flwr", "run", str(info.root), federation]
    if stream:
        cmd.append("--stream")

    try:
        result = subprocess.run(cmd, check=False)
        return_code = result.returncode
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow] Attempting cleanup...")
        return_code = 130
    except FileNotFoundError:
        console.print("[red]✗ flwr CLI not found.[/red] Ensure Flower is installed.")
        return 1
    finally:
        if pre_cleanup:
            try:
                pre_cleanup()
            except Exception as exc:
                console.print(f"[yellow]Warning:[/yellow] Pre-cleanup hook failed: {exc}")
        if destroy:
            console.print()
            console.print("[bold cyan]Cleanup[/bold cyan] [bold]-[/bold] Destroy Nomad jobs")
            destroy_status = run_destroy(
                experiment=exp_name,
                destroy_all=False,
                namespace=namespace,
                purge=True,
                profile=profile,
                endpoint=endpoint,
                token=token,
            )
            if destroy_status != 0:
                console.print("[yellow]Warning:[/yellow] Cleanup failed.")
        else:
            console.print("[yellow]Note:[/yellow] Skipping cleanup (--no-destroy).")

    return return_code


def _timestamp_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _resolve_run_repo_config(*, repo_config: str | None, project_root: Path) -> str | None:
    if repo_config:
        return repo_config
    path = resolve_repo_config_path(
        project_root=project_root,
        include_project_local=True,
    )
    return str(path) if path else None
