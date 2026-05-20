#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from common import cache_is_fresh, force_refresh_requested, plot_output_path, write_csv_plot, write_json_plot

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
TARGET_ACC = 0.60
WARMUP_CLIENT_TRIPS = 20
CIFAR10_CNN = "cifar10_cnn"
FASHION_MNIST_CNN = "fashion_mnist_cnn"
TASK_LABELS = {
    CIFAR10_CNN: "CIFAR-10",
    FASHION_MNIST_CNN: "Fashion-MNIST",
}

RAW_FILENAME = "fedcover_pilot_raw.csv"
SUMMARY_FILENAME = "fedcover_pilot_summary.csv"
TABLE_FILENAME = "fedcover_pilot_table_rows.tex"


@dataclass(frozen=True)
class RunSpec:
    task: str
    regime: str
    method: str
    label: str
    seed: int
    run_id: str
    synchronous: bool
    coverage: str
    target_acc: float


@dataclass(frozen=True)
class RunRow:
    task: str
    regime: str
    method: str
    label: str
    seed: int
    run_id: str
    target_acc: float
    target_reached: bool
    best_acc: float
    final_acc: float
    target_client_trips: float
    target_wall_clock_s: float
    post_warmup_target_wall_clock_s: float
    final_client_trips: float
    runtime_s: float
    rpi4_weight_share: float | None
    coverage_gain_mean: float | None
    coverage_mass_mean: float | None


