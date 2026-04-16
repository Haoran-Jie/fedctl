from __future__ import annotations

import hashlib
import os
import json
import re
import shlex
from urllib.parse import urlparse
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from rich.text import Text
import httpx
import tomlkit

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.config.repo import (
    get_cluster_image_registry,
    get_repo_config_label,
    get_repo_network_profile_label,
    parse_submit_repo_config,
    get_image_registry,
    rewrite_image_registry,
    resolve_repo_config,
)
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.project.errors import ProjectError
from fedctl.project.experiment_config import (
    extract_seed_sweep,
    materialize_run_config,
    resolve_experiment_config,
)
from fedctl.project.flwr_inspect import inspect_flwr_project
from fedctl.submit.artifact import ArtifactUploadError, upload_artifact
from fedctl.submit.client import SubmitServiceClient, SubmitServiceError
from fedctl.submit.render import SubmitJobSpec, render_submit_job
from fedctl.deploy.spec import normalize_experiment_name
from fedctl.state.errors import StateError
from fedctl.state.submissions import (
    SubmissionRecord,
    clear_submission,
    clear_submissions,
    load_submissions,
    record_submission,
)
from fedctl.util.console import console, print_table

_ARCHIVE_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "dist",
    "rendered",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".ruff_cache",
}
_SUBMIT_NODE_CLASS = "submit"


def _print_step(idx: int, total: int, title: str) -> None:
    if idx > 1:
        console.print()
    console.print(f"[bold cyan]Step {idx}/{total}[/bold cyan] [bold]-[/bold] {title}")


def _print_ok(message: str) -> None:
    console.print(f"[green]✓[/green] {message}")


