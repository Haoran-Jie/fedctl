#!/usr/bin/env python3
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from common import (
    PUBLICATION_FIGURE_WIDTH,
    apply_publication_style,
    default_cycle_colors,
    save_figure_dual,
    write_json_plot,
)
from network_main_common import (
    BUDGET_TRIPS,
    METHOD_LABELS,
    METHOD_ORDER,
    REGIME_LABELS,
    REGIME_ORDER,
    TARGET_ACC,
    TASK,
    TOPOLOGY_LABELS,
    TOPOLOGY_ORDER,
    aggregate_curve,
    aggregate_targets,
    fetch_or_load,
    run_specs,
    summaries_for,
    write_curve_aggregate,
    write_target_aggregate,
)

RAW_FILENAME = "network_main_accuracy_vs_client_trips_raw.csv"
SUMMARY_FILENAME = "network_main_accuracy_vs_client_trips_summary.csv"


def main() -> None:
    points, summaries = fetch_or_load(RAW_FILENAME, SUMMARY_FILENAME)
    curve_rows = aggregate_curve(points, x_axis="client_trip")
    target_rows = aggregate_targets(summaries)
    write_curve_aggregate("network_main_accuracy_vs_client_trips_aggregate.csv", curve_rows)
    write_target_aggregate("network_main_target_aggregate.csv", target_rows)

    coverage = []
    for spec in run_specs():
        run_points = [p for p in points if p.run_id == spec.run_id and p.client_trip is not None]
        run_summaries = summaries_for(
            summaries,
            regime=spec.regime,
            topology=spec.topology,
            method=spec.method,
        )
        summary = next((row for row in run_summaries if row.seed == spec.seed), None)
        coverage.append(
            {
                "run_id": spec.run_id,
                "seed": spec.seed,
                "regime": spec.regime,
                "topology": spec.topology,
                "method": spec.method,
                "points": len(run_points),
                "first_trip": min((p.client_trip for p in run_points if p.client_trip is not None), default=None),
                "last_trip": max((p.client_trip for p in run_points if p.client_trip is not None), default=None),
                "target_reached": summary.target_reached if summary else None,
                "target_client_trips": summary.target_client_trips if summary else None,
            }
        )
    write_json_plot(
        "network_main_accuracy_vs_client_trips_coverage.json",
        {"task": TASK, "target_acc": TARGET_ACC, "runs": coverage},
    )

    apply_publication_style()
    colors = dict(zip(METHOD_ORDER, default_cycle_colors(len(METHOD_ORDER)), strict=True))
    linestyles = {"fedavg": "-", "fedbuff": "--", "fedstaleweight": "-."}

    fig, axes = plt.subplots(2, 2, figsize=(PUBLICATION_FIGURE_WIDTH, 7), sharex=True, sharey=True)
    for row_idx, regime in enumerate(REGIME_ORDER):
        for col_idx, topology in enumerate(TOPOLOGY_ORDER):
            ax = axes[row_idx, col_idx]
            for method in METHOD_ORDER:
                curve = [
                    row
                    for row in curve_rows
                    if row.regime == regime and row.topology == topology and row.method == method
                ]
                if not curve:
                    continue
                xs = np.array([row.x for row in curve], dtype=float)
                means = np.array([row.eval_acc_mean for row in curve], dtype=float)
                stds = np.array([row.eval_acc_std for row in curve], dtype=float)
                order = np.argsort(xs)
                ax.plot(
                    xs[order],
                    means[order],
                    marker="o",
                    markersize=4.0,
                    linewidth=2.0,
                    linestyle=linestyles[method],
                    color=colors[method],
                    label=METHOD_LABELS[method],
                )
                band = stds[order] > 0
                if np.any(band):
                    ax.fill_between(
                        xs[order],
                        means[order] - stds[order],
                        means[order] + stds[order],
                        where=band,
                        color=colors[method],
                        alpha=0.16,
                        linewidth=0,
                    )
                target = next(
                    (
                        row
                        for row in target_rows
                        if row.regime == regime and row.topology == topology and row.method == method
                    ),
                    None,
                )
                if target and not target.target_censored:
                    ax.scatter(
                        [target.target_client_trips_mean],
                        [TARGET_ACC],
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
            ax.set_xlim(0, BUDGET_TRIPS)
            ax.set_ylim(0.30, 0.66)
            ax.set_xticks([0, 250, 500, 750, 1000])
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
                ax.set_xlabel("Client trips")
            if col_idx == 0:
                ax.set_ylabel("Accuracy")

    handles, labels = axes[0, 0].get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    fig.legend(by_label.values(), by_label.keys(), loc="upper center", ncol=3, frameon=True, bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.93))

    outputs = save_figure_dual(fig, "network_main_accuracy_vs_client_trips")
    left_pdf, right_pdf = outputs["pdf"]
    print(
        json.dumps(
            {
                "points": len(points),
                "seeds": sorted({summary.seed for summary in summaries}),
                "plot_output": {"pdf": str(left_pdf)},
                "writeup_output": {"pdf": str(right_pdf)},
                "coverage": coverage,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
