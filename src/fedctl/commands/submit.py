from __future__ import annotations

import os
import json
import re
from urllib.parse import urlparse
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from rich.text import Text
import httpx

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.config.repo import load_repo_config, parse_submit_repo_config, get_image_registry
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.project.errors import ProjectError
from fedctl.project.flwr_inspect import inspect_flwr_project
from fedctl.submit.artifact import ArtifactUploadError, upload_artifact
from fedctl.submit.client import SubmitServiceClient, SubmitServiceError
from fedctl.submit.render import SubmitJobSpec, render_submit_job
from fedctl.deploy.spec import normalize_experiment_name
from fedctl.build.tagging import default_image_tag
from fedctl.state.errors import StateError
from fedctl.state.submissions import (
    SubmissionRecord,
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


def _print_step(idx: int, total: int, title: str) -> None:
    if idx > 1:
        console.print()
    console.print(f"[bold cyan]Step {idx}/{total}[/bold cyan] [bold]-[/bold] {title}")


def _print_ok(message: str) -> None:
    console.print(f"[green]✓[/green] {message}")


def run_submit(
    *,
    path: str,
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
    no_wait: bool,
    federation: str,
    stream: bool,
    verbose: bool,
    destroy: bool,
    submit_node_class: str | None,
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

    exp_name = normalize_experiment_name(
        experiment or f"{project_name}-{_timestamp_compact()}"
    )
    submit_client = _submit_service_client(repo_config=repo_config)
    submission_id = None
    if not submit_client:
        submission_id = f"submit-{exp_name}-{_timestamp_compact()}"
        _print_ok(f"Submission ID: {submission_id}")

    repo_cfg = _load_repo_cfg(repo_config=repo_config)
    submit_cfg = parse_submit_repo_config(repo_cfg)
    resolved_node_class = submit_node_class or submit_cfg.node_class or "submit"
    resolved_image = submit_image or submit_cfg.image
    resolved_artifact_store = artifact_store or submit_cfg.artifact_store
    if not resolved_image:
        console.print("[red]✗ Missing submit image.[/red] Use --submit-image or repo config.")
        return 1
    if not resolved_artifact_store:
        console.print(
            "[red]✗ Missing artifact store.[/red] Use --artifact-store or repo config."
        )
        return 1

    resolved_superexec_image = image
    if not resolved_superexec_image:
        registry = get_image_registry(repo_cfg)
        project_name_for_tag = project_name or "project"
        resolved_superexec_image = default_image_tag(
            project_name_for_tag,
            repo_root=info.root,
            registry=registry,
        )

    repo_cfg_path = _resolve_repo_cfg_path(repo_config=repo_config)

    _print_step(2, 4, "Package project")
    try:
        archive_path = _build_project_archive(
            info.root,
            project_name,
            repo_config_path=repo_cfg_path,
        )
    except OSError as exc:
        console.print(f"[red]✗ Archive error:[/red] {exc}")
        return 1
    _print_ok(f"Created archive: {archive_path}")

    _print_step(3, 4, "Upload artifact")
    try:
        artifact_url = upload_artifact(archive_path, resolved_artifact_store)
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
                    "node_class": resolved_node_class,
                    "args": _runner_args(
                        project_root=info.root,
                        artifact_dest="/local/project",
                        project_dir_name=project_path.name,
                        exp_name=exp_name,
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
                    "env": _runner_env(eff, result_store=resolved_artifact_store),
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
            node_class=resolved_node_class,
            image=resolved_image,
            artifact_url=artifact_url,
            namespace=eff.namespace or "default",
            args=_runner_args(
                project_root=info.root,
                artifact_dest="/local/project",
                project_dir_name=project_path.name,
                exp_name=exp_name,
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
            env=_runner_env(eff, result_store=resolved_artifact_store),
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
        namespace=eff.namespace,
        artifact_url=artifact_url,
        submit_image=resolved_image,
        node_class=resolved_node_class,
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


def run_submit_ls(*, limit: int, active: bool = False) -> int:
    submit_client = _submit_service_client()
    if submit_client:
        try:
            entries = submit_client.list_submissions(limit=limit)
        except SubmitServiceError as exc:
            console.print(f"[red]✗ Submit service error:[/red] {exc}")
            return 1
        if not entries:
            console.print("[yellow]No submissions recorded.[/yellow]")
            return 0
        rows = []
        for entry in entries:
            if active and entry.get("status") not in {"queued", "running", "blocked"}:
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
    display_limit = max(limit, 0) or len(entries)
    for entry in entries[:display_limit]:
        if active and entry.get("status") not in {"queued", "running", "blocked"}:
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


def run_submit_purge() -> int:
    submit_client = _submit_service_client()
    if submit_client:
        try:
            submit_client.purge_submissions()
            console.print("[green]✓ Cleared submit-service history.[/green]")
        except SubmitServiceError as exc:
            console.print(f"[red]✗ Submit service error:[/red] {exc}")
            return 1
    else:
        console.print("[yellow]![/yellow] Submit service not configured; skipping remote purge.")

    try:
        path = clear_submissions()
    except Exception as exc:
        console.print(f"[red]✗ Failed to clear local history:[/red] {exc}")
        return 1
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
) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="fedctl-submit-"))
    archive_path = temp_dir / f"{project_name}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if d not in _ARCHIVE_SKIP_DIRS]
            rel_root = Path(root).relative_to(project_root)
            for name in files:
                if name in _ARCHIVE_SKIP_DIRS:
                    continue
                full_path = Path(root) / name
                rel_path = rel_root / name if rel_root != Path(".") else Path(name)
                arcname = Path(project_root.name) / rel_path
                tar.add(full_path, arcname=arcname)
        local_repo_cfg = project_root / ".fedctl" / "fedctl.yaml"
        if (
            repo_config_path is not None
            and repo_config_path.exists()
            and not local_repo_cfg.exists()
        ):
            arcname = Path(project_root.name) / ".fedctl" / "fedctl.yaml"
            tar.add(repo_config_path, arcname=arcname)
    return archive_path


def _runner_args(
    *,
    project_root: Path,
    artifact_dest: str,
    project_dir_name: str,
    exp_name: str,
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
        "--num-supernodes",
        str(num_supernodes),
        "--timeout",
        str(timeout_seconds),
        "--federation",
        federation,
    ]
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


def _runner_env(eff: object, *, result_store: str | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    endpoint = getattr(eff, "endpoint", None)
    namespace = getattr(eff, "namespace", None)
    token = getattr(eff, "nomad_token", None)
    profile = getattr(eff, "profile_name", None)
    tls_ca = getattr(eff, "tls_ca", None)
    tls_skip_verify = getattr(eff, "tls_skip_verify", None)
    if endpoint:
        env["FEDCTL_ENDPOINT"] = _rewrite_local_endpoint(str(endpoint))
    if namespace:
        env["FEDCTL_NAMESPACE"] = str(namespace)
    if profile:
        env["FEDCTL_PROFILE"] = str(profile)
    if token:
        env["NOMAD_TOKEN"] = str(token)
    if tls_ca:
        env["FEDCTL_TLS_CA"] = str(tls_ca)
    if tls_skip_verify is not None:
        env["FEDCTL_TLS_SKIP_VERIFY"] = "true" if tls_skip_verify else "false"
    if result_store:
        env["FEDCTL_RESULT_STORE"] = str(result_store)
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


def _load_repo_cfg(*, repo_config: str | None) -> dict[str, object]:
    path = _resolve_repo_cfg_path(repo_config=repo_config)
    if path:
        return load_repo_config(config_path=path)
    return {}


def _resolve_repo_cfg_path(*, repo_config: str | None) -> Path | None:
    if repo_config:
        path = Path(repo_config).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if path.exists():
            return path
        return None
    try:
        cfg = load_config()
        profile_cfg = cfg.profiles.get(cfg.active_profile)
        if profile_cfg and profile_cfg.repo_config:
            path = Path(profile_cfg.repo_config).expanduser()
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            if path.exists():
                return path
    except Exception:
        return None
    return None


def _submit_service_client(*, repo_config: str | None = None) -> SubmitServiceClient | None:
    endpoint = os.environ.get("FEDCTL_SUBMIT_ENDPOINT")
    token = os.environ.get("FEDCTL_SUBMIT_TOKEN")
    user = os.environ.get("FEDCTL_SUBMIT_USER")
    
    repo_cfg = _load_repo_cfg(repo_config=repo_config)
    submit_cfg = parse_submit_repo_config(repo_cfg)
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


def _record_submission_state(
    *,
    submission_id: str,
    experiment: str,
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