def run_submit(
    *,
    path: str,
    experiment_config: str | None = None,
    run_config_overrides: list[str] | None = None,
    seed: int | None = None,
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
    repo_config: str | None,
    experiment: str | None,
    timeout_seconds: int,
    federation: str,
    stream: bool,
    verbose: bool,
    destroy: bool,
    submit_image: str | None,
    artifact_store: str | None,
    priority: int | None,
) -> int:
    project_path = Path(path)
    _print_step(1, 4, "Inspect project")
    try:
        info = inspect_flwr_project(project_path)
    except ProjectError as exc:
        console.print(f"[red]✗ Project error:[/red] {exc}")
        return 1

    project_name = info.project_name or "project"
    if not supernodes and auto_supernodes and info.local_sim_num_supernodes:
        num_supernodes = info.local_sim_num_supernodes
        _print_ok(f"Using num-supernodes={num_supernodes}")

    repo_resolution = resolve_repo_config(
        repo_config=repo_config,
        include_profile=True,
        include_project_local=True,
        project_root=project_path,
    )
    repo_cfg = repo_resolution.data
    repo_cfg_path = repo_resolution.path
    repo_config_label = get_repo_config_label(repo_cfg, path=repo_cfg_path)
    network_profile_label = get_repo_network_profile_label(repo_cfg)

    try:
        resolved_experiment_config = resolve_experiment_config(info.root, experiment_config)
        exp_name = normalize_experiment_name(
            experiment
            or _default_submit_experiment_name(
                project_name=project_name,
                resolved_experiment_config=resolved_experiment_config,
                run_config_overrides=run_config_overrides,
                seed=seed,
                network_profile_label=network_profile_label,
            )
        )
    except ProjectError as exc:
        console.print(f"[red]✗ Experiment config error:[/red] {exc}")
        return 1
    if seed is None:
        try:
            seed_sweep = extract_seed_sweep(info.root, experiment_config)
        except ProjectError as exc:
            console.print(f"[red]✗ Experiment config error:[/red] {exc}")
            return 1
        if seed_sweep:
            return _submit_seed_sweep(
                seed_sweep=seed_sweep,
                base_experiment=exp_name,
                path=path,
                experiment_config=experiment_config,
                run_config_overrides=run_config_overrides,
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
                repo_config=repo_config,
                timeout_seconds=timeout_seconds,
                federation=federation,
                stream=stream,
                verbose=verbose,
                destroy=destroy,
                submit_image=submit_image,
                artifact_store=artifact_store,
                priority=priority,
            )
    repo_supernodes = _repo_supernodes(repo_cfg)
    if not supernodes and repo_supernodes:
        supernodes = [f"{device_type}={count}" for device_type, count in repo_supernodes.items()]
    if allow_oversubscribe is None:
        repo_allow_oversubscribe = _repo_allow_oversubscribe(repo_cfg)
        if repo_allow_oversubscribe is not None:
            allow_oversubscribe = repo_allow_oversubscribe

    submit_client = _submit_service_client(repo_cfg=repo_cfg)
    submission_id = None
    if not submit_client:
        submission_id = f"submit-{exp_name}-{_timestamp_compact()}"
        _print_ok(f"Submission ID: {submission_id}")

    submit_cfg = parse_submit_repo_config(repo_cfg)
    external_registry = get_image_registry(repo_cfg)
    internal_registry = get_cluster_image_registry(repo_cfg)

    resolved_image = submit_image or submit_cfg.image
    resolved_artifact_store = artifact_store or submit_cfg.artifact_store
    presign_endpoint = (
        submit_client.endpoint.rstrip("/") + "/v1/presign" if submit_client else None
    )
    presign_token = submit_client.token if submit_client else submit_cfg.token
    if not resolved_image:
        console.print("[red]✗ Missing submit image.[/red] Use --submit-image or repo config.")
        return 1
    if not resolved_artifact_store:
        console.print(
            "[red]✗ Missing artifact store.[/red] Use --artifact-store or repo config."
        )
        return 1
    resolved_image = rewrite_image_registry(
        resolved_image,
        source_registry=external_registry,
        target_registry=internal_registry,
    )

    resolved_superexec_image = None
    if image:
        resolved_superexec_image = rewrite_image_registry(
            image,
            source_registry=external_registry,
            target_registry=internal_registry,
        )
    attempt_started_at = _timestamp_iso()

    _print_step(2, 4, "Package project")
    try:
        archive_path = _build_project_archive(
            info.root,
            project_name,
            repo_config_path=repo_cfg_path,
            experiment_config_path=(
                resolved_experiment_config.archive_source if resolved_experiment_config else None
            ),
            experiment_config_arcname=(
                resolved_experiment_config.runner_path if resolved_experiment_config else None
            ),
        )
    except OSError as exc:
        console.print(f"[red]✗ Archive error:[/red] {exc}")
        return 1
    _print_ok(f"Created archive: {archive_path}")

    _print_step(3, 4, "Upload artifact")
    try:
        artifact_url = upload_artifact(
            archive_path,
            resolved_artifact_store,
            presign_endpoint=presign_endpoint,
            presign_token=presign_token,
        )
    except ArtifactUploadError as exc:
        console.print(f"[red]✗ Artifact upload error:[/red] {exc}")
        return 1
    _print_ok("Uploaded artifact")
    console.print(f"[cyan]URL:[/cyan] {artifact_url}")

    _print_step(4, 4, "Submit Nomad job")
    cfg = load_config()
    try:
        eff = get_effective_config(cfg)
    except ValueError as exc:
        console.print(f"[red]✗ Config error:[/red] {exc}")
        return 1

    if submit_client:
        try:
            response = submit_client.create_submission(
                {
                    "project_name": project_name,
                    "experiment": exp_name,
                    "artifact_url": artifact_url,
                    "submit_image": resolved_image,
                    "node_class": _SUBMIT_NODE_CLASS,
                    "submit_request": _original_submit_request(
                        path=path,
                        project_root=info.root,
                        experiment=exp_name,
                        experiment_config=experiment_config,
                        run_config_overrides=run_config_overrides,
                        seed=seed,
                        flwr_version=flwr_version,
                        image=resolved_superexec_image,
                        no_cache=no_cache,
                        platform=platform,
                        context=context,
                        push=push,
                        num_supernodes=num_supernodes,
                        auto_supernodes=auto_supernodes,
                        supernodes=supernodes,
                        net=net,
                        allow_oversubscribe=allow_oversubscribe,
                        repo_config=repo_config,
                        federation=federation,
                        stream=stream,
                        timeout_seconds=timeout_seconds,
                        verbose=verbose,
                        destroy=destroy,
                        submit_image=resolved_image,
                        artifact_store=resolved_artifact_store,
                        priority=priority or 50,
                    ),
                    "args": _runner_args(
                        project_dir_name=project_path.name,
                        exp_name=exp_name,
                        experiment_config=(
                            resolved_experiment_config.runner_path
                            if resolved_experiment_config
                            else None
                        ),
                        run_config_overrides=run_config_overrides,
                        seed=seed,
                        flwr_version=flwr_version,
                        image=resolved_superexec_image,
                        no_cache=no_cache,
                        platform=platform,
                        context=context,
                        push=push,
                        num_supernodes=num_supernodes,
                        auto_supernodes=auto_supernodes,
                        supernodes=supernodes,
                        net=net,
                        allow_oversubscribe=allow_oversubscribe,
                        federation=federation,
                        stream=stream,
                        timeout_seconds=timeout_seconds,
                        verbose=verbose,
                        destroy=destroy,
                    ),
                    "env": _runner_env(
                        eff,
                        result_store=resolved_artifact_store,
                        image_registry=internal_registry,
                        attempt_started_at=attempt_started_at,
                        experiment_config=(
                            resolved_experiment_config.runner_path
                            if resolved_experiment_config
                            else None
                        ),
                        repo_config_label=repo_config_label,
                    ),
                    "priority": priority or 50,
                    "namespace": eff.namespace,
                }
            )
        except SubmitServiceError as exc:
            console.print(f"[red]✗ Submit service error:[/red] {exc}")
            return 1
        submission_id = response.get("submission_id", "<unknown>")
        _print_ok(f"Submitted job: {submission_id}")
        console.print(f"[cyan]Next:[/cyan] fedctl submit status {submission_id}")
        return 0

    job = render_submit_job(
        SubmitJobSpec(
            job_name=submission_id or f"submit-{exp_name}-{_timestamp_compact()}",
            node_class=_SUBMIT_NODE_CLASS,
            image=resolved_image,
            artifact_url=artifact_url,
            namespace=eff.namespace or "default",
            args=_runner_args(
                project_dir_name=project_path.name,
                exp_name=exp_name,
                experiment_config=(
                    resolved_experiment_config.runner_path
                    if resolved_experiment_config
                    else None
                ),
                run_config_overrides=run_config_overrides,
                seed=seed,
                flwr_version=flwr_version,
                image=resolved_superexec_image,
                no_cache=no_cache,
                platform=platform,
                context=context,
                push=push,
                num_supernodes=num_supernodes,
                auto_supernodes=auto_supernodes,
                supernodes=supernodes,
                net=net,
                allow_oversubscribe=allow_oversubscribe,
                federation=federation,
                stream=stream,
                timeout_seconds=timeout_seconds,
                verbose=verbose,
                destroy=destroy,
            ),
            env=_runner_env(
                eff,
                result_store=resolved_artifact_store,
                image_registry=internal_registry,
                submission_id=submission_id,
                attempt_started_at=attempt_started_at,
                experiment_config=(
                    resolved_experiment_config.runner_path
                    if resolved_experiment_config
                    else None
                ),
                repo_config_label=repo_config_label,
            ),
            priority=priority or 50,
            artifact_dest="/local/project",
            work_dir="/local/project",
        )
    )

    client = NomadClient(eff)
    try:
        client.submit_job(job)
    except NomadTLSError as exc:
        console.print(f"[red]✗ TLS error:[/red] {exc}")
        return 2
    except NomadHTTPError as exc:
        console.print(f"[red]✗ HTTP error:[/red] {exc}")
        if getattr(exc, "status_code", None) == 403:
            console.print("[yellow]Hint:[/yellow] Token/ACL invalid or missing permissions.")
        return 3
    except NomadConnectionError as exc:
        console.print(f"[red]✗ Connection error:[/red] {exc}")
        console.print(
            "[yellow]Hint:[/yellow] Check endpoint reachability (LAN/Tailscale/SSH tunnel)."
        )
        return 4
    finally:
        client.close()

    _record_submission_state(
        submission_id=submission_id or job["Job"]["ID"],
        experiment=exp_name,
        status="queued",
        namespace=eff.namespace,
        artifact_url=artifact_url,
        submit_image=resolved_image,
        node_class=_SUBMIT_NODE_CLASS,
    )
    _print_ok(f"Submitted job: {submission_id}")
    console.print(f"[cyan]Next:[/cyan] fedctl submit status {submission_id}")
    return 0


