"""Fashion-MNIST tiny width-scaled MLP task."""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from fedctl_research.runtime.classification import (
    evaluate_classifier,
    masked_cross_entropy_loss,
    should_use_masked_cross_entropy,
    train_classifier,
)
from fedctl_research.partitioning.partition_request import PartitionRequest
from fedctl_research.tasks.base import PartitionBundle
from fedctl_research.tasks.fashion_mnist.data import (
    load_centralized_test_dataset,
    load_partitioned_data,
)


class HeteroMLP(nn.Module):
    """A tiny width-scaled MLP for Fashion-MNIST."""

    def __init__(self, hidden: int, num_classes: int = 10):
        super().__init__()
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(28 * 28, hidden),
            nn.ReLU(inplace=True),
            nn.Linear(hidden, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(x)


def _scaled_hidden(model_rate: float) -> int:
    return max(16, int(round(128 * model_rate)))


def build_model_for_rate(
    model_rate: float,
    *,
    global_model_rate: float = 1.0,
) -> HeteroMLP:
    _ = global_model_rate
    return HeteroMLP(hidden=_scaled_hidden(model_rate))


def load_model_state(model: nn.Module, state_dict: dict[str, torch.Tensor]) -> None:
    model.load_state_dict(state_dict, strict=True)


def train(
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
) -> float:
    return train_classifier(
        model,
        trainloader,
        epochs,
        lr,
        device,
        optimizer=optimizer,
        label_mask=label_mask,
        use_masked_cross_entropy=should_use_masked_cross_entropy(
            masked_cross_entropy,
            partitioning=partitioning,
        ),
        log_prefix=log_prefix or "[fashion_mnist_mlp]",
    )


def test(model: nn.Module, testloader: DataLoader, device: torch.device | str) -> tuple[float, float]:
    return evaluate_classifier(model, testloader, device)


def compute_loss(
    model_output: torch.Tensor,
    labels: torch.Tensor,
    *,
    label_mask: torch.Tensor | None = None,
    masked_cross_entropy: str = "off",
    partitioning: str = "iid",
) -> torch.Tensor:
    if should_use_masked_cross_entropy(masked_cross_entropy, partitioning=partitioning):
        return masked_cross_entropy_loss(model_output, labels, label_mask=label_mask)
    return nn.functional.cross_entropy(model_output, labels, reduction="mean")


@dataclass(frozen=True)
class FashionMnistMlpTask:
    name: str = "fashion_mnist_mlp"
    primary_score_name: str = "acc"
    primary_score_direction: str = "max"

    def build_model_for_rate(
        self,
        model_rate: float,
        *,
        global_model_rate: float = 1.0,
    ) -> nn.Module:
        return build_model_for_rate(model_rate, global_model_rate=global_model_rate)

    def load_model_state(self, model: nn.Module, state_dict: dict[str, torch.Tensor]) -> None:
        load_model_state(model, state_dict)

    def load_data(
        self,
        request: PartitionRequest,
        batch_size: int,
        *,
        max_train_examples: int | None = None,
        max_test_examples: int | None = None,
    ) -> PartitionBundle:
        return load_partitioned_data(
            request,
            batch_size,
            max_train_examples=max_train_examples,
            max_test_examples=max_test_examples,
        )

    def load_centralized_test_dataset(self, batch_size: int = 256, *, seed: int | None = None) -> DataLoader:
        return load_centralized_test_dataset(batch_size=batch_size, seed=seed)

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
    ) -> float:
        return train(
            model,
            trainloader,
            epochs,
            lr,
            device,
            optimizer=optimizer,
            label_mask=label_mask,
            masked_cross_entropy=masked_cross_entropy,
            partitioning=partitioning,
            log_prefix=log_prefix,
        )

    def test(
        self,
        model: nn.Module,
        testloader: DataLoader,
        device: torch.device | str,
    ) -> tuple[float, float]:
        return test(model, testloader, device)

    def compute_loss(
        self,
        model_output: torch.Tensor,
        labels: torch.Tensor,
        *,
        label_mask: torch.Tensor | None = None,
        masked_cross_entropy: str = "off",
        partitioning: str = "iid",
    ) -> torch.Tensor:
        return compute_loss(
            model_output,
            labels,
            label_mask=label_mask,
            masked_cross_entropy=masked_cross_entropy,
            partitioning=partitioning,
        )


TASK = FashionMnistMlpTask()
