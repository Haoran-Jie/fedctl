from __future__ import annotations

import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from typing import Callable

from fedctl.commands.build import build_and_record
from fedctl.commands.configure import run_configure
from fedctl.commands.deploy import run_deploy
from fedctl.commands.destroy import run_destroy
from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.constants import DEFAULT_FLWR_VERSION
from fedctl.deploy import naming
from fedctl.project.errors import ProjectError
from datetime import datetime, timezone

from fedctl.deploy.spec import normalize_experiment_name
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadHTTPError
from fedctl.project.flwr_inspect import inspect_flwr_project
from fedctl.build.state import load_project_build
from fedctl.build.build import image_exists, pull_image
from fedctl.build.errors import BuildError
from fedctl.project.run_config import (
    extract_seed_sweep,
    materialize_run_config,
    resolve_run_config,
)
from fedctl.config.deploy import get_deploy_config_label, resolve_deploy_config
from fedctl.project.flwr_config import resolve_flwr_home
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
    run_config: str | None = None,
    run_config_overrides: list[str] | None = None,
    seed: int | None = None,
    flwr_version: str = DEFAULT_FLWR_VERSION,
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
    deploy_config: str | None = None,
    experiment: str | None = None,
    timeout_seconds: int = 120,
    no_wait: bool = False,
    namespace: str | None = None,
    profile: str | None = None,
    endpoint: str | None = None,
    token: str | None = None,
    federation: str = "remote-deployment",
    stream: bool = True,
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

    exp_name = resolve_run_experiment_name(project_name=project_name, experiment=experiment)
    _print_ok(f"Experiment: {exp_name}")
    if seed is None:
        try:
            seed_sweep = extract_seed_sweep(info.root, run_config)
        except ProjectError as exc:
            console.print(f"[red]✗ Run config error:[/red] {exc}")
            return 1
        if seed_sweep:
            return _run_seed_sweep(
                seed_sweep=seed_sweep,
                base_experiment=exp_name,
                path=path,
                run_config=run_config,
                flwr_version=flwr_version,
                image=image,
                no_cache=no_cache,
                platform=platform,
                context=context,
                push=push,
                num_supernodes=num_supernodes,
                auto_supernodes=auto_supernodes,
                supernodes=supernodes,
                net=net,
                allow_oversubscribe=allow_oversubscribe,
                deploy_config=deploy_config,
                timeout_seconds=timeout_seconds,
                no_wait=no_wait,
                namespace=namespace,
                profile=profile,
                endpoint=endpoint,
                token=token,
                federation=federation,
                stream=stream,
                pre_cleanup=pre_cleanup,
                destroy=destroy,
            )
    try:
        resolved_run_config = resolve_run_config(info.root, run_config)
    except ProjectError as exc:
        console.print(f"[red]✗ Run config error:[/red] {exc}")
        return 1

    image_tag = None
    if image:
        _print_step(2, 5, "Select SuperExec image")
        ignored_flags: list[str] = []
        if no_cache:
            ignored_flags.append("--no-cache")
        if platform:
            ignored_flags.append("--platform")
        if context:
            ignored_flags.append("--context")
        if push:
            ignored_flags.append("--push")
        if ignored_flags:
            console.print(
                "[yellow]Note:[/yellow] Ignoring build flags when reusing "
                f"explicit image: {', '.join(ignored_flags)}"
            )
        image_tag = image
        _print_ok(f"Using provided image: {image_tag}")
    else:
        _print_step(2, 5, "Build SuperExec image")
        reuse_allowed = not no_cache and context is None
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
                )
                _print_ok(f"Built image: {image_tag}")
            except BuildError as exc:
                console.print(f"[red]✗ Build error:[/red] {exc}")
                return 1

    deploy_num_supernodes = None if supernodes else num_supernodes

    _print_step(3, 5, "Deploy to Nomad")
    resolved_deploy = resolve_deploy_config(
        deploy_config=deploy_config,
        include_project_local=True,
        project_root=info.root,
    )
    resolved_deploy_config = _resolve_run_deploy_config(
        deploy_config=deploy_config,
        project_root=info.root,
    )
    deploy_config_label = get_deploy_config_label(
        resolved_deploy.data, path=resolved_deploy.path
    )
    with _temporary_run_tracking_env(
        run_config=(
            resolved_run_config.runner_path if resolved_run_config else None
        ),
        deploy_config_label=deploy_config_label,
    ):
        deploy_status = run_deploy(
            dry_run=False,
            out=None,
            fmt="json",
            num_supernodes=deploy_num_supernodes,
            supernodes=supernodes,
            net=net,
            allow_oversubscribe=allow_oversubscribe,
            deploy_config=resolved_deploy_config,
            image=image_tag,
            flwr_version=flwr_version,
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

    _print_step(4, 5, "Configure Flower connection")
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
    merged_overrides = _build_run_config_overrides(
        run_config_overrides=run_config_overrides,
        seed=seed,
    )
    resolved_run_config = materialize_run_config(
        base_path=resolved_run_config.resolved_path if resolved_run_config else None,
        run_config_overrides=merged_overrides,
    )
    if resolved_run_config:
        cmd.extend(["--run-config", str(resolved_run_config)])
    else:
        for override in merged_overrides:
            cmd.extend(["--run-config", override])
    if stream:
        cmd.append("--stream")
    env = os.environ.copy()
    env["FLWR_HOME"] = str(resolve_flwr_home(project_root=info.root))
    src_dir = info.root / "src"
    if src_dir.is_dir():
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{src_dir}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(src_dir)
        )

    return_code = 1
    try:
        result = subprocess.run(cmd, check=False, env=env)
        return_code = result.returncode
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow] Attempting cleanup...")
        return_code = 130
    except FileNotFoundError:
        console.print("[red]✗ flwr CLI not found.[/red] Ensure Flower is installed.")
        return 1
    finally:
        if (
            return_code == 0
            and federation == "remote-deployment"
            and not stream
        ):
            wait_code = _wait_for_remote_run_completion(
                experiment=exp_name,
                profile=profile,
                endpoint=endpoint,
                namespace=namespace,
                token=token,
            )
            if wait_code != 0:
                return_code = wait_code
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


