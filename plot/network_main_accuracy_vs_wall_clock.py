#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import wandb

from common import (
    PUBLICATION_FIGURE_WIDTH,
    apply_publication_style,
    cache_is_fresh,
    default_cycle_colors,
    force_refresh_requested,
    plot_output_path,
    save_figure_dual,
    write_csv_plot,
    write_json_plot,
)

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
TASK = "cifar10_cnn"
TARGET_ACC = 0.60
MAX_SECONDS = 4500

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

RUNS = (
    ("iid", "all_rpi5", "fedavg", "c97h9zuy"),
    ("iid", "all_rpi5", "fedbuff", "6eom2gov"),
    ("iid", "all_rpi5", "fedstaleweight", "ey33oqo6"),
    ("noniid", "all_rpi5", "fedavg", "6l03ojrq"),
    ("noniid", "all_rpi5", "fedbuff", "k2bpz79x"),
    ("noniid", "all_rpi5", "fedstaleweight", "59wlhy0n"),
    ("iid", "mixed", "fedavg", "t9vlpy39"),
    ("iid", "mixed", "fedbuff", "stlelmg4"),
    ("iid", "mixed", "fedstaleweight", "4k0nvn9k"),
    ("noniid", "mixed", "fedavg", "0ysztwpg"),
    ("noniid", "mixed", "fedbuff", "j81afai0"),
    ("noniid", "mixed", "fedstaleweight", "wyc9rjxq"),
)


@dataclass(frozen=True)
class RunSpec:
    regime: str
    topology: str
    method: str
    run_id: str


@dataclass(frozen=True)
class EvalPoint:
    regime: str
    topology: str
    method: str
    run_id: str
    wall_clock_s: float
    client_trip: int | None
    eval_acc: float
    server_step: int | None


@dataclass(frozen=True)
class SummaryRow:
    regime: str
    topology: str
    method: str
    run_id: str
    target_reached: bool
    target_wall_clock_s: float | None
    target_client_trips: int | None
    final_acc: float | None


def _run_specs() -> list[RunSpec]:
    return [RunSpec(*row) for row in RUNS]


