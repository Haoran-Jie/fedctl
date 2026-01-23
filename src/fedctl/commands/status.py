from __future__ import annotations

from rich.console import Console

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.deploy.status import fetch_status
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.state.errors import StateError
from fedctl.state.store import load_manifest
from fedctl.util.console import print_table

console = Console()


def run_status(
    *,
    experiment: str | None,
    show_all: bool = False,
    namespace: str | None = None,
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

    if not show_all and not experiment:
        console.print("[red]✗ Missing experiment name.[/red] Use --all to show all.")
        return 1

    client = NomadClient(eff)
    try:
        statuses = fetch_status(
            client,
            experiment=experiment,
            all_experiments=show_all,
        )
        rows = [[s.name, s.status, str(s.running)] for s in statuses]
        print_table("Jobs", ["Job", "Status", "Running"], rows)
        if not show_all and experiment:
            _print_network_summary(eff.namespace or "default", experiment)
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


def _print_network_summary(namespace: str, experiment: str) -> None:
    try:
        manifest = load_manifest(namespace=namespace, experiment=experiment)
    except StateError:
        return
    if not isinstance(manifest, dict):
        return
    supernodes = manifest.get("supernodes")
    if not isinstance(supernodes, dict):
        return
    placements = supernodes.get("placements")
    if not isinstance(placements, list) or not placements:
        return
    network = supernodes.get("network")
    assignments = {}
    default_profile = "none"
    if isinstance(network, dict):
        assignments = network.get("assignments", {})
        default_profile = network.get("default_profile", default_profile)
    if not isinstance(assignments, dict):
        assignments = {}
    rows = []
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        device_type = placement.get("device_type")
        instance_idx = placement.get("instance_idx")
        node_id = placement.get("node_id")
        profile = _resolve_profile(assignments, default_profile, device_type, instance_idx)
        rows.append(
            [
                _format_instance(device_type, instance_idx),
                str(node_id) if node_id else "-",
                profile,
            ]
        )
    if rows:
        print_table("Supernodes", ["Instance", "Node", "Profile"], rows)


def _format_instance(device_type: object, instance_idx: object) -> str:
    if isinstance(device_type, str) and isinstance(instance_idx, int):
        return f"{device_type}-{instance_idx}"
    if isinstance(instance_idx, int):
        return str(instance_idx)
    return "-"


def _resolve_profile(
    assignments: dict[object, object],
    default_profile: object,
    device_type: object,
    instance_idx: object,
) -> str:
    if not isinstance(instance_idx, int) or instance_idx < 1:
        return str(default_profile) if default_profile else "none"
    key = str(device_type) if isinstance(device_type, str) else "_untyped"
    values = assignments.get(key)
    if isinstance(values, list) and instance_idx <= len(values):
        profile = values[instance_idx - 1]
        if isinstance(profile, str) and profile:
            return profile
    return str(default_profile) if default_profile else "none"
