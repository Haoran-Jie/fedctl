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
from network_common import (
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
    aggregate_diagnostics,
    aggregate_targets,
    fetch_or_load,
    run_specs,
    summaries_for,
    write_curve_aggregate,
    write_diagnostic_aggregate,
    write_target_aggregate,
)

RAW_FILENAME = "network_main_accuracy_vs_client_trips_raw.csv"
SUMMARY_FILENAME = "network_main_accuracy_vs_client_trips_summary.csv"
MAX_SECONDS = 4500


def _plot_panel(
    ax: plt.Axes,
    *,
    curve_rows,
    target_rows,
    x_axis: str,
    regime: str,
    topology: str,
    colors: dict[str, str],
    linestyles: dict[str, str],
    show_target_label: bool,
) -> None:
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
            linewidth=1.35 if method == "fedasync" else 1.7,
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
                alpha=0.10,
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
            target_x = (
                target.target_client_trips_mean
                if x_axis == "client_trip"
                else target.target_wall_clock_s_mean
            )
            ax.scatter(
                [target_x],
                [TARGET_ACC],
                s=46,
                marker="*",
                color=colors[method],
                edgecolors="black",
                linewidths=0.45,
                zorder=5,
            )

    ax.axhline(TARGET_ACC, color="#444444", linestyle=":", linewidth=1.2)
    if show_target_label:
        ax.text(
            0.985,
            TARGET_ACC - 0.04,
            r"60\%",
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="bottom",
            fontsize=11,
            color="#333333",
        )

    ax.set_ylim(0.39, 0.62)
    ax.set_yticks([0.40, 0.50, 0.60])

    if x_axis == "client_trip":
        ax.set_xlim(0, BUDGET_TRIPS)
        ax.set_xticks([0, 250, 500, 750, 1000])
    else:
        ax.set_xlim(0, MAX_SECONDS)
        ax.set_xticks([0, 1000, 2000, 3000, 4000])


def main() -> None:
    points, summaries = fetch_or_load(RAW_FILENAME, SUMMARY_FILENAME)
    trip_curve_rows = aggregate_curve(points, x_axis="client_trip")
    wall_curve_rows = aggregate_curve(points, x_axis="wall_clock")
    target_rows = aggregate_targets(summaries)
    diagnostic_rows = aggregate_diagnostics(summaries)

    write_curve_aggregate("network_main_accuracy_combined_client_trips_aggregate.csv", trip_curve_rows)
    write_curve_aggregate("network_main_accuracy_combined_wall_clock_aggregate.csv", wall_curve_rows)
    write_target_aggregate("network_main_target_aggregate.csv", target_rows)
    write_diagnostic_aggregate("network_main_async_diagnostics_aggregate.csv", diagnostic_rows)

    coverage = []
    for spec in run_specs():
        run_points = [p for p in points if p.run_id == spec.run_id]
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
                "client_trip_points": sum(1 for p in run_points if p.client_trip is not None),
                "wall_clock_points": sum(1 for p in run_points if p.wall_clock_s is not None),
                "first_trip": min((p.client_trip for p in run_points if p.client_trip is not None), default=None),
                "last_trip": max((p.client_trip for p in run_points if p.client_trip is not None), default=None),
                "first_wall_clock_s": min((p.wall_clock_s for p in run_points if p.wall_clock_s is not None), default=None),
                "last_wall_clock_s": max((p.wall_clock_s for p in run_points if p.wall_clock_s is not None), default=None),
                "target_reached": summary.target_reached if summary else None,
                "target_client_trips": summary.target_client_trips if summary else None,
                "target_wall_clock_s": summary.target_wall_clock_s if summary else None,
            }
        )
    write_json_plot(
        "network_main_accuracy_combined_coverage.json",
        {"task": TASK, "target_acc": TARGET_ACC, "runs": coverage},
    )

    apply_publication_style()
    colors = dict(zip(METHOD_ORDER, default_cycle_colors(len(METHOD_ORDER)), strict=True))
    linestyles = {"fedavg": "-", "fedasync": "-", "fedbuff": "--", "fedstaleweight": "-."}
    columns = [(regime, topology) for regime in REGIME_ORDER for topology in TOPOLOGY_ORDER]

    fig, axes = plt.subplots(
        2,
        4,
        figsize=(PUBLICATION_FIGURE_WIDTH, 6),
        sharex=False,
        sharey=False,
    )

    for col_idx, (regime, topology) in enumerate(columns):
        title = f"{REGIME_LABELS[regime]}, {TOPOLOGY_LABELS[topology]}"
        axes[0, col_idx].set_title(title, pad=8)

        _plot_panel(
            axes[0, col_idx],
            curve_rows=trip_curve_rows,
            target_rows=target_rows,
            x_axis="client_trip",
            regime=regime,
            topology=topology,
            colors=colors,
            linestyles=linestyles,
            show_target_label=col_idx == len(columns) - 1,
        )
        _plot_panel(
            axes[1, col_idx],
            curve_rows=wall_curve_rows,
            target_rows=target_rows,
            x_axis="wall_clock",
            regime=regime,
            topology=topology,
            colors=colors,
            linestyles=linestyles,
            show_target_label=col_idx == len(columns) - 1,
        )

        axes[0, col_idx].set_xlabel("Client trips")
        axes[1, col_idx].set_xlabel("Wall-clock time (s)")

        if col_idx == 0:
            axes[0, col_idx].set_ylabel("Accuracy")
            axes[1, col_idx].set_ylabel("Accuracy")
        else:
            axes[0, col_idx].tick_params(labelleft=False)
            axes[1, col_idx].tick_params(labelleft=False)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    fig.legend(
        by_label.values(),
        by_label.keys(),
        loc="upper center",
        ncol=4,
        frameon=True,
        bbox_to_anchor=(0.5, 1.03),
    )

    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.94), h_pad=1.0, w_pad=0.9)

    outputs = save_figure_dual(fig, "network_main_accuracy_combined")
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
