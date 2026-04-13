"""Request object for deterministic client-side partition reconstruction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PartitionRequest:
    partition_id: int
    num_partitions: int
    partitioning: str
    device_type: str = "unknown"
    partitioning_num_labels: int = 2
    partitioning_dirichlet_alpha: float = 0.1
    assignment_seed: int | None = None
    loader_seed: int | None = None
    typed_partition_idx: int | None = None
    typed_partition_count: int | None = None

    @property
    def effective_partition_id(self) -> int:
        if self.partitioning == "device-correlated-label-skew" and self.typed_partition_idx is not None:
            return int(self.typed_partition_idx)
        return int(self.partition_id)

    @property
    def effective_num_partitions(self) -> int:
        if self.partitioning == "device-correlated-label-skew" and self.typed_partition_count is not None:
            return int(self.typed_partition_count)
        return int(self.num_partitions)

    @property
    def effective_assignment_seed(self) -> int:
        return int(self.assignment_seed or 0)
