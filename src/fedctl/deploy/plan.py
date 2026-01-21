from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class SupernodePlacement:
    device_type: str | None
    instance_idx: int
    node_id: str | None


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
    nodes: list[dict[str, Any]] | None,
) -> list[SupernodePlacement]:
    placements: list[SupernodePlacement] = []
    for device_type, count in counts.items():
        if count == 0:
            continue
        if allow_oversubscribe:
            for idx in range(1, count + 1):
                placements.append(
                    SupernodePlacement(
                        device_type=device_type,
                        instance_idx=idx,
                        node_id=None,
                    )
                )
            continue

        if nodes is None:
            raise ValueError("Node inventory required for non-oversubscribed placement.")
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
                    node_id=available[idx],
                )
            )
    return placements


def _nodes_by_type(nodes: list[dict[str, Any]], device_type: str) -> list[str]:
    matches: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        meta = node.get("Meta", {}) if isinstance(node.get("Meta"), dict) else {}
        if str(meta.get("device_type", "")) != device_type:
            continue
        node_id = node.get("ID")
        if isinstance(node_id, str):
            matches.append(node_id)
    return matches