def resolve_run_experiment_name(*, project_name: str | None, experiment: str | None) -> str:
    base_project = project_name or "project"
    return normalize_experiment_name(experiment or f"{base_project}-{_timestamp_compact()}")


def _resolve_run_deploy_config(
    *, deploy_config: str | Path | None, project_root: Path
) -> str | None:
    if deploy_config is not None:
        return str(deploy_config)
    resolved = resolve_deploy_config(
        deploy_config=None,
        include_project_local=True,
        project_root=project_root,
    )
    return str(resolved.path) if resolved.path else None


def _timestamp_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def _temporary_run_tracking_env(
    *, run_config: str | None, deploy_config_label: str | None
):
    updates = {
        "FEDCTL_ATTEMPT_STARTED_AT": os.environ.get("FEDCTL_ATTEMPT_STARTED_AT", _timestamp_iso()),
    }
    if run_config:
        updates["FEDCTL_RUN_CONFIG"] = run_config
    if deploy_config_label:
        updates["FEDCTL_DEPLOY_CONFIG_LABEL"] = deploy_config_label
        updates["FEDCTL_REPO_CONFIG_LABEL"] = deploy_config_label
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _build_run_config_overrides(
    *,
    run_config_overrides: list[str] | None,
    seed: int | None,
) -> list[str]:
    overrides = list(run_config_overrides or [])
    if seed is not None:
        overrides.append(f"seed={seed}")
    return overrides


def _wait_for_remote_run_completion(
    *,
    experiment: str,
    profile: str | None,
    endpoint: str | None,
    namespace: str | None,
    token: str | None,
    poll_interval_s: float = 5.0,
) -> int:
    console.print(
        "[cyan]Wait[/cyan] [bold]-[/bold] Monitoring remote server run until completion"
    )
    client = _nomad_client_for_run_wait(
        profile=profile,
        endpoint=endpoint,
        namespace=namespace,
        token=token,
    )
    job_name = naming.job_superexec_serverapp(experiment)
    task_name = job_name
    last_status: str | None = None
    try:
        while True:
            alloc = _latest_serverapp_alloc(client, job_name)
            if alloc is None:
                status = "waiting for serverapp allocation"
                if status != last_status:
                    console.print(f"[yellow]Note:[/yellow] {status}")
                    last_status = status
                time.sleep(poll_interval_s)
                continue
            detail = _allocation_detail_or_none(client, alloc)
            summary = _serverapp_completion_summary(
                alloc=detail or alloc,
                task_name=task_name,
            )
            if summary["status"] != last_status:
                console.print(f"[cyan]Status:[/cyan] {summary['status']}")
                last_status = str(summary["status"])
            if bool(summary["active"]):
                time.sleep(poll_interval_s)
                continue
            if bool(summary["success"]):
                _print_ok("Remote server run completed")
                return 0
            console.print(
                f"[red]✗ Remote server run failed.[/red] {summary['status']}"
            )
            return 1
    finally:
        client.close()


def _nomad_client_for_run_wait(
    *,
    profile: str | None,
    endpoint: str | None,
    namespace: str | None,
    token: str | None,
) -> NomadClient:
    cfg = load_config()
    eff = get_effective_config(
        cfg,
        profile_name=profile,
        endpoint=endpoint,
        namespace=namespace,
        token=token,
    )
    return NomadClient(eff)


