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
    tls_ca: str | None = None,
    tls_skip_verify: bool | None = None,
) -> int:
    cfg = load_config()
    try:
        eff = get_effective_config(
            cfg,
            profile_name=profile,
            endpoint=endpoint,
            namespace=namespace,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
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
