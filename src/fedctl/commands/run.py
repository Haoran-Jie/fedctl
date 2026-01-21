from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

from fedctl.build.errors import BuildError
from fedctl.commands.build import build_and_record
from fedctl.commands.configure import run_configure
from fedctl.commands.deploy import run_deploy
from fedctl.project.errors import ProjectError
from datetime import datetime, timezone

from fedctl.deploy.spec import normalize_experiment_name
from fedctl.project.flwr_inspect import inspect_flwr_project

console = Console()


def run_run(
    *,
    path: str = ".",
    flwr_version: str = "1.23.0",
    image: str | None = None,
    no_cache: bool = False,
    platform: str | None = None,
    context: str | None = None,
    push: bool = False,
    num_supernodes: int = 2,
    auto_supernodes: bool = False,
    supernodes: list[str] | None = None,
    allow_oversubscribe: bool | None = None,
    repo_config: str | None = None,
    experiment: str | None = None,
    timeout_seconds: int = 120,
    no_wait: bool = False,
    namespace: str | None = None,
    profile: str | None = None,
    endpoint: str | None = None,
    token: str | None = None,
    tls_ca: str | None = None,
    tls_skip_verify: bool | None = None,
    federation: str = "remote-deployment",
    stream: bool = True,
    verbose: bool = False,
) -> int:
    project_path = Path(path)
    console.print("[bold]Step 1/5:[/bold] Inspect project")
    try:
        info = inspect_flwr_project(project_path)
    except ProjectError as exc:
        console.print(f"[red]✗ Project error:[/red] {exc}")
        return 1

    project_name = info.project_name or "project"
    if not supernodes and auto_supernodes and info.local_sim_num_supernodes:
        num_supernodes = info.local_sim_num_supernodes
        console.print(f"[green]✓ Using num-supernodes={num_supernodes}[/green]")

    exp_name = normalize_experiment_name(
        experiment or f"{project_name}-{_timestamp_compact()}"
    )
    console.print(f"[green]✓ Experiment:[/green] {exp_name}")

    console.print("[bold]Step 2/5:[/bold] Build SuperExec image")
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
        console.print(f"[green]✓ Built image:[/green] {image_tag}")
    except BuildError as exc:
        console.print(f"[red]✗ Build error:[/red] {exc}")
        return 1

    console.print("[bold]Step 3/5:[/bold] Deploy to Nomad")
    deploy_status = run_deploy(
        dry_run=False,
        out=None,
        fmt="json",
        num_supernodes=num_supernodes,
        supernodes=supernodes,
        allow_oversubscribe=allow_oversubscribe,
        repo_config=repo_config,
        image=image_tag,
        experiment=exp_name,
        timeout_seconds=timeout_seconds,
        no_wait=no_wait,
        profile=profile,
        endpoint=endpoint,
        namespace=namespace,
        token=token,
        tls_ca=tls_ca,
        tls_skip_verify=tls_skip_verify,
    )
    if deploy_status != 0:
        return deploy_status

    console.print("[bold]Step 4/5:[/bold] Configure project federation")
    configure_status = run_configure(
        path=str(info.root),
        namespace=namespace,
        backup=True,
        show_next=False,
        experiment=exp_name,
        profile=profile,
        endpoint=endpoint,
        token=token,
        tls_ca=tls_ca,
        tls_skip_verify=tls_skip_verify,
    )
    if configure_status != 0:
        return configure_status

    console.print("[bold]Step 5/5:[/bold] Run Flower")
    cmd = ["flwr", "run", str(info.root), federation]
    if stream:
        cmd.append("--stream")

    try:
        result = subprocess.run(cmd, check=False)
    except FileNotFoundError as exc:
        console.print("[red]✗ flwr CLI not found.[/red] Ensure Flower is installed.")
        return 1

    return result.returncode


def _timestamp_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