RUNS = (
    RunSpec(CIFAR10_CNN, "iid", "heterofl", "HeteroFL", 1337, "skgjfp96", True, "--", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "heterofl", "HeteroFL", 1338, "swcyl60o", True, "--", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "heterofl", "HeteroFL", 1339, "0fprnayr", True, "--", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "async_heterofl", "Async HeteroFL", 1337, "rbbmbqrk", False, "off", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "async_heterofl", "Async HeteroFL", 1338, "tdvy3281", False, "off", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "async_heterofl", "Async HeteroFL", 1339, "yh7l1gn2", False, "off", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_025", "FedCover (gamma=0.25)", 1337, "r9qfq30j", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_025", "FedCover (gamma=0.25)", 1338, "34a2mba7", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_025", "FedCover (gamma=0.25)", 1339, "v6cy9cxd", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_050", "FedCover (gamma=0.5)", 1337, "snek24c3", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_050", "FedCover (gamma=0.5)", 1338, "8mik8rtd", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_050", "FedCover (gamma=0.5)", 1339, "92un87jd", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_100", "FedCover (gamma=1.0)", 1337, "ulvt1676", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_100", "FedCover (gamma=1.0)", 1338, "fjl051me", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_100", "FedCover (gamma=1.0)", 1339, "qbn78ulq", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_150", "FedCover (gamma=1.5)", 1337, "twi7tjzf", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_150", "FedCover (gamma=1.5)", 1338, "dmywljiz", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedcover_150", "FedCover (gamma=1.5)", 1339, "nv03dvin", False, "on", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedbuff_full", "Full-model FedBuff", 1337, "ml89yipf", False, "--", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedbuff_full", "Full-model FedBuff", 1338, "l7fazyan", False, "--", 0.70),
    RunSpec(CIFAR10_CNN, "iid", "fedbuff_full", "Full-model FedBuff", 1339, "xdrjj60u", False, "--", 0.70),
    RunSpec(CIFAR10_CNN, "noniid", "heterofl", "HeteroFL", 1337, "p7mswz2d", True, "--", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "heterofl", "HeteroFL", 1338, "uez5yc9s", True, "--", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "heterofl", "HeteroFL", 1339, "z2a8to3q", True, "--", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "async_heterofl", "Async HeteroFL", 1337, "entgqdnf", False, "off", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "async_heterofl", "Async HeteroFL", 1338, "l1qhsxeq", False, "off", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "async_heterofl", "Async HeteroFL", 1339, "wi1dsf8d", False, "off", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_025", "FedCover (gamma=0.25)", 1337, "4u407gbw", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_025", "FedCover (gamma=0.25)", 1338, "kopt79h3", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_025", "FedCover (gamma=0.25)", 1339, "p7aoy1fe", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_050", "FedCover (gamma=0.5)", 1337, "sya5lejq", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_050", "FedCover (gamma=0.5)", 1338, "fof1ybkp", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_050", "FedCover (gamma=0.5)", 1339, "aeinm9ad", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_100", "FedCover (gamma=1.0)", 1337, "w6ee9u31", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_100", "FedCover (gamma=1.0)", 1338, "nr4vekx5", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_100", "FedCover (gamma=1.0)", 1339, "4tk6e8bs", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_150", "FedCover (gamma=1.5)", 1337, "3aqm4h2m", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_150", "FedCover (gamma=1.5)", 1338, "sfvlphdn", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedcover_150", "FedCover (gamma=1.5)", 1339, "bclh4bsr", False, "on", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedbuff_full", "Full-model FedBuff", 1337, "myahfz65", False, "--", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedbuff_full", "Full-model FedBuff", 1338, "96hydsfz", False, "--", 0.60),
    RunSpec(CIFAR10_CNN, "noniid", "fedbuff_full", "Full-model FedBuff", 1339, "wr5u7vc0", False, "--", 0.60),
    RunSpec(FASHION_MNIST_CNN, "iid", "heterofl", "HeteroFL", 1337, "xbk5a0d7", True, "--", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "heterofl", "HeteroFL", 1338, "3xe4f92g", True, "--", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "heterofl", "HeteroFL", 1339, "9kpa75am", True, "--", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "async_heterofl", "Async HeteroFL", 1337, "5g63o6yh", False, "off", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "async_heterofl", "Async HeteroFL", 1338, "rt6cqg71", False, "off", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "async_heterofl", "Async HeteroFL", 1339, "hngxry4a", False, "off", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_025", "FedCover (gamma=0.25)", 1337, "0zlvu078", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_025", "FedCover (gamma=0.25)", 1338, "1izdzlgf", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_025", "FedCover (gamma=0.25)", 1339, "3l1kaacp", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_050", "FedCover (gamma=0.5)", 1337, "xinsr69a", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_050", "FedCover (gamma=0.5)", 1338, "vtqjdo1h", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_050", "FedCover (gamma=0.5)", 1339, "g8srvurq", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_100", "FedCover (gamma=1.0)", 1337, "lbu83hxg", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_100", "FedCover (gamma=1.0)", 1338, "4lvs9uck", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_100", "FedCover (gamma=1.0)", 1339, "nqv19jvu", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_150", "FedCover (gamma=1.5)", 1337, "uv40yr5z", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_150", "FedCover (gamma=1.5)", 1338, "jx12kmpw", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedcover_150", "FedCover (gamma=1.5)", 1339, "48uuxc54", False, "on", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedbuff_full", "Full-model FedBuff", 1337, "8d3qk95x", False, "--", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedbuff_full", "Full-model FedBuff", 1338, "9ned06a0", False, "--", 0.80),
    RunSpec(FASHION_MNIST_CNN, "iid", "fedbuff_full", "Full-model FedBuff", 1339, "aqwbw2vt", False, "--", 0.80),
    RunSpec(FASHION_MNIST_CNN, "noniid", "heterofl", "HeteroFL", 1337, "pt8w9zh4", True, "--", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "heterofl", "HeteroFL", 1338, "5kq7hj2z", True, "--", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "heterofl", "HeteroFL", 1339, "owxt6cco", True, "--", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "async_heterofl", "Async HeteroFL", 1337, "g82jlxnl", False, "off", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "async_heterofl", "Async HeteroFL", 1338, "ki8ngk96", False, "off", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "async_heterofl", "Async HeteroFL", 1339, "c0i58l5x", False, "off", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_025", "FedCover (gamma=0.25)", 1337, "a2rowzvn", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_025", "FedCover (gamma=0.25)", 1338, "91s7xboq", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_025", "FedCover (gamma=0.25)", 1339, "ng0e7if0", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_050", "FedCover (gamma=0.5)", 1337, "btg9s4t9", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_050", "FedCover (gamma=0.5)", 1338, "gm4gyrg9", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_050", "FedCover (gamma=0.5)", 1339, "53p6367y", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_100", "FedCover (gamma=1.0)", 1337, "91wjngil", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_100", "FedCover (gamma=1.0)", 1338, "lfbmt0qj", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_100", "FedCover (gamma=1.0)", 1339, "7qo54riw", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_150", "FedCover (gamma=1.5)", 1337, "s86cw117", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_150", "FedCover (gamma=1.5)", 1338, "zmovdfg8", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedcover_150", "FedCover (gamma=1.5)", 1339, "30ao1wq8", False, "on", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedbuff_full", "Full-model FedBuff", 1337, "abz74nkf", False, "--", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedbuff_full", "Full-model FedBuff", 1338, "4q3u22we", False, "--", 0.75),
    RunSpec(FASHION_MNIST_CNN, "noniid", "fedbuff_full", "Full-model FedBuff", 1339, "1wrk9gl0", False, "--", 0.75),
)

