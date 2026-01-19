from __future__ import annotations

from rich.console import Console
from rich.table import Table

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError

console = Console()


def run_doctor(
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

    table = Table(title="fedctl doctor")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("profile", eff.profile_name)
    table.add_row("endpoint", eff.endpoint)
    table.add_row("namespace", str(eff.namespace))
    table.add_row("access_mode", eff.access_mode)
    table.add_row("tailscale.subnet_cidr", str(eff.tailscale_subnet_cidr))
    table.add_row("tls_ca", str(eff.tls_ca))
    table.add_row("tls_skip_verify", str(eff.tls_skip_verify))
    table.add_row("nomad_token", "set" if eff.nomad_token else "missing")
    console.print(table)

    client = NomadClient(eff)
    try:
        leader = client.status_leader()
        console.print(f"[green]✓[/green] Nomad reachable. Leader: {leader}")

        agent = client.agent_self()
        name = agent.get("config", {}).get("Name")
        region = agent.get("config", {}).get("Region")
        dc = agent.get("config", {}).get("Datacenter")
        console.print(
            f"[green]✓[/green] Agent self ok. name={name} region={region} dc={dc}"
        )

        nodes = client.nodes()
        count = len(nodes) if isinstance(nodes, list) else "?"
        console.print(f"[green]✓[/green] Nodes visible: {count}")

        if eff.access_mode == "tailscale-subnet":
            if not eff.tailscale_subnet_cidr:
                console.print(
                    "[yellow]![/yellow] access_mode=tailscale-subnet but no subnet_cidr set."
                )
            else:
                console.print(
                    "[green]i[/green] tailscale-subnet expects route to "
                    f"{eff.tailscale_subnet_cidr} to be enabled."
                )

        if not eff.nomad_token:
            console.print(
                "[yellow]![/yellow] No NOMAD_TOKEN set. Deploy operations may fail if ACLs are enabled."
            )

        return 0

    except NomadTLSError as e:
        console.print(f"[red]✗ TLS error:[/red] {e}")
        console.print(
            "[yellow]Hint:[/yellow] If this is a lab/private CA, set `tls_ca` in your "
            "profile or use `--tls-skip-verify` for dev only."
        )
        return 2

    except NomadHTTPError as e:
        console.print(f"[red]✗ HTTP error:[/red] {e}")
        console.print(
            "[yellow]Hint:[/yellow] This often means ACL permissions or wrong namespace. "
            "Check NOMAD_TOKEN and namespace."
        )
        return 3

    except NomadConnectionError as e:
        console.print(f"[red]✗ Connection error:[/red] {e}")
        console.print(
            "[yellow]Hint:[/yellow] Check endpoint URL, DNS, VPN/Tailscale/SSH tunnel reachability."
        )
        return 4

    finally:
        client.close()