def _score_from_row(row: dict[str, object]) -> float | None:
    for key in ("eval_server_trip/eval-acc", "eval_server_trip/eval-score"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _runtime_from_row(row: dict[str, object]) -> float | None:
    value = row.get("_runtime")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _client_trip_from_row(row: dict[str, object]) -> int | None:
    value = row.get("client_trip")
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _server_step_from_row(row: dict[str, object]) -> int | None:
    for key in ("eval_server_trip/server-round", "server_step", "server_round"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _fetch_run(api: wandb.Api, spec: RunSpec) -> tuple[list[EvalPoint], SummaryRow]:
    run = api.run(f"{ENTITY}/{PROJECT}/{spec.run_id}")
    points: list[EvalPoint] = []
    seen: set[tuple[float, float]] = set()
    for row in run.scan_history(page_size=1000):
        score = _score_from_row(row)
        runtime = _runtime_from_row(row)
        if score is None or runtime is None:
            continue
        key = (runtime, score)
        if key in seen:
            continue
        seen.add(key)
        points.append(
            EvalPoint(
                regime=spec.regime,
                topology=spec.topology,
                method=spec.method,
                run_id=spec.run_id,
                wall_clock_s=runtime,
                client_trip=_client_trip_from_row(row),
                eval_acc=score,
                server_step=_server_step_from_row(row),
            )
        )
    points.sort(key=lambda p: p.wall_clock_s)
    summary = dict(run.summary)
    target_wall = summary.get("target/wall_clock_s_to_target")
    target_trips = summary.get("target/client_trips_to_target")
    final_acc = summary.get("final/eval_server/eval-acc", summary.get("final/eval_server/eval-score"))
    return points, SummaryRow(
        regime=spec.regime,
        topology=spec.topology,
        method=spec.method,
        run_id=spec.run_id,
        target_reached=bool(summary.get("target/reached")),
        target_wall_clock_s=float(target_wall) if isinstance(target_wall, (int, float)) else None,
        target_client_trips=int(target_trips) if isinstance(target_trips, (int, float)) else None,
        final_acc=float(final_acc) if isinstance(final_acc, (int, float)) else None,
    )


def _load_cached() -> tuple[list[EvalPoint], list[SummaryRow]]:
    points_path = plot_output_path("network_main_accuracy_vs_wall_clock_raw.csv")
    summary_path = plot_output_path("network_main_accuracy_vs_wall_clock_summary.csv")
    if force_refresh_requested() or not cache_is_fresh(points_path) or not summary_path.exists():
        return [], []
    points: list[EvalPoint] = []
    with points_path.open(newline="") as f:
        for row in csv.DictReader(f):
            points.append(
                EvalPoint(
                    regime=row["regime"],
                    topology=row["topology"],
                    method=row["method"],
                    run_id=row["run_id"],
                    wall_clock_s=float(row["wall_clock_s"]),
                    client_trip=int(row["client_trip"]) if row["client_trip"] else None,
                    eval_acc=float(row["eval_acc"]),
                    server_step=int(row["server_step"]) if row["server_step"] else None,
                )
            )
    summaries: list[SummaryRow] = []
    with summary_path.open(newline="") as f:
        for row in csv.DictReader(f):
            summaries.append(
                SummaryRow(
                    regime=row["regime"],
                    topology=row["topology"],
                    method=row["method"],
                    run_id=row["run_id"],
                    target_reached=row["target_reached"].lower() == "true",
                    target_wall_clock_s=float(row["target_wall_clock_s"]) if row["target_wall_clock_s"] else None,
                    target_client_trips=int(row["target_client_trips"]) if row["target_client_trips"] else None,
                    final_acc=float(row["final_acc"]) if row["final_acc"] else None,
                )
            )
    return points, summaries


def _write_cache(points: list[EvalPoint], summaries: list[SummaryRow]) -> None:
    write_csv_plot(
        "network_main_accuracy_vs_wall_clock_raw.csv",
        ["regime", "topology", "method", "run_id", "wall_clock_s", "client_trip", "eval_acc", "server_step"],
        (
            [p.regime, p.topology, p.method, p.run_id, p.wall_clock_s, p.client_trip or "", p.eval_acc, p.server_step or ""]
            for p in points
        ),
    )
    write_csv_plot(
        "network_main_accuracy_vs_wall_clock_summary.csv",
        [
            "regime",
            "topology",
            "method",
            "run_id",
            "target_reached",
            "target_wall_clock_s",
            "target_client_trips",
            "final_acc",
        ],
        (
            [
                s.regime,
                s.topology,
                s.method,
                s.run_id,
                s.target_reached,
                s.target_wall_clock_s or "",
                s.target_client_trips or "",
                s.final_acc or "",
            ]
            for s in summaries
        ),
    )


def _points_for(points: list[EvalPoint], *, regime: str, topology: str, method: str) -> list[EvalPoint]:
    return [p for p in points if p.regime == regime and p.topology == topology and p.method == method]


def _summary_for(summaries: list[SummaryRow], *, regime: str, topology: str, method: str) -> SummaryRow | None:
    for s in summaries:
        if s.regime == regime and s.topology == topology and s.method == method:
            return s
    return None


def main() -> None:
    points, summaries = _load_cached()
    if not points or not summaries:
        api = wandb.Api(timeout=30)
        all_points: list[EvalPoint] = []
        all_summaries: list[SummaryRow] = []
        for spec in _run_specs():
            run_points, summary = _fetch_run(api, spec)
            all_points.extend(run_points)
            all_summaries.append(summary)
        points, summaries = all_points, all_summaries
        _write_cache(points, summaries)

    coverage = []
    for spec in _run_specs():
        run_points = [p for p in points if p.run_id == spec.run_id]
        summary = _summary_for(summaries, regime=spec.regime, topology=spec.topology, method=spec.method)
        coverage.append(
            {
                "run_id": spec.run_id,
                "regime": spec.regime,
                "topology": spec.topology,
                "method": spec.method,
                "points": len(run_points),
                "first_wall_clock_s": min((p.wall_clock_s for p in run_points), default=None),
                "last_wall_clock_s": max((p.wall_clock_s for p in run_points), default=None),
                "target_reached": summary.target_reached if summary else None,
                "target_wall_clock_s": summary.target_wall_clock_s if summary else None,
            }
        )
    write_json_plot(
        "network_main_accuracy_vs_wall_clock_coverage.json",
        {"task": TASK, "target_acc": TARGET_ACC, "runs": coverage},
    )

    apply_publication_style()
    colors = dict(zip(METHOD_ORDER, default_cycle_colors(len(METHOD_ORDER)), strict=True))
    linestyles = {"fedavg": "-", "fedbuff": "--", "fedstaleweight": "-."}

    fig, axes = plt.subplots(2, 2, figsize=(PUBLICATION_FIGURE_WIDTH, 7.2), sharex=True, sharey=True)
    for row_idx, regime in enumerate(REGIME_ORDER):
        for col_idx, topology in enumerate(TOPOLOGY_ORDER):
            ax = axes[row_idx, col_idx]
            for method in METHOD_ORDER:
                subset = _points_for(points, regime=regime, topology=topology, method=method)
                if not subset:
                    continue
                xs = np.array([p.wall_clock_s for p in subset], dtype=float)
                ys = np.array([p.eval_acc for p in subset], dtype=float)
                order = np.argsort(xs)
                summary = _summary_for(summaries, regime=regime, topology=topology, method=method)
                label = METHOD_LABELS[method]
                if summary and not summary.target_reached:
                    label = f"{label} (censored)"
                ax.plot(
                    xs[order],
                    ys[order],
                    marker="o",
                    markersize=4.0,
                    linewidth=2.0,
                    linestyle=linestyles[method],
                    color=colors[method],
                    label=label,
                )
                if summary and summary.target_reached and summary.target_wall_clock_s is not None:
                    closest = min(subset, key=lambda p: abs(p.wall_clock_s - summary.target_wall_clock_s))
                    ax.scatter(
                        [closest.wall_clock_s],
                        [closest.eval_acc],
                        s=62,
                        marker="*",
                        color=colors[method],
                        edgecolors="black",
                        linewidths=0.5,
                        zorder=5,
                    )
            ax.axhline(TARGET_ACC, color="#444444", linestyle=":", linewidth=1.4)
            if row_idx == 0:
                ax.set_title(TOPOLOGY_LABELS[topology])
            ax.set_xlim(0, MAX_SECONDS)
            ax.set_ylim(0.30, 0.66)
            ax.set_xticks([0, 1000, 2000, 3000, 4000])
            ax.text(
                0.03,
                0.95,
                REGIME_LABELS[regime],
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=14,
                color="#333333",
                bbox={
                    "boxstyle": "round,pad=0.20",
                    "facecolor": "white",
                    "alpha": 0.8,
                    "edgecolor": "#cccccc",
                },
            )
            ax.text(
                0.985,
                TARGET_ACC + 0.006,
                r"60\% target",
                transform=ax.get_yaxis_transform(),
                ha="right",
                va="bottom",
                fontsize=13,
                color="#333333",
            )
            if row_idx == 1:
                ax.set_xlabel("Elapsed wall-clock time (s)")
            if col_idx == 0:
                ax.set_ylabel("Accuracy")

    handles, labels = axes[0, 0].get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    fig.legend(by_label.values(), by_label.keys(), loc="upper center", ncol=3, frameon=True, bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.93))

    outputs = save_figure_dual(fig, "network_main_accuracy_vs_wall_clock")
    left_pdf, right_pdf = outputs["pdf"]
    print(
        json.dumps(
            {
                "points": len(points),
                "plot_output": {"pdf": str(left_pdf)},
                "writeup_output": {"pdf": str(right_pdf)},
                "coverage": coverage,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
