"""Device-correlated balanced label-skew partitioner."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from fedctl_research.partitioning.balanced_label_skew_partitioner import (
    BalancedLabelSkewPartitioner,
)
from fedctl_research.partitioning.partition_request import PartitionRequest


class DeviceCorrelatedLabelSkewPartitioner(BalancedLabelSkewPartitioner):
    """Balanced label skew with low/high label bias across partition groups."""

    @classmethod
    def from_request(
        cls,
        labels: tuple[int, ...],
        *,
        num_classes: int,
        request: PartitionRequest,
        label_sets: tuple[tuple[int, ...], ...] | None = None,
        class_probabilities=None,
        partition_device_types: tuple[str, ...] | None = None,
    ) -> DeviceCorrelatedLabelSkewPartitioner:
        del class_probabilities
        return cls(
            labels,
            num_classes=num_classes,
            num_partitions=request.effective_num_partitions,
            num_labels_per_partition=request.partitioning_num_labels,
            seed=request.effective_assignment_seed,
            label_sets=label_sets,
            device_type=request.device_type,
            partition_device_types=partition_device_types,
        )

    def __init__(
        self,
        labels: Sequence[int],
        *,
        num_classes: int,
        num_partitions: int,
        num_labels_per_partition: int,
        seed: int,
        label_sets: Sequence[Sequence[int]] | None = None,
        device_type: str = "unknown",
        partition_device_types: Sequence[str] | None = None,
    ) -> None:
        super().__init__(
            labels,
            num_classes=num_classes,
            num_partitions=num_partitions,
            num_labels_per_partition=num_labels_per_partition,
            seed=seed,
            label_sets=label_sets,
        )
        self.partition_device_types = (
            tuple(str(device_type) for device_type in partition_device_types)
            if partition_device_types is not None
            else None
        )
        self.device_type = str(device_type)

    def _resolve_label_sets(self) -> list[tuple[int, ...]]:
        if self._provided_label_sets is not None:
            return super()._resolve_label_sets()
        repeated = np.repeat(
            np.arange(self.num_classes, dtype=np.int64),
            (self.num_labels_per_partition * self.num_partitions) // self.num_classes,
        )
        label_matrix = _device_correlated_label_matrix(
            num_classes=self.num_classes,
            num_partitions=self.num_partitions,
            num_labels_per_partition=self.num_labels_per_partition,
            repeated_labels=repeated,
            seed=self.seed,
            device_type=self.device_type,
            partition_device_types=self.partition_device_types,
        )
        return [tuple(sorted(np.unique(row).tolist())) for row in label_matrix]


def _device_correlated_label_matrix(
    *,
    num_classes: int,
    num_partitions: int,
    num_labels_per_partition: int,
    repeated_labels: np.ndarray,
    seed: int,
    device_type: str = "unknown",
    partition_device_types: Sequence[str] | None = None,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    low_labels = np.arange(max(1, num_classes // 2), dtype=np.int64)
    high_labels = np.arange(num_classes // 2, num_classes, dtype=np.int64)
    if low_labels.size == 0:
        low_labels = np.arange(num_classes, dtype=np.int64)
    if high_labels.size == 0:
        high_labels = np.arange(num_classes, dtype=np.int64)

    if partition_device_types is not None and len(partition_device_types) != num_partitions:
        raise ValueError("partition_device_types must have one entry per partition")

    label_matrix = np.empty((num_partitions, num_labels_per_partition), dtype=np.int64)
    midpoint = max(num_partitions // 2, 1)
    for partition_id in range(num_partitions):
        if partition_device_types is None:
            normalized_device_type = str(device_type).lower()
            if normalized_device_type == "rpi4":
                source = low_labels
            elif normalized_device_type == "rpi5":
                source = high_labels
            else:
                source = low_labels if partition_id < midpoint else high_labels
        else:
            device_type = str(partition_device_types[partition_id]).lower()
            source = low_labels if device_type == "rpi4" else high_labels
        picks = rng.choice(
            source,
            size=num_labels_per_partition,
            replace=source.size < num_labels_per_partition,
        )
        label_matrix[partition_id] = picks

    counts = {
        int(label): int(np.sum(label_matrix == label)) for label in range(num_classes)
    }
    target_counts = {
        int(label): int(np.sum(repeated_labels == label)) for label in range(num_classes)
    }
    deficits = [
        label
        for label in range(num_classes)
        for _ in range(max(target_counts[label] - counts.get(label, 0), 0))
    ]
    rng.shuffle(deficits)
    for label in range(num_classes):
        overflow = max(counts.get(label, 0) - target_counts[label], 0)
        if overflow <= 0:
            continue
        rows, cols = np.where(label_matrix == label)
        order = rng.permutation(len(rows))
        for idx in order[:overflow]:
            if not deficits:
                break
            label_matrix[rows[idx], cols[idx]] = deficits.pop()
    return label_matrix
