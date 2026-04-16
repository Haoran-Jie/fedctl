"""Shared supervised regression train/eval loops."""

from __future__ import annotations

import time

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from fedctl_research.runtime.classification import create_optimizer


def regression_mse_loss(
    predictions: torch.Tensor,
    labels: torch.Tensor,
) -> torch.Tensor:
    preds = predictions.squeeze(-1)
    targets = labels.to(dtype=predictions.dtype).reshape_as(preds)
    return nn.functional.mse_loss(preds, targets, reduction="mean")


def train_regressor(
    model: nn.Module,
    trainloader: DataLoader,
    epochs: int,
    lr: float,
    device: torch.device | str,
    *,
    optimizer: str = "adam",
    log_prefix: str | None = None,
) -> float:
    model.to(device)
    optimizer_instance = create_optimizer(optimizer, model.parameters(), lr=lr)
    model.train()
    prefix = log_prefix or "[fedctl_research]"
    print(
        f"{prefix} train:enter "
        f"device={device} epochs={epochs} batches={len(trainloader)}",
        flush=True,
    )
    running_loss = 0.0
    steps = 0
    for epoch in range(epochs):
        epoch_start = time.perf_counter()
        epoch_loss = 0.0
        epoch_steps = 0
        for batch_idx, (features, labels) in enumerate(trainloader, start=1):
            if batch_idx == 1:
                batch_start = time.perf_counter()
            features = features.to(device)
            labels = labels.to(device)
            optimizer_instance.zero_grad()
            predictions = model(features)
            loss = regression_mse_loss(predictions, labels)
            loss.backward()
            optimizer_instance.step()
            if batch_idx == 1:
                print(
                    f"{prefix} train:first_batch done "
                    f"loss={float(loss.item()):.6f} elapsed_s={time.perf_counter() - batch_start:.2f}",
                    flush=True,
                )
            loss_value = float(loss.item())
            running_loss += loss_value
            steps += 1
            epoch_loss += loss_value
            epoch_steps += 1
        print(
            f"{prefix} train:epoch_done "
            f"epoch={epoch + 1}/{epochs} avg_loss={epoch_loss / max(epoch_steps, 1):.6f} "
            f"steps={epoch_steps} elapsed_s={time.perf_counter() - epoch_start:.2f}",
            flush=True,
        )
    return running_loss / max(steps, 1)


def evaluate_regressor(
    model: nn.Module,
    testloader: DataLoader,
    device: torch.device | str,
) -> tuple[float, float]:
    model.to(device)
    model.eval()
    total_loss = 0.0
    total_examples = 0
    all_targets: list[torch.Tensor] = []
    all_predictions: list[torch.Tensor] = []
    with torch.no_grad():
        for features, labels in testloader:
            features = features.to(device)
            labels = labels.to(device)
            predictions = model(features).squeeze(-1)
            loss = regression_mse_loss(predictions, labels)
            batch_size = int(labels.shape[0])
            total_loss += float(loss.item()) * batch_size
            total_examples += batch_size
            all_targets.append(labels.detach().cpu().reshape(-1))
            all_predictions.append(predictions.detach().cpu().reshape(-1))
    if total_examples <= 0:
        return 0.0, 0.0
    targets = torch.cat(all_targets)
    predictions = torch.cat(all_predictions)
    centered = targets - targets.mean()
    denominator = float(torch.sum(centered * centered).item())
    if denominator <= 1e-12:
        r2 = 0.0
    else:
        residual = targets - predictions
        numerator = float(torch.sum(residual * residual).item())
        r2 = 1.0 - (numerator / denominator)
    return total_loss / total_examples, float(r2)
