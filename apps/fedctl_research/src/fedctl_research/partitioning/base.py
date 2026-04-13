"""Partitioner base classes inspired by Flower Datasets."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Partitioner(ABC):
    """Base partitioner abstraction for reproducible dataset partitions."""

    def __init__(self, num_partitions: int) -> None:
        if num_partitions <= 0:
            raise ValueError("num_partitions must be positive")
        self._num_partitions = int(num_partitions)

    @property
    def num_partitions(self) -> int:
        return self._num_partitions

    @abstractmethod
    def load_partition(self, partition_id: int):
        """Return the requested partition."""

