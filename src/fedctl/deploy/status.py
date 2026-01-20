from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fedctl.deploy.spec import normalize_experiment_name
from fedctl.nomad.client import NomadClient


@dataclass(frozen=True)
class JobStatus:
    name: str
    status: str
    running: int


def fetch_status(
    client: NomadClient,
    *,
    experiment: str | None,
    all_experiments: bool = False,
) -> list[JobStatus]:
    jobs = client.jobs()
    if all_experiments:
        job_names = _filter_experiment_jobs(jobs, None)
    else:
        exp_name = normalize_experiment_name(experiment or "")
        job_names = _filter_experiment_jobs(jobs, exp_name)
    statuses: list[JobStatus] = []
    for name in job_names:
        allocs = client.job_allocations(name)
        statuses.append(_summarize_allocs(name, allocs))
    return statuses


def _filter_experiment_jobs(jobs: object, exp_name: str | None) -> list[str]:
    if not isinstance(jobs, list):
        return []
    names: list[str] = []
    for job in jobs:
        if isinstance(job, dict):
            name = job.get("ID") or job.get("Name")
            if not isinstance(name, str):
                continue
            if exp_name:
                if name.startswith(f"{exp_name}-"):
                    names.append(name)
            else:
                if _is_experiment_job(name):
                    names.append(name)
    return names


def _is_experiment_job(name: str) -> bool:
    return any(
        key in name
        for key in (
            "-superlink",
            "-supernodes",
            "-superexec-serverapp",
            "-superexec-clientapp-",
        )
    )


def _summarize_allocs(name: str, allocs: Any) -> JobStatus:
    if not isinstance(allocs, list) or not allocs:
        return JobStatus(name=name, status="unknown", running=0)
    running = 0
    status = "unknown"
    allocs = sorted(
        allocs,
        key=lambda a: a.get("CreateTime") if isinstance(a, dict) else 0,
    )
    for alloc in allocs:
        if not isinstance(alloc, dict):
            continue
        alloc_status = alloc.get("ClientStatus") or alloc.get("Status")
        if isinstance(alloc_status, str):
            status = alloc_status
            if alloc_status.lower() == "running":
                running += 1
    return JobStatus(name=name, status=status, running=running)
