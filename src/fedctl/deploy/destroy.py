from __future__ import annotations

from typing import Iterable

from fedctl.deploy.spec import normalize_experiment_name
from fedctl.nomad.client import NomadClient
from fedctl.state.store import manifest_path


def destroy_experiment(
    client: NomadClient,
    *,
    experiment: str,
    namespace: str,
    purge: bool,
) -> list[str]:
    exp_name = normalize_experiment_name(experiment)
    jobs = client.jobs()
    job_names = _filter_experiment_jobs(jobs, exp_name)
    for name in _order_destroy(job_names):
        client.stop_job(name, purge=purge)

    _remove_manifest(namespace, exp_name)
    return job_names


def destroy_all_experiments(
    client: NomadClient,
    *,
    namespace: str,
    purge: bool,
) -> list[str]:
    jobs = client.jobs()
    job_names = _filter_experiment_jobs(jobs, None)
    for name in _order_destroy(job_names):
        client.stop_job(name, purge=purge)

    experiments = _extract_experiments(job_names)
    for exp_name in experiments:
        _remove_manifest(namespace, exp_name)

    return job_names


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


def _order_destroy(job_names: Iterable[str]) -> list[str]:
    def rank(name: str) -> int:
        if "superexec-clientapp" in name:
            return 0
        if "superexec-serverapp" in name:
            return 1
        if "supernodes" in name:
            return 2
        if "superlink" in name:
            return 3
        return 4

    return sorted(job_names, key=rank)


def _remove_manifest(namespace: str, experiment: str) -> None:
    path = manifest_path(namespace, experiment)
    if path.exists():
        path.unlink()


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


def _extract_experiments(job_names: Iterable[str]) -> list[str]:
    experiments: set[str] = set()
    for name in job_names:
        for suffix in (
            "-superlink",
            "-supernodes",
            "-superexec-serverapp",
        ):
            if name.endswith(suffix):
                experiments.add(name[: -len(suffix)])
                break
        else:
            marker = "-superexec-clientapp-"
            if marker in name:
                experiments.add(name.split(marker, 1)[0])
    return sorted(experiments)
