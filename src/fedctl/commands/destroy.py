from __future__ import annotations

from rich.console import Console

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.deploy.destroy import destroy_all_experiments, destroy_experiment
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError

console = Console()


def run_destroy(
    *,
    experiment: str | None,
    destroy_all: bool = False,
    namespace: str | None = None,
    purge: bool = False,
    profile: str | None = None,
    endpoint: str | None = None,
    token: str | None = None,
) -> int:
    cfg = load_config()
    try:
        eff = get_effective_config(
            cfg,
            profile_name=profile,
            endpoint=endpoint,
            namespace=namespace,
            token=token,
        )
    except ValueError as exc:
        console.print(f"[red]✗ Config error:[/red] {exc}")
        return 1

    client = NomadClient(eff)
    try:
        if destroy_all:
            job_names = destroy_all_experiments(
                client,
                namespace=eff.namespace or "default",
                purge=purge,
            )
            submit_jobs = _destroy_submit_jobs(
                client,
                namespace=eff.namespace or "default",
                purge=purge,
            )
            job_names.extend([name for name in submit_jobs if name not in job_names])
        else:
            if not experiment:
                console.print("[red]✗ Missing experiment name.[/red] Use --all to destroy all.")
                return 1
            job_names = destroy_experiment(
                client,
                experiment=experiment,
                namespace=eff.namespace or "default",
                purge=purge,
            )
        if not job_names:
            console.print("[yellow]No jobs found for experiment.[/yellow]")
        else:
            for name in job_names:
                console.print(f"[green]✓ Stopped job:[/green] {name}")
        return 0

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


def _destroy_submit_jobs(
    client: NomadClient,
    *,
    namespace: str,
    purge: bool,
) -> list[str]:
    try:
        jobs = client.jobs()
    except Exception:
        return []
    if not isinstance(jobs, list):
        return []
    stopped: list[str] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        name = job.get("ID") or job.get("Name")
        if not isinstance(name, str):
            continue
        if not name.startswith("sub-"):
            continue
        try:
            client.stop_job(name, purge=purge)
        except Exception:
            continue
        stopped.append(name)
    return stopped
