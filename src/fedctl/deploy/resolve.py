from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from fedctl.deploy import naming
from fedctl.deploy.errors import DeployError
from fedctl.nomad.client import NomadClient
from fedctl.state.store import load_manifest
from fedctl.util.console import console


@dataclass(frozen=True)
class SuperlinkAllocation:
    alloc_id: str
    node_id: str | None
    ports: dict[str, int]
    ip: str | None


def wait_for_superlink(
    client: NomadClient,
    *,
    job_name: str = "superlink",
    timeout_seconds: int = 120,
    poll_interval: float = 2.0,
) -> SuperlinkAllocation:
    deadline = time.monotonic() + timeout_seconds
    last_status: str | None = None
    console.print(f"[bold]SuperLink job:[/bold] {job_name}")
    while True:
        if time.monotonic() >= deadline:
            break
        
        alloc_id = _find_superlink_alloc(client, job_name)
        if not alloc_id:
            time.sleep(poll_interval)
            continue
        alloc = client.allocation(alloc_id)
        status = _alloc_status(alloc)
        last_status = status or last_status

        if status in {"failed", "lost"}:
            raise DeployError(f"SuperLink allocation {alloc_id} entered {status}.")

        task_state = _task_state(alloc, job_name)
        if task_state == "dead":
            raise DeployError(f"SuperLink task exited for allocation {alloc_id}.")
        console.print(
            f"[cyan]Alloc status:[/cyan] {_style_state(status)}, "
            f"[cyan]task state:[/cyan] {_style_state(task_state)}"
        )
        if status == "running" and task_state == "running":
            console.print("[green]✓ SuperLink is running[/green]")
            ports = _extract_ports(alloc)
            _ensure_ports(
                ports,
                {
                    "control",
                    "fleet",
                    "serverappio",
                },
            )
            node_id = alloc.get("NodeID") if isinstance(alloc.get("NodeID"), str) else None
            ip = _extract_ip(alloc)
            return SuperlinkAllocation(
                alloc_id=alloc_id,
                node_id=node_id,
                ports=ports,
                ip=ip,
            )
        time.sleep(poll_interval)

    msg = "Timed out waiting for SuperLink to become ready."
    if last_status:
        msg = f"{msg} Last status: {last_status}."
    raise DeployError(msg)


