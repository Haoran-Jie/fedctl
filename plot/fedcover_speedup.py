#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import statistics
from dataclasses import asdict, dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    PUBLICATION_FIGURE_WIDTH,
    apply_publication_style,
    default_cycle_colors,
    plot_output_path,
    save_figure_plot_with_writeup_pdf,
    write_csv_plot,
    write_json_plot,
)
from fedcover_pilot import RAW_FILENAME

TASK_ORDER = ("cifar10_cnn", "fashion_mnist_cnn")
REGIME_ORDER = ("iid", "noniid")
TASK_LABELS = {
    "cifar10_cnn": "CIFAR-10",
    "fashion_mnist_cnn": "Fashion-MNIST",
}
REGIME_LABELS = {
    "iid": "IID",
    "noniid": "Non-IID",
}
FEDCOVER_METHODS = (
    ("fedcover_025", r"$0.25$"),
    ("fedcover_050", r"$0.5$"),
    ("fedcover_100", r"$1.0$"),
    ("fedcover_150", r"$1.5$"),
)
BASELINE_METHOD = "async_heterofl"

SUMMARY_FILENAME = "fedcover_post_warmup_speedup_summary.csv"
JSON_FILENAME = "fedcover_post_warmup_speedup_summary.json"
FIGURE_STEM = "fedcover_post_warmup_speedup"
FIGURE_HEIGHT = 4.05
KAPPA_LABEL_Y = -7.0


@dataclass(frozen=True)
class SpeedupRow:
    task: str
    regime: str
    method: str
    gamma_label: str
    seed: int
    baseline_post_warmup_min: float
    fedcover_post_warmup_min: float
    speedup_pct: float
    coverage_gain: float


@dataclass(frozen=True)
class AggregateRow:
    task: str
    regime: str
    method: str
    gamma_label: str
    speedup_mean_pct: float
    speedup_std_pct: float
    coverage_gain_mean: float
    coverage_gain_std: float
    n: int


def _read_raw_rows() -> list[dict[str, str]]:
    path = plot_output_path(RAW_FILENAME)
    if not path.exists():
        raise FileNotFoundError(
            f"missing {path}; run plot/fedcover_pilot.py before generating the speedup figure"
        )
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _seed_rows(rows: list[dict[str, str]]) -> list[SpeedupRow]:
    baseline_by_key: dict[tuple[str, str, int], float] = {}
    for row in rows:
        if row["method"] != BASELINE_METHOD:
            continue
        key = (row["task"], row["regime"], int(row["seed"]))
        baseline_by_key[key] = float(row["post_warmup_target_wall_clock_s"]) / 60.0

    output: list[SpeedupRow] = []
    for method, gamma_label in FEDCOVER_METHODS:
        for row in rows:
            if row["method"] != method:
                continue
            key = (row["task"], row["regime"], int(row["seed"]))
            baseline_min = baseline_by_key[key]
            fedcover_min = float(row["post_warmup_target_wall_clock_s"]) / 60.0
            output.append(
                SpeedupRow(
                    task=row["task"],
                    regime=row["regime"],
                    method=method,
                    gamma_label=gamma_label,
                    seed=int(row["seed"]),
                    baseline_post_warmup_min=baseline_min,
                    fedcover_post_warmup_min=fedcover_min,
                    speedup_pct=((baseline_min - fedcover_min) / baseline_min) * 100.0,
                    coverage_gain=float(row["coverage_gain_mean"]),
                )
            )
    return output


def _aggregate(rows: list[SpeedupRow]) -> list[AggregateRow]:
    aggregates: list[AggregateRow] = []
    for task in TASK_ORDER:
        for regime in REGIME_ORDER:
            for method, gamma_label in FEDCOVER_METHODS:
                group = [
                    row
                    for row in rows
                    if row.task == task and row.regime == regime and row.method == method
                ]
                speedups = [row.speedup_pct for row in group]
                gains = [row.coverage_gain for row in group]
                aggregates.append(
                    AggregateRow(
                        task=task,
                        regime=regime,
                        method=method,
                        gamma_label=gamma_label,
                        speedup_mean_pct=statistics.fmean(speedups),
                        speedup_std_pct=statistics.stdev(speedups) if len(speedups) > 1 else 0.0,
                        coverage_gain_mean=statistics.fmean(gains),
                        coverage_gain_std=statistics.stdev(gains) if len(gains) > 1 else 0.0,
                        n=len(group),
                    )
                )
    return aggregates


