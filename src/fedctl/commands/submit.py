from __future__ import annotations

import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.text import Text

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.config.repo import load_repo_config, parse_submit_repo_config
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.project.errors import ProjectError
from fedctl.project.flwr_inspect import inspect_flwr_project
from fedctl.submit.artifact import ArtifactUploadError, upload_artifact
from fedctl.submit.render import SubmitJobSpec, render_submit_job
from fedctl.deploy.spec import normalize_experiment_name
from fedctl.state.errors import StateError
from fedctl.state.submissions import SubmissionRecord, load_submissions, record_submission
from fedctl.util.console import print_table

console = Console()

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
    submit_node_class: str | None,
    submit_image: str | None,
    artifact_store: str | None,
    priority: int | None,
) -> int:
    project_path = Path(path)
    console.print("[bold]Step 1/4:[/bold] Inspect project")
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
    submission_id = f"submit-{exp_name}-{_timestamp_compact()}"
    console.print(f"[green]✓ Submission ID:[/green] {submission_id}")

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

    console.print("[bold]Step 2/4:[/bold] Package project")
    try:
        archive_path = _build_project_archive(info.root, project_name)
    except OSError as exc:
        console.print(f"[red]✗ Archive error:[/red] {exc}")
        return 1
    console.print(f"[green]✓ Created archive:[/green] {archive_path}")

    console.print("[bold]Step 3/4:[/bold] Upload artifact")
    try:
        artifact_url = upload_artifact(archive_path, resolved_artifact_store)
    except ArtifactUploadError as exc:
        console.print(f"[red]✗ Artifact upload error:[/red] {exc}")
        return 1
    console.print(f"[green]✓ Uploaded to:[/green] {artifact_url}")

    console.print("[bold]Step 4/4:[/bold] Submit Nomad job")
    cfg = load_config()
    try:
        eff = get_effective_config(cfg)
    except ValueError as exc:
        console.print(f"[red]✗ Config error:[/red] {exc}")
        return 1

    job = render_submit_job(
        SubmitJobSpec(
            job_name=submission_id,
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
                federation=federation,
                stream=stream,
                timeout_seconds=timeout_seconds,
                verbose=verbose,
            ),
            env=_runner_env(eff),
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
        submission_id=submission_id,
        experiment=exp_name,
        namespace=eff.namespace,
        artifact_url=artifact_url,
        submit_image=resolved_image,
        node_class=resolved_node_class,
    )
    console.print(f"[green]✓ Submitted job:[/green] {submission_id}")
    console.print(f"[blue]Next:[/blue] fedctl submit status {submission_id}")
    return 0


def run_submit_status(*, submission_id: str) -> int:
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
    task: str,
    stderr: bool,
    follow: bool,
) -> int:
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
        logs = client.alloc_logs(alloc_id, task, stderr=stderr, follow=follow)
        rendered = Text.from_ansi(logs)
        console.print(rendered, end="" if logs.endswith("\n") else "\n")
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


def run_submit_ls(*, limit: int) -> int:
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
        submission_id = entry.get("submission_id", "-")
        experiment = entry.get("experiment", "-")
        created_at = entry.get("created_at", "-")
        namespace = entry.get("namespace") or "-"
        rows.append([submission_id, experiment, namespace, created_at])
    print_table("Submissions", ["ID", "Experiment", "Namespace", "Created"], rows)
    return 0


def _build_project_archive(project_root: Path, project_name: str) -> Path:
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
    return args


def _runner_env(eff: object) -> dict[str, str]:
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
    if repo_config:
        return load_repo_config(config_path=Path(repo_config))
    try:
        cfg = load_config()
        profile_cfg = cfg.profiles.get(cfg.active_profile)
        if profile_cfg and profile_cfg.repo_config:
            return load_repo_config(config_path=Path(profile_cfg.repo_config))
    except Exception:
        return {}
    return {}


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