def run_submit_status(*, submission_id: str) -> int:
    submit_client = _submit_service_client()
    if submit_client:
        try:
            record = submit_client.get_submission(submission_id)
        except SubmitServiceError as exc:
            console.print(f"[red]✗ Submit service error:[/red] {exc}")
            return 1
        resolved_id = record.get("submission_id", submission_id)
        status = record.get("status", "-")
        blocked_reason = record.get("blocked_reason")
        error_message = record.get("error_message")
        console.print(f"[bold]Job:[/bold] {resolved_id}")
        console.print(f"[bold]Status:[/bold] {status}")
        if status == "blocked" and blocked_reason:
            console.print(f"[bold]Blocked reason:[/bold] {blocked_reason}")
        if status == "failed" and isinstance(error_message, str) and error_message:
            console.print(f"[bold]Error:[/bold] {error_message}")
        nomad_job_id = record.get("nomad_job_id")
        if nomad_job_id and nomad_job_id != resolved_id:
            console.print(f"[bold]Nomad Job:[/bold] {nomad_job_id}")
        return 0

    cfg = load_config()
    try:
        eff = get_effective_config(cfg)
    except ValueError as exc:
        console.print(f"[red]✗ Config error:[/red] {exc}")
        return 1

    client = NomadClient(eff)
    try:
        job = client.job(submission_id)
        allocs = client.job_allocations(submission_id)
        alloc = _latest_alloc(allocs)
        job_status = _job_status(job)
        alloc_status = _alloc_status(alloc)
        console.print(f"[bold]Job:[/bold] {submission_id} ({job_status})")
        if alloc_status:
            console.print(f"[bold]Alloc:[/bold] {alloc_status}")
        if alloc:
            alloc_id = alloc.get("ID")
            if isinstance(alloc_id, str):
                console.print(f"[bold]Alloc ID:[/bold] {alloc_id}")
        return 0

    except NomadTLSError as exc:
        console.print(f"[red]✗ TLS error:[/red] {exc}")
        return 2

    except NomadHTTPError as exc:
        console.print(f"[red]✗ HTTP error:[/red] {exc}")
        if getattr(exc, "status_code", None) == 404:
            console.print("[yellow]Hint:[/yellow] Submission ID not found.")
        elif getattr(exc, "status_code", None) == 403:
            console.print("[yellow]Hint:[/yellow] Token/ACL invalid or missing permissions.")
        return 3

    except NomadConnectionError as exc:
        console.print(f"[red]✗ Connection error:[/red] {exc}")
        console.print(
            "[yellow]Hint:[/yellow] Check endpoint reachability (LAN/Tailscale/SSH tunnel)."
        )
        return 4

    finally:
        client.close()


def run_submit_cancel(*, submission_id: str) -> int:
    submit_client = _submit_service_client()
    if not submit_client:
        console.print("[red]✗ Submit service not configured.[/red]")
        console.print("[yellow]Hint:[/yellow] Set FEDCTL_SUBMIT_ENDPOINT or repo submit.endpoint.")
        return 1
    try:
        record = submit_client.cancel_submission(submission_id)
    except SubmitServiceError as exc:
        console.print(f"[red]✗ Submit service error:[/red] {exc}")
        return 1
    resolved_id = record.get("submission_id", submission_id)
    status = record.get("status", "-")
    _print_ok(f"Cancelled submission: {resolved_id}")
    console.print(f"[bold]Status:[/bold] {status}")
    return 0


def run_submit_logs(
    *,
    submission_id: str,
    job: str,
    task: str | None,
    stderr: bool,
    follow: bool,
    index: int,
) -> int:
    submit_client = _submit_service_client()
    if submit_client:
        try:
            if follow:
                _print_streamed_logs(
                    submit_client.stream_logs(
                        submission_id,
                        job=job,
                        task=task,
                        stderr=stderr,
                        index=index,
                    )
                )
                return 0
            logs = submit_client.get_logs(
                submission_id,
                job=job,
                task=task,
                stderr=stderr,
                follow=follow,
                index=index,
            )
        except KeyboardInterrupt:
            return 130
        except SubmitServiceError as exc:
            console.print(f"[red]✗ Submit service error:[/red] {exc}")
            return 1
        _print_structured_logs(logs)
        return 0

    cfg = load_config()
    try:
        eff = get_effective_config(cfg)
    except ValueError as exc:
        console.print(f"[red]✗ Config error:[/red] {exc}")
        return 1

    client = NomadClient(eff)
    try:
        allocs = client.job_allocations(submission_id)
        alloc = _latest_alloc(allocs)
        if not alloc:
            console.print("[red]✗ No allocations found for submission.[/red]")
            return 1
        alloc_id = alloc.get("ID")
        if not isinstance(alloc_id, str):
            console.print("[red]✗ Allocation ID missing.[/red]")
            return 1
        resolved_task = task or "submit"
        logs = client.alloc_logs(alloc_id, resolved_task, stderr=stderr, follow=follow)
        _print_structured_logs(logs)
        return 0

    except NomadTLSError as exc:
        console.print(f"[red]✗ TLS error:[/red] {exc}")
        return 2

    except NomadHTTPError as exc:
        console.print(f"[red]✗ HTTP error:[/red] {exc}")
        if getattr(exc, "status_code", None) == 404:
            console.print("[yellow]Hint:[/yellow] Submission ID not found.")
        elif getattr(exc, "status_code", None) == 403:
            console.print("[yellow]Hint:[/yellow] Token/ACL invalid or missing permissions.")
        return 3

    except NomadConnectionError as exc:
        console.print(f"[red]✗ Connection error:[/red] {exc}")
        console.print(
            "[yellow]Hint:[/yellow] Check endpoint reachability (LAN/Tailscale/SSH tunnel)."
        )
        return 4

    finally:
        client.close()


