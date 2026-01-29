from __future__ import annotations

import argparse
import os
import tarfile
import tempfile
import shutil
from pathlib import Path

from rich.console import Console
import httpx
import logging

from fedctl.commands.run import run_run
from fedctl.deploy import naming
from fedctl.deploy.plan import parse_supernodes

console = Console()
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fedctl submit runner")
    parser.add_argument("--path", default=".", help="Path to a Flower project")
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Expected project directory name inside the workspace",
    )
    parser.add_argument("--exp", dest="experiment")
    parser.add_argument("--flwr-version", default="1.23.0")
    parser.add_argument("--image")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--platform")
    parser.add_argument("--context")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--num-supernodes", type=int, default=2)
    parser.add_argument(
        "--no-auto-supernodes", action="store_true", help="Disable auto supernode count"
    )
    parser.add_argument("--supernodes", action="append")
    parser.add_argument("--net", action="append")
    parser.add_argument("--allow-oversubscribe", dest="allow_oversubscribe", action="store_true")
    parser.add_argument(
        "--no-allow-oversubscribe", dest="allow_oversubscribe", action="store_false"
    )
    parser.set_defaults(allow_oversubscribe=None)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--federation", default="remote-deployment")
    parser.add_argument("--no-stream", dest="stream", action="store_false")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    endpoint = os.environ.get("FEDCTL_ENDPOINT")
    namespace = os.environ.get("FEDCTL_NAMESPACE")
    profile = os.environ.get("FEDCTL_PROFILE")
    token = os.environ.get("NOMAD_TOKEN")
    tls_ca = os.environ.get("FEDCTL_TLS_CA")
    tls_skip_verify = _parse_bool_env("FEDCTL_TLS_SKIP_VERIFY")
    submission_id = os.environ.get("SUBMIT_SUBMISSION_ID")
    submit_service_endpoint = os.environ.get("SUBMIT_SERVICE_ENDPOINT")
    submit_service_token = os.environ.get("SUBMIT_SERVICE_TOKEN")

    # _print_docker_info()
    project_path = _resolve_project_path(Path(args.path), args.project_dir)
    _report_jobs(
        submission_id=submission_id,
        submit_service_endpoint=submit_service_endpoint,
        submit_service_token=submit_service_token,
        experiment=args.experiment,
        num_supernodes=args.num_supernodes,
        supernodes=args.supernodes,
    )
    exit_code = run_run(
        path=str(project_path),
        flwr_version=args.flwr_version,
        image=args.image,
        no_cache=args.no_cache,
        platform=args.platform,
        context=args.context,
        push=args.push,
        num_supernodes=args.num_supernodes,
        auto_supernodes=not args.no_auto_supernodes,
        supernodes=args.supernodes,
        net=args.net,
        allow_oversubscribe=args.allow_oversubscribe,
        experiment=args.experiment,
        timeout_seconds=args.timeout,
        federation=args.federation,
        stream=args.stream,
        verbose=args.verbose,
        profile=profile,
        endpoint=endpoint,
        namespace=namespace,
        token=token,
        tls_ca=tls_ca,
        tls_skip_verify=tls_skip_verify,
    )
    return exit_code


def _parse_bool_env(key: str) -> bool | None:
    value = os.environ.get(key)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return None


def _resolve_project_path(path: Path, project_dir: str | None) -> Path:
    # _print_tree(path.parent if path.parent != Path("") else Path("."), "workspace tree")

    if project_dir:
        candidate = path.parent / project_dir
        if candidate.exists():
            return candidate

    if path.exists():
        if path.is_dir():
            resolved = _find_project_dir(path)
            return resolved if resolved else path
        return path.parent

    base = path.parent
    extracted = _extract_archives_to_temp(base)
    if extracted and extracted.exists():
        # _print_tree(extracted, "extracted tree")
        if project_dir:
            candidate = extracted / project_dir
            if candidate.exists():
                return candidate
        resolved = _find_project_dir(extracted)
        return resolved if resolved else extracted

    # Fall back to the first directory inside the artifact destination.
    if base.exists():
        resolved = _find_project_dir(base)
        if resolved:
            return resolved
    return path


def _print_docker_info() -> None:
    docker_path = shutil.which("docker")
    console.print(f"[yellow]Debug:[/yellow] PATH={os.environ.get('PATH')}")
    if not docker_path:
        console.print("[yellow]Debug:[/yellow] docker not found on PATH")
        return
    console.print(f"[yellow]Debug:[/yellow] docker path: {docker_path}")


