"""Model and data pipeline for the fixed-rate HeteroFL prototype."""

from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Tuple

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"
DOWNLOAD_LOCK = DATA_ROOT / ".fashion-mnist.lock"


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


def build_model_for_rate(model_rate: float) -> HeteroMLP:
    return HeteroMLP(hidden=_scaled_hidden(model_rate))



def load_model_state(model: nn.Module, state_dict: dict[str, torch.Tensor]) -> None:
    model.load_state_dict(state_dict, strict=True)


@lru_cache(maxsize=2)
def _datasets() -> tuple[datasets.FashionMNIST, datasets.FashionMNIST]:
    transform = transforms.Compose(
        [transforms.ToTensor(), transforms.Normalize((0.2860,), (0.3530,))]
    )
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    _ensure_fashion_mnist_downloaded(transform)
    trainset = datasets.FashionMNIST(
        root=DATA_ROOT, train=True, download=False, transform=transform
    )
    testset = datasets.FashionMNIST(
        root=DATA_ROOT, train=False, download=False, transform=transform
    )
    return trainset, testset


def _fashion_mnist_exists() -> bool:
    processed = DATA_ROOT / "FashionMNIST" / "processed"
    return (processed / "training.pt").exists() and (processed / "test.pt").exists()


def _ensure_fashion_mnist_downloaded(transform: transforms.Compose) -> None:
    if _fashion_mnist_exists():
        return

    while True:
        try:
            fd = os.open(DOWNLOAD_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if _fashion_mnist_exists():
                return
            time.sleep(0.2)

    try:
        if not _fashion_mnist_exists():
            datasets.FashionMNIST(
                root=DATA_ROOT, train=True, download=True, transform=transform
            )
            datasets.FashionMNIST(
                root=DATA_ROOT, train=False, download=True, transform=transform
            )
    finally:
        try:
            DOWNLOAD_LOCK.unlink()
        except FileNotFoundError:
            pass



def _iid_partition_indices(length: int, partition_id: int, num_partitions: int) -> list[int]:
    if partition_id < 0 or partition_id >= num_partitions:
        raise ValueError(
            f"partition_id={partition_id} out of range for num_partitions={num_partitions}"
        )
    base = length // num_partitions
    remainder = length % num_partitions
    start = partition_id * base + min(partition_id, remainder)
    stop = start + base + (1 if partition_id < remainder else 0)
    return list(range(start, stop))



def load_data(
    partition_id: int,
    num_partitions: int,
    batch_size: int,
    *,
    partitioning: str = "iid",
    max_train_examples: int | None = None,
    max_test_examples: int | None = None,
) -> tuple[DataLoader, DataLoader]:
    if partitioning != "iid":
        raise NotImplementedError(
            "Only IID partitioning is implemented in the first HeteroFL scaffold."
        )

    trainset, testset = _datasets()
    train_indices = _iid_partition_indices(len(trainset), partition_id, num_partitions)
    test_indices = _iid_partition_indices(len(testset), partition_id, num_partitions)
    if max_train_examples is not None:
        train_indices = train_indices[: max(max_train_examples, 0)]
    if max_test_examples is not None:
        test_indices = test_indices[: max(max_test_examples, 0)]

    trainloader = DataLoader(
        Subset(trainset, train_indices),
        batch_size=batch_size,
        shuffle=True,
        num_workers=0,
    )
    testloader = DataLoader(
        Subset(testset, test_indices),
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
    )
    return trainloader, testloader



def load_centralized_test_dataset(batch_size: int = 256) -> DataLoader:
    _, testset = _datasets()
    return DataLoader(testset, batch_size=batch_size, shuffle=False, num_workers=0)



def train(
    model: nn.Module,
    trainloader: DataLoader,
    epochs: int,
    lr: float,
    device: torch.device,
    *,
    log_prefix: str | None = None,
) -> float:
    model.to(device)
    criterion = nn.CrossEntropyLoss().to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9)
    model.train()
    running_loss = 0.0
    steps = 0
    for epoch in range(epochs):
        epoch_start = time.perf_counter()
        epoch_loss = 0.0
        epoch_steps = 0
        for batch_idx, (images, labels) in enumerate(trainloader, start=1):
            batch_start = time.perf_counter()
            images = images.to(device)
            labels = labels.to(device)
            optimizer.zero_grad()
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            loss_value = float(loss.item())
            running_loss += loss_value
            steps += 1
            epoch_loss += loss_value
            epoch_steps += 1
            print(
                f"{log_prefix or '[heterofl]'} train:batch_done "
                f"epoch={epoch + 1}/{epochs} batch={batch_idx}/{len(trainloader)} "
                f"loss={loss_value:.6f} elapsed_s={time.perf_counter() - batch_start:.2f}",
                flush=True,
            )
        print(
            f"{log_prefix or '[heterofl]'} train:epoch_done "
            f"epoch={epoch + 1}/{epochs} avg_loss={epoch_loss / max(epoch_steps, 1):.6f} "
            f"steps={epoch_steps} elapsed_s={time.perf_counter() - epoch_start:.2f}",
            flush=True,
        )
    return running_loss / max(steps, 1)



def test(model: nn.Module, testloader: DataLoader, device: torch.device) -> Tuple[float, float]:
    model.to(device)
    criterion = nn.CrossEntropyLoss().to(device)
    model.eval()
    correct = 0
    loss = 0.0
    total = 0
    with torch.no_grad():
        for images, labels in testloader:
            images = images.to(device)
            labels = labels.to(device)
            logits = model(images)
            loss += float(criterion(logits, labels).item())
            correct += int((logits.argmax(dim=1) == labels).sum().item())
            total += int(labels.numel())
    return loss / max(len(testloader), 1), correct / max(total, 1)