_STEP_LINE_RE = re.compile(r"^step\s+\d+/\d+:", re.IGNORECASE)


def _print_streamed_logs(lines: Iterable[str]) -> None:
    printed = False
    previous_blank = True
    for line in lines:
        stripped = _plain(line).strip()
        is_step = bool(_STEP_LINE_RE.match(stripped))
        if is_step and printed and not previous_blank:
            console.print()

        rendered = Text.from_ansi(line)
        _style_log_line(rendered, stripped)
        console.print(rendered)
        printed = True
        previous_blank = stripped == ""


def _print_structured_logs(logs: str) -> None:
    if not logs:
        return

    printed = False
    previous_blank = True
    for raw_line in logs.splitlines(keepends=True):
        has_newline = raw_line.endswith("\n")
        line = raw_line[:-1] if has_newline else raw_line
        stripped = _plain(line).strip()
        is_step = bool(_STEP_LINE_RE.match(stripped))
        if is_step and printed and not previous_blank:
            console.print()

        rendered = Text.from_ansi(line)
        _style_log_line(rendered, stripped)
        console.print(rendered, end="\n" if has_newline else "")
        printed = True
        previous_blank = stripped == ""

    if printed and not logs.endswith("\n"):
        console.print()

    if not printed:
        rendered = Text.from_ansi(logs)
        _style_log_line(rendered, _plain(logs).strip())
        console.print(rendered, end="" if logs.endswith("\n") else "\n")


def _plain(value: str) -> str:
    return Text.from_ansi(value).plain


def _style_log_line(text: Text, stripped: str) -> None:
    lowered = stripped.lower()
    if _STEP_LINE_RE.match(stripped):
        text.stylize("bold cyan")
        return
    if stripped.startswith("✓") or lowered == "success":
        text.stylize("green")
        return
    if stripped.startswith("✗"):
        text.stylize("bold red")
        return
    if lowered.startswith("warning"):
        text.stylize("yellow")
        return
    if lowered.startswith("hint:") or lowered.startswith("note:"):
        text.stylize("bright_yellow")
        return
    if lowered.startswith("loading project configuration"):
        text.stylize("cyan")
        return
    if lowered.startswith("alloc status:"):
        text.highlight_regex(r"\brunning\b", "green")
        text.highlight_regex(r"\b(pending|starting)\b", "yellow")
        text.highlight_regex(r"\b(failed|lost|dead)\b", "red")
        return
    if lowered.startswith("manifest:") or lowered.startswith("/"):
        text.stylize("bright_black")


_ACTIVE_SUBMISSION_STATUSES = {"queued", "running", "blocked"}


def run_submit_ls(*, limit: int, status_filter: str = "active") -> int:
    submit_client = _submit_service_client()
    if submit_client:
        try:
            entries = submit_client.list_submissions(limit=limit, status_filter=status_filter)
        except SubmitServiceError as exc:
            console.print(f"[red]✗ Submit service error:[/red] {exc}")
            return 1
        if not entries:
            console.print("[yellow]No submissions recorded.[/yellow]")
            return 0
        rows = []
        for entry in entries:
            if not _submit_ls_matches_status(entry.get("status"), status_filter):
                continue
            submission_id = entry.get("submission_id", "-")
            experiment = entry.get("experiment", "-")
            created_at = entry.get("created_at", "-")
            namespace = entry.get("namespace") or "-"
            rows.append([submission_id, experiment, namespace, created_at])
        if not rows:
            console.print("[yellow]No matching submissions.[/yellow]")
            return 0
        print_table("Submissions", ["ID", "Experiment", "Namespace", "Created"], rows)
        return 0

    try:
        entries = load_submissions()
    except StateError as exc:
        console.print(f"[red]✗ State error:[/red] {exc}")
        return 1

    if not entries:
        console.print("[yellow]No submissions recorded.[/yellow]")
        return 0

    rows = []
    filtered_entries = [
        entry for entry in entries if _submit_ls_matches_status(entry.get("status"), status_filter)
    ]
    display_limit = max(limit, 0) or len(filtered_entries)
    for entry in filtered_entries[:display_limit]:
        submission_id = entry.get("submission_id", "-")
        experiment = entry.get("experiment", "-")
        created_at = entry.get("created_at", "-")
        namespace = entry.get("namespace") or "-"
        rows.append([submission_id, experiment, namespace, created_at])
    if not rows:
        console.print("[yellow]No matching submissions.[/yellow]")
        return 0
    print_table("Submissions", ["ID", "Experiment", "Namespace", "Created"], rows)
    return 0


def _submit_ls_matches_status(status: object, status_filter: str) -> bool:
    value = str(status or "")
    if status_filter == "all":
        return True
    if status_filter == "active":
        return value in _ACTIVE_SUBMISSION_STATUSES
    return value == status_filter


