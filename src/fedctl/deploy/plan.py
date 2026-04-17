from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from fedctl.nomad.nodeview import extract_device_type


@dataclass(frozen=True)
class SupernodePlacement:
    device_type: str | None
    instance_idx: int
    node_id: str | None
    preferred_node_id: str | None = None


def parse_supernodes(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw in values:
        parts = [p for p in raw.split(",") if p]
        for part in parts:
            if "=" not in part:
                raise ValueError(f"Invalid supernodes entry: {part}")
            key, val = part.split("=", 1)
            key = key.strip()
            if not key:
                raise ValueError("Supernodes device type cannot be empty.")
            try:
                count = int(val)
            except ValueError as exc:
                raise ValueError(f"Invalid supernodes count: {part}") from exc
            if count < 0:
                raise ValueError(f"Supernodes count must be >= 0: {part}")
            result[key] = result.get(key, 0) + count
    return result


def plan_supernodes(
    *,
    counts: dict[str, int],
    allow_oversubscribe: bool,
    spread_across_hosts: bool = False,
    prefer_spread_across_hosts: bool = False,
    nodes: list[dict[str, Any]] | None,
) -> list[SupernodePlacement]:
    placements: list[SupernodePlacement] = []
    for device_type, count in counts.items():
        if count == 0:
            continue
        requires_host_placement = spread_across_hosts or not allow_oversubscribe
        if not requires_host_placement:
            if prefer_spread_across_hosts:
                if nodes is None:
                    raise ValueError("Node inventory required for soft host-spread placement.")
                available = _nodes_by_type(nodes, device_type)
                if not available:
                    raise ValueError(
                        f"Insufficient nodes for device_type '{device_type}': need at least 1, have 0."
                    )
                for idx in range(1, count + 1):
                    placements.append(
                        SupernodePlacement(
                            device_type=device_type,
                            instance_idx=idx,
                            node_id=None,
                            preferred_node_id=available[(idx - 1) % len(available)],
                        )
                    )
                continue
            for idx in range(1, count + 1):
                placements.append(
                    SupernodePlacement(
                        device_type=device_type,
                        instance_idx=idx,
                        node_id=None,
                        preferred_node_id=None,
                    )
                )
            continue

        if nodes is None:
            raise ValueError("Node inventory required for host-pinned placement.")
        available = _nodes_by_type(nodes, device_type)
        if len(available) < count:
            raise ValueError(
                f"Insufficient nodes for device_type '{device_type}': "
                f"need {count}, have {len(available)}."
            )
        for idx in range(1, count + 1):
            placements.append(
                SupernodePlacement(
                    device_type=device_type,
                    instance_idx=idx,
                    node_id=available[idx - 1],
                    preferred_node_id=available[idx - 1],
                )
            )
    return placements


def _nodes_by_type(nodes: list[dict[str, Any]], device_type: str) -> list[str]:
    matches: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if extract_device_type(node) != device_type:
            continue
        node_id = node.get("ID")
        if isinstance(node_id, str):
            matches.append(node_id)
    return matches
