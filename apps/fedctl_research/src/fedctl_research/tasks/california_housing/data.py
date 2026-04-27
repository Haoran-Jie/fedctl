"""Shared California Housing data helpers."""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, Subset

from fedctl_research.partitioning.continuous_partitioner import ContinuousPartitioner
from fedctl_research.partitioning.partition_request import PartitionRequest
from fedctl_research.seeding import make_torch_generator
from fedctl_research.tasks.base import PartitionBundle

DATA_ROOT = Path(__file__).resolve().parents[4] / "data"
NPZ_PATH = DATA_ROOT / "california_housing.npz"
DOWNLOAD_LOCK = DATA_ROOT / ".california-housing.lock"
DOWNLOAD_URLS = (
    "https://storage.googleapis.com/tensorflow/tf-keras-datasets/california_housing.npz",
)
FEATURE_COLUMNS = (
    "MedInc",
    "HouseAge",
    "AveRooms",
    "AveBedrms",
    "Population",
    "AveOccup",
    "Latitude",
    "Longitude",
)
TARGET_COLUMN = "MedHouseVal"
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ParsedDataset:
    features: np.ndarray
    targets: np.ndarray
    continuous_columns: dict[str, np.ndarray]
    feature_dim: int


class CaliforniaHousingDataset(Dataset):
    def __init__(
        self,
        *,
        features: np.ndarray,
        targets: np.ndarray,
        continuous_columns: dict[str, np.ndarray],
    ) -> None:
        self.features = torch.tensor(features, dtype=torch.float32)
        self.targets = torch.tensor(targets, dtype=torch.float32)
        self.continuous_columns = {
            key: np.asarray(value, dtype=np.float64) for key, value in continuous_columns.items()
        }

    def __len__(self) -> int:
        return int(self.targets.shape[0])

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        return self.features[index], self.targets[index]


def _progress(message: str) -> None:
    print(f"[california_housing_data] {message}", flush=True)


def _dataset_exists() -> bool:
    return NPZ_PATH.exists()


