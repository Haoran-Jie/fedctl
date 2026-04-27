"""Task protocol for research experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

if TYPE_CHECKING:
    from fedctl_research.partitioning.partition_request import PartitionRequest


@dataclass(frozen=True)
class PartitionBundle:
    trainloader: DataLoader
    testloader: DataLoader
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    label_set: tuple[int, ...]
    label_mask: torch.Tensor | None
    num_train_examples: int
    num_test_examples: int


class TaskSpec(Protocol):
    name: str
    primary_score_name: str
    primary_score_direction: str

    def build_model_for_rate(
        self,
        model_rate: float,
        *,
        global_model_rate: float = 1.0,
    ) -> nn.Module: ...

    def load_model_state(self, model: nn.Module, state_dict: dict[str, torch.Tensor]) -> None: ...

    def load_data(
        self,
        request: PartitionRequest,
        batch_size: int,
        *,
        max_train_examples: int | None = None,
        max_test_examples: int | None = None,
    ) -> PartitionBundle: ...

    def load_centralized_test_dataset(
        self, batch_size: int = 256, *, seed: int | None = None
    ) -> DataLoader: ...

    def train(
        self,
        model: nn.Module,
        trainloader: DataLoader,
        epochs: int,
        lr: float,
        device: torch.device | str,
        *,
        optimizer: str = "sgd",
        label_mask: torch.Tensor | None = None,
        masked_cross_entropy: str = "off",
        partitioning: str = "iid",
        log_prefix: str | None = None,
    ) -> float: ...

    def test(
        self,
        model: nn.Module,
        testloader: DataLoader,
        device: torch.device | str,
    ) -> tuple[float, float]: ...

    def compute_loss(
        self,
        model_output: torch.Tensor,
        labels: torch.Tensor,
        *,
        label_mask: torch.Tensor | None = None,
        masked_cross_entropy: str = "off",
        partitioning: str = "iid",
    ) -> torch.Tensor: ...


@dataclass(frozen=True)
class RegisteredTask:
    name: str
    spec: TaskSpec
