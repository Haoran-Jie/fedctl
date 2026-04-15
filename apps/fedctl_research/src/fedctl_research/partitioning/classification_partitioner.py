"""Shared classification partitioners and bundle helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import TypeAlias

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, Subset

from fedctl_research.partitioning.base import Partitioner
from fedctl_research.partitioning.partition_request import PartitionRequest
from fedctl_research.seeding import make_torch_generator
from fedctl_research.tasks.base import PartitionBundle


@dataclass(frozen=True)
class ClassificationPartitionResult:
    indices_by_partition: tuple[tuple[int, ...], ...]
    label_sets_by_partition: tuple[tuple[int, ...], ...]
    class_probabilities: tuple[tuple[float, ...], ...] | None = None


class ClassificationPartitioner(Partitioner):
    """Base partitioner for label-indexable classification datasets."""

    def __init__(
        self,
        labels: tuple[int, ...],
        *,
        num_classes: int,
        num_partitions: int,
        seed: int,
    ) -> None:
        super().__init__(num_partitions)
        self.labels = tuple(int(label) for label in labels)
        self.num_classes = int(num_classes)
        self.seed = int(seed)

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
    ) -> ClassificationPartitioner:
        raise NotImplementedError

    def load_partition(self, partition_id: int) -> tuple[int, ...]:
        self._validate_partition_id(partition_id)
        return self.partition_result.indices_by_partition[partition_id]

    def load_label_set(self, partition_id: int) -> tuple[int, ...]:
        self._validate_partition_id(partition_id)
        return self.partition_result.label_sets_by_partition[partition_id]

    @cached_property
    def partition_result(self) -> ClassificationPartitionResult:
        return self._compute_partition_result()

    def _validate_partition_id(self, partition_id: int) -> None:
        if partition_id < 0 or partition_id >= self.num_partitions:
            raise IndexError(
                f"partition_id must be in [0, {self.num_partitions}), got {partition_id}"
            )

    def _label_sets_from_indices(
        self, indices_by_partition: tuple[tuple[int, ...], ...]
    ) -> tuple[tuple[int, ...], ...]:
        return tuple(
            tuple(sorted({self.labels[idx] for idx in partition_indices}))
            for partition_indices in indices_by_partition
        )

    def _shuffled_class_shards(
        self, *, num_labels_per_partition: int
    ) -> tuple[dict[int, list[np.ndarray]], np.random.Generator]:
        if self.num_classes <= 0:
            raise ValueError("num_classes must be positive")
        if num_labels_per_partition <= 0:
            raise ValueError("partitioning-num-labels must be positive")
        shard_per_class = (num_labels_per_partition * self.num_partitions) / self.num_classes
        if int(shard_per_class) != shard_per_class:
            raise ValueError(
                "Balanced label-skew requires "
                "(num_labels_per_partition * num_partitions) to be divisible by num_classes"
            )
        shard_per_class = int(shard_per_class)
        rng = np.random.default_rng(self.seed)
        label_idx_split: dict[int, list[np.ndarray]] = {}
        for class_id in range(self.num_classes):
            class_indices = np.array(
                [idx for idx, label in enumerate(self.labels) if label == class_id],
                dtype=np.int64,
            )
            rng.shuffle(class_indices)
            if class_indices.size == 0:
                label_idx_split[class_id] = [
                    np.array([], dtype=np.int64) for _ in range(shard_per_class)
                ]
                continue
            shards = np.array_split(class_indices, shard_per_class)
            label_idx_split[class_id] = [
                np.array(shard, dtype=np.int64) for shard in shards
            ]
        return label_idx_split, rng

    def _compute_partition_result(self) -> ClassificationPartitionResult:
        raise NotImplementedError


ClassificationPartitionerClass: TypeAlias = type[ClassificationPartitioner]
_PARTITIONERS: dict[str, ClassificationPartitionerClass] | None = None


def partitioners() -> dict[str, ClassificationPartitionerClass]:
    global _PARTITIONERS
    if _PARTITIONERS is None:
        from fedctl_research.partitioning.balanced_label_skew_partitioner import (
            BalancedLabelSkewPartitioner,
        )
        from fedctl_research.partitioning.device_correlated_label_skew_partitioner import (
            DeviceCorrelatedLabelSkewPartitioner,
        )
        from fedctl_research.partitioning.dirichlet_partitioner import DirichletPartitioner
        from fedctl_research.partitioning.iid_partitioner import IidPartitioner

        _PARTITIONERS = {
            "iid": IidPartitioner,
            "dirichlet": DirichletPartitioner,
            "label-skew-balanced": BalancedLabelSkewPartitioner,
            "device-correlated-label-skew": DeviceCorrelatedLabelSkewPartitioner,
        }
    return _PARTITIONERS


def labels_tuple(dataset: Dataset) -> tuple[int, ...]:
    cached = getattr(dataset, "_fedctl_labels_tuple", None)
    if cached is not None:
        return cached
    if hasattr(dataset, "targets"):
        raw = getattr(dataset, "targets")
    elif hasattr(dataset, "target"):
        raw = getattr(dataset, "target")
    else:
        raise AttributeError("Dataset does not expose .targets or .target")
    if isinstance(raw, torch.Tensor):
        labels = tuple(int(item) for item in raw.tolist())
    else:
        labels = tuple(int(item) for item in list(raw))
    setattr(dataset, "_fedctl_labels_tuple", labels)
    return labels


def build_classification_partitioner(
    *,
    labels: tuple[int, ...],
    num_classes: int,
    request: PartitionRequest,
    label_sets: tuple[tuple[int, ...], ...] | None = None,
    class_probabilities: np.ndarray | None = None,
    partition_device_types: tuple[str, ...] | None = None,
) -> ClassificationPartitioner:
    partitioner_cls = partitioners().get(request.partitioning)
    if partitioner_cls is None:
        raise ValueError(f"Unsupported partitioning mode: {request.partitioning}")
    return partitioner_cls.from_request(
        labels,
        num_classes=num_classes,
        request=request,
        label_sets=label_sets,
        class_probabilities=class_probabilities,
        partition_device_types=partition_device_types,
    )


def build_classification_partition_bundle(
    *,
    trainset: Dataset,
    testset: Dataset,
    num_classes: int,
    batch_size: int,
    request: PartitionRequest,
    max_train_examples: int | None,
    max_test_examples: int | None,
) -> PartitionBundle:
    train_result, test_result = _build_partition_results(
        train_labels=labels_tuple(trainset),
        test_labels=labels_tuple(testset),
        num_classes=num_classes,
        request=_assignment_request(request),
    )
    effective_partition_id = request.effective_partition_id

    train_indices = list(train_result.indices_by_partition[effective_partition_id])
    test_indices = list(test_result.indices_by_partition[effective_partition_id])
    if max_train_examples is not None:
        train_indices = train_indices[: max(max_train_examples, 0)]
    if max_test_examples is not None:
        test_indices = test_indices[: max(max_test_examples, 0)]

    label_set = tuple(sorted(train_result.label_sets_by_partition[effective_partition_id]))
    label_mask = torch.zeros(num_classes, dtype=torch.bool)
    if label_set:
        label_mask[list(label_set)] = True

    trainloader = DataLoader(
        Subset(trainset, train_indices),
        batch_size=batch_size,
        shuffle=True,
        num_workers=0,
        generator=make_torch_generator(request.loader_seed) if request.loader_seed is not None else None,
    )
    testloader = DataLoader(
        Subset(testset, test_indices),
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
    )
    return PartitionBundle(
        trainloader=trainloader,
        testloader=testloader,
        train_indices=tuple(train_indices),
        test_indices=tuple(test_indices),
        label_set=label_set,
        label_mask=label_mask,
        num_train_examples=len(train_indices),
        num_test_examples=len(test_indices),
    )


@lru_cache(maxsize=32)
def _build_partition_results(
    *,
    train_labels: tuple[int, ...],
    test_labels: tuple[int, ...],
    num_classes: int,
    request: PartitionRequest,
) -> tuple[ClassificationPartitionResult, ClassificationPartitionResult]:
    train_partitioner = build_classification_partitioner(
        labels=train_labels,
        num_classes=num_classes,
        request=request,
    )
    train_result = train_partitioner.partition_result

    class_probabilities = (
        np.array(train_result.class_probabilities, dtype=np.float64)
        if train_result.class_probabilities is not None
        else None
    )
    test_partitioner = build_classification_partitioner(
        labels=test_labels,
        num_classes=num_classes,
        request=request,
        label_sets=train_result.label_sets_by_partition,
        class_probabilities=class_probabilities,
    )
    return train_result, test_partitioner.partition_result


def _assignment_request(request: PartitionRequest) -> PartitionRequest:
    return PartitionRequest(
        partition_id=0,
        num_partitions=request.effective_num_partitions,
        partitioning=request.partitioning,
        device_type=request.device_type,
        partitioning_num_labels=request.partitioning_num_labels,
        partitioning_dirichlet_alpha=request.partitioning_dirichlet_alpha,
        assignment_seed=request.effective_assignment_seed,
        loader_seed=None,
    )