RAW_FIELDS = [
    "task",
    "regime",
    "method",
    "label",
    "seed",
    "run_id",
    "target_acc",
    "target_reached",
    "best_acc",
    "final_acc",
    "target_client_trips",
    "target_wall_clock_s",
    "post_warmup_target_wall_clock_s",
    "final_client_trips",
    "runtime_s",
    "rpi4_weight_share",
    "coverage_gain_mean",
    "coverage_mass_mean",
]


def mean_std(values: Iterable[float]) -> tuple[float, float]:
    items = [float(value) for value in values]
    if not items:
        raise ValueError("cannot compute mean/std over empty values")
    return statistics.fmean(items), statistics.stdev(items) if len(items) > 1 else 0.0


def _summary_number(summary: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = summary.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _history_best_acc(run) -> float:
    best: float | None = None
    keys = (
        "eval_server/eval-acc",
        "eval_server/eval-score",
        "eval_server_trip/eval-acc",
        "eval_server_trip/eval-score",
    )
    for key in keys:
        for row in run.scan_history(keys=[key], page_size=500):
            value = row.get(key)
            if isinstance(value, (int, float)):
                best = float(value) if best is None else max(best, float(value))
    if best is None:
        summary = dict(run.summary)
        for key in (
            "final/eval_server/eval-acc",
            "final/eval_server/eval-score",
            "eval_server/eval-acc",
            "eval_server/eval-score",
        ):
            value = summary.get(key)
            if isinstance(value, (int, float)):
                best = float(value) if best is None else max(best, float(value))
    if best is None:
        raise RuntimeError(f"No eval accuracy found for {run.id}")
    return best


def _warmup_wall_clock_s(run, spec: RunSpec) -> float:
    if spec.synchronous:
        for row in run.scan_history(keys=["server_round", "round_system/train_duration_s"], page_size=1000):
            if row.get("server_round") == 1 and isinstance(row.get("round_system/train_duration_s"), (int, float)):
                return float(row["round_system/train_duration_s"])
        raise RuntimeError(f"Missing first-round warm-up duration for {run.id}")

    candidates: list[tuple[int, float]] = []
    for row in run.scan_history(keys=["client_trip", "progress/wall_clock_s"], page_size=1000):
        client_trip = row.get("client_trip")
        wall_clock_s = row.get("progress/wall_clock_s")
        if isinstance(client_trip, (int, float)) and isinstance(wall_clock_s, (int, float)):
            candidates.append((int(client_trip), float(wall_clock_s)))
    for client_trip, wall_clock_s in sorted(candidates):
        if client_trip >= WARMUP_CLIENT_TRIPS:
            return wall_clock_s
    raise RuntimeError(f"Missing warm-up wall-clock point at {WARMUP_CLIENT_TRIPS} client trips for {run.id}")


def _fetch_row(api, spec: RunSpec) -> RunRow:
    run = api.run(f"{ENTITY}/{PROJECT}/{spec.run_id}")
    if run.state != "finished":
        raise RuntimeError(f"Expected finished run for {spec.run_id}, got {run.state}")
    summary = dict(run.summary)
    runtime_s = _summary_number(summary, ("runtime/total_server_s", "_runtime"))
    if runtime_s is None:
        raise RuntimeError(f"Missing runtime for {spec.run_id}")

    final_acc = _summary_number(summary, ("final/eval_server/eval-acc", "final/eval_server/eval-score", "eval_server/eval-acc"))
    if final_acc is None:
        raise RuntimeError(f"Missing final eval accuracy for {spec.run_id}")

    target_reached = bool(summary.get("target/reached"))
    final_client_trips = _summary_number(summary, ("progress/client_trips_total", "client_trip", "target/client_trip_budget"))
    target_client_trips = _summary_number(summary, ("target/client_trips_to_target",)) or final_client_trips
    target_wall_clock_s = _summary_number(summary, ("target/wall_clock_s_to_target",)) or runtime_s
    if target_client_trips is None:
        raise RuntimeError(f"Missing client trips for {spec.run_id}")
    warmup_wall_clock_s = _warmup_wall_clock_s(run, spec)
    post_warmup_target_wall_clock_s = max(0.0, float(target_wall_clock_s) - warmup_wall_clock_s)

    rpi4_weight = _summary_number(summary, ("fairness/run_weight_total_rpi4",))
    rpi5_weight = _summary_number(summary, ("fairness/run_weight_total_rpi5",))
    rpi4_weight_share: float | None
    if spec.synchronous:
        rpi4_weight_share = 0.5
    elif rpi4_weight is not None and rpi5_weight is not None and (rpi4_weight + rpi5_weight) > 0:
        rpi4_weight_share = rpi4_weight / (rpi4_weight + rpi5_weight)
    else:
        rpi4_weight_share = None

    return RunRow(
        task=spec.task,
        regime=spec.regime,
        method=spec.method,
        label=spec.label,
        seed=spec.seed,
        run_id=spec.run_id,
        target_acc=spec.target_acc,
        target_reached=target_reached,
        best_acc=_history_best_acc(run),
        final_acc=float(final_acc),
        target_client_trips=float(target_client_trips),
        target_wall_clock_s=float(target_wall_clock_s),
        post_warmup_target_wall_clock_s=post_warmup_target_wall_clock_s,
        final_client_trips=float(final_client_trips),
        runtime_s=float(runtime_s),
        rpi4_weight_share=rpi4_weight_share,
        coverage_gain_mean=_summary_number(summary, ("fedcover/coverage_gain_mean",)),
        coverage_mass_mean=_summary_number(summary, ("fedcover/coverage_mass_mean",)),
    )


def _load_cached() -> list[RunRow]:
    path = plot_output_path(RAW_FILENAME)
    if force_refresh_requested() or not cache_is_fresh(path):
        return []
    rows: list[RunRow] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != RAW_FIELDS:
            return []
        for row in reader:
            rows.append(
                RunRow(
                    task=row["task"],
                    regime=row["regime"],
                    method=row["method"],
                    label=row["label"],
                    seed=int(row["seed"]),
                    run_id=row["run_id"],
                    target_acc=float(row["target_acc"]),
                    target_reached=row["target_reached"].lower() == "true",
                    best_acc=float(row["best_acc"]),
                    final_acc=float(row["final_acc"]),
                    target_client_trips=float(row["target_client_trips"]),
                    target_wall_clock_s=float(row["target_wall_clock_s"]),
                    post_warmup_target_wall_clock_s=float(row["post_warmup_target_wall_clock_s"]),
                    final_client_trips=float(row["final_client_trips"]),
                    runtime_s=float(row["runtime_s"]),
                    rpi4_weight_share=float(row["rpi4_weight_share"]) if row["rpi4_weight_share"] else None,
                    coverage_gain_mean=float(row["coverage_gain_mean"]) if row["coverage_gain_mean"] else None,
                    coverage_mass_mean=float(row["coverage_mass_mean"]) if row["coverage_mass_mean"] else None,
                )
            )
    return rows


def _write_raw(rows: list[RunRow]) -> None:
    write_csv_plot(
        RAW_FILENAME,
        RAW_FIELDS,
        (
            [
                row.task,
                row.regime,
                row.method,
                row.label,
                row.seed,
                row.run_id,
                row.target_acc,
                row.target_reached,
                row.best_acc,
                row.final_acc,
                row.target_client_trips,
                row.target_wall_clock_s,
                row.post_warmup_target_wall_clock_s,
                row.final_client_trips,
                row.runtime_s,
                row.rpi4_weight_share if row.rpi4_weight_share is not None else "",
                row.coverage_gain_mean if row.coverage_gain_mean is not None else "",
                row.coverage_mass_mean if row.coverage_mass_mean is not None else "",
            ]
            for row in rows
        ),
    )


def _fmt_mean_std(mean: float, std: float, *, scale: float = 1.0, digits: int = 1) -> str:
    return rf"{mean * scale:.{digits}f}\pm{std * scale:.{digits}f}"


def _write_summary(rows: list[RunRow]) -> list[dict[str, object]]:
    summary_rows: list[dict[str, object]] = []
    for spec in RUNS[::3]:
        group = [
            row
            for row in rows
            if row.task == spec.task and row.regime == spec.regime and row.method == spec.method
        ]
        best_mean, best_std = mean_std(row.best_acc for row in group)
        final_mean, final_std = mean_std(row.final_acc for row in group)
        trips_mean, trips_std = mean_std(row.target_client_trips for row in group)
        time_mean, time_std = mean_std(row.target_wall_clock_s / 60.0 for row in group)
        post_warmup_time_mean, post_warmup_time_std = mean_std(
            row.post_warmup_target_wall_clock_s / 60.0 for row in group
        )
        runtime_mean, runtime_std = mean_std(row.runtime_s / 60.0 for row in group)
        weight_values = [row.rpi4_weight_share for row in group if row.rpi4_weight_share is not None]
        weight_mean, weight_std = mean_std(weight_values) if weight_values else (0.0, 0.0)
        gain_values = [row.coverage_gain_mean for row in group if row.coverage_gain_mean is not None]
        mass_values = [row.coverage_mass_mean for row in group if row.coverage_mass_mean is not None]
        gain_mean, gain_std = mean_std(gain_values) if gain_values else (0.0, 0.0)
        mass_mean, mass_std = mean_std(mass_values) if mass_values else (0.0, 0.0)
        reached = sum(1 for row in group if row.target_reached)
        censored = reached < len(group)
        summary_rows.append(
            {
                "task": spec.task,
                "task_label": TASK_LABELS.get(spec.task, spec.task),
                "regime": spec.regime,
                "method": spec.method,
                "label": spec.label,
                "execution": "sync" if spec.synchronous else "async",
                "coverage": spec.coverage,
                "target_acc": spec.target_acc,
                "n": len(group),
                "target_reached_count": reached,
                "target_censored": censored,
                "best_acc_mean": best_mean,
                "best_acc_std": best_std,
                "final_acc_mean": final_mean,
                "final_acc_std": final_std,
                "target_client_trips_mean": trips_mean,
                "target_client_trips_std": trips_std,
                "target_wall_clock_min_mean": time_mean,
                "target_wall_clock_min_std": time_std,
                "post_warmup_target_wall_clock_min_mean": post_warmup_time_mean,
                "post_warmup_target_wall_clock_min_std": post_warmup_time_std,
                "runtime_min_mean": runtime_mean,
                "runtime_min_std": runtime_std,
                "rpi4_weight_share_mean": weight_mean,
                "rpi4_weight_share_std": weight_std,
                "coverage_gain_mean": gain_mean if gain_values else None,
                "coverage_gain_std": gain_std if gain_values else None,
                "coverage_mass_mean": mass_mean if mass_values else None,
                "coverage_mass_std": mass_std if mass_values else None,
            }
        )
    write_csv_plot(
        SUMMARY_FILENAME,
        list(summary_rows[0].keys()),
        ([row[key] if row[key] is not None else "" for key in summary_rows[0].keys()] for row in summary_rows),
    )
    return summary_rows


def _tex_method(label: str) -> str:
    if label == "Async HeteroFL":
        return r"\texttt{Async-HeteroFL}"
    if label == "Full-model FedBuff":
        return r"\texttt{FedBuff}\(^*\)"
    if label.startswith("FedCover (gamma="):
        gamma = label.removeprefix("FedCover (gamma=").removesuffix(")")
        return rf"\texttt{{FedCover}} \((\gamma={gamma})\)"
    return rf"\texttt{{{label}}}"


def _tex_data_label(regime: str) -> str:
    if regime == "iid":
        return "IID"
    if regime == "noniid":
        return "Non-IID"
    return regime


def _tex_task_label(task: str) -> str:
    return TASK_LABELS.get(task, task.replace("_", r"\_"))


TABLE_METHOD_ORDER = {
    "fedbuff_full": 0,
    "heterofl": 1,
    "async_heterofl": 2,
    "fedcover_025": 3,
    "fedcover_050": 4,
    "fedcover_100": 5,
    "fedcover_150": 6,
}


def _write_table_rows(summary_rows: list[dict[str, object]]) -> Path:
    lines: list[str] = []
    ordered_rows = sorted(
        summary_rows,
        key=lambda row: (
            (CIFAR10_CNN, FASHION_MNIST_CNN).index(str(row["task"])),
            ("iid", "noniid").index(str(row["regime"])),
            TABLE_METHOD_ORDER[str(row["method"])],
        ),
    )
    rank_fields = (
        ("target_client_trips_mean", "target_client_trips_std"),
        ("target_wall_clock_min_mean", "target_wall_clock_min_std"),
        ("post_warmup_target_wall_clock_min_mean", "post_warmup_target_wall_clock_min_std"),
    )
    ranks: dict[tuple[str, str, str, str], str] = {}
    for task in (CIFAR10_CNN, FASHION_MNIST_CNN):
        for regime in ("iid", "noniid"):
            comparable = [
                row
                for row in ordered_rows
                if row["task"] == task
                and row["regime"] == regime
                and row["method"] != "fedbuff_full"
                and not bool(row["target_censored"])
            ]
            for mean_field, std_field in rank_fields:
                ranked = sorted(
                    comparable,
                    key=lambda row: (float(row[mean_field]), float(row[std_field]), str(row["method"])),
                )
                if ranked:
                    ranks[(task, regime, str(ranked[0]["method"]), mean_field)] = "best"
                if len(ranked) > 1:
                    ranks[(task, regime, str(ranked[1]["method"]), mean_field)] = "second"

    def _target_metric_cell(row: dict[str, object], mean_field: str, std_field: str, digits: int) -> str:
        value = _fmt_mean_std(float(row[mean_field]), float(row[std_field]), digits=digits)
        if bool(row["target_censored"]):
            return rf"\evalcensored{{{value}}}"
        cell = r"\(" + value + r"\)"
        rank = ranks.get((str(row["task"]), str(row["regime"]), str(row["method"]), mean_field))
        if rank == "best":
            return rf"\evalbest{{{cell}}}"
        if rank == "second":
            return rf"\evalsecond{{{cell}}}"
        return cell

    task_counts = Counter(str(row["task"]) for row in ordered_rows)
    regime_counts: Counter[tuple[str, str]] = Counter()
    for row in ordered_rows:
        task = str(row["task"])
        regime = str(row["regime"])
        regime_counts[(task, regime)] += 1
    task_seen: dict[str, int] = {}
    regime_seen: dict[tuple[str, str], int] = {}
    for row in ordered_rows:
        task = str(row["task"])
        regime = str(row["regime"])
        if task_seen and task not in task_seen:
            lines.append(r"\addlinespace[0.35em]")
        elif regime_seen and (task, regime) not in regime_seen:
            lines.append(r"\addlinespace[0.2em]")
        task_cell = ""
        task_seen_count = task_seen.get(task, 0)
        if task_seen_count == 0:
            task_cell = rf"\multirow{{{task_counts[task]}}}{{*}}{{\makecell[l]{{{_tex_task_label(task)}}}}}"
        task_seen[task] = task_seen_count + 1
        seen = regime_seen.get((task, regime), 0)
        data_cell = ""
        if seen == 0:
            data_cell = rf"\multirow{{{regime_counts[(task, regime)]}}}{{*}}{{{_tex_data_label(regime)}}}"
        regime_seen[(task, regime)] = seen + 1
        trips = _target_metric_cell(row, "target_client_trips_mean", "target_client_trips_std", 0)
        time = _target_metric_cell(row, "target_wall_clock_min_mean", "target_wall_clock_min_std", 1)
        post_warmup_time = _target_metric_cell(
            row,
            "post_warmup_target_wall_clock_min_mean",
            "post_warmup_target_wall_clock_min_std",
            1,
        )
        gain = "--"
        if row["coverage"] == "off":
            gain = r"\(1.00^\dagger\)"
        elif row["coverage_gain_mean"] is not None:
            gain = r"\(" + _fmt_mean_std(float(row["coverage_gain_mean"]), float(row["coverage_gain_std"]), digits=2) + r"\)"
        lines.append(
            " & ".join(
                [
                    task_cell,
                    data_cell,
                    _tex_method(str(row["label"])),
                    trips,
                    time,
                    post_warmup_time,
                    r"\(" + _fmt_mean_std(float(row["rpi4_weight_share_mean"]), float(row["rpi4_weight_share_std"]), scale=100.0, digits=1) + r"\)",
                    gain,
                ]
            )
            + r" \\"
        )
    path = plot_output_path(TABLE_FILENAME)
    path.write_text("\n".join(lines) + "\n")
    return path


def main() -> None:
    rows = _load_cached()
    rows_by_id = {row.run_id: row for row in rows}
    missing_specs = [spec for spec in RUNS if spec.run_id not in rows_by_id]
    if missing_specs or not rows:
        import wandb

        api = wandb.Api(timeout=60)
        fetched_rows = {spec.run_id: _fetch_row(api, spec) for spec in missing_specs or RUNS}
        rows_by_id.update(fetched_rows)
        rows = [rows_by_id[spec.run_id] for spec in RUNS]
        _write_raw(rows)
    summary_rows = _write_summary(rows)
    table_path = _write_table_rows(summary_rows)
    payload = {
        "targets": {
            f"{task}:{regime}": target
            for (task, regime), target in sorted({(row.task, row.regime): row.target_acc for row in rows}.items())
        },
        "runs": [row.__dict__ for row in rows],
        "summary": summary_rows,
        "table_rows": str(table_path),
    }
    write_json_plot("fedcover_pilot_summary.json", payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