def run_submit_purge(*, submission_id: str | None = None) -> int:
    submit_client = _submit_service_client()
    if submit_client:
        try:
            if submission_id:
                submit_client.purge_submission(submission_id)
                console.print(
                    f"[green]✓ Purged submit-service record:[/green] {submission_id}"
                )
            else:
                submit_client.purge_submissions()
                console.print("[green]✓ Cleared submit-service history.[/green]")
        except SubmitServiceError as exc:
            console.print(f"[red]✗ Submit service error:[/red] {exc}")
            return 1
    else:
        console.print(
            "[yellow]![/yellow] Submit service not configured; skipping remote purge."
        )

    try:
        if submission_id:
            path = clear_submission(submission_id)
        else:
            path = clear_submissions()
    except Exception as exc:
        if submission_id:
            console.print(f"[red]✗ Failed to purge local submission:[/red] {exc}")
        else:
            console.print(f"[red]✗ Failed to clear local history:[/red] {exc}")
        return 1
    if submission_id:
        console.print(f"[green]✓ Purged local submission:[/green] {submission_id}")
        console.print(f"[dim]{path}[/dim]")
    else:
        console.print(f"[green]✓ Cleared local history:[/green] {path}")
    return 0


def run_submit_results(
    *,
    submission_id: str,
    download: bool = False,
    out: str | None = None,
) -> int:
    submit_client = _submit_service_client()
    if not submit_client:
        console.print("[red]✗ Submit service not configured.[/red]")
        console.print("[yellow]Hint:[/yellow] Set FEDCTL_SUBMIT_ENDPOINT or repo submit.endpoint.")
        return 1
    try:
        record = submit_client.get_submission(submission_id)
    except SubmitServiceError as exc:
        console.print(f"[red]✗ Submit service error:[/red] {exc}")
        return 1

    artifacts = record.get("result_artifacts")
    urls: list[str] = []
    if isinstance(artifacts, list):
        urls = [u for u in artifacts if isinstance(u, str)]
    if not urls:
        result_location = record.get("result_location")
        if isinstance(result_location, str) and result_location:
            urls = [result_location]

    if not urls:
        console.print("[yellow]No result artifacts recorded.[/yellow]")
        return 0

    if not download:
        for url in urls:
            print(url)
        return 0

    out_path = Path(out).expanduser() if out else Path.cwd()
    if len(urls) > 1:
        if out and out_path.exists() and out_path.is_file():
            console.print("[red]✗ --out must be a directory when multiple artifacts exist.[/red]")
            return 1
        out_path.mkdir(parents=True, exist_ok=True)
    else:
        if out:
            out_path = Path(out).expanduser()
            if out_path.exists() and out_path.is_dir():
                out_path = out_path / _url_basename(urls[0])
        else:
            out_path = Path.cwd() / _url_basename(urls[0])

    for url in urls:
        dest = out_path
        if len(urls) > 1:
            dest = out_path / _url_basename(url)
        try:
            _download_url(url, dest)
        except OSError as exc:
            console.print(f"[red]✗ Download failed:[/red] {exc}")
            return 1
        console.print(f"[green]✓ Downloaded:[/green] {dest}")
    return 0


def run_submit_inventory(
    *,
    include_allocs: bool = False,
    json_output: bool = False,
    status: str | None = None,
    node_class: str | None = None,
    device_type: str | None = None,
    detail: bool = False,
) -> int:
    submit_client = _submit_service_client()
    if not submit_client:
        console.print("[red]✗ Submit service not configured.[/red]")
        console.print("[yellow]Hint:[/yellow] Set FEDCTL_SUBMIT_ENDPOINT or repo submit.endpoint.")
        return 1
    try:
        nodes = submit_client.list_nodes(
            include_allocs=include_allocs or detail,
            status=status,
            node_class=node_class,
            device_type=device_type,
        )
    except SubmitServiceError as exc:
        console.print(f"[red]✗ Submit service error:[/red] {exc}")
        return 1

    if json_output:
        print(json.dumps(nodes, indent=2, sort_keys=True))
        return 0

    rows = []
    for node in nodes:
        resources = node.get("resources") if isinstance(node.get("resources"), dict) else {}
        total_cpu = resources.get("total_cpu")
        total_mem = resources.get("total_mem")
        used_cpu = resources.get("used_cpu")
        used_mem = resources.get("used_mem")
        allocs = node.get("allocations") if isinstance(node.get("allocations"), dict) else None
        if allocs:
            alloc_count = allocs.get("count", "-")
            running_jobs = allocs.get("running_jobs", [])
            running_jobs_count = (
                len(running_jobs) if isinstance(running_jobs, list) else "-"
            )
        else:
            alloc_count = "-"
            running_jobs_count = "-"
        rows.append(
            [
                node.get("name") or node.get("id") or "-",
                node.get("status") or "-",
                node.get("node_class") or "-",
                node.get("device_type") or "-",
                _format_pair(used_cpu, total_cpu),
                _format_pair(used_mem, total_mem),
                alloc_count,
                running_jobs_count,
            ]
        )
    print_table(
        "Nomad Inventory",
        ["Node", "Status", "Class", "DeviceType", "CPU", "Mem", "Allocs", "RunningJobs"],
        rows,
    )

    if detail:
        _print_inventory_detail(nodes)
    return 0