def wait_for_supernodes(
    client: NomadClient,
    *,
    job_name: str = "supernodes",
    expected_allocs: int | None = None,
    timeout_seconds: int = 120,
    poll_interval: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_report: tuple[int, int] | None = None
    console.print(f"[bold]SuperNodes job:[/bold] {job_name}")
    while True:
        if time.monotonic() >= deadline:
            break

        allocs = client.job_allocations(job_name)
        alloc_list = [alloc for alloc in allocs if isinstance(alloc, dict)] if isinstance(allocs, list) else []
        ready_allocs = 0
        fatal_state: tuple[str, str] | None = None

        for alloc in alloc_list:
            alloc_id = alloc.get("ID")
            if not isinstance(alloc_id, str) or not alloc_id:
                continue
            detail = client.allocation(alloc_id)
            if not isinstance(detail, dict):
                continue
            status = _alloc_status(detail) or "unknown"
            if status in {"failed", "lost"}:
                fatal_state = (alloc_id, status)
                break
            if status != "running":
                continue
            if _all_task_states_running(detail):
                ready_allocs += 1

        if fatal_state is not None:
            alloc_id, status = fatal_state
            raise DeployError(f"SuperNodes allocation {alloc_id} entered {status}.")

        total_expected = expected_allocs if isinstance(expected_allocs, int) else len(alloc_list)
        if total_expected < 1:
            total_expected = 1
        report = (ready_allocs, total_expected)
        if report != last_report:
            console.print(
                f"[cyan]Ready allocs:[/cyan] {ready_allocs}/{total_expected}"
            )
            last_report = report

        if expected_allocs is not None:
            ready = ready_allocs >= expected_allocs
        else:
            ready = len(alloc_list) > 0 and ready_allocs == len(alloc_list)
        if ready:
            console.print("[green]✓ SuperNodes are running[/green]")
            return

        time.sleep(poll_interval)

    raise DeployError("Timed out waiting for SuperNodes to become ready.")


def _style_state(state: str | None) -> str:
    if not state:
        return "[white]unknown[/white]"
    lowered = state.lower()
    if lowered in {"running"}:
        return f"[green]{lowered}[/green]"
    if lowered in {"pending"}:
        return f"[yellow]{lowered}[/yellow]"
    if lowered in {"failed", "lost", "dead"}:
        return f"[red]{lowered}[/red]"
    return f"[white]{lowered}[/white]"


def resolve_superlink_address(
    client: NomadClient,
    *,
    namespace: str = "default",
    experiment: str | None = None,
) -> str:
    job_name = _resolve_superlink_job_name(client, experiment)
    alloc = _resolve_superlink_allocation(
        client, namespace=namespace, job_name=job_name, experiment=experiment
    )
    status = _alloc_status(alloc)
    if status != "running":
        raise DeployError(f"SuperLink allocation not running (status={status}).")

    task_state = _task_state(alloc, job_name)
    if task_state != "running":
        raise DeployError(f"SuperLink task not running (state={task_state}).")

    ports = _extract_ports(alloc)
    control_port = ports.get("control")
    if not isinstance(control_port, int):
        raise DeployError("SuperLink control port not found.")

    ip = _extract_ip(alloc)
    if not ip:
        raise DeployError(
            "SuperLink allocation has no IP. Ensure Nomad advertises a reachable IP."
        )
    return f"{ip}:{control_port}"


def _find_superlink_alloc(client: NomadClient, job_name: str) -> str | None:
    allocs = client.job_allocations(job_name)
    if not isinstance(allocs, list):
        return None

    for alloc in allocs:
        if not isinstance(alloc, dict):
            continue
        alloc_id = alloc.get("ID")
        status = alloc.get("ClientStatus")
        if isinstance(alloc_id, str) and alloc_id and status == "running":
            return alloc_id
    return None


def _resolve_superlink_allocation(
    client: NomadClient,
    *,
    namespace: str,
    job_name: str,
    experiment: str | None,
) -> dict[str, Any]:
    alloc_id = _alloc_id_from_manifest(namespace, experiment)
    if alloc_id:
        alloc = client.allocation(alloc_id)
        if isinstance(alloc, dict):
            return alloc

    allocs = client.job_allocations(job_name)
    if not isinstance(allocs, list):
        raise DeployError("Unexpected allocation response from Nomad.")

    for alloc in allocs:
        if not isinstance(alloc, dict):
            continue
        alloc_id = alloc.get("ID")
        if not isinstance(alloc_id, str) or not alloc_id:
            continue
        alloc_detail = client.allocation(alloc_id)
        if not isinstance(alloc_detail, dict):
            continue
        status = _alloc_status(alloc_detail)
        task_state = _task_state(alloc_detail, job_name)
        if status == "running" and task_state == "running":
            return alloc_detail

    raise DeployError("No running SuperLink allocation found.")

def _alloc_id_from_manifest(namespace: str, experiment: str | None) -> str | None:
    if not experiment:
        return None
    try:
        manifest = load_manifest(namespace, experiment)
    except Exception:
        return None
    superlink = manifest.get("superlink")
    if not isinstance(superlink, dict):
        return None
    alloc_id = superlink.get("alloc_id")
    return alloc_id if isinstance(alloc_id, str) else None


def _resolve_superlink_job_name(
    client: NomadClient,
    experiment: str | None,
) -> str:
    if experiment:
        return naming.job_superlink(experiment)

    jobs = client.jobs()
    candidates = _match_superlink_jobs(jobs)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise DeployError("No SuperLink job found. Specify --exp.")
    raise DeployError("Multiple SuperLink jobs found. Specify --exp.")


def _match_superlink_jobs(jobs: object) -> list[str]:
    if not isinstance(jobs, list):
        return []
    names: list[str] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        name = job.get("ID") or job.get("Name")
        if isinstance(name, str) and name.endswith("-superlink"):
            names.append(name)
    return names


def _alloc_status(alloc: dict[str, Any]) -> str | None:
    status = alloc.get("ClientStatus")
    if isinstance(status, str):
        return status.lower()
    status = alloc.get("Status")
    if isinstance(status, str):
        return status.lower()
    return None


def _task_state(alloc: dict[str, Any], task_name: str) -> str | None:
    task_states = alloc.get("TaskStates")
    if not isinstance(task_states, dict):
        return None
    task = task_states.get(task_name)
    if not isinstance(task, dict):
        return None
    state = task.get("State")
    return state.lower() if isinstance(state, str) else None


def _all_task_states_running(alloc: dict[str, Any]) -> bool:
    task_states = alloc.get("TaskStates")
    if not isinstance(task_states, dict) or not task_states:
        return False
    for task in task_states.values():
        if not isinstance(task, dict):
            return False
        state = task.get("State")
        if not isinstance(state, str) or state.lower() != "running":
            return False
    return True


def _extract_ports(alloc: dict[str, Any]) -> dict[str, int]:
    ports: dict[str, int] = {}
    resources = alloc.get("AllocatedResources")
    if isinstance(resources, dict):
        shared = resources.get("Shared")
        if isinstance(shared, dict):
            _collect_ports_from_networks(shared.get("Networks"), ports)

    if not ports:
        resources = alloc.get("Resources")
        if isinstance(resources, dict):
            _collect_ports_from_networks(resources.get("Networks"), ports)
    return ports


def _extract_ip(alloc: dict[str, Any]) -> str | None:
    resources = alloc.get("AllocatedResources")
    if isinstance(resources, dict):
        shared = resources.get("Shared")
        if isinstance(shared, dict):
            ip = _first_network_ip(shared.get("Networks"))
            if ip:
                return ip

    resources = alloc.get("Resources")
    if isinstance(resources, dict):
        return _first_network_ip(resources.get("Networks"))
    return None


def _first_network_ip(networks: Any) -> str | None:
    if not isinstance(networks, list):
        return None
    for network in networks:
        if not isinstance(network, dict):
            continue
        ip = network.get("IP")
        if isinstance(ip, str) and ip:
            return ip
    return None


def _collect_ports_from_networks(networks: Any, ports: dict[str, int]) -> None:
    if not isinstance(networks, list):
        return
    for network in networks:
        if not isinstance(network, dict):
            continue
        for port in network.get("DynamicPorts", []) or []:
            if not isinstance(port, dict):
                continue
            label = port.get("Label")
            value = port.get("Value")
            if isinstance(label, str) and isinstance(value, int):
                ports[label] = value


def _ensure_ports(ports: dict[str, int], required: set[str]) -> None:
    missing = required - set(ports.keys())
    if missing:
        raise DeployError(f"SuperLink ports missing: {sorted(missing)}.")
