from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import wandb
import numpy as np

from common import cache_is_fresh, force_refresh_requested, plot_output_path, write_csv_plot

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
TASK = "cifar10_cnn"
TARGET_ACC = 0.60
BUDGET_TRIPS = 1000

METHOD_ORDER = ("fedavg", "fedbuff", "fedstaleweight")
METHOD_LABELS = {
    "fedavg": "FedAvg",
    "fedbuff": "FedBuff",
    "fedstaleweight": "FedStaleWeight",
}
REGIME_ORDER = ("iid", "noniid")
REGIME_LABELS = {
    "iid": "IID",
    "noniid": "Non-IID",
}
TOPOLOGY_ORDER = ("all_rpi5", "mixed")
TOPOLOGY_LABELS = {
    "all_rpi5": "all rpi5",
    "mixed": "rpi5+rpi4",
}


@dataclass(frozen=True)
class RunSpec:
    regime: str
    topology: str
    method: str
    seed: int
    run_id: str


@dataclass(frozen=True)
class EvalPoint:
    regime: str
    topology: str
    method: str
    seed: int
    run_id: str
    client_trip: int | None
    wall_clock_s: float | None
    eval_acc: float
    server_step: int | None


@dataclass(frozen=True)
class SummaryRow:
    regime: str
    topology: str
    method: str
    seed: int
    run_id: str
    target_reached: bool
    target_client_trips: int | None
    target_wall_clock_s: float | None
    final_acc: float | None
    client_trip_budget: int | None
    final_client_trips: int | None
    final_wall_clock_s: float | None
    rpi4_update_share: float | None
    rpi4_weight_share: float | None
    rpi4_staleness: float | None
    rpi5_staleness: float | None
    updates_per_second: float | None


@dataclass(frozen=True)
class CurvePoint:
    regime: str
    topology: str
    method: str
    x: float
    n: int
    eval_acc_mean: float
    eval_acc_std: float


@dataclass(frozen=True)
class AggregateTargetRow:
    regime: str
    topology: str
    method: str
    n: int
    target_reached_count: int
    target_censored: bool
    target_client_trips_mean: float
    target_client_trips_std: float
    target_wall_clock_s_mean: float
    target_wall_clock_s_std: float
    final_acc_mean: float
    final_acc_std: float


@dataclass(frozen=True)
class AggregateDiagnosticRow:
    regime: str
    method: str
    n: int
    rpi4_update_share_mean: float
    rpi4_update_share_std: float
    rpi4_weight_share_mean: float
    rpi4_weight_share_std: float
    rpi4_staleness_mean: float
    rpi4_staleness_std: float
    rpi5_staleness_mean: float
    rpi5_staleness_std: float
    updates_per_second_mean: float
    updates_per_second_std: float


