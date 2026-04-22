#!/usr/bin/env python3
from __future__ import annotations

import csv
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import wandb

from common import (
    PUBLICATION_FIGURE_WIDTH,
    apply_publication_style,
    cache_is_fresh,
    default_cycle_colors,
    force_refresh_requested,
    plot_output_path,
    save_figure_plot_with_writeup_pdf,
    write_csv_plot,
    write_json_plot,
)

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
STEM = "compute_slow_minority_tradeoff"


@dataclass(frozen=True)
class RunSpec:
    case: str
    clients: str
    method: str
    data_used: str
    rpi5_rate: str
    rpi4_rate: str
    run_id: str


@dataclass(frozen=True)
class EvalPoint:
    case: str
    run_id: str
    wall_clock_s: float
    server_round: int | None
    eval_acc: float


@dataclass(frozen=True)
class SummaryRow:
    case: str
    clients: str
    method: str
    data_used: str
    rpi5_rate: str
    rpi4_rate: str
    run_id: str
    final_acc: float
    best_acc: float
    total_time_s: float
    mean_round_time_s: float
    round_count: int


RUNS = (
    RunSpec("A", "12 rpi5", "FedAvg", "12/15", "1.0", "excluded", "xfb856p2"),
    RunSpec("B", "12rpi5 + 3 rpi4", "FedAvg", "15/15", "1.0", "1.0", "vq2hb555"),
    RunSpec("C", "12rpi5 + 3 rpi4", "HeteroFL", "15/15", "1.0", "1/8", "0qujvgnw"),
    RunSpec("D", "12rpi5 + 3 rpi4", "FedRolex", "15/15", "1.0", "1/8", "2qe5vs0v"),
    RunSpec("E", "12rpi5 + 3 rpi4", "FIARSE", "15/15", "1.0", "1/8", "11po16lu"),
)

EVAL_ACC_KEYS = (
    "eval_server/eval-acc",
    "eval_server/eval-score",
    "eval_server_trip/eval-acc",
    "eval_server_trip/eval-score",
)
SERVER_ROUND_KEYS = (
    "eval_server/server-round",
    "eval_server_trip/server-round",
    "server_round",
    "server_step",
)