def _build_project_archive(
    project_root: Path,
    project_name: str,
    *,
    repo_config_path: Path | None = None,
    experiment_config_path: Path | None = None,
    experiment_config_arcname: str | None = None,
) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="fedctl-submit-"))
    archive_path = temp_dir / f"{project_name}.tar.gz"
    replace_rel_path = Path(experiment_config_arcname) if experiment_config_arcname else None
    with tarfile.open(archive_path, "w:gz") as tar:
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if d not in _ARCHIVE_SKIP_DIRS]
            rel_root = Path(root).relative_to(project_root)
            for name in files:
                if name in _ARCHIVE_SKIP_DIRS:
                    continue
                full_path = Path(root) / name
                rel_path = rel_root / name if rel_root != Path(".") else Path(name)
                if replace_rel_path is not None and rel_path == replace_rel_path:
                    continue
                arcname = Path(project_root.name) / rel_path
                tar.add(full_path, arcname=arcname)
        local_repo_cfg = project_root / ".fedctl" / "fedctl.yaml"
        if repo_config_path is not None and repo_config_path.exists():
            arcname = Path(project_root.name) / ".fedctl" / "fedctl.yaml"
            tar.add(repo_config_path, arcname=arcname)
        elif local_repo_cfg.exists():
            arcname = Path(project_root.name) / ".fedctl" / "fedctl.yaml"
            tar.add(local_repo_cfg, arcname=arcname)
        if (
            experiment_config_path is not None
            and experiment_config_path.exists()
            and experiment_config_arcname
        ):
            arcname = Path(project_root.name) / experiment_config_arcname
            tar.add(experiment_config_path, arcname=arcname)
    return archive_path


def _repo_supernodes(repo_cfg: dict[str, object]) -> dict[str, int]:
    deploy = repo_cfg.get("deploy")
    if not isinstance(deploy, dict):
        return {}
    raw = deploy.get("supernodes")
    if not isinstance(raw, dict):
        return {}

    counts: dict[str, int] = {}
    for key, value in raw.items():
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            counts[str(key)] = count
    return counts


def _repo_allow_oversubscribe(repo_cfg: dict[str, object]) -> bool | None:
    deploy = repo_cfg.get("deploy")
    if not isinstance(deploy, dict):
        return None
    placement = deploy.get("placement")
    if not isinstance(placement, dict):
        return None
    value = placement.get("allow_oversubscribe")
    return bool(value) if isinstance(value, bool) else None


def _runner_args(
    *,
    project_dir_name: str,
    exp_name: str,
    experiment_config: str | None,
    run_config_overrides: list[str] | None,
    seed: int | None,
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
    federation: str,
    stream: bool,
    timeout_seconds: int,
    verbose: bool,
    destroy: bool,
) -> list[str]:
    project_dir = project_dir_name or "."
    use_typed_supernodes = bool(supernodes)
    args = [
        "-m",
        "fedctl.submit.runner",
        "--path",
        project_dir,
        "--project-dir",
        project_dir_name,
        "--exp",
        exp_name,
        "--flwr-version",
        flwr_version,
        "--timeout",
        str(timeout_seconds),
        "--federation",
        federation,
    ]
    if experiment_config:
        args.extend(["--experiment-config", experiment_config])
    for override in run_config_overrides or []:
        args.extend(["--run-config-override", override])
    if seed is not None:
        args.extend(["--seed", str(seed)])
    if not use_typed_supernodes:
        args.extend(["--num-supernodes", str(num_supernodes)])
    if image:
        args.extend(["--image", image])
    if no_cache:
        args.append("--no-cache")
    if platform:
        args.extend(["--platform", platform])
    if context:
        args.extend(["--context", context])
    if push:
        args.append("--push")
    if not auto_supernodes:
        args.append("--no-auto-supernodes")
    if supernodes:
        for value in supernodes:
            args.extend(["--supernodes", value])
    if net:
        for value in net:
            args.extend(["--net", value])
    if allow_oversubscribe is True:
        args.append("--allow-oversubscribe")
    elif allow_oversubscribe is False:
        args.append("--no-allow-oversubscribe")
    if not stream:
        args.append("--no-stream")
    if verbose:
        args.append("--verbose")
    if not destroy:
        args.append("--no-destroy")
    return args


def _runner_env(
    eff: object,
    *,
    submission_id: str | None = None,
    result_store: str | None = None,
    image_registry: str | None = None,
    attempt_started_at: str | None = None,
    experiment_config: str | None = None,
    repo_config_label: str | None = None,
) -> dict[str, str]:
    env: dict[str, str] = {}
    endpoint = getattr(eff, "endpoint", None)
    namespace = getattr(eff, "namespace", None)
    token = getattr(eff, "nomad_token", None)
    profile = getattr(eff, "profile_name", None)
    if endpoint:
        env["FEDCTL_ENDPOINT"] = _rewrite_local_endpoint(str(endpoint))
    if namespace:
        env["FEDCTL_NAMESPACE"] = str(namespace)
    if profile:
        env["FEDCTL_PROFILE"] = str(profile)
    if token:
        env["NOMAD_TOKEN"] = str(token)
    if submission_id:
        env["FEDCTL_SUBMISSION_ID"] = str(submission_id)
    if result_store:
        env["FEDCTL_RESULT_STORE"] = str(result_store)
    if image_registry:
        env["FEDCTL_IMAGE_REGISTRY"] = str(image_registry)
    if attempt_started_at:
        env["FEDCTL_ATTEMPT_STARTED_AT"] = str(attempt_started_at)
    if experiment_config:
        env["FEDCTL_EXPERIMENT_CONFIG"] = str(experiment_config)
    if repo_config_label:
        env["FEDCTL_REPO_CONFIG_LABEL"] = str(repo_config_label)
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    ):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _timestamp_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _original_submit_request(
    *,
    path: str,
    project_root: Path,
    experiment: str,
    experiment_config: str | None,
    run_config_overrides: list[str] | None,
    seed: int | None,
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
    repo_config: str | None,
    federation: str,
    stream: bool,
    timeout_seconds: int,
    verbose: bool,
    destroy: bool,
    submit_image: str | None,
    artifact_store: str | None,
    priority: int,
) -> dict[str, object]:
    cwd = Path.cwd()
    use_typed_supernodes = bool(supernodes)
    options: dict[str, object] = {
        "path": path,
        "experiment": experiment,
        "flwr_version": flwr_version,
        "federation": federation,
        "timeout": timeout_seconds,
        "priority": priority,
        "destroy": destroy,
        "stream": stream,
        "auto_supernodes": auto_supernodes,
    }
    if experiment_config:
        options["experiment_config"] = experiment_config
    if run_config_overrides:
        options["run_config_overrides"] = list(run_config_overrides)
    if seed is not None:
        options["seed"] = seed
    if not use_typed_supernodes:
        options["num_supernodes"] = num_supernodes
    if image:
        options["image"] = image
    if no_cache:
        options["no_cache"] = True
    if platform:
        options["platform"] = platform
    if context:
        options["context"] = context
    if push:
        options["push"] = True
    if supernodes:
        options["supernodes"] = supernodes
    if net:
        options["net"] = net
    if allow_oversubscribe is not None:
        options["allow_oversubscribe"] = allow_oversubscribe
    if repo_config:
        options["repo_config"] = repo_config
    if verbose:
        options["verbose"] = True
    if submit_image:
        options["submit_image"] = submit_image
    if artifact_store:
        options["artifact_store"] = artifact_store
    return {
        "path_input": path,
        "project_root": str(project_root.resolve()),
        "cwd": str(cwd.resolve()),
        "command_preview": _submit_command_preview(options),
        "options": options,
    }