RUNS = (
    RunSpec("iid", "all_rpi5", "fedavg", 1337, "c97h9zuy"),
    RunSpec("iid", "all_rpi5", "fedavg", 1338, "vu1dgghm"),
    RunSpec("iid", "all_rpi5", "fedavg", 1339, "evb7ctp1"),
    RunSpec("iid", "all_rpi5", "fedbuff", 1337, "6eom2gov"),
    RunSpec("iid", "all_rpi5", "fedbuff", 1338, "jvq0wis5"),
    RunSpec("iid", "all_rpi5", "fedbuff", 1339, "nkc9y10n"),
    RunSpec("iid", "all_rpi5", "fedstaleweight", 1337, "ey33oqo6"),
    RunSpec("iid", "all_rpi5", "fedstaleweight", 1338, "wgzj3fw7"),
    RunSpec("iid", "all_rpi5", "fedstaleweight", 1339, "eoe8x9av"),
    RunSpec("noniid", "all_rpi5", "fedavg", 1337, "6l03ojrq"),
    RunSpec("noniid", "all_rpi5", "fedavg", 1338, "ypycfovi"),
    RunSpec("noniid", "all_rpi5", "fedavg", 1339, "l7hyd4rp"),
    RunSpec("noniid", "all_rpi5", "fedbuff", 1337, "k2bpz79x"),
    RunSpec("noniid", "all_rpi5", "fedbuff", 1338, "y1zp1xa5"),
    RunSpec("noniid", "all_rpi5", "fedbuff", 1339, "gxhcey0d"),
    RunSpec("noniid", "all_rpi5", "fedstaleweight", 1337, "59wlhy0n"),
    RunSpec("noniid", "all_rpi5", "fedstaleweight", 1338, "baw5mrtc"),
    RunSpec("noniid", "all_rpi5", "fedstaleweight", 1339, "nrfy8dhr"),
    RunSpec("iid", "mixed", "fedavg", 1337, "t9vlpy39"),
    RunSpec("iid", "mixed", "fedavg", 1338, "5vjjx5qo"),
    RunSpec("iid", "mixed", "fedavg", 1339, "3apbb0nc"),
    RunSpec("iid", "mixed", "fedbuff", 1337, "stlelmg4"),
    RunSpec("iid", "mixed", "fedbuff", 1338, "3f1a6ign"),
    RunSpec("iid", "mixed", "fedbuff", 1339, "gmlpn1sy"),
    RunSpec("iid", "mixed", "fedstaleweight", 1337, "4k0nvn9k"),
    RunSpec("iid", "mixed", "fedstaleweight", 1338, "9p57d59x"),
    RunSpec("iid", "mixed", "fedstaleweight", 1339, "u2ichefy"),
    RunSpec("noniid", "mixed", "fedavg", 1337, "0ysztwpg"),
    RunSpec("noniid", "mixed", "fedavg", 1338, "kqc9pciy"),
    RunSpec("noniid", "mixed", "fedavg", 1339, "5cari6u0"),
    RunSpec("noniid", "mixed", "fedbuff", 1337, "j81afai0"),
    RunSpec("noniid", "mixed", "fedbuff", 1338, "kouohvbb"),
    RunSpec("noniid", "mixed", "fedbuff", 1339, "o7i4mdii"),
    RunSpec("noniid", "mixed", "fedstaleweight", 1337, "wyc9rjxq"),
    RunSpec("noniid", "mixed", "fedstaleweight", 1338, "b0xxbbi7"),
    RunSpec("noniid", "mixed", "fedstaleweight", 1339, "9qv2c0qb"),
)

RAW_FIELDS = [
    "regime",
    "topology",
    "method",
    "seed",
    "run_id",
    "client_trip",
    "wall_clock_s",
    "eval_acc",
    "server_step",
]

SUMMARY_FIELDS = [
    "regime",
    "topology",
    "method",
    "seed",
    "run_id",
    "target_reached",
    "target_client_trips",
    "target_wall_clock_s",
    "final_acc",
    "client_trip_budget",
    "final_client_trips",
    "final_wall_clock_s",
    "rpi4_update_share",
    "rpi4_weight_share",
    "rpi4_staleness",
    "rpi5_staleness",
    "updates_per_second",
]

EVAL_ACC_KEYS = ("eval_server_trip/eval-acc", "eval_server_trip/eval-score")
SERVER_STEP_KEYS = ("eval_server_trip/server-round", "server_step", "server_round")


def run_specs() -> list[RunSpec]:
    return list(RUNS)


def mean_std(values: Iterable[float]) -> tuple[float, float]:
    items = [float(value) for value in values]
    if not items:
        raise ValueError("cannot compute mean/std over an empty collection")
    mean = statistics.fmean(items)
    std = statistics.stdev(items) if len(items) > 1 else 0.0
    return mean, std


