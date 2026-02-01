from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from .config import SubmitConfig
from .nomad_client import NomadClient, NomadError


@dataclass
class InventoryCache:
    ttl_seconds: int
    _timestamp: float | None = None
    _data: list[dict[str, Any]] | None = None

    def get(self) -> list[dict[str, Any]] | None:
        if self._timestamp is None or self._data is None:
            return None
        if self.ttl_seconds <= 0:
            return None
        if monotonic() - self._timestamp > self.ttl_seconds:
            return None
        return self._data

    def set(self, data: list[dict[str, Any]]) -> None:
        self._data = data
        self._timestamp = monotonic()


class NomadInventory:
    def __init__(
        self,
        cfg: SubmitConfig,
        *,
        client_factory: Callable[[], NomadClient] | None = None,
    ) -> None:
        self._cfg = cfg
        self._client_factory = client_factory or self._default_client_factory
        ttl = max(int(cfg.nomad_inventory_ttl or 0), 0)
        self._base_cache = InventoryCache(ttl_seconds=ttl)
        self._alloc_cache = InventoryCache(ttl_seconds=ttl)

    def list_nodes(self, *, include_allocs: bool = False) -> list[dict[str, Any]]:
        cache = self._alloc_cache if include_allocs else self._base_cache
        cached = cache.get()
        if cached is not None:
            return cached
        data = self._fetch_nodes(include_allocs=include_allocs)
        cache.set(data)
        return data

    def _default_client_factory(self) -> NomadClient:
        if not self._cfg.nomad_endpoint:
            raise ValueError("Nomad endpoint not configured")
        return NomadClient(
            self._cfg.nomad_endpoint,
            token=self._cfg.nomad_token,
            namespace=self._cfg.nomad_namespace,
            tls_ca=self._cfg.nomad_tls_ca,
            tls_skip_verify=self._cfg.nomad_tls_skip_verify,
        )

    def _fetch_nodes(self, *, include_allocs: bool) -> list[dict[str, Any]]:
        client = self._client_factory()
        try:
            nodes = client.nodes()
            if not isinstance(nodes, list):
                raise NomadError("Unexpected /v1/nodes response")
            results: list[dict[str, Any]] = []
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                entry = _normalize_node_summary(node)
                node_id = entry.get("id")
                if isinstance(node_id, str):
                    detail = client.node(node_id)
                    allocs = client.node_allocations(node_id) if include_allocs else None
                    _enrich_node(entry, detail, allocs, include_allocs=include_allocs)
                results.append(entry)
            return results
        finally:
            client.close()


def _normalize_node_summary(node: dict[str, Any]) -> dict[str, Any]:
    meta = node.get("Meta") if isinstance(node.get("Meta"), dict) else {}
    device_type = meta.get("device_type")
    device = meta.get("device")
    gpu = meta.get("gpu")
    return {
        "id": node.get("ID"),
        "name": node.get("Name"),
        "status": node.get("Status"),
        "drain": node.get("Drain"),
        "node_class": node.get("NodeClass"),
        "datacenter": node.get("Datacenter"),
        "address": node.get("Address"),
        "meta": meta,
        "device_type": device_type,
        "device": device,
        "gpu": gpu,
    }


