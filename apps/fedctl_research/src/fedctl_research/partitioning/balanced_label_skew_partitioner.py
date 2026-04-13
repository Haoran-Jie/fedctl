"""Balanced label-skew partitioners for classification datasets."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from fedctl_research.partitioning.classification_partitioner import (
    ClassificationPartitionResult,
    ClassificationPartitioner,
)
from fedctl_research.partitioning.partition_request import PartitionRequest


class BalancedLabelSkewPartitioner(ClassificationPartitioner):
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
    ) -> BalancedLabelSkewPartitioner:
        del class_probabilities, partition_device_types
        return cls(
            labels,
            num_classes=num_classes,
            num_partitions=request.effective_num_partitions,
            num_labels_per_partition=request.partitioning_num_labels,
            seed=request.effective_assignment_seed,
            label_sets=label_sets,
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
    ) -> None:
        super().__init__(
            labels,
            num_classes=num_classes,
            num_partitions=num_partitions,
            seed=seed,
        )
        self.num_labels_per_partition = int(num_labels_per_partition)
        self._provided_label_sets = (
            tuple(tuple(int(label) for label in row) for row in label_sets)
            if label_sets is not None
            else None
        )

    def _resolve_label_sets(self) -> list[tuple[int, ...]]:
        if self._provided_label_sets is not None:
            return [
                tuple(sorted(int(label) for label in labels_i))
                for labels_i in self._provided_label_sets
            ]
        repeated = np.repeat(
            np.arange(self.num_classes, dtype=np.int64),
            (self.num_labels_per_partition * self.num_partitions) // self.num_classes,
        )
        rng = np.random.default_rng(self.seed)
        rng.shuffle(repeated)
        label_matrix = repeated.reshape((self.num_partitions, self.num_labels_per_partition))
        return [tuple(sorted(np.unique(row).tolist())) for row in label_matrix]

    def _compute_partition_result(self) -> ClassificationPartitionResult:
        label_idx_split, rng = self._shuffled_class_shards(
            num_labels_per_partition=self.num_labels_per_partition
        )
        resolved_label_sets = self._resolve_label_sets()

        indices_by_partition: list[tuple[int, ...]] = []
        for partition_labels in resolved_label_sets:
            partition_indices: list[int] = []
            for class_id in partition_labels:
                shards = label_idx_split[class_id]
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
