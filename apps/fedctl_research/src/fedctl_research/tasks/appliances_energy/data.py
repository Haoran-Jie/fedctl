"""Shared Appliances Energy Prediction data helpers."""

from __future__ import annotations

import contextlib
import csv
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime
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
CSV_PATH = DATA_ROOT / "energydata_complete.csv"
DOWNLOAD_LOCK = DATA_ROOT / ".appliances-energy.lock"
DOWNLOAD_URLS = (
    "https://archive.ics.uci.edu/ml/machine-learning-databases/00374/energydata_complete.csv",
    "https://archive.ics.uci.edu/static/public/374/energydata_complete.csv",
    "https://raw.githubusercontent.com/LuisM78/Appliances-energy-prediction-data/master/energydata_complete.csv",
)
TARGET_COLUMN = "Appliances"
DATE_COLUMN = "date"
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
PARSE_PROGRESS_ROWS = 5_000


@dataclass(frozen=True)
class ParsedDataset:
    features: np.ndarray
    targets: np.ndarray
    continuous_columns: dict[str, np.ndarray]
    feature_dim: int


class AppliancesEnergyDataset(Dataset):
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


def _dataset_exists() -> bool:
    return CSV_PATH.exists()


def _progress(message: str) -> None:
    print(f"[appliances_energy_data] {message}", flush=True)


def _download_dataset() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    if _dataset_exists():
        _progress(f"using cached dataset at {CSV_PATH}")
        return
    _progress(f"dataset cache miss; target path is {CSV_PATH}")
    while True:
        try:
            fd = os.open(DOWNLOAD_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            _progress(f"acquired download lock {DOWNLOAD_LOCK}")
            break
        except FileExistsError:
            if _dataset_exists():
                _progress(f"dataset appeared while waiting; using cached file at {CSV_PATH}")
                return
            _progress("another process is downloading the dataset; waiting for cache file")
            time.sleep(0.2)
    try:
        if _dataset_exists():
            _progress(f"dataset appeared after lock acquisition; using cached file at {CSV_PATH}")
            return
        for url in DOWNLOAD_URLS:
            try:
                _progress(f"downloading dataset from {url}")
                with contextlib.closing(urlopen(url, timeout=30)) as response:
                    total_size_raw = response.headers.get("content-length")
                    total_size = int(total_size_raw) if total_size_raw and total_size_raw.isdigit() else None
                    bytes_downloaded = 0
                    next_progress_bytes = DOWNLOAD_CHUNK_BYTES
                    with CSV_PATH.open("wb") as handle:
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
                _progress(f"download complete: {CSV_PATH}")
                return
            except Exception as exc:
                _progress(f"download failed from {url}: {exc}")
                with contextlib.suppress(FileNotFoundError):
                    CSV_PATH.unlink()
                continue
        raise RuntimeError("Unable to download Appliances Energy Prediction dataset")
    finally:
        try:
            DOWNLOAD_LOCK.unlink()
        except FileNotFoundError:
            pass


def _cyclical_features(dt: datetime) -> tuple[float, ...]:
    hour = dt.hour / 24.0
    weekday = dt.weekday() / 7.0
    month = (dt.month - 1) / 12.0
    return (
        math.sin(2.0 * math.pi * hour),
        math.cos(2.0 * math.pi * hour),
        math.sin(2.0 * math.pi * weekday),
        math.cos(2.0 * math.pi * weekday),
        math.sin(2.0 * math.pi * month),
        math.cos(2.0 * math.pi * month),
    )


def _parse_csv(path: Path) -> ParsedDataset:
    _progress(f"parsing CSV at {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Dataset CSV is missing a header row")
        fieldnames = list(reader.fieldnames)
        numeric_columns = [
            name for name in fieldnames if name not in {DATE_COLUMN, TARGET_COLUMN}
        ]
        features_rows: list[list[float]] = []
        targets: list[float] = []
        continuous_columns: dict[str, list[float]] = {TARGET_COLUMN: []}
        for name in numeric_columns:
            continuous_columns[name] = []
        for row_idx, row in enumerate(reader, start=1):
            dt = datetime.strptime(row[DATE_COLUMN], "%Y-%m-%d %H:%M:%S")
            numeric_values = [float(row[name]) for name in numeric_columns]
            for name, value in zip(numeric_columns, numeric_values, strict=True):
                continuous_columns[name].append(value)
            target = float(row[TARGET_COLUMN])
            continuous_columns[TARGET_COLUMN].append(target)
            features_rows.append([*numeric_values, *_cyclical_features(dt)])
            targets.append(target)
            if row_idx % PARSE_PROGRESS_ROWS == 0:
                _progress(f"parsed {row_idx} rows")
    features = np.asarray(features_rows, dtype=np.float32)
    target_array = np.asarray(targets, dtype=np.float32)
    _progress(
        f"parse complete: rows={features.shape[0]} feature_dim={features.shape[1]}"
    )
    return ParsedDataset(
        features=features,
        targets=target_array,
        continuous_columns={
            key: np.asarray(values, dtype=np.float64)
            for key, values in continuous_columns.items()
        },
        feature_dim=int(features.shape[1]),
    )


def _train_test_split(parsed: ParsedDataset) -> tuple[AppliancesEnergyDataset, AppliancesEnergyDataset]:
    _progress("standardizing features and creating chronological 80/20 split")
    split_idx = int(round(parsed.features.shape[0] * 0.8))
    train_features = parsed.features[:split_idx]
    test_features = parsed.features[split_idx:]
    train_targets = parsed.targets[:split_idx]
    test_targets = parsed.targets[split_idx:]

    mean = train_features.mean(axis=0, dtype=np.float64)
    std = train_features.std(axis=0, dtype=np.float64)
    std = np.where(std > 1e-12, std, 1.0)
    train_features = ((train_features - mean) / std).astype(np.float32)
    test_features = ((test_features - mean) / std).astype(np.float32)

    train_columns = {
        key: values[:split_idx] for key, values in parsed.continuous_columns.items()
    }
    test_columns = {
        key: values[split_idx:] for key, values in parsed.continuous_columns.items()
    }
    _progress(
        f"dataset ready: train_examples={train_features.shape[0]} test_examples={test_features.shape[0]}"
    )
    return (
        AppliancesEnergyDataset(
            features=train_features,
            targets=train_targets,
            continuous_columns=train_columns,
        ),
        AppliancesEnergyDataset(
            features=test_features,
            targets=test_targets,
            continuous_columns=test_columns,
        ),
    )


@lru_cache(maxsize=2)
def datasets_pair() -> tuple[AppliancesEnergyDataset, AppliancesEnergyDataset]:
    _download_dataset()
    parsed = _parse_csv(CSV_PATH)
    return _train_test_split(parsed)


@lru_cache(maxsize=1)
def feature_dim() -> int:
    _download_dataset()
    return _parse_csv(CSV_PATH).feature_dim


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
    dataset: AppliancesEnergyDataset,
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
    raise ValueError(f"Unsupported partitioning mode for Appliances task: {request.partitioning}")


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
