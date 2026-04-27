"""Appliances Energy Prediction width-scaled MLP task."""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from fedctl_research.partitioning.partition_request import PartitionRequest
from fedctl_research.runtime.regression import (
    evaluate_regressor,
    regression_mse_loss,
    train_regressor,
)
from fedctl_research.tasks.appliances_energy.data import (
    load_centralized_test_dataset,
    load_partitioned_data,
)
from fedctl_research.tasks.base import PartitionBundle

INPUT_DIM = 33


class AppliancesEnergyMLP(nn.Module):
    def __init__(self, input_dim: int, hidden1: int, hidden2: int):
        super().__init__()
        self.regressor = nn.Sequential(
            nn.Linear(input_dim, hidden1),
            nn.ReLU(inplace=True),
            nn.Linear(hidden1, hidden2),
            nn.ReLU(inplace=True),
            nn.Linear(hidden2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.regressor(x)


def _scaled_hidden(model_rate: float, base_width: int) -> int:
    return max(16, int(round(base_width * model_rate)))


def build_model_for_rate(
    model_rate: float,
    *,
    global_model_rate: float = 1.0,
) -> AppliancesEnergyMLP:
    _ = global_model_rate
    return AppliancesEnergyMLP(
        input_dim=INPUT_DIM,
        hidden1=_scaled_hidden(model_rate, 256),
        hidden2=_scaled_hidden(model_rate, 128),
    )


def load_model_state(model: nn.Module, state_dict: dict[str, torch.Tensor]) -> None:
    model.load_state_dict(state_dict, strict=True)


def train(
    model: nn.Module,
    trainloader: DataLoader,
    epochs: int,
    lr: float,
    device: torch.device | str,
    *,
    optimizer: str = "adam",
    label_mask: torch.Tensor | None = None,
    masked_cross_entropy: str = "off",
    partitioning: str = "iid",
    log_prefix: str | None = None,
) -> float:
    del label_mask, masked_cross_entropy, partitioning
    return train_regressor(
        model,
        trainloader,
        epochs,
        lr,
        device,
        optimizer=optimizer,
        log_prefix=log_prefix or "[appliances_energy_mlp]",
    )


def test(model: nn.Module, testloader: DataLoader, device: torch.device | str) -> tuple[float, float]:
    return evaluate_regressor(model, testloader, device)


def compute_loss(
    model_output: torch.Tensor,
    labels: torch.Tensor,
    *,
    label_mask: torch.Tensor | None = None,
    masked_cross_entropy: str = "off",
    partitioning: str = "iid",
) -> torch.Tensor:
    del label_mask, masked_cross_entropy, partitioning
    return regression_mse_loss(model_output, labels)


@dataclass(frozen=True)
class AppliancesEnergyMlpTask:
    name: str = "appliances_energy_mlp"
    primary_score_name: str = "r2"
    primary_score_direction: str = "max"
    example_input_shape: tuple[int, int] = (1, INPUT_DIM)

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
        optimizer: str = "adam",
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


TASK = AppliancesEnergyMlpTask()
