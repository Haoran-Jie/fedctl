"""Dirichlet partitioner for classification datasets."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from fedctl_research.partitioning.classification_partitioner import (
    ClassificationPartitionResult,
    ClassificationPartitioner,
)
from fedctl_research.partitioning.partition_request import PartitionRequest


class DirichletPartitioner(ClassificationPartitioner):
    @classmethod
    def from_request(
        cls,
        labels: tuple[int, ...],
        *,
        num_classes: int,
        request: PartitionRequest,
        label_sets: tuple[tuple[int, ...], ...] | None = None,
        class_probabilities: np.ndarray | None = None,
        partition_device_types: tuple[str, ...] | None = None,
    ) -> DirichletPartitioner:
        del label_sets, partition_device_types
        return cls(
            labels,
            num_classes=num_classes,
            num_partitions=request.effective_num_partitions,
            alpha=request.partitioning_dirichlet_alpha,
            seed=request.effective_assignment_seed,
            class_probabilities=class_probabilities,
        )

    def __init__(
        self,
        labels: Sequence[int],
        *,
        num_classes: int,
        num_partitions: int,
        alpha: float,
        seed: int,
        class_probabilities: np.ndarray | None = None,
    ) -> None:
        super().__init__(
            labels,
            num_classes=num_classes,
            num_partitions=num_partitions,
            seed=seed,
        )
        self.alpha = float(alpha)
        self._provided_class_probabilities = (
            np.asarray(class_probabilities, dtype=np.float64)
            if class_probabilities is not None
            else None
        )

    def _compute_partition_result(self) -> ClassificationPartitionResult:
        if self.alpha <= 0:
            raise ValueError("partitioning-dirichlet-alpha must be positive")
        labels_np = np.asarray(self.labels, dtype=np.int64)
        rng = np.random.default_rng(self.seed)

        if self._provided_class_probabilities is None:
            class_probabilities = _sample_dirichlet_probabilities(
                labels_np,
                num_classes=self.num_classes,
                num_partitions=self.num_partitions,
                alpha=self.alpha,
                seed=self.seed,
            )
        else:
            class_probabilities = np.asarray(
                self._provided_class_probabilities, dtype=np.float64
            )
            if class_probabilities.shape != (self.num_classes, self.num_partitions):
                raise ValueError("class_probabilities has incompatible shape")

        partition_indices: list[list[int]] = [[] for _ in range(self.num_partitions)]
        for class_id in range(self.num_classes):
            class_indices = np.where(labels_np == class_id)[0]
            if class_indices.size == 0:
                continue
            class_indices = class_indices.copy()
            rng.shuffle(class_indices)
            probs = class_probabilities[class_id]
            counts = rng.multinomial(class_indices.size, probs / probs.sum())
            start = 0
            for partition_id, count in enumerate(counts.tolist()):
                if count <= 0:
                    continue
                stop = start + count
                partition_indices[partition_id].extend(
                    int(idx) for idx in class_indices[start:stop].tolist()
                )
                start = stop

        if any(len(indices) == 0 for indices in partition_indices):
            partition_indices = _rebalance_empty_partitions(partition_indices)

        indices_tuple = tuple(tuple(sorted(indices)) for indices in partition_indices)
        probs_tuple = tuple(
            tuple(float(value) for value in row.tolist()) for row in class_probabilities
        )
        return ClassificationPartitionResult(
            indices_by_partition=indices_tuple,
            label_sets_by_partition=self._label_sets_from_indices(indices_tuple),
            class_probabilities=probs_tuple,
        )


def _sample_dirichlet_probabilities(
    labels: np.ndarray,
    *,
    num_classes: int,
    num_partitions: int,
    alpha: float,
    seed: int,
) -> np.ndarray:
    for offset in range(32):
        rng = np.random.default_rng(seed + offset)
        probs = rng.dirichlet(
            np.full(num_partitions, alpha, dtype=np.float64), size=num_classes
        )
        non_empty_possible = True
        for class_id in range(num_classes):
            if np.sum(labels == class_id) == 0:
                continue
            expected = probs[class_id] * np.sum(labels == class_id)
            if np.all(expected < 1e-6):
                non_empty_possible = False
                break
        if non_empty_possible:
            return probs
    raise RuntimeError("Failed to sample valid Dirichlet partition probabilities")


def _rebalance_empty_partitions(
    partition_indices: list[list[int]],
) -> list[list[int]]:
    donors = sorted(
        range(len(partition_indices)),
        key=lambda idx: len(partition_indices[idx]),
        reverse=True,
    )
    for partition_id, indices in enumerate(partition_indices):
        if indices:
            continue
        for donor_id in donors:
            if len(partition_indices[donor_id]) > 1:
                indices.append(partition_indices[donor_id].pop())
                break
    return partition_indices
