"""IID partitioner for classification datasets."""

from __future__ import annotations

import numpy as np

from fedctl_research.partitioning.classification_partitioner import (
    ClassificationPartitionResult,
    ClassificationPartitioner,
)
from fedctl_research.partitioning.partition_request import PartitionRequest


class IidPartitioner(ClassificationPartitioner):
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
    ) -> IidPartitioner:
        del label_sets, class_probabilities, partition_device_types
        return cls(
            labels,
            num_classes=num_classes,
            num_partitions=request.effective_num_partitions,
            seed=request.effective_assignment_seed,
        )

    def _compute_partition_result(self) -> ClassificationPartitionResult:
        rng = np.random.default_rng(self.seed)
        permutation = rng.permutation(len(self.labels)).tolist()
        splits = np.array_split(np.array(permutation, dtype=np.int64), self.num_partitions)
        indices_by_partition = tuple(
            tuple(int(i) for i in split.tolist()) for split in splits
        )
        return ClassificationPartitionResult(
            indices_by_partition=indices_by_partition,
            label_sets_by_partition=self._label_sets_from_indices(indices_by_partition),
        )