def _submit_command_preview(options: dict[str, object]) -> str:
    parts = ["fedctl", "submit", "run", str(options["path"])]
    if options.get("experiment"):
        parts.extend(["--exp", str(options["experiment"])])
    if options.get("experiment_config"):
        parts.extend(["--experiment-config", str(options["experiment_config"])])
    for value in options.get("run_config_overrides") or []:
        parts.extend(["--run-config-override", str(value)])
    if options.get("seed") is not None:
        parts.extend(["--seed", str(options["seed"])])
    if options.get("image"):
        parts.extend(["--image", str(options["image"])])
    if options.get("no_cache"):
        parts.append("--no-cache")
    if options.get("platform"):
        parts.extend(["--platform", str(options["platform"])])
    if options.get("context"):
        parts.extend(["--context", str(options["context"])])
    if options.get("push"):
        parts.append("--push")
    if options.get("num_supernodes") is not None:
        parts.extend(["--num-supernodes", str(options["num_supernodes"])])
    if options.get("auto_supernodes") is False:
        parts.append("--no-auto-supernodes")
    for value in options.get("supernodes") or []:
        parts.extend(["--supernodes", str(value)])
    for value in options.get("net") or []:
        parts.extend(["--net", str(value)])
    if options.get("allow_oversubscribe") is True:
        parts.append("--allow-oversubscribe")
    elif options.get("allow_oversubscribe") is False:
        parts.append("--no-allow-oversubscribe")
    if options.get("repo_config"):
        parts.extend(["--repo-config", str(options["repo_config"])])
    if options.get("federation"):
        parts.extend(["--federation", str(options["federation"])])
    if options.get("stream") is False:
        parts.append("--no-stream")
    if options.get("timeout") is not None:
        parts.extend(["--timeout", str(options["timeout"])])
    if options.get("verbose"):
        parts.append("--verbose")
    if options.get("destroy") is False:
        parts.append("--no-destroy")
    if options.get("submit_image"):
        parts.extend(["--submit-image", str(options["submit_image"])])
    if options.get("artifact_store"):
        parts.extend(["--artifact-store", str(options["artifact_store"])])
    if options.get("priority") is not None:
        parts.extend(["--priority", str(options["priority"])])
    return shlex.join(parts)


def _submit_seed_sweep(
    *,
    seed_sweep: tuple[int, ...],
    base_experiment: str,
    path: str,
    experiment_config: str | None,
    run_config_overrides: list[str] | None,
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
    repo_config: str | None,
    timeout_seconds: int,
    federation: str,
    stream: bool,
    verbose: bool,
    destroy: bool,
    submit_image: str | None,
    artifact_store: str | None,
    priority: int | None,
) -> int:
    console.print(f"[cyan]Detected seed sweep:[/cyan] {', '.join(str(seed) for seed in seed_sweep)}")
    failures = 0
    for sweep_seed in seed_sweep:
        child_experiment = normalize_experiment_name(f"{base_experiment}-seed{sweep_seed}")
        console.print()
        console.print(
            f"[bold cyan]Seed[/bold cyan] [bold]-[/bold] {sweep_seed} -> {child_experiment}"
        )
        status = run_submit(
            path=path,
            experiment_config=experiment_config,
            run_config_overrides=run_config_overrides,
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
            repo_config=repo_config,
            experiment=child_experiment,
            timeout_seconds=timeout_seconds,
            federation=federation,
            stream=stream,
            verbose=verbose,
            destroy=destroy,
            submit_image=submit_image,
            artifact_store=artifact_store,
            priority=priority,
        )
        if status != 0:
            failures += 1
    return 0 if failures == 0 else 1


def _rewrite_local_endpoint(endpoint: str) -> str:
    try:
        from urllib.parse import urlparse
    except Exception:
        return endpoint

    parsed = urlparse(endpoint)
    host = parsed.hostname
    if host not in {"127.0.0.1", "localhost"}:
        return endpoint
    scheme = parsed.scheme or "http"
    port = parsed.port or (443 if scheme == "https" else 80)
    return f"{scheme}://${{attr.unique.network.ip-address}}:{port}"


