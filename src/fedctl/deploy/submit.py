from __future__ import annotations

from typing import Any

from fedctl.deploy import naming
from fedctl.deploy.render import RenderedJobs
from fedctl.nomad.client import NomadClient


def submit_jobs(client: NomadClient, rendered: RenderedJobs) -> list[str]:
    submitted: list[str] = []
    _submit(client, rendered.superlink)
    submitted.append(_job_name(rendered.superlink) or "")

    _submit(client, rendered.supernodes)
    submitted.append(_job_name(rendered.supernodes) or "")

    _submit(client, rendered.superexec_serverapp)
    submitted.append(_job_name(rendered.superexec_serverapp) or "")

    for job in rendered.superexec_clientapps:
        _submit(client, job)
        name = _job_name(job)
        if name:
            submitted.append(name)

    return [name for name in submitted if name]


def _submit(client: NomadClient, job: dict[str, Any]) -> None:
    client.submit_job(job)


def _job_name(job: dict[str, Any]) -> str | None:
    name = job.get("Job", {}).get("Name")
    return name if isinstance(name, str) else None
