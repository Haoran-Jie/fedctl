#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from common import cache_is_fresh, force_refresh_requested, plot_output_path, write_csv_plot, write_json_plot

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
TARGET_ACC = 0.60
WARMUP_CLIENT_TRIPS = 20

RAW_FILENAME = "fedcover_pilot_raw.csv"
SUMMARY_FILENAME = "fedcover_pilot_summary.csv"
TABLE_FILENAME = "fedcover_pilot_table_rows.tex"


@dataclass(frozen=True)
class RunSpec:
    method: str
    label: str
    seed: int
    run_id: str
    synchronous: bool
    coverage: str


@dataclass(frozen=True)
class RunRow:
    method: str
    label: str
    seed: int
    run_id: str
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
    RunSpec("heterofl", "HeteroFL", 1337, "p7mswz2d", True, "--"),
    RunSpec("heterofl", "HeteroFL", 1338, "uez5yc9s", True, "--"),
    RunSpec("heterofl", "HeteroFL", 1339, "z2a8to3q", True, "--"),
    RunSpec("async_heterofl", "Async HeteroFL", 1337, "entgqdnf", False, "off"),
    RunSpec("async_heterofl", "Async HeteroFL", 1338, "l1qhsxeq", False, "off"),
    RunSpec("async_heterofl", "Async HeteroFL", 1339, "wi1dsf8d", False, "off"),
    RunSpec("fedcover", "FedCover", 1337, "eajmk8ms", False, "on"),
    RunSpec("fedcover", "FedCover", 1338, "kawgrsj8", False, "on"),
    RunSpec("fedcover", "FedCover", 1339, "pu8puo1w", False, "on"),
)

RAW_FIELDS = [
    "method",
    "label",
    "seed",
    "run_id",
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
    for row in run.scan_history(page_size=1000):
        for key in ("eval_server/eval-acc", "eval_server/eval-score", "eval_server_trip/eval-acc", "eval_server_trip/eval-score"):
            value = row.get(key)
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
        method=spec.method,
        label=spec.label,
        seed=spec.seed,
        run_id=spec.run_id,
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
                    method=row["method"],
                    label=row["label"],
                    seed=int(row["seed"]),
                    run_id=row["run_id"],
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
    if {row.run_id for row in rows} != {spec.run_id for spec in RUNS}:
        return []
    return rows


def _write_raw(rows: list[RunRow]) -> None:
    write_csv_plot(
        RAW_FILENAME,
        RAW_FIELDS,
        (
            [
                row.method,
                row.label,
                row.seed,
                row.run_id,
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
        group = [row for row in rows if row.method == spec.method]
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
                "method": spec.method,
                "label": spec.label,
                "execution": "sync" if spec.synchronous else "async",
                "coverage": spec.coverage,
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
    return rf"\texttt{{{label}}}"


def _write_table_rows(summary_rows: list[dict[str, object]]) -> Path:
    lines: list[str] = []
    for row in summary_rows:
        censored = bool(row["target_censored"])
        trips = _fmt_mean_std(float(row["target_client_trips_mean"]), float(row["target_client_trips_std"]), digits=0)
        time = _fmt_mean_std(float(row["target_wall_clock_min_mean"]), float(row["target_wall_clock_min_std"]), digits=1)
        post_warmup_time = _fmt_mean_std(
            float(row["post_warmup_target_wall_clock_min_mean"]),
            float(row["post_warmup_target_wall_clock_min_std"]),
            digits=1,
        )
        if censored:
            trips = r"\cellcolor{gray!12}\(" + trips + r"\)"
            time = r"\cellcolor{gray!12}\(" + time + r"\)"
            post_warmup_time = r"\cellcolor{gray!12}\(" + post_warmup_time + r"\)"
        else:
            trips = r"\(" + trips + r"\)"
            time = r"\(" + time + r"\)"
            post_warmup_time = r"\(" + post_warmup_time + r"\)"
        gain = "--"
        if row["coverage"] == "off":
            gain = r"\(1.00^\dagger\)"
        elif row["coverage_gain_mean"] is not None:
            gain = r"\(" + _fmt_mean_std(float(row["coverage_gain_mean"]), float(row["coverage_gain_std"]), digits=2) + r"\)"
        lines.append(
            " & ".join(
                [
                    _tex_method(str(row["label"])),
                    r"\(" + _fmt_mean_std(float(row["best_acc_mean"]), float(row["best_acc_std"]), scale=100.0, digits=1) + r"\)",
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
    if not rows:
        import wandb

        api = wandb.Api(timeout=60)
        rows = [_fetch_row(api, spec) for spec in RUNS]
        _write_raw(rows)
    summary_rows = _write_summary(rows)
    table_path = _write_table_rows(summary_rows)
    payload = {
        "target_acc": TARGET_ACC,
        "runs": [row.__dict__ for row in rows],
        "summary": summary_rows,
        "table_rows": str(table_path),
    }
    write_json_plot("fedcover_pilot_summary.json", payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
