from __future__ import annotations

from typing import Any

from fedctl.deploy.render import RenderedJobs
from fedctl.nomad.client import NomadClient


def submit_superlink_job(client: NomadClient, rendered: RenderedJobs) -> str | None:
    _submit(client, rendered.superlink)
    return _job_name(rendered.superlink)


def submit_supernodes_job(client: NomadClient, rendered: RenderedJobs) -> str | None:
    _submit(client, rendered.supernodes)
    return _job_name(rendered.supernodes)


def submit_superexec_jobs(client: NomadClient, rendered: RenderedJobs) -> list[str]:
    submitted: list[str] = []
    _submit(client, rendered.superexec_serverapp)
    serverapp = _job_name(rendered.superexec_serverapp)
    if serverapp:
        submitted.append(serverapp)

    for job in rendered.superexec_clientapps:
        _submit(client, job)
        name = _job_name(job)
        if name:
            submitted.append(name)
    return submitted


def submit_jobs(client: NomadClient, rendered: RenderedJobs) -> list[str]:
    submitted: list[str] = []
    superlink = submit_superlink_job(client, rendered)
    if superlink:
        submitted.append(superlink)
    supernodes = submit_supernodes_job(client, rendered)
    if supernodes:
        submitted.append(supernodes)
    submitted.extend(submit_superexec_jobs(client, rendered))

    return [name for name in submitted if name]


def _submit(client: NomadClient, job: dict[str, Any]) -> None:
    client.submit_job(job)


def _job_name(job: dict[str, Any]) -> str | None:
    name = job.get("Job", {}).get("Name")
    return name if isinstance(name, str) else None
