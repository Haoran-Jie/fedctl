"""CIFAR-10 width-scaled PreAct ResNet18 task."""

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
from fedctl_research.tasks.cifar10.data import (
    load_centralized_test_dataset,
    load_partitioned_data,
)
from fedctl_research.tasks.layers import Scaler, StaticBatchNorm2d


class PreActBlock(nn.Module):
    expansion = 1

    def __init__(self, in_planes: int, planes: int, stride: int, scaler_rate: float):
        super().__init__()
        self.bn1 = StaticBatchNorm2d(in_planes)
        self.conv1 = nn.Conv2d(in_planes, planes, kernel_size=3, stride=stride, padding=1, bias=False)
        self.scale1 = Scaler(scaler_rate)
        self.bn2 = StaticBatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=1, padding=1, bias=False)
        self.scale2 = Scaler(scaler_rate)
        if stride != 1 or in_planes != planes:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_planes, planes, kernel_size=1, stride=stride, bias=False),
                Scaler(scaler_rate),
            )
        else:
            self.shortcut = nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = torch.relu(self.bn1(x))
        shortcut = self.shortcut(out if not isinstance(self.shortcut, nn.Identity) else x)
        out = self.scale1(self.conv1(out))
        out = torch.relu(self.bn2(out))
        out = self.scale2(self.conv2(out))
        return out + shortcut


class PreActResNet(nn.Module):
    def __init__(self, widths: list[int], scaler_rate: float, num_classes: int = 10):
        super().__init__()
        self.in_planes = widths[0]
        self.conv1 = nn.Conv2d(3, widths[0], kernel_size=3, stride=1, padding=1, bias=False)
        self.scale0 = Scaler(scaler_rate)
        self.layer1 = self._make_layer(widths[0], num_blocks=2, stride=1, scaler_rate=scaler_rate)
        self.layer2 = self._make_layer(widths[1], num_blocks=2, stride=2, scaler_rate=scaler_rate)
        self.layer3 = self._make_layer(widths[2], num_blocks=2, stride=2, scaler_rate=scaler_rate)
        self.layer4 = self._make_layer(widths[3], num_blocks=2, stride=2, scaler_rate=scaler_rate)
        self.bn = StaticBatchNorm2d(widths[3])
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.fc = nn.Linear(widths[3], num_classes)

    def _make_layer(self, planes: int, num_blocks: int, stride: int, scaler_rate: float) -> nn.Sequential:
        strides = [stride] + [1] * (num_blocks - 1)
        blocks: list[nn.Module] = []
        for current_stride in strides:
            blocks.append(PreActBlock(self.in_planes, planes, current_stride, scaler_rate))
            self.in_planes = planes * PreActBlock.expansion
        return nn.Sequential(*blocks)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.scale0(self.conv1(x))
        out = self.layer1(out)
        out = self.layer2(out)
        out = self.layer3(out)
        out = self.layer4(out)
        out = torch.relu(self.bn(out))
        out = self.pool(out)
        out = torch.flatten(out, 1)
        return self.fc(out)


def _scaled_widths(model_rate: float) -> list[int]:
    return [
        max(8, int(round(64 * model_rate))),
        max(16, int(round(128 * model_rate))),
        max(32, int(round(256 * model_rate))),
        max(64, int(round(512 * model_rate))),
    ]


def build_model_for_rate(model_rate: float, *, global_model_rate: float = 1.0) -> PreActResNet:
    scaler_rate = float(model_rate) / float(global_model_rate)
    return PreActResNet(_scaled_widths(model_rate), scaler_rate=scaler_rate)


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
        log_prefix=log_prefix or "[cifar10_preresnet18]",
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
class Cifar10PreActResNet18Task:
    name: str = "cifar10_preresnet18"
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


TASK = Cifar10PreActResNet18Task()