def _extract_archives_to_temp(base: Path) -> Path | None:
    if not base.exists():
        return None
    archive = None
    for entry in base.iterdir():
        if entry.is_file() and entry.name.endswith((".tar.gz", ".tgz", ".tar")):
            archive = entry
            break
    if not archive:
        return None
    temp_dir = Path(tempfile.mkdtemp(prefix="fedctl-submit-"))
    try:
        with tarfile.open(archive) as tar:
            tar.extractall(path=temp_dir)
    except tarfile.TarError:
        return None

    # If the archive contains a single top-level dir, use it.
    entries = [p for p in temp_dir.iterdir() if p.is_dir()]
    if len(entries) == 1:
        return entries[0]
    return temp_dir


def _find_project_dir(base: Path) -> Path | None:
    pyproject = base / "pyproject.toml"
    if pyproject.exists():
        return base
    candidates = []
    for entry in base.iterdir():
        if entry.is_dir() and (entry / "pyproject.toml").exists():
            candidates.append(entry)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _print_tree(base: Path, label: str, max_entries: int = 200) -> None:
    if not base.exists():
        console.print(f"[yellow]Debug:[/yellow] {label}: {base} does not exist")
        return
    lines = []
    for root, dirs, files in os.walk(base):
        dirs.sort()
        files.sort()
        rel_root = str(Path(root).relative_to(base)) or "."
        lines.append(f"{rel_root}/")
        for name in files:
            lines.append(f"  {name}")
        if len(lines) >= max_entries:
            lines.append("  ...")
            break
    console.print(f"[yellow]Debug:[/yellow] {label} {base}:\n" + "\n".join(lines))


def _report_jobs(
    *,
    submission_id: str | None,
    submit_service_endpoint: str | None,
    submit_service_token: str | None,
    experiment: str | None,
    num_supernodes: int,
    supernodes: list[str] | None,
) -> None:
    if not submission_id or not submit_service_endpoint or not experiment:
        return
    jobs = _build_jobs_report(
        experiment=experiment,
        num_supernodes=num_supernodes,
        supernodes=supernodes,
    )
    if not jobs:
        return
    url = submit_service_endpoint.rstrip("/") + f"/v1/submissions/{submission_id}/jobs"
    headers = {}
    if submit_service_token:
        headers["Authorization"] = f"Bearer {submit_service_token}"
    try:
        response = httpx.post(url, json={"jobs": jobs}, headers=headers, timeout=10.0)
    except httpx.HTTPError as exc:
        logger.warning("submit-service job report failed: %s", exc)
        console.print(f"[yellow]Warning:[/yellow] Job mapping report failed: {exc}")
        return
    if response.status_code >= 400:
        logger.warning(
            "submit-service job report failed: status=%s body=%s",
            response.status_code,
            response.text[:200],
        )
        console.print(
            f"[yellow]Warning:[/yellow] Job mapping report failed: {response.status_code}"
        )
        return
    logger.info("submit-service job report ok: submission_id=%s", submission_id)
    console.print("[green]✓ Reported job mapping to submit service[/green]")


def _build_jobs_report(
    *, experiment: str, num_supernodes: int, supernodes: list[str] | None
) -> dict[str, object]:
    placements = _supernode_placements_for_report(
        num_supernodes=num_supernodes, supernodes=supernodes
    )
    tasks = [_supernode_task_name(p["device_type"], p["instance_idx"]) for p in placements]
    clientapps = [
        naming.job_superexec_clientapp(
            experiment, p["instance_idx"], p["device_type"]
        )
        for p in placements
    ]
    return {
        "superlink": {
            "job_id": naming.job_superlink(experiment),
            "task": naming.job_superlink(experiment),
        },
        "supernodes": {
            "job_id": naming.job_supernodes(experiment),
            "tasks": tasks,
        },
        "superexec_serverapp": {
            "job_id": naming.job_superexec_serverapp(experiment),
            "task": naming.job_superexec_serverapp(experiment),
        },
        "superexec_clientapps": {
            "job_ids": clientapps,
        },
    }


def _supernode_placements_for_report(
    *, num_supernodes: int, supernodes: list[str] | None
) -> list[dict[str, object]]:
    placements: list[dict[str, object]] = []
    if supernodes:
        counts = parse_supernodes(supernodes)
        for device_type, count in counts.items():
            for idx in range(1, count + 1):
                placements.append(
                    {"device_type": device_type, "instance_idx": idx}
                )
        return placements
    for idx in range(1, max(num_supernodes, 0) + 1):
        placements.append({"device_type": None, "instance_idx": idx})
    return placements


def _supernode_task_name(device_type: str | None, instance_idx: int) -> str:
    group_suffix = f"{device_type}-{instance_idx}" if device_type else str(instance_idx)
    return f"supernode-{group_suffix}"


if __name__ == "__main__":
    raise SystemExit(main())
