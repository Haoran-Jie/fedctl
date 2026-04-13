"""Shared supervised classification train/eval loops."""

from __future__ import annotations

import time

import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def masked_cross_entropy_loss(
    logits: torch.Tensor,
    labels: torch.Tensor,
    *,
    label_mask: torch.Tensor | None,
) -> torch.Tensor:
    if label_mask is None:
        return nn.functional.cross_entropy(logits, labels, reduction="mean")
    if label_mask.dtype != torch.bool:
        label_mask = label_mask.to(dtype=torch.bool)
    label_mask = label_mask.to(device=logits.device)
    masked_logits = logits.masked_fill(~label_mask.unsqueeze(0), 0.0)
    return nn.functional.cross_entropy(masked_logits, labels, reduction="mean")


def should_use_masked_cross_entropy(mode: str, *, partitioning: str) -> bool:
    normalized = str(mode).strip().lower()
    if normalized == "on":
        return True
    if normalized == "off":
        return False
    if normalized != "auto":
        raise ValueError(f"Unsupported masked-cross-entropy mode: {mode}")
    return partitioning == "label-skew-balanced"


def train_classifier(
    model: nn.Module,
    trainloader: DataLoader,
    epochs: int,
    lr: float,
    device: torch.device | str,
    *,
    label_mask: torch.Tensor | None = None,
    use_masked_cross_entropy: bool = False,
    log_prefix: str | None = None,
) -> float:
    model.to(device)
    criterion = nn.CrossEntropyLoss().to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9)
    model.train()
    prefix = log_prefix or "[fedctl_research]"
    print(
        f"{prefix} train:enter "
        f"device={device} epochs={epochs} batches={len(trainloader)}",
        flush=True,
    )
    running_loss = 0.0
    steps = 0
    label_mask_device = label_mask.to(device) if label_mask is not None else None
    for epoch in range(epochs):
        epoch_start = time.perf_counter()
        epoch_loss = 0.0
        epoch_steps = 0
        for batch_idx, (images, labels) in enumerate(trainloader, start=1):
            batch_start = time.perf_counter()
            if batch_idx == 1:
                print(
                    f"{prefix} train:first_batch fetched "
                    f"images_shape={tuple(images.shape)} labels_shape={tuple(labels.shape)} "
                    f"images_dtype={images.dtype} labels_dtype={labels.dtype}",
                    flush=True,
                )
            images = images.to(device)
            labels = labels.to(device)
            if batch_idx == 1:
                print(
                    f"{prefix} train:first_batch on_device "
                    f"elapsed_s={time.perf_counter() - batch_start:.2f}",
                    flush=True,
                )
            optimizer.zero_grad()
            logits = model(images)
            if batch_idx == 1:
                print(
                    f"{prefix} train:first_batch forward_done "
                    f"logits_shape={tuple(logits.shape)} "
                    f"elapsed_s={time.perf_counter() - batch_start:.2f}",
                    flush=True,
                )
            if use_masked_cross_entropy:
                loss = masked_cross_entropy_loss(logits, labels, label_mask=label_mask_device)
            else:
                loss = criterion(logits, labels)
            if batch_idx == 1:
                print(
                    f"{prefix} train:first_batch loss_done "
                    f"loss={float(loss.item()):.6f} "
                    f"elapsed_s={time.perf_counter() - batch_start:.2f}",
                    flush=True,
                )
            loss.backward()
            if batch_idx == 1:
                print(
                    f"{prefix} train:first_batch backward_done "
                    f"elapsed_s={time.perf_counter() - batch_start:.2f}",
                    flush=True,
                )
            optimizer.step()
            if batch_idx == 1:
                print(
                    f"{prefix} train:first_batch step_done "
                    f"elapsed_s={time.perf_counter() - batch_start:.2f}",
                    flush=True,
                )
            loss_value = float(loss.item())
            running_loss += loss_value
            steps += 1
            epoch_loss += loss_value
            epoch_steps += 1
            print(
                f"{prefix} train:batch_done "
                f"epoch={epoch + 1}/{epochs} batch={batch_idx}/{len(trainloader)} "
                f"loss={loss_value:.6f} elapsed_s={time.perf_counter() - batch_start:.2f}",
                flush=True,
            )
        print(
            f"{prefix} train:epoch_done "
            f"epoch={epoch + 1}/{epochs} avg_loss={epoch_loss / max(epoch_steps, 1):.6f} "
            f"steps={epoch_steps} elapsed_s={time.perf_counter() - epoch_start:.2f}",
            flush=True,
        )
    return running_loss / max(steps, 1)


def evaluate_classifier(
    model: nn.Module,
    testloader: DataLoader,
    device: torch.device | str,
) -> tuple[float, float]:
    model.to(device)
    criterion = nn.CrossEntropyLoss().to(device)
    model.eval()
    correct = 0
    loss = 0.0
    count = 0
    with torch.no_grad():
        for images, labels in testloader:
            images = images.to(device)
            labels = labels.to(device)
            logits = model(images)
            loss += float(criterion(logits, labels).item()) * len(labels)
            preds = logits.argmax(dim=1)
            correct += int((preds == labels).sum().item())
            count += len(labels)
    return loss / max(count, 1), correct / max(count, 1)
