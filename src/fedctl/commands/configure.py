from __future__ import annotations

from pathlib import Path

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.deploy.errors import DeployError
from fedctl.deploy.resolve import resolve_superlink_address
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.project.flwr_config import resolve_flwr_home, write_superlink_connection
from fedctl.util.console import console

def run_configure(
    *,
    path: str = ".",
    namespace: str | None = None,
    flwr_home: str | None = None,
    backup: bool = True,
    show_next: bool = True,
    experiment: str | None = None,
    profile: str | None = None,
    endpoint: str | None = None,
    token: str | None = None,
) -> int:
    cfg = load_config()
    project_path = Path(path)
    project_root = project_path if project_path.is_dir() else project_path.parent
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
        resolved_flwr_home = resolve_flwr_home(
            project_root=project_root,
            flwr_home=flwr_home,
        )
        config_path = write_superlink_connection(
            flwr_home=resolved_flwr_home,
            name="remote-deployment",
            address=addr,
            insecure=True,
            backup=backup,
            default_connection="remote-deployment",
        )
        console.print(f"[green]✓ Updated Flower config:[/green] {config_path}")
        console.print(f"[green]✓ FLWR_HOME:[/green] {resolved_flwr_home}")
        if show_next:
            console.print(
                "Next step:\n"
                f"  FLWR_HOME={resolved_flwr_home} flwr run {project_root} "
                "remote-deployment --stream"
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
