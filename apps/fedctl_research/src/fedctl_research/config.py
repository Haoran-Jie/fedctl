"""Shared configuration helpers for research experiments."""

from __future__ import annotations

import os
from typing import Mapping

from flwr.app import Context


DEFAULT_MODEL_RATE_LEVELS = (1.0, 0.5, 0.25, 0.125, 0.0625)


def _get_required(run_config: Mapping[str, object], key: str) -> object:
    if key not in run_config:
        raise KeyError(f"Missing run_config key: {key}")
    return run_config[key]


def get_int(run_config: Mapping[str, object], key: str) -> int:
    return int(_get_required(run_config, key))


def get_optional_int(run_config: Mapping[str, object], key: str) -> int | None:
    value = run_config.get(key)
    return None if value is None else int(value)


def get_float(run_config: Mapping[str, object], key: str) -> float:
    return float(_get_required(run_config, key))


def get_optional_float(run_config: Mapping[str, object], key: str) -> float | None:
    value = run_config.get(key)
    if value is None:
        return None
    raw = str(value).strip()
    if raw == "":
        return None
    return float(raw)


def get_str(run_config: Mapping[str, object], key: str) -> str:
    return str(_get_required(run_config, key))


def get_optional_str(run_config: Mapping[str, object], key: str) -> str | None:
    value = run_config.get(key)
    if value is None:
        return None
    raw = str(value).strip()
    return raw if raw else None


def get_optional_bool(run_config: Mapping[str, object], key: str) -> bool | None:
    value = run_config.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"Invalid boolean value for {key}: {value!r}")


def get_method_name(run_config: Mapping[str, object]) -> str:
    return str(run_config.get("method", "heterofl")).strip() or "heterofl"


def get_task_name(run_config: Mapping[str, object]) -> str:
    return str(run_config.get("task", "fashion_mnist_mlp")).strip() or "fashion_mnist_mlp"


def get_model_split_mode(run_config: Mapping[str, object]) -> str:
    return str(run_config.get("model-split-mode", "fix")).strip().lower() or "fix"


def get_partitioning_num_labels(run_config: Mapping[str, object]) -> int:
    return int(run_config.get("partitioning-num-labels", 2))


def get_partitioning_dirichlet_alpha(run_config: Mapping[str, object]) -> float:
    return float(run_config.get("partitioning-dirichlet-alpha", 0.1))


def get_masked_cross_entropy_mode(run_config: Mapping[str, object]) -> str:
    return str(run_config.get("masked-cross-entropy", "auto")).strip().lower() or "auto"


def get_client_eval_enabled(run_config: Mapping[str, object]) -> bool:
    value = get_optional_bool(run_config, "client-eval-enabled")
    return True if value is None else value


def get_final_client_eval_enabled(run_config: Mapping[str, object]) -> bool:
    value = get_optional_bool(run_config, "final-client-eval-enabled")
    return False if value is None else value


def get_fedavgm_momentum(run_config: Mapping[str, object]) -> float:
    return float(run_config.get("fedavgm-server-momentum", 0.9))


def get_fedbuff_buffer_size(run_config: Mapping[str, object]) -> int:
    return int(run_config.get("fedbuff-buffer-size", 10))


def get_fedbuff_train_concurrency(run_config: Mapping[str, object]) -> int | None:
    return get_optional_int(run_config, "fedbuff-train-concurrency")


def get_fedbuff_poll_interval_s(run_config: Mapping[str, object]) -> float:
    return float(run_config.get("fedbuff-poll-interval-s", 1.0))


def get_fedbuff_num_server_steps(run_config: Mapping[str, object]) -> int:
    return int(run_config.get("fedbuff-num-server-steps", 3))


def get_fedbuff_evaluate_every_steps(run_config: Mapping[str, object]) -> int:
    return int(run_config.get("fedbuff-evaluate-every-steps", 1))


def get_fedbuff_staleness_weighting(run_config: Mapping[str, object]) -> str:
    return str(run_config.get("fedbuff-staleness-weighting", "polynomial")).strip().lower() or "polynomial"