def _submit_service_client(
    *,
    repo_cfg: dict[str, object] | None = None,
    repo_config: str | None = None,
) -> SubmitServiceClient | None:
    endpoint = os.environ.get("FEDCTL_SUBMIT_ENDPOINT")
    token = os.environ.get("FEDCTL_SUBMIT_TOKEN")
    user = os.environ.get("FEDCTL_SUBMIT_USER")

    if repo_cfg is None:
        repo_cfg = resolve_repo_config(
            repo_config=repo_config,
            include_profile=True,
        ).data

    submit_cfg = parse_submit_repo_config(repo_cfg or {})
    if not endpoint:
        endpoint = submit_cfg.endpoint
    if not token:
        token = submit_cfg.token
    if not user:
        user = submit_cfg.user

    if not endpoint:
        return None
    return SubmitServiceClient(endpoint=endpoint, token=token, user=user)


def _timestamp_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _default_submit_experiment_name(
    *,
    project_name: str,
    resolved_experiment_config: object,
    run_config_overrides: list[str] | None,
    seed: int | None,
    network_profile_label: str | None = None,
) -> str:
    config_path = getattr(resolved_experiment_config, "resolved_path", None)
    if not isinstance(config_path, Path):
        return f"{project_name}-{_timestamp_compact()}"
    try:
        materialized = materialize_run_config(
            base_path=config_path,
            run_config_overrides=run_config_overrides,
        )
    except ProjectError:
        raise
    effective_path = materialized or config_path
    try:
        data = tomlkit.parse(effective_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProjectError(f"Experiment config not readable: {effective_path}") from exc
    except Exception as exc:
        raise ProjectError(f"Experiment config not parseable: {effective_path}") from exc

    method = _experiment_name_token(data.get("method"))
    task = _experiment_name_token(data.get("task"))
    parts = [token for token in (task, method) if token]
    regime = _experiment_regime_token(data)
    if regime:
        parts.append(regime)
    parts.append(_experiment_config_token(effective_path))
    if network_profile_label:
        parts.append(f"profile-{_experiment_name_token(network_profile_label)}")

    node_count = _experiment_node_count(data)
    if node_count is not None:
        parts.append(f"n{node_count}")

    seed_value = seed if seed is not None else _experiment_seed(data)
    if seed_value is not None:
        parts.append(f"seed{seed_value}")

    return "-".join(parts) if parts else f"{project_name}-{_timestamp_compact()}"


def _experiment_name_token(value: object) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")


def _experiment_regime_token(data: dict[str, object]) -> str:
    partitioning = _experiment_name_token(data.get("partitioning"))
    if not partitioning:
        return ""
    if partitioning == "iid":
        return "iid"
    return "noniid"


def _experiment_config_token(path: Path) -> str:
    digest = hashlib.blake2s(path.read_bytes(), digest_size=4).hexdigest()
    return f"cfg{digest}"


def _experiment_node_count(data: dict[str, object]) -> int | None:
    for key in ("min-available-nodes", "min-train-nodes", "min-evaluate-nodes"):
        value = data.get(key)
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            return count
    return None


def _experiment_seed(data: dict[str, object]) -> int | None:
    value = data.get("seed")
    try:
        seed = int(value)
    except (TypeError, ValueError):
        return None
    return seed if seed >= 0 else None


def _record_submission_state(
    *,
    submission_id: str,
    experiment: str,
    status: str,
    namespace: str | None,
    artifact_url: str,
    submit_image: str,
    node_class: str,
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    record = SubmissionRecord(
        submission_id=submission_id,
        experiment=experiment,
        created_at=created_at,
        status=status,
        namespace=namespace,
        artifact_url=artifact_url,
        submit_image=submit_image,
        node_class=node_class,
    )
    try:
        record_submission(record)
    except StateError as exc:
        console.print(f"[yellow]Warning:[/yellow] Failed to record submission: {exc}")


def _latest_alloc(allocs: object) -> dict[str, object] | None:
    if not isinstance(allocs, list) or not allocs:
        return None
    candidates = [a for a in allocs if isinstance(a, dict)]
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


def _job_status(job: object) -> str:
    if isinstance(job, dict):
        status = job.get("Status")
        if isinstance(status, str):
            return status
    return "unknown"


def _alloc_status(alloc: object) -> str | None:
    if isinstance(alloc, dict):
        status = alloc.get("ClientStatus")
        if isinstance(status, str):
            return status
    return None


def _format_pair(used: object, total: object) -> str:
    if used is None and total is None:
        return "-"
    used_val = str(used) if used is not None else "?"
    total_val = str(total) if total is not None else "?"
    return f"{used_val}/{total_val}"


def _url_basename(url: str) -> str:
    path = urlparse(url).path
    base = os.path.basename(path)
    return base or "artifact"


def _download_url(url: str, dest: Path) -> None:
    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as r:
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as handle:
            for chunk in r.iter_bytes():
                handle.write(chunk)


def _print_inventory_detail(nodes: list[dict[str, object]]) -> None:
    for node in nodes:
        allocs = node.get("allocations")
        if not isinstance(allocs, dict):
            continue
        items = allocs.get("items")
        if not isinstance(items, list) or not items:
            continue
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            resources = item.get("resources") if isinstance(item.get("resources"), dict) else {}
            cpu = resources.get("cpu")
            mem = resources.get("mem")
            tasks = item.get("tasks")
            task_names = []
            if isinstance(tasks, list):
                for task in tasks:
                    if isinstance(task, dict) and isinstance(task.get("name"), str):
                        task_names.append(task["name"])
            rows.append(
                [
                    item.get("id") or "-",
                    item.get("job_id") or "-",
                    item.get("status") or "-",
                    _format_pair(cpu, None),
                    _format_pair(mem, None),
                    ", ".join(task_names) if task_names else "-",
                ]
            )
        node_label = node.get("name") or node.get("id") or "node"
        print_table(
            f"Allocations for {node_label}",
            ["Alloc", "Job", "Status", "CPU", "Mem", "Tasks"],
            rows,
        )
