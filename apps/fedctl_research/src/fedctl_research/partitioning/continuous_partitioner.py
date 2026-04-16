"""Continuous partitioner for sortable scalar-valued datasets."""

from __future__ import annotations

import numpy as np

from fedctl_research.partitioning.base import Partitioner


class ContinuousPartitioner(Partitioner):
    """Partition data by sorting a continuous property with controllable noise."""

    def __init__(
        self,
        values: np.ndarray | list[float] | tuple[float, ...],
        *,
        num_partitions: int,
        seed: int,
        strictness: float,
    ) -> None:
        super().__init__(num_partitions)
        self.values = np.asarray(values, dtype=np.float64)
        self.seed = int(seed)
        self.strictness = float(strictness)

    def load_partition(self, partition_id: int) -> tuple[int, ...]:
        if partition_id < 0 or partition_id >= self.num_partitions:
            raise IndexError(
                f"partition_id must be in [0, {self.num_partitions}), got {partition_id}"
            )
        return self.partitions[partition_id]

    @property
    def partitions(self) -> tuple[tuple[int, ...], ...]:
        if not hasattr(self, "_cached_partitions"):
            if not 0.0 <= self.strictness <= 1.0:
                raise ValueError("strictness must be in [0, 1]")
            mean = float(np.mean(self.values))
            std = float(np.std(self.values))
            if std <= 1e-12:
                normalized = np.zeros_like(self.values, dtype=np.float64)
            else:
                normalized = (self.values - mean) / std
            rng = np.random.default_rng(self.seed)
            noise = rng.standard_normal(self.values.shape[0])
            blended = (self.strictness * normalized) + ((1.0 - self.strictness) * noise)
            order = np.argsort(blended, kind="mergesort")
            splits = np.array_split(order, self.num_partitions)
            self._cached_partitions = tuple(
                tuple(int(index) for index in split.tolist()) for split in splits
            )
        return self._cached_partitions