def _number(row: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _summary_number(summary: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = summary.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _fetch_run(api: wandb.Api, spec: RunSpec) -> tuple[list[EvalPoint], SummaryRow]:
    run = api.run(f"{ENTITY}/{PROJECT}/{spec.run_id}")
    points: list[EvalPoint] = []
    seen: set[tuple[int | None, float | None, float]] = set()
    for row in run.scan_history(page_size=1000):
        score = _number(row, EVAL_ACC_KEYS)
        if score is None:
            continue
        trip_value = row.get("client_trip")
        runtime_value = row.get("_runtime")
        client_trip = int(trip_value) if isinstance(trip_value, (int, float)) else None
        wall_clock_s = float(runtime_value) if isinstance(runtime_value, (int, float)) else None
        server_step = _number(row, SERVER_STEP_KEYS)
        key = (client_trip, wall_clock_s, float(score))
        if key in seen:
            continue
        seen.add(key)
        points.append(
            EvalPoint(
                regime=spec.regime,
                topology=spec.topology,
                method=spec.method,
                seed=spec.seed,
                run_id=spec.run_id,
                client_trip=client_trip,
                wall_clock_s=wall_clock_s,
                eval_acc=float(score),
                server_step=int(server_step) if server_step is not None else None,
            )
        )
    points.sort(key=lambda p: ((p.client_trip if p.client_trip is not None else 10**9), p.wall_clock_s or 0.0))
    if not points:
        raise RuntimeError(f"No centralized eval points found for W&B run {spec.run_id}")

    summary = dict(run.summary)
    target_trips = _summary_number(summary, ("target/client_trips_to_target",))
    target_wall = _summary_number(summary, ("target/wall_clock_s_to_target",))
    final_acc = _summary_number(summary, ("final/eval_server/eval-acc", "final/eval_server/eval-score"))
    budget = _summary_number(summary, ("target/client_trip_budget",))
    weight_rpi4 = _summary_number(summary, ("fairness/run_weight_total_rpi4",))
    weight_rpi5 = _summary_number(summary, ("fairness/run_weight_total_rpi5",))
    rpi4_weight_share: float | None = None
    if weight_rpi4 is not None and weight_rpi5 is not None and (weight_rpi4 + weight_rpi5) > 0:
        rpi4_weight_share = weight_rpi4 / (weight_rpi4 + weight_rpi5)

    last_with_trip = next((p for p in reversed(points) if p.client_trip is not None), None)
    last_with_time = next((p for p in reversed(points) if p.wall_clock_s is not None), None)
    return points, SummaryRow(
        regime=spec.regime,
        topology=spec.topology,
        method=spec.method,
        seed=spec.seed,
        run_id=spec.run_id,
        target_reached=bool(summary.get("target/reached")),
        target_client_trips=int(target_trips) if target_trips is not None else None,
        target_wall_clock_s=float(target_wall) if target_wall is not None else None,
        final_acc=float(final_acc) if final_acc is not None else None,
        client_trip_budget=int(budget) if budget is not None else None,
        final_client_trips=last_with_trip.client_trip if last_with_trip is not None else None,
        final_wall_clock_s=last_with_time.wall_clock_s if last_with_time is not None else None,
        rpi4_update_share=_summary_number(summary, ("fairness/run_update_share_rpi4",)),
        rpi4_weight_share=rpi4_weight_share,
        rpi4_staleness=_summary_number(summary, ("fairness/run_avg_staleness_rpi4",)),
        rpi5_staleness=_summary_number(summary, ("fairness/run_avg_staleness_rpi5",)),
        updates_per_second=_summary_number(summary, ("progress/updates_per_second",)),
    )


def load_cached(raw_filename: str, summary_filename: str) -> tuple[list[EvalPoint], list[SummaryRow]]:
    raw_path = plot_output_path(raw_filename)
    summary_path = plot_output_path(summary_filename)
    if force_refresh_requested() or not cache_is_fresh(raw_path) or not summary_path.exists():
        return [], []

    points: list[EvalPoint] = []
    with raw_path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != RAW_FIELDS:
            return [], []
        for row in reader:
            points.append(
                EvalPoint(
                    regime=row["regime"],
                    topology=row["topology"],
                    method=row["method"],
                    seed=int(row["seed"]),
                    run_id=row["run_id"],
                    client_trip=int(row["client_trip"]) if row["client_trip"] else None,
                    wall_clock_s=float(row["wall_clock_s"]) if row["wall_clock_s"] else None,
                    eval_acc=float(row["eval_acc"]),
                    server_step=int(row["server_step"]) if row["server_step"] else None,
                )
            )

    summaries: list[SummaryRow] = []
    with summary_path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != SUMMARY_FIELDS:
            return [], []
        for row in reader:
            summaries.append(
                SummaryRow(
                    regime=row["regime"],
                    topology=row["topology"],
                    method=row["method"],
                    seed=int(row["seed"]),
                    run_id=row["run_id"],
                    target_reached=row["target_reached"].lower() == "true",
                    target_client_trips=int(row["target_client_trips"]) if row["target_client_trips"] else None,
                    target_wall_clock_s=float(row["target_wall_clock_s"]) if row["target_wall_clock_s"] else None,
                    final_acc=float(row["final_acc"]) if row["final_acc"] else None,
                    client_trip_budget=int(row["client_trip_budget"]) if row["client_trip_budget"] else None,
                    final_client_trips=int(row["final_client_trips"]) if row["final_client_trips"] else None,
                    final_wall_clock_s=float(row["final_wall_clock_s"]) if row["final_wall_clock_s"] else None,
                    rpi4_update_share=float(row["rpi4_update_share"]) if row["rpi4_update_share"] else None,
                    rpi4_weight_share=float(row["rpi4_weight_share"]) if row["rpi4_weight_share"] else None,
                    rpi4_staleness=float(row["rpi4_staleness"]) if row["rpi4_staleness"] else None,
                    rpi5_staleness=float(row["rpi5_staleness"]) if row["rpi5_staleness"] else None,
                    updates_per_second=float(row["updates_per_second"]) if row["updates_per_second"] else None,
                )
            )

    expected_run_ids = {spec.run_id for spec in run_specs()}
    cached_run_ids = {summary.run_id for summary in summaries}
    if cached_run_ids != expected_run_ids:
        return [], []
    return points, summaries


def write_cache(raw_filename: str, summary_filename: str, points: list[EvalPoint], summaries: list[SummaryRow]) -> None:
    write_csv_plot(
        raw_filename,
        RAW_FIELDS,
        (
            [
                p.regime,
                p.topology,
                p.method,
                p.seed,
                p.run_id,
                p.client_trip or "",
                p.wall_clock_s or "",
                p.eval_acc,
                p.server_step or "",
            ]
            for p in points
        ),
    )
    write_csv_plot(
        summary_filename,
        SUMMARY_FIELDS,
        (
            [
                s.regime,
                s.topology,
                s.method,
                s.seed,
                s.run_id,
                s.target_reached,
                s.target_client_trips or "",
                s.target_wall_clock_s or "",
                s.final_acc or "",
                s.client_trip_budget or "",
                s.final_client_trips or "",
                s.final_wall_clock_s or "",
                s.rpi4_update_share or "",
                s.rpi4_weight_share or "",
                s.rpi4_staleness or "",
                s.rpi5_staleness or "",
                s.updates_per_second or "",
            ]
            for s in summaries
        ),
    )


def fetch_or_load(raw_filename: str, summary_filename: str) -> tuple[list[EvalPoint], list[SummaryRow]]:
    points, summaries = load_cached(raw_filename, summary_filename)
    if points and summaries:
        return points, summaries

    api = wandb.Api(timeout=60)
    all_points: list[EvalPoint] = []
    all_summaries: list[SummaryRow] = []
    for spec in run_specs():
        run_points, summary = _fetch_run(api, spec)
        all_points.extend(run_points)
        all_summaries.append(summary)
    write_cache(raw_filename, summary_filename, all_points, all_summaries)
    return all_points, all_summaries


def points_for(
    points: list[EvalPoint],
    *,
    regime: str,
    topology: str,
    method: str,
) -> list[EvalPoint]:
    return [p for p in points if p.regime == regime and p.topology == topology and p.method == method]


def summaries_for(
    summaries: list[SummaryRow],
    *,
    regime: str,
    topology: str,
    method: str,
) -> list[SummaryRow]:
    return [s for s in summaries if s.regime == regime and s.topology == topology and s.method == method]


def aggregate_curve(points: list[EvalPoint], *, x_axis: str) -> list[CurvePoint]:
    if x_axis not in {"client_trip", "wall_clock"}:
        raise ValueError(f"Unsupported x_axis: {x_axis}")

    by_cell: dict[tuple[str, str, str], dict[int, list[EvalPoint]]] = defaultdict(lambda: defaultdict(list))
    for point in points:
        x_value = point.client_trip if x_axis == "client_trip" else point.wall_clock_s
        if x_value is None:
            continue
        by_cell[(point.regime, point.topology, point.method)][point.seed].append(point)

    rows: list[CurvePoint] = []
    for (regime, topology, method), seed_groups in sorted(by_cell.items()):
        ordered_groups: dict[int, list[EvalPoint]] = {}
        for seed, seed_points in seed_groups.items():
            ordered_groups[seed] = sorted(
                seed_points,
                key=lambda point: float(point.client_trip if x_axis == "client_trip" else point.wall_clock_s or 0.0),
            )

        if x_axis == "client_trip":
            grid = np.array(
                sorted(
                    {
                        float(point.client_trip)
                        for seed_points in ordered_groups.values()
                        for point in seed_points
                        if point.client_trip is not None
                    }
                ),
                dtype=float,
            )
        else:
            max_x = max(
                float(point.wall_clock_s or 0.0)
                for seed_points in ordered_groups.values()
                for point in seed_points
            )
            first_common_x = max(
                float(seed_points[0].wall_clock_s or 0.0)
                for seed_points in ordered_groups.values()
                if seed_points
            )
            grid = np.arange(np.ceil(first_common_x / 100.0) * 100.0, max_x + 100.0, 100.0)

        for x_value in grid:
            values: list[float] = []
            for seed_points in ordered_groups.values():
                xs = np.array(
                    [
                        float(point.client_trip if x_axis == "client_trip" else point.wall_clock_s)
                        for point in seed_points
                        if (point.client_trip if x_axis == "client_trip" else point.wall_clock_s) is not None
                    ],
                    dtype=float,
                )
                ys = np.array(
                    [
                        point.eval_acc
                        for point in seed_points
                        if (point.client_trip if x_axis == "client_trip" else point.wall_clock_s) is not None
                    ],
                    dtype=float,
                )
                if len(xs) == 0 or x_value < xs[0]:
                    continue
                if len(xs) == 1 or x_value > xs[-1]:
                    values.append(float(ys[-1]))
                else:
                    values.append(float(np.interp(x_value, xs, ys)))
            if len(values) == len(ordered_groups):
                mean, std = mean_std(values)
                rows.append(
                    CurvePoint(
                        regime=regime,
                        topology=topology,
                        method=method,
                        x=float(x_value),
                        n=len(values),
                        eval_acc_mean=mean,
                        eval_acc_std=std,
                    )
                )
    return rows


def aggregate_targets(summaries: list[SummaryRow]) -> list[AggregateTargetRow]:
    grouped: dict[tuple[str, str, str], list[SummaryRow]] = defaultdict(list)
    for summary in summaries:
        grouped[(summary.regime, summary.topology, summary.method)].append(summary)

    rows: list[AggregateTargetRow] = []
    for (regime, topology, method), group in sorted(grouped.items()):
        trip_values = [
            float(summary.target_client_trips or summary.client_trip_budget or summary.final_client_trips or BUDGET_TRIPS)
            for summary in group
        ]
        time_values = [
            float(summary.target_wall_clock_s or summary.final_wall_clock_s or 0.0)
            for summary in group
        ]
        final_acc_values = [float(summary.final_acc or 0.0) for summary in group]
        trip_mean, trip_std = mean_std(trip_values)
        time_mean, time_std = mean_std(time_values)
        final_mean, final_std = mean_std(final_acc_values)
        reached = sum(1 for summary in group if summary.target_reached)
        rows.append(
            AggregateTargetRow(
                regime=regime,
                topology=topology,
                method=method,
                n=len(group),
                target_reached_count=reached,
                target_censored=reached < len(group),
                target_client_trips_mean=trip_mean,
                target_client_trips_std=trip_std,
                target_wall_clock_s_mean=time_mean,
                target_wall_clock_s_std=time_std,
                final_acc_mean=final_mean,
                final_acc_std=final_std,
            )
        )
    return rows


def aggregate_diagnostics(summaries: list[SummaryRow]) -> list[AggregateDiagnosticRow]:
    grouped: dict[tuple[str, str], list[SummaryRow]] = defaultdict(list)
    for summary in summaries:
        if summary.topology != "mixed" or summary.method not in {"fedbuff", "fedstaleweight"}:
            continue
        grouped[(summary.regime, summary.method)].append(summary)

    rows: list[AggregateDiagnosticRow] = []
    for (regime, method), group in sorted(grouped.items()):
        required = [
            summary
            for summary in group
            if summary.rpi4_update_share is not None
            and summary.rpi4_weight_share is not None
            and summary.rpi4_staleness is not None
            and summary.rpi5_staleness is not None
            and summary.updates_per_second is not None
        ]
        if len(required) != len(group):
            raise RuntimeError(f"Missing async diagnostics for {regime}/{method}")
        update_mean, update_std = mean_std(summary.rpi4_update_share for summary in required if summary.rpi4_update_share is not None)
        weight_mean, weight_std = mean_std(summary.rpi4_weight_share for summary in required if summary.rpi4_weight_share is not None)
        rpi4_stale_mean, rpi4_stale_std = mean_std(summary.rpi4_staleness for summary in required if summary.rpi4_staleness is not None)
        rpi5_stale_mean, rpi5_stale_std = mean_std(summary.rpi5_staleness for summary in required if summary.rpi5_staleness is not None)
        throughput_mean, throughput_std = mean_std(summary.updates_per_second for summary in required if summary.updates_per_second is not None)
        rows.append(
            AggregateDiagnosticRow(
                regime=regime,
                method=method,
                n=len(required),
                rpi4_update_share_mean=update_mean,
                rpi4_update_share_std=update_std,
                rpi4_weight_share_mean=weight_mean,
                rpi4_weight_share_std=weight_std,
                rpi4_staleness_mean=rpi4_stale_mean,
                rpi4_staleness_std=rpi4_stale_std,
                rpi5_staleness_mean=rpi5_stale_mean,
                rpi5_staleness_std=rpi5_stale_std,
                updates_per_second_mean=throughput_mean,
                updates_per_second_std=throughput_std,
            )
        )
    return rows


def write_curve_aggregate(filename: str, rows: list[CurvePoint]) -> Path:
    return write_csv_plot(
        filename,
        ["regime", "topology", "method", "x", "n", "eval_acc_mean", "eval_acc_std"],
        ([row.regime, row.topology, row.method, row.x, row.n, row.eval_acc_mean, row.eval_acc_std] for row in rows),
    )


def write_target_aggregate(filename: str, rows: list[AggregateTargetRow]) -> Path:
    return write_csv_plot(
        filename,
        [
            "regime",
            "topology",
            "method",
            "n",
            "target_reached_count",
            "target_censored",
            "target_client_trips_mean",
            "target_client_trips_std",
            "target_wall_clock_s_mean",
            "target_wall_clock_s_std",
            "final_acc_mean",
            "final_acc_std",
        ],
        (
            [
                row.regime,
                row.topology,
                row.method,
                row.n,
                row.target_reached_count,
                row.target_censored,
                row.target_client_trips_mean,
                row.target_client_trips_std,
                row.target_wall_clock_s_mean,
                row.target_wall_clock_s_std,
                row.final_acc_mean,
                row.final_acc_std,
            ]
            for row in rows
        ),
    )


def write_diagnostic_aggregate(filename: str, rows: list[AggregateDiagnosticRow]) -> Path:
    return write_csv_plot(
        filename,
        [
            "regime",
            "method",
            "n",
            "rpi4_update_share_mean",
            "rpi4_update_share_std",
            "rpi4_weight_share_mean",
            "rpi4_weight_share_std",
            "rpi4_staleness_mean",
            "rpi4_staleness_std",
            "rpi5_staleness_mean",
            "rpi5_staleness_std",
            "updates_per_second_mean",
            "updates_per_second_std",
        ],
        (
            [
                row.regime,
                row.method,
                row.n,
                row.rpi4_update_share_mean,
                row.rpi4_update_share_std,
                row.rpi4_weight_share_mean,
                row.rpi4_weight_share_std,
                row.rpi4_staleness_mean,
                row.rpi4_staleness_std,
                row.rpi5_staleness_mean,
                row.rpi5_staleness_std,
                row.updates_per_second_mean,
                row.updates_per_second_std,
            ]
            for row in rows
        ),
    )
