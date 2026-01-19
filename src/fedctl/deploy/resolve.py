from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from fedctl.deploy import naming
from fedctl.deploy.errors import DeployError
from fedctl.nomad.client import NomadClient


@dataclass(frozen=True)
class SuperlinkAllocation:
    alloc_id: str
    node_id: str | None
    ports: dict[str, int]


def wait_for_superlink(
    client: NomadClient,
    *,
    job_name: str = naming.job_superlink(),
    timeout_seconds: int = 120,
    poll_interval: float = 2.0,
) -> SuperlinkAllocation:
    deadline = time.monotonic() + timeout_seconds
    last_status: str | None = None

    while True:
        if time.monotonic() >= deadline:
            break
        
        alloc_id = _find_superlink_alloc(client, job_name)
        print(0)
        if not alloc_id:
            time.sleep(poll_interval)
            continue
        print(1)
        alloc = client.allocation(alloc_id)
        status = _alloc_status(alloc)
        last_status = status or last_status

        if status in {"failed", "lost"}:
            raise DeployError(f"SuperLink allocation {alloc_id} entered {status}.")

        task_state = _task_state(alloc, "superlink")
        if task_state == "dead":
            raise DeployError(f"SuperLink task exited for allocation {alloc_id}.")

        if status == "running" and task_state == "running":
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
            return SuperlinkAllocation(alloc_id=alloc_id, node_id=node_id, ports=ports)
        time.sleep(poll_interval)

    msg = "Timed out waiting for SuperLink to become ready."
    if last_status:
        msg = f"{msg} Last status: {last_status}."
    raise DeployError(msg)


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