def _enrich_node(
    entry: dict[str, Any],
    detail: Any,
    allocs: Any,
    *,
    include_allocs: bool,
) -> None:
    detail_root = detail
    if isinstance(detail, dict) and isinstance(detail.get("Node"), dict):
        detail_root = detail.get("Node")

    if isinstance(detail_root, dict):
        meta = detail_root.get("Meta")
        if isinstance(meta, dict) and meta:
            entry["meta"] = meta
            entry["device_type"] = meta.get("device_type")
            entry["device"] = meta.get("device")
            entry["gpu"] = meta.get("gpu")

    resources = {}
    if isinstance(detail_root, dict) and isinstance(detail_root.get("Resources"), dict):
        resources = detail_root.get("Resources") or {}

    total_cpu = _int_or_none(resources.get("CPU"))
    total_mem = _int_or_none(resources.get("MemoryMB"))
    devices = _normalize_devices(resources.get("Devices"))
    node_resources = (
        detail_root.get("NodeResources")
        if isinstance(detail_root, dict)
        else None
    )
    if (total_cpu is None or total_cpu == 0) or (total_mem is None or total_mem == 0):
        alt_cpu, alt_mem = _node_resources_totals(node_resources)
        if total_cpu is None or total_cpu == 0:
            total_cpu = alt_cpu
        if total_mem is None or total_mem == 0:
            total_mem = alt_mem

    used_cpu = 0
    used_mem = 0
    alloc_count = 0
    running_jobs: set[str] = set()
    alloc_items: list[dict[str, Any]] = []
    if include_allocs and isinstance(allocs, list):
        alloc_count = len(allocs)
        for alloc in allocs:
            if not isinstance(alloc, dict):
                continue
            task_breakdown = _alloc_task_breakdown(alloc)
            cpu, mem = _alloc_totals(task_breakdown, alloc)
            used_cpu += cpu
            used_mem += mem
            if alloc.get("ClientStatus") == "running":
                job_id = alloc.get("JobID")
                if isinstance(job_id, str) and job_id:
                    running_jobs.add(job_id)
            alloc_items.append(
                {
                    "id": alloc.get("ID"),
                    "job_id": alloc.get("JobID"),
                    "task_group": alloc.get("TaskGroup"),
                    "status": alloc.get("ClientStatus"),
                    "desired_status": alloc.get("DesiredStatus"),
                    "create_time": alloc.get("CreateTime"),
                    "modify_time": alloc.get("ModifyTime"),
                    "resources": {"cpu": cpu, "mem": mem},
                    "tasks": task_breakdown,
                }
            )

    entry["resources"] = {
        "total_cpu": total_cpu,
        "total_mem": total_mem,
        **({"used_cpu": used_cpu, "used_mem": used_mem} if include_allocs else {}),
    }
    if devices:
        entry["devices"] = devices
    if include_allocs:
        entry["allocations"] = {
            "count": alloc_count,
            "running_jobs": sorted(running_jobs),
            "items": alloc_items,
        }


def _alloc_task_breakdown(alloc: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    allocated = alloc.get("AllocatedResources")
    if isinstance(allocated, dict):
        task_map = allocated.get("Tasks")
        if isinstance(task_map, dict):
            for name, task in task_map.items():
                if not isinstance(task, dict):
                    continue
                cpu, mem = _resource_pair(task)
                devices = _normalize_devices(task.get("Devices"))
                tasks.append(
                    {
                        "name": name,
                        "cpu": cpu,
                        "mem": mem,
                        **({"devices": devices} if devices else {}),
                    }
                )
    if tasks:
        return tasks
    resources = alloc.get("Resources")
    if isinstance(resources, dict):
        cpu, mem = _resource_pair(resources)
        tasks.append({"name": "alloc", "cpu": cpu, "mem": mem})
    return tasks


def _alloc_totals(tasks: list[dict[str, Any]], alloc: dict[str, Any]) -> tuple[int, int]:
    if tasks:
        cpu = sum(_int_or_zero(t.get("cpu")) for t in tasks)
        mem = sum(_int_or_zero(t.get("mem")) for t in tasks)
        return cpu, mem

    resources = alloc.get("Resources")
    if isinstance(resources, dict):
        return _resource_pair(resources)
    return 0, 0


def _resource_pair(obj: dict[str, Any]) -> tuple[int, int]:
    cpu = _int_or_zero(obj.get("CPU"))
    mem = _int_or_zero(obj.get("MemoryMB"))
    return cpu, mem


def _normalize_devices(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        for key in ("Name", "Vendor", "Type"):
            if isinstance(item.get(key), str):
                entry[key.lower()] = item.get(key)
        attrs = item.get("Attributes")
        if isinstance(attrs, dict):
            entry["attributes"] = attrs
        instances = item.get("Instances")
        if isinstance(instances, list):
            entry["instances"] = instances
        if entry:
            cleaned.append(entry)
    return cleaned


def _node_resources_totals(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, dict):
        return None, None
    cpu_info = value.get("Cpu")
    mem_info = value.get("Memory")
    cpu_total = None
    mem_total = None
    if isinstance(cpu_info, dict):
        cpu_total = _int_or_none(cpu_info.get("CpuShares"))
    if isinstance(mem_info, dict):
        mem_total = _int_or_none(mem_info.get("MemoryMB"))
    return cpu_total, mem_total


def _int_or_zero(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None