def _write_outputs(seed_rows: list[SpeedupRow], aggregates: list[AggregateRow]) -> None:
    write_csv_plot(
        SUMMARY_FILENAME,
        [
            "task",
            "regime",
            "method",
            "gamma",
            "n",
            "speedup_mean_pct",
            "speedup_std_pct",
            "coverage_gain_mean",
            "coverage_gain_std",
        ],
        (
            [
                row.task,
                row.regime,
                row.method,
                row.gamma_label.replace("$", ""),
                row.n,
                f"{row.speedup_mean_pct:.6f}",
                f"{row.speedup_std_pct:.6f}",
                f"{row.coverage_gain_mean:.6f}",
                f"{row.coverage_gain_std:.6f}",
            ]
            for row in aggregates
        ),
    )
    write_json_plot(
        JSON_FILENAME,
        {
            "definition": (
                "Post-warm-up speedup is computed per matched seed as "
                "(T_async_heterofl - T_fedcover) / T_async_heterofl."
            ),
            "baseline": BASELINE_METHOD,
            "controlled_parameter": "fedcover coverage power gamma",
            "coverage_gain_note": (
                "Coverage gain is an observed diagnostic and is not the independent x-axis variable."
            ),
            "seed_rows": [asdict(row) for row in seed_rows],
            "aggregates": [asdict(row) for row in aggregates],
        },
    )


def _plot(seed_rows: list[SpeedupRow], aggregates: list[AggregateRow]) -> None:
    apply_publication_style()
    plt.rcParams.update(
        {
            "font.size": 14,
            "axes.titlesize": 16,
            "axes.labelsize": 15,
            "xtick.labelsize": 13,
            "ytick.labelsize": 13,
        }
    )

    fig, axes = plt.subplots(
        1,
        4,
        figsize=(PUBLICATION_FIGURE_WIDTH, FIGURE_HEIGHT),
        sharey=True,
    )
    panel_keys = [(task, regime) for task in TASK_ORDER for regime in REGIME_ORDER]
    x_positions = list(range(len(FEDCOVER_METHODS)))
    seed_offsets = {1337: -0.12, 1338: 0.0, 1339: 0.12}

    aggregate_by_key = {
        (row.task, row.regime, row.method): row
        for row in aggregates
    }
    seed_by_key: dict[tuple[str, str, str], list[SpeedupRow]] = {}
    for row in seed_rows:
        seed_by_key.setdefault((row.task, row.regime, row.method), []).append(row)
    colors = default_cycle_colors(len(FEDCOVER_METHODS))

    for ax, (task, regime) in zip(axes, panel_keys, strict=True):
        for idx, (method, gamma_label) in enumerate(FEDCOVER_METHODS):
            agg = aggregate_by_key[(task, regime, method)]
            ax.bar(
                idx,
                agg.speedup_mean_pct,
                width=0.58,
                color=colors[idx],
                alpha=0.88,
                edgecolor="black",
                linewidth=0.45,
            )
            YMIN, YMAX = -23, 80

            for seed_row in seed_by_key[(task, regime, method)]:
                y = seed_row.speedup_pct
                clipped_y = max(YMIN + 1.5, min(YMAX - 1.5, y))

                ax.scatter(
                    idx + seed_offsets.get(seed_row.seed, 0.0),
                    clipped_y,
                    s=14,
                    facecolor="white",
                    edgecolor="black",
                    linewidth=0.55,
                    zorder=3,
                )

                if y < YMIN:
                    ax.annotate(
                        f"{y:.1f}",
                        xy=(idx + seed_offsets.get(seed_row.seed, 0.0), YMIN + 1.5),
                        xytext=(0, 8),
                        textcoords="offset points",
                        ha="center",
                        fontsize=9,
                        arrowprops=dict(arrowstyle="-|>", lw=0.5),
                    )
                            
                
            ax.text(
                idx,
                KAPPA_LABEL_Y,
                rf"$\bar{{\kappa}}={agg.coverage_gain_mean:.2f}$",
                ha="center",
                va="center",
                fontsize=12,
                bbox={
                    "boxstyle": "round,pad=0.12",
                    "facecolor": "white",
                    "edgecolor": "0.8",
                    "linewidth": 0.3,
                    "alpha": 0.95,
                },
            )

        ax.axhline(0, color="black", linewidth=0.7)
        ax.set_title(f"{TASK_LABELS[task]}\n{REGIME_LABELS[regime]}", pad=3)
        ax.set_xticks(x_positions)
        ax.set_xticklabels([label for _, label in FEDCOVER_METHODS])
        ax.set_xlim(-0.55, len(FEDCOVER_METHODS) - 0.45)
        ax.set_ylim(-23, 80)
        ax.set_axisbelow(True)

    axes[0].set_ylabel("Post-warm-up speedup\nover Async-HeteroFL (\\%)")
    fig.text(
        0.5,
        0.01,
        r"FedCover coverage power \(\gamma\); \(\bar{\kappa}\) labels are mean observed coverage gain",
        ha="center",
        va="bottom",
        fontsize=16,
    )
    fig.tight_layout(w_pad=0.45, pad=0.25, rect=(0, 0.07, 1, 1))
    save_figure_plot_with_writeup_pdf(fig, FIGURE_STEM)
    plt.close(fig)


def main() -> None:
    seed_rows = _seed_rows(_read_raw_rows())
    aggregates = _aggregate(seed_rows)
    _write_outputs(seed_rows, aggregates)
    _plot(seed_rows, aggregates)
    print(f"Wrote {FIGURE_STEM} outputs")


if __name__ == "__main__":
    main()