def _latest_serverapp_alloc(client: NomadClient, job_name: str) -> dict[str, object] | None:
    try:
        allocs = client.job_allocations(job_name)
    except NomadHTTPError as exc:
        if exc.status_code == 404:
            return None
        raise
    return _latest_alloc(allocs)


def _latest_alloc(allocs: object) -> dict[str, object] | None:
    if not isinstance(allocs, list) or not allocs:
        return None
    candidates = [alloc for alloc in allocs if isinstance(alloc, dict)]
    if not candidates:
        return None
    candidates.sort(key=_alloc_sort_key, reverse=True)
    return candidates[0]


def _alloc_sort_key(alloc: dict[str, object]) -> int:
    for key in ("ModifyTime", "CreateTime"):
        value = alloc.get(key)
        if isinstance(value, int):
            return value
    return 0


def _allocation_detail_or_none(
    client: NomadClient, alloc: dict[str, object]
) -> dict[str, object] | None:
    alloc_id = alloc.get("ID")
    if not isinstance(alloc_id, str) or not alloc_id:
        return None
    try:
        detail = client.allocation(alloc_id)
    except NomadHTTPError:
        return None
    return detail if isinstance(detail, dict) else None


def _serverapp_completion_summary(
    *, alloc: dict[str, object], task_name: str
) -> dict[str, object]:
    client_status = str(alloc.get("ClientStatus") or "").lower()
    task_states = alloc.get("TaskStates")
    task_info = task_states.get(task_name) if isinstance(task_states, dict) else None
    if not isinstance(task_info, dict) and isinstance(task_states, dict) and len(task_states) == 1:
        task_info = next(iter(task_states.values()))
    task_state = str(task_info.get("State") or "").lower() if isinstance(task_info, dict) else ""
    task_failed = bool(task_info.get("Failed")) if isinstance(task_info, dict) else False

    if client_status in {"pending", "running"} or task_state in {"pending", "running"}:
        return {
            "active": True,
            "success": False,
            "status": f"client={client_status or 'unknown'} task={task_state or 'unknown'}",
        }
    if client_status == "complete":
        return {
            "active": False,
            "success": True,
            "status": f"client={client_status} task={task_state or 'dead'}",
        }
    if task_state == "dead" and not task_failed and client_status not in {"failed", "lost"}:
        return {
            "active": False,
            "success": True,
            "status": f"client={client_status or 'complete'} task={task_state}",
        }
    return {
        "active": False,
        "success": False,
        "status": f"client={client_status or 'unknown'} task={task_state or 'unknown'} failed={task_failed}",
    }


def _run_seed_sweep(
    *,
    seed_sweep: tuple[int, ...],
    base_experiment: str,
    path: str,
    run_config: str | None,
    flwr_version: str,
    image: str | None,
    no_cache: bool,
    platform: str | None,
    context: str | None,
    push: bool,
    num_supernodes: int,
    auto_supernodes: bool,
    supernodes: list[str] | None,
    net: list[str] | None,
    allow_oversubscribe: bool | None,
    deploy_config: str | None,
    timeout_seconds: int,
    no_wait: bool,
    namespace: str | None,
    profile: str | None,
    endpoint: str | None,
    token: str | None,
    federation: str,
    stream: bool,
    pre_cleanup: Callable[[], None] | None,
    destroy: bool,
) -> int:
    console.print(f"[cyan]Detected seed sweep:[/cyan] {', '.join(str(seed) for seed in seed_sweep)}")
    failures = 0
    for sweep_seed in seed_sweep:
        child_experiment = normalize_experiment_name(f"{base_experiment}-seed{sweep_seed}")
        console.print()
        console.print(
            f"[bold cyan]Seed[/bold cyan] [bold]-[/bold] {sweep_seed} -> {child_experiment}"
        )
        status = run_run(
            path=path,
            run_config=run_config,
            run_config_overrides=None,
            seed=sweep_seed,
            flwr_version=flwr_version,
            image=image,
            no_cache=no_cache,
            platform=platform,
            context=context,
            push=push,
            num_supernodes=num_supernodes,
            auto_supernodes=auto_supernodes,
            supernodes=supernodes,
            net=net,
            allow_oversubscribe=allow_oversubscribe,
            deploy_config=deploy_config,
            experiment=child_experiment,
            timeout_seconds=timeout_seconds,
            no_wait=no_wait,
            namespace=namespace,
            profile=profile,
            endpoint=endpoint,
            token=token,
            federation=federation,
            stream=stream,
            pre_cleanup=pre_cleanup,
            destroy=destroy,
        )
        if status != 0:
            failures += 1
    return 0 if failures == 0 else 1
