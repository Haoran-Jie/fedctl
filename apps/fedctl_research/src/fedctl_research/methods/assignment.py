"""Shared model-rate assignment helpers for heterogeneous methods."""

from __future__ import annotations

from dataclasses import dataclass
import random

from fedctl_research.seeding import derive_seed


@dataclass
class ModelRateAssigner:
    mode: str
    default_model_rate: float
    explicit_rate_by_node_id: dict[int, float]
    explicit_rate_by_partition_id: dict[int, float]
    rate_by_device_type: dict[str, float]
    device_type_by_node_id: dict[int, str]
    partition_id_by_node_id: dict[int, int]
    dynamic_levels: tuple[float, ...]
    dynamic_proportions: tuple[float, ...]
    seed: int | None = None

    def set_node_capabilities(self, device_type_by_node_id: dict[int, str]) -> None:
        self.device_type_by_node_id = dict(device_type_by_node_id)

    def set_node_partition_ids(self, partition_id_by_node_id: dict[int, int]) -> None:
        self.partition_id_by_node_id = dict(partition_id_by_node_id)

    def summary_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "default_model_rate": self.default_model_rate,
            "explicit_rate_by_node_id": dict(self.explicit_rate_by_node_id),
            "explicit_rate_by_partition_id": dict(self.explicit_rate_by_partition_id),
            "rate_by_device_type": dict(self.rate_by_device_type),
            "device_type_by_node_id": dict(self.device_type_by_node_id),
            "partition_id_by_node_id": dict(self.partition_id_by_node_id),
            "dynamic_levels": self.dynamic_levels,
            "dynamic_proportions": self.dynamic_proportions,
        }

    def eval_rates(self, *, global_model_rate: float) -> tuple[float, ...]:
        configured_rates: set[float] = {float(global_model_rate)}
        if self.mode == "fix":
            configured_rates.add(float(self.default_model_rate))
            configured_rates.update(float(rate) for rate in self.explicit_rate_by_node_id.values())
            configured_rates.update(float(rate) for rate in self.explicit_rate_by_partition_id.values())
            configured_rates.update(float(rate) for rate in self.rate_by_device_type.values())
        elif self.mode == "dynamic":
            configured_rates.add(float(self.default_model_rate))
            configured_rates.update(float(rate) for rate in self.dynamic_levels)
        else:
            raise ValueError(f"Unsupported model-split-mode: {self.mode}")
        return tuple(sorted(rate for rate in configured_rates if 0.0 < rate <= global_model_rate))

    def assign_for_round(self, node_ids: list[int], server_round: int) -> dict[int, float]:
        if self.mode == "fix":
            return {node_id: self._resolve_fixed_rate(node_id) for node_id in node_ids}
        if self.mode == "dynamic":
            return {node_id: self._sample_dynamic_rate(node_id, server_round) for node_id in node_ids}
        raise ValueError(f"Unsupported model-split-mode: {self.mode}")

    def _resolve_fixed_rate(self, node_id: int) -> float:
        explicit_rate = self.explicit_rate_by_node_id.get(node_id)
        if explicit_rate is not None:
            return float(explicit_rate)
        partition_id = self.partition_id_by_node_id.get(node_id)
        if partition_id is not None:
            partition_rate = self.explicit_rate_by_partition_id.get(int(partition_id))
            if partition_rate is not None:
                return float(partition_rate)
        device_type = self.device_type_by_node_id.get(node_id)
        if device_type is not None and device_type in self.rate_by_device_type:
            return float(self.rate_by_device_type[device_type])
        return float(self.default_model_rate)

    def _sample_dynamic_rate(self, node_id: int, server_round: int) -> float:
        if not self.dynamic_levels:
            raise ValueError("dynamic model-rate assignment requires non-empty model-rate-levels")
        seed = derive_seed(
            int(self.seed or 0),
            "model-rate",
            server_round,
            node_id,
        )
        rng = random.Random(seed)
        threshold = rng.random()
        cumulative = 0.0
        for rate, proportion in zip(self.dynamic_levels, self.dynamic_proportions):
            cumulative += proportion
            if threshold <= cumulative:
                return float(rate)
        return float(self.dynamic_levels[-1])
