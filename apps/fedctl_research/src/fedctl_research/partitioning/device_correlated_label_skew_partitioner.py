"""Device-correlated balanced label-skew partitioner."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from fedctl_research.partitioning.balanced_label_skew_partitioner import (
    BalancedLabelSkewPartitioner,
)
from fedctl_research.partitioning.classification_partitioner import (
    ClassificationPartitionResult,
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
        label_matrix = _device_correlated_label_matrix(
            num_classes=self.num_classes,
            num_partitions=self.num_partitions,
            num_labels_per_partition=self.num_labels_per_partition,
            seed=self.seed,
            device_type=self.device_type,
            partition_device_types=self.partition_device_types,
        )
        return [tuple(sorted(np.unique(row).tolist())) for row in label_matrix]

    def _compute_partition_result(self) -> ClassificationPartitionResult:
        resolved_label_sets = self._resolve_label_sets()
        shards_by_class, rng = _shards_for_resolved_label_sets(
            labels=self.labels,
            num_classes=self.num_classes,
            label_sets=resolved_label_sets,
            seed=self.seed,
        )

        indices_by_partition: list[tuple[int, ...]] = []
        for partition_labels in resolved_label_sets:
            partition_indices: list[int] = []
            for class_id in partition_labels:
                shards = shards_by_class[class_id]
                available = [
                    idx for idx, shard in enumerate(shards) if shard.size > 0
                ]
                if not available:
                    continue
                shard_idx = int(rng.choice(np.array(available, dtype=np.int64)))
                partition_indices.extend(int(i) for i in shards[shard_idx].tolist())
                shards[shard_idx] = np.array([], dtype=np.int64)
            indices_by_partition.append(tuple(sorted(partition_indices)))

        indices_tuple = tuple(indices_by_partition)
        return ClassificationPartitionResult(
            indices_by_partition=indices_tuple,
            label_sets_by_partition=self._label_sets_from_indices(indices_tuple),
        )


def _device_correlated_label_matrix(
    *,
    num_classes: int,
    num_partitions: int,
    num_labels_per_partition: int,
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

    midpoint = max(num_partitions // 2, 1)
    source_by_partition: list[str] = []
    for partition_id in range(num_partitions):
        if partition_device_types is None:
            normalized_device_type = str(device_type).lower()
            if normalized_device_type == "rpi4":
                source_key = "low"
            elif normalized_device_type == "rpi5":
                source_key = "high"
            else:
                source_key = "low" if partition_id < midpoint else "high"
        else:
            device_type = str(partition_device_types[partition_id]).lower()
            source_key = "low" if device_type == "rpi4" else "high"
        source_by_partition.append(source_key)

    label_matrix = np.empty((num_partitions, num_labels_per_partition), dtype=np.int64)
    for source_key, source in (("low", low_labels), ("high", high_labels)):
        partition_ids = [
            partition_id
            for partition_id, partition_source in enumerate(source_by_partition)
            if partition_source == source_key
        ]
        if not partition_ids:
            continue
        counts = {int(label): 0 for label in source.tolist()}
        for partition_id in partition_ids:
            row: list[int] = []
            for _ in range(num_labels_per_partition):
                candidates = [
                    int(label) for label in source.tolist() if int(label) not in row
                ]
                if not candidates:
                    candidates = [int(label) for label in source.tolist()]
                min_count = min(counts[label] for label in candidates)
                least_used = [label for label in candidates if counts[label] == min_count]
                label = int(rng.choice(least_used))
                counts[label] += 1
                row.append(label)
            label_matrix[partition_id] = np.array(row, dtype=np.int64)
    return label_matrix


def _shards_for_resolved_label_sets(
    *,
    labels: Sequence[int],
    num_classes: int,
    label_sets: Sequence[Sequence[int]],
    seed: int,
) -> tuple[dict[int, list[np.ndarray]], np.random.Generator]:
    rng = np.random.default_rng(seed)
    occurrences = {
        class_id: sum(class_id in set(label_set) for label_set in label_sets)
        for class_id in range(num_classes)
    }
    shards_by_class: dict[int, list[np.ndarray]] = {}
    for class_id in range(num_classes):
        class_indices = np.array(
            [idx for idx, label in enumerate(labels) if int(label) == class_id],
            dtype=np.int64,
        )
        rng.shuffle(class_indices)
        shard_count = occurrences[class_id]
        if shard_count <= 0:
            shards_by_class[class_id] = []
        else:
            shards_by_class[class_id] = [
                np.array(shard, dtype=np.int64)
                for shard in np.array_split(class_indices, shard_count)
            ]
    return shards_by_class, rng