def get_fedbuff_staleness_alpha(run_config: Mapping[str, object]) -> float:
    return float(run_config.get("fedbuff-staleness-alpha", 0.5))


def get_fiarse_selection_mode(run_config: Mapping[str, object]) -> str:
    return str(run_config.get("fiarse-selection-mode", "structured-magnitude")).strip().lower() or "structured-magnitude"


def get_fiarse_threshold_mode(run_config: Mapping[str, object]) -> str:
    return str(run_config.get("fiarse-threshold-mode", "global")).strip().lower() or "global"


def parse_csv_floats(value: str | object | None) -> tuple[float, ...]:
    if value is None:
        return ()
    raw = str(value).strip()
    if not raw:
        return ()
    return tuple(float(part.strip()) for part in raw.split(",") if part.strip())


def get_model_rate_levels(run_config: Mapping[str, object]) -> tuple[float, ...]:
    parsed = parse_csv_floats(run_config.get("model-rate-levels"))
    return parsed if parsed else DEFAULT_MODEL_RATE_LEVELS


def get_submodel_eval_rates(run_config: Mapping[str, object]) -> tuple[float, ...]:
    configured = {
        round(rate, 6)
        for rate in (
            0.125,
            0.25,
            0.5,
            1.0,
            *get_model_rate_levels(run_config),
            float(run_config.get("default-model-rate", 1.0)),
            float(run_config.get("global-model-rate", 1.0)),
        )
        if rate > 0
    }
    return tuple(sorted(configured))


def get_model_rate_proportions(run_config: Mapping[str, object]) -> tuple[float, ...]:
    levels = get_model_rate_levels(run_config)
    parsed = parse_csv_floats(run_config.get("model-rate-proportions"))
    if not parsed:
        uniform = 1.0 / len(levels)
        return tuple(uniform for _ in levels)
    if len(parsed) != len(levels):
        raise ValueError(
            "model-rate-proportions must have the same number of entries as model-rate-levels"
        )
    total = sum(parsed)
    if total <= 0:
        raise ValueError("model-rate-proportions must sum to a positive value")
    return tuple(value / total for value in parsed)


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


def parse_partition_rate_map(value: str | object) -> dict[int, float]:
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
                "Invalid heterofl-partition-rates entry. Expected '<partition_id>:<rate>'"
            )
        partition_id_str, rate_str = entry.split(":", 1)
        mapping[int(partition_id_str.strip())] = float(rate_str.strip())
    return mapping


def parse_device_type_allocations(
    value: str | object,
) -> dict[str, tuple[tuple[float, int], ...]]:
    if value is None:
        return {}
    raw = str(value).strip()
    if not raw:
        return {}

    allocations: dict[str, tuple[tuple[float, int], ...]] = {}
    for device_chunk in raw.split(";"):
        device_entry = device_chunk.strip()
        if not device_entry:
            continue
        if ":" not in device_entry:
            raise ValueError(
                "Invalid heterofl-device-type-allocations entry. "
                "Expected '<device_type>:<rate>@<count>,<rate>@<count>'"
            )
        device_type, allocation_raw = device_entry.split(":", 1)
        parsed_allocations: list[tuple[float, int]] = []
        for rate_chunk in allocation_raw.split(","):
            rate_entry = rate_chunk.strip()
            if not rate_entry:
                continue
            if "@" not in rate_entry:
                raise ValueError(
                    "Invalid heterofl-device-type-allocations allocation. "
                    "Expected '<rate>@<count>'"
                )
            rate_str, count_str = rate_entry.split("@", 1)
            rate = float(rate_str.strip())
            count = int(count_str.strip())
            if rate <= 0:
                raise ValueError("heterofl-device-type-allocations rates must be positive")
            if count <= 0:
                raise ValueError("heterofl-device-type-allocations counts must be positive")
            parsed_allocations.append((rate, count))
        normalized_device_type = device_type.strip()
        if not normalized_device_type:
            raise ValueError("heterofl-device-type-allocations device type cannot be empty")
        if not parsed_allocations:
            raise ValueError(
                "heterofl-device-type-allocations device buckets must define at least one rate"
            )
        allocations[normalized_device_type] = tuple(parsed_allocations)
    return allocations


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
