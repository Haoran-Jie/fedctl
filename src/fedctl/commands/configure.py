from __future__ import annotations

from pathlib import Path

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.deploy.errors import DeployError
from fedctl.deploy.resolve import resolve_superlink_address
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.project.pyproject_patch import patch_remote_deployment
from fedctl.util.console import console

def run_configure(
    *,
    path: str = ".",
    namespace: str | None = None,
    backup: bool = True,
    show_next: bool = True,
    experiment: str | None = None,
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
        addr = resolve_superlink_address(
            client,
            namespace=eff.namespace or "default",
            experiment=experiment,
        )
        patched_path = patch_remote_deployment(
            Path(path), address=addr, insecure=True, backup=backup
        )
        console.print(f"[green]✓ Updated[/green] {patched_path}")
        if show_next:
            console.print(
                f"Next step:\n  flwr run {patched_path} remote-deployment --stream"
            )
        return 0

    except (DeployError, FileNotFoundError, ValueError) as exc:
        console.print(f"[red]✗ Configure error:[/red] {exc}")
        return 1

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