def _number(row: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _server_round(row: dict[str, object]) -> int | None:
    value = _number(row, SERVER_ROUND_KEYS)
    return int(value) if value is not None else None


def _summary_number(summary: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = summary.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _fetch_run(api: wandb.Api, spec: RunSpec) -> tuple[list[EvalPoint], SummaryRow]:
    run = api.run(f"{ENTITY}/{PROJECT}/{spec.run_id}")
    eval_points: list[EvalPoint] = []
    round_durations: list[float] = []
    seen_eval: set[tuple[int | None, float]] = set()

    for row in run.scan_history(page_size=1000):
        duration = row.get("round_system/train_duration_s")
        if isinstance(duration, (int, float)):
            round_durations.append(float(duration))

        score = _number(row, EVAL_ACC_KEYS)
        runtime = row.get("_runtime")
        if score is None or not isinstance(runtime, (int, float)):
            continue

        server_round = _server_round(row)
        key = (server_round, float(score))
        if key in seen_eval:
            continue
        seen_eval.add(key)
        eval_points.append(
            EvalPoint(
                case=spec.case,
                run_id=spec.run_id,
                wall_clock_s=float(runtime),
                server_round=server_round,
                eval_acc=float(score),
            )
        )

    eval_points.sort(key=lambda point: (point.server_round if point.server_round is not None else 10**9, point.wall_clock_s))
    if not eval_points:
        raise RuntimeError(f"No centralized eval points found for W&B run {spec.run_id}")

    summary = dict(run.summary)
    total_time_s = _summary_number(summary, ("runtime/total_server_s", "_runtime")) or eval_points[-1].wall_clock_s
    final_acc = _summary_number(summary, ("final/eval_server/eval-acc", "final/eval_server/eval-score")) or eval_points[-1].eval_acc
    best_acc = max(point.eval_acc for point in eval_points)
    mean_round_time_s = sum(round_durations) / len(round_durations) if round_durations else total_time_s / 20.0

    return eval_points, SummaryRow(
        case=spec.case,
        clients=spec.clients,
        method=spec.method,
        data_used=spec.data_used,
        rpi5_rate=spec.rpi5_rate,
        rpi4_rate=spec.rpi4_rate,
        run_id=spec.run_id,
        final_acc=float(final_acc),
        best_acc=float(best_acc),
        total_time_s=float(total_time_s),
        mean_round_time_s=float(mean_round_time_s),
        round_count=len(round_durations),
    )


def _load_cache() -> tuple[list[EvalPoint], list[SummaryRow]]:
    raw_path = plot_output_path(f"{STEM}_raw.csv")
    summary_path = plot_output_path(f"{STEM}_summary.csv")
    if force_refresh_requested() or not cache_is_fresh(raw_path) or not summary_path.exists():
        return [], []

    points: list[EvalPoint] = []
    with raw_path.open(newline="") as f:
        for row in csv.DictReader(f):
            points.append(
                EvalPoint(
                    case=row["case"],
                    run_id=row["run_id"],
                    wall_clock_s=float(row["wall_clock_s"]),
                    server_round=int(row["server_round"]) if row["server_round"] else None,
                    eval_acc=float(row["eval_acc"]),
                )
            )

    summaries: list[SummaryRow] = []
    with summary_path.open(newline="") as f:
        for row in csv.DictReader(f):
            summaries.append(
                SummaryRow(
                    case=row["case"],
                    clients=row["clients"],
                    method=row["method"],
                    data_used=row["data_used"],
                    rpi5_rate=row["rpi5_rate"],
                    rpi4_rate=row["rpi4_rate"],
                    run_id=row["run_id"],
                    final_acc=float(row["final_acc"]),
                    best_acc=float(row["best_acc"]),
                    total_time_s=float(row["total_time_s"]),
                    mean_round_time_s=float(row["mean_round_time_s"]),
                    round_count=int(row["round_count"]),
                )
            )
    return points, summaries


def _write_cache(points: list[EvalPoint], summaries: list[SummaryRow]) -> None:
    write_csv_plot(
        f"{STEM}_raw.csv",
        ["case", "run_id", "wall_clock_s", "wall_clock_min", "server_round", "eval_acc"],
        (
            [p.case, p.run_id, p.wall_clock_s, p.wall_clock_s / 60.0, p.server_round or "", p.eval_acc]
            for p in points
        ),
    )
    write_csv_plot(
        f"{STEM}_summary.csv",
        [
            "case",
            "clients",
            "method",
            "data_used",
            "rpi5_rate",
            "rpi4_rate",
            "run_id",
            "final_acc",
            "best_acc",
            "total_time_s",
            "total_time_min",
            "mean_round_time_s",
            "round_count",
        ],
        (
            [
                s.case,
                s.clients,
                s.method,
                s.data_used,
                s.rpi5_rate,
                s.rpi4_rate,
                s.run_id,
                s.final_acc,
                s.best_acc,
                s.total_time_s,
                s.total_time_s / 60.0,
                s.mean_round_time_s,
                s.round_count,
            ]
            for s in summaries
        ),
    )


def _points_for(points: list[EvalPoint], case: str) -> list[EvalPoint]:
    return sorted((point for point in points if point.case == case), key=lambda p: p.wall_clock_s)


def main() -> None:
    points, summaries = _load_cache()
    if not points or not summaries:
        api = wandb.Api(timeout=30)
        fetched_points: list[EvalPoint] = []
        fetched_summaries: list[SummaryRow] = []
        for spec in RUNS:
            run_points, summary = _fetch_run(api, spec)
            fetched_points.extend(run_points)
            fetched_summaries.append(summary)
        points, summaries = fetched_points, fetched_summaries
        _write_cache(points, summaries)

    coverage = [
        {
            "case": spec.case,
            "run_id": spec.run_id,
            "eval_points": len(_points_for(points, spec.case)),
            "has_summary": any(summary.case == spec.case for summary in summaries),
        }
        for spec in RUNS
    ]
    write_json_plot(f"{STEM}_coverage.json", {"runs": coverage})

    apply_publication_style()
    colors_by_case = {spec.case: color for spec, color in zip(RUNS, default_cycle_colors(len(RUNS)), strict=True)}
    fig, ax = plt.subplots(figsize=(PUBLICATION_FIGURE_WIDTH, 6.0))

    label_by_case = {spec.case: f"{spec.case}: {spec.method}, {spec.clients}" for spec in RUNS}
    for spec in RUNS:
        case_points = _points_for(points, spec.case)
        ax.plot(
            [point.wall_clock_s / 60.0 for point in case_points],
            [point.eval_acc * 100.0 for point in case_points],
            marker="o",
            linewidth=2.3,
            markersize=5.5,
            color=colors_by_case[spec.case],
            label=label_by_case.get(spec.case, f"{spec.case}: {spec.method}"),
        )

    ax.set_xlabel("Wall-clock time (min)")
    ax.set_ylabel("Accuracy (\\%)")
    ax.set_ylim(0, 76)
    ax.legend(loc="lower right", frameon=True)
    fig.tight_layout()

    outputs = save_figure_plot_with_writeup_pdf(fig, STEM)
    plt.close(fig)

    print(f"Wrote {outputs['pdf'][0]}")
    print(f"Wrote {outputs['pdf'][1]}")


if __name__ == "__main__":
    main()
