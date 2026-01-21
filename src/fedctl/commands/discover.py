from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from rich.console import Console

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.nomad.nodeview import extract_device, extract_device_type, extract_gpu
from fedctl.util.console import print_table

console = Console()


def _matches(value: Optional[str], expected: Optional[str]) -> bool:
    if expected is None:
        return True
    if value is None:
        return False
    return value == expected


def _iter_nodes(nodes: Any) -> Iterable[dict]:
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict):
                yield node


def run_discover(
    profile: str | None = None,
    endpoint: str | None = None,
    namespace: str | None = None,
    token: str | None = None,
    tls_ca: str | None = None,
    tls_skip_verify: bool | None = None,
    wide: bool = False,
    json_output: bool = False,
    device: str | None = None,
    status: str | None = None,
    node_class: str | None = None,
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
        nodes = client.nodes()
        if json_output:
            console.print_json(json.dumps(nodes))
            return 0

        columns = ["Name", "Status", "DC", "Class", "DeviceType", "Device", "GPU", "Addr"]
        if wide:
            columns.extend(["Arch", "OS", "ID"])

        rows = []
        for node in _iter_nodes(nodes):
            name = str(node.get("Name", ""))
            node_status = str(node.get("Status", ""))
            dc = str(node.get("Datacenter", ""))
            nclass = str(node.get("NodeClass", ""))
            addr = str(node.get("Address", ""))
            device_type = extract_device_type(node)
            device_val = extract_device(node)
            gpu_val = extract_gpu(node)

            if not _matches(device_val, device):
                continue
            if not _matches(node_status, status):
                continue
            if not _matches(nclass, node_class):
                continue

            row = [
                name,
                node_status,
                dc,
                nclass,
                device_type or "",
                device_val or "",
                gpu_val or "",
                addr,
            ]
            if wide:
                attrs = node.get("Attributes", {}) if isinstance(node.get("Attributes"), dict) else {}
                arch = attrs.get("arch", "")
                os_name = attrs.get("os", "")
                node_id = str(node.get("ID", ""))
                row.extend([str(arch), str(os_name), node_id])
            rows.append(row)

        print_table("Nomad Nodes", columns, rows)
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