def _download_dataset() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    if _dataset_exists():
        _progress(f"using cached dataset at {NPZ_PATH}")
        return
    _progress(f"dataset cache miss; target path is {NPZ_PATH}")
    while True:
        try:
            fd = os.open(DOWNLOAD_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            _progress(f"acquired download lock {DOWNLOAD_LOCK}")
            break
        except FileExistsError:
            if _dataset_exists():
                _progress(f"dataset appeared while waiting; using cached file at {NPZ_PATH}")
                return
            _progress("another process is downloading the dataset; waiting for cache file")
            time.sleep(0.2)
    try:
        if _dataset_exists():
            _progress(f"dataset appeared after lock acquisition; using cached file at {NPZ_PATH}")
            return
        for url in DOWNLOAD_URLS:
            try:
                _progress(f"downloading dataset from {url}")
                with contextlib.closing(urlopen(url, timeout=30)) as response:
                    total_size_raw = response.headers.get("content-length")
                    total_size = int(total_size_raw) if total_size_raw and total_size_raw.isdigit() else None
                    bytes_downloaded = 0
                    next_progress_bytes = DOWNLOAD_CHUNK_BYTES
                    with NPZ_PATH.open("wb") as handle:
                        while True:
                            chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                            if not chunk:
                                break
                            handle.write(chunk)
                            bytes_downloaded += len(chunk)
                            if bytes_downloaded >= next_progress_bytes:
                                if total_size:
                                    pct = 100.0 * bytes_downloaded / total_size
                                    _progress(
                                        f"downloaded {bytes_downloaded / (1024 * 1024):.1f} MiB / "
                                        f"{total_size / (1024 * 1024):.1f} MiB ({pct:.1f}%)"
                                    )
                                else:
                                    _progress(f"downloaded {bytes_downloaded / (1024 * 1024):.1f} MiB")
                                next_progress_bytes += DOWNLOAD_CHUNK_BYTES
                _progress(f"download complete: {NPZ_PATH}")
                return
            except Exception as exc:
                _progress(f"download failed from {url}: {exc}")
                with contextlib.suppress(FileNotFoundError):
                    NPZ_PATH.unlink()
                continue
        raise RuntimeError("Unable to download California Housing dataset")
    finally:
        with contextlib.suppress(FileNotFoundError):
            DOWNLOAD_LOCK.unlink()


def _parse_npz(path: Path) -> ParsedDataset:
    _progress(f"loading npz at {path}")
    with np.load(path) as raw:
        features = np.asarray(raw["x"], dtype=np.float32)
        targets = np.asarray(raw["y"], dtype=np.float32)
    continuous_columns = {
        name: features[:, idx].astype(np.float64)
        for idx, name in enumerate(FEATURE_COLUMNS)
    }
    continuous_columns[TARGET_COLUMN] = targets.astype(np.float64)
    _progress(f"load complete: rows={features.shape[0]} feature_dim={features.shape[1]}")
    return ParsedDataset(
        features=features,
        targets=targets,
        continuous_columns=continuous_columns,
        feature_dim=int(features.shape[1]),
    )


def _train_test_split(
    parsed: ParsedDataset,
    *,
    split_seed: int = 2026,
) -> tuple[CaliforniaHousingDataset, CaliforniaHousingDataset]:
    _progress("shuffling rows, standardizing features/target, and creating 80/20 split")
    rng = np.random.default_rng(split_seed)
    order = rng.permutation(parsed.features.shape[0])
    split_idx = int(round(parsed.features.shape[0] * 0.8))
    train_indices = order[:split_idx]
    test_indices = order[split_idx:]

    train_features = parsed.features[train_indices]
    test_features = parsed.features[test_indices]
    train_targets = parsed.targets[train_indices]
    test_targets = parsed.targets[test_indices]

    feature_mean = train_features.mean(axis=0, dtype=np.float64)
    feature_std = train_features.std(axis=0, dtype=np.float64)
    feature_std = np.where(feature_std > 1e-12, feature_std, 1.0)
    train_features = ((train_features - feature_mean) / feature_std).astype(np.float32)
    test_features = ((test_features - feature_mean) / feature_std).astype(np.float32)

    target_mean = float(train_targets.mean(dtype=np.float64))
    target_std = float(train_targets.std(dtype=np.float64))
    if target_std <= 1e-12:
        target_std = 1.0
    train_targets = ((train_targets - target_mean) / target_std).astype(np.float32)
    test_targets = ((test_targets - target_mean) / target_std).astype(np.float32)

    train_columns = {
        key: values[train_indices] for key, values in parsed.continuous_columns.items()
    }
    test_columns = {
        key: values[test_indices] for key, values in parsed.continuous_columns.items()
    }
    _progress(
        f"dataset ready: train_examples={train_features.shape[0]} test_examples={test_features.shape[0]}"
    )
    return (
        CaliforniaHousingDataset(
            features=train_features,
            targets=train_targets,
            continuous_columns=train_columns,
        ),
        CaliforniaHousingDataset(
            features=test_features,
            targets=test_targets,
            continuous_columns=test_columns,
        ),
    )


@lru_cache(maxsize=2)
def datasets_pair() -> tuple[CaliforniaHousingDataset, CaliforniaHousingDataset]:
    _download_dataset()
    parsed = _parse_npz(NPZ_PATH)
    return _train_test_split(parsed)


@lru_cache(maxsize=1)
def feature_dim() -> int:
    _download_dataset()
    return _parse_npz(NPZ_PATH).feature_dim


def _iid_indices(
    *,
    dataset_size: int,
    num_partitions: int,
    seed: int,
) -> tuple[tuple[int, ...], ...]:
    rng = np.random.default_rng(seed)
    permutation = rng.permutation(dataset_size)
    splits = np.array_split(permutation, num_partitions)
    return tuple(tuple(int(idx) for idx in split.tolist()) for split in splits)


def _partition_indices(
    dataset: CaliforniaHousingDataset,
    request: PartitionRequest,
) -> tuple[tuple[int, ...], ...]:
    num_partitions = request.effective_num_partitions
    seed = request.effective_assignment_seed
    if request.partitioning == "iid":
        return _iid_indices(dataset_size=len(dataset), num_partitions=num_partitions, seed=seed)
    if request.partitioning == "continuous":
        column = request.partitioning_continuous_column
        if not column:
            raise ValueError("partitioning-continuous-column must be set for continuous partitioning")
        try:
            values = dataset.continuous_columns[column]
        except KeyError as exc:
            known = ", ".join(sorted(dataset.continuous_columns))
            raise ValueError(
                f"Unknown continuous partitioning column '{column}'. Known columns: {known}"
            ) from exc
        return ContinuousPartitioner(
            values,
            num_partitions=num_partitions,
            seed=seed,
            strictness=float(request.partitioning_continuous_strictness),
        ).partitions
    raise ValueError(f"Unsupported partitioning mode for California Housing task: {request.partitioning}")


def load_partitioned_data(
    request: PartitionRequest,
    batch_size: int,
    *,
    max_train_examples: int | None = None,
    max_test_examples: int | None = None,
) -> PartitionBundle:
    trainset, testset = datasets_pair()
    train_indices_all = _partition_indices(trainset, request)[request.effective_partition_id]
    test_indices_all = _partition_indices(testset, request)[request.effective_partition_id]
    train_limit = len(train_indices_all) if max_train_examples is None else max_train_examples
    test_limit = len(test_indices_all) if max_test_examples is None else max_test_examples
    train_indices = list(train_indices_all[:train_limit])
    test_indices = list(test_indices_all[:test_limit])
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
        label_set=(),
        label_mask=None,
        num_train_examples=len(train_indices),
        num_test_examples=len(test_indices),
    )


def load_centralized_test_dataset(batch_size: int = 256, *, seed: int | None = None) -> DataLoader:
    _ = seed
    _, testset = datasets_pair()
    return DataLoader(testset, batch_size=batch_size, shuffle=False, num_workers=0)

