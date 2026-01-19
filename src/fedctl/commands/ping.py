from __future__ import annotations

from rich.console import Console

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError

console = Console()


def run_ping(
    profile: str | None = None,
    endpoint: str | None = None,
    namespace: str | None = None,
    token: str | None = None,
    tls_ca: str | None = None,
    tls_skip_verify: bool | None = None,
) -> int:
    cfg = load_config()
    eff = get_effective_config(
        cfg,
        profile_name=profile,
        endpoint=endpoint,
        namespace=namespace,
        token=token,
        tls_ca=tls_ca,
        tls_skip_verify=tls_skip_verify,
    )

    client = NomadClient(eff)
    try:
        leader = client.status_leader()
        console.print(f"[green]✓[/green] Nomad leader: {leader}")
        return 0

    except NomadTLSError as e:
        console.print(f"[red]✗ TLS error:[/red] {e}")
        console.print(
            "[yellow]Hint:[/yellow] Set `tls_ca` or use `--tls-skip-verify` for dev."
        )
        return 2

    except NomadHTTPError as e:
        console.print(f"[red]✗ HTTP error:[/red] {e}")
        if getattr(e, "status_code", None) == 403:
            console.print("[yellow]Hint:[/yellow] Token/ACL invalid or missing permissions.")
        return 3

    except NomadConnectionError as e:
        console.print(f"[red]✗ Connection error:[/red] {e}")
        console.print(
            "[yellow]Hint:[/yellow] Check endpoint reachability (LAN/Tailscale/SSH tunnel)."
        )
        return 4

    finally:
        client.close()
