"""Shared Fashion-MNIST data helpers."""

from __future__ import annotations

import contextlib
import io
import os
import time
from functools import lru_cache
from pathlib import Path

from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from fedctl_research.partitioning import build_classification_partition_bundle
from fedctl_research.partitioning.partition_request import PartitionRequest
from fedctl_research.tasks.base import PartitionBundle

DATA_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "data"
DOWNLOAD_LOCK = DATA_ROOT / ".fashion-mnist.lock"
NUM_CLASSES = 10


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
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
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


@lru_cache(maxsize=2)
def datasets_pair() -> tuple[datasets.FashionMNIST, datasets.FashionMNIST]:
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


def load_partitioned_data(
    request: PartitionRequest,
    batch_size: int,
    *,
    max_train_examples: int | None = None,
    max_test_examples: int | None = None,
) -> PartitionBundle:
    trainset, testset = datasets_pair()
    return build_classification_partition_bundle(
        trainset=trainset,
        testset=testset,
        num_classes=NUM_CLASSES,
        batch_size=batch_size,
        request=request,
        max_train_examples=max_train_examples,
        max_test_examples=max_test_examples,
    )


def load_centralized_test_dataset(batch_size: int = 256, *, seed: int | None = None) -> DataLoader:
    _ = seed
    _, testset = datasets_pair()
    return DataLoader(testset, batch_size=batch_size, shuffle=False, num_workers=0)
