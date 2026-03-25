"""Configuration helpers for the fixed-rate HeteroFL prototype."""

from __future__ import annotations

import os
from flwr.app import Context
from typing import Mapping


def _get_required(run_config: Mapping[str, object], key: str) -> object:
    if key not in run_config:
        raise KeyError(f"Missing run_config key: {key}")
    return run_config[key]



def get_int(run_config: Mapping[str, object], key: str) -> int:
    return int(_get_required(run_config, key))



def get_float(run_config: Mapping[str, object], key: str) -> float:
    return float(_get_required(run_config, key))



def get_str(run_config: Mapping[str, object], key: str) -> str:
    return str(_get_required(run_config, key))



def parse_node_rate_map(value: str | object) -> dict[int, float]:
    if value is None:
        return {}
    raw = str(value).strip()
    if not raw:
        return {}
    mapping: dict[int, float] = {}
    for part in raw.split(","):
        entry = part.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(
                "Invalid heterofl-node-rates entry. Expected '<node_id>:<rate>'"
            )
        node_id_str, rate_str = entry.split(":", 1)
        mapping[int(node_id_str.strip())] = float(rate_str.strip())
    return mapping


def parse_node_device_type_map(value: str | object) -> dict[int, str]:
    if value is None:
        return {}
    raw = str(value).strip()
    if not raw:
        return {}
    mapping: dict[int, str] = {}
    for part in raw.split(","):
        entry = part.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(
                "Invalid heterofl-node-device-types entry. Expected '<node_id>:<device_type>'"
            )
        node_id_str, device_type = entry.split(":", 1)
        mapping[int(node_id_str.strip())] = device_type.strip()
    return mapping



def device_rate_map(run_config: Mapping[str, object]) -> dict[str, float]:
    return {
        "rpi4": get_float(run_config, "rpi4-model-rate"),
        "rpi5": get_float(run_config, "rpi5-model-rate"),
    }



def resolve_device_type() -> str:
    return os.environ.get("FEDCTL_DEVICE_TYPE", "unknown")


def resolve_instance_idx() -> str:
    return os.environ.get("FEDCTL_INSTANCE_IDX", "")


def resolve_nomad_node_id() -> str:
    return os.environ.get("FEDCTL_NOMAD_NODE_ID", "")


def resolve_device_type_for_context(context: Context) -> str:
    device_type = resolve_device_type()
    if device_type != "unknown":
        return device_type

    partition_id = context.node_config.get("partition-id")
    num_partitions = context.node_config.get("num-partitions")
    if isinstance(partition_id, int) and isinstance(num_partitions, int) and num_partitions > 1:
        midpoint = num_partitions // 2
        return "rpi4" if partition_id < midpoint else "rpi5"

    try:
        partition_id_int = int(str(partition_id))
        num_partitions_int = int(str(num_partitions))
    except (TypeError, ValueError):
        return "unknown"
    if num_partitions_int <= 1:
        return "unknown"
    midpoint = num_partitions_int // 2
    return "rpi4" if partition_id_int < midpoint else "rpi5"
