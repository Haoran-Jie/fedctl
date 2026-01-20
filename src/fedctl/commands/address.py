from __future__ import annotations

from rich.console import Console

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.deploy.errors import DeployError
from fedctl.deploy.resolve import resolve_superlink_address
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError

console = Console()


def run_address(
    *,
    namespace: str | None = None,
    experiment: str | None = None,
    fmt: str = "plain",
    profile: str | None = None,
    endpoint: str | None = None,
    token: str | None = None,
    tls_ca: str | None = None,
    tls_skip_verify: bool | None = None,
) -> int:
    if fmt not in {"plain", "toml"}:
        console.print(f"[red]✗ Unsupported format:[/red] {fmt}")
        return 1

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
        addr = resolve_superlink_address(
            client,
            namespace=eff.namespace or "default",
            experiment=experiment,
        )
        if fmt == "plain":
            print(addr)
        else:
            print(_format_toml(addr))
        return 0

    except DeployError as exc:
        console.print(f"[red]✗ Address error:[/red] {exc}")
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


def _format_toml(address: str) -> str:
    return (
        "[tool.flwr.federations.remote-deployment]\n"
        f'address = "{address}"\n'
        "insecure = true\n"
    )
