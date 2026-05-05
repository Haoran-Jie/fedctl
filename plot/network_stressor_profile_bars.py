#!/usr/bin/env python3
from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from common import (
    PUBLICATION_FIGURE_WIDTH,
    apply_publication_style,
    default_cycle_colors,
    plot_output_path,
    save_figure_plot_with_writeup_pdf,
    write_csv_plot,
    write_json_plot,
)
from network_stressor_sweep import PROFILE_ORDER, SUMMARY_FILENAME, VARIANT_ORDER

PROFILE_LABELS = {
    "none": "none\ncontrol",
    "mild": "mild\n20 ms",
    "med": "med\n60 ms",
    "asym_up": "asym up\negress",
    "asym_down": "asym down\ningress",
}

METHOD_LABELS = {
    ("fedavg", None): r"\texttt{FedAvg}",
    ("fedbuff", 10): r"\texttt{FedBuff}\(_{10}\)",
    ("fedstaleweight", 10): r"\texttt{FedSW}\(_{10}\)",
    ("fedasync", 1): r"\texttt{FedAsync}",
    ("fedbuff", 5): r"\texttt{FedBuff}\(_{5}\)",
    ("fedstaleweight", 5): r"\texttt{FedSW}\(_{5}\)",
}

SUMMARY_FIELDS = [
    "profile",
    "method",
    "buffer_size",
    "label",
    "seeds",
    "reached_seeds",
    "censored",
    "mean_wall_clock_min",
    "std_wall_clock_min",
    "slowdown_vs_none",
]


@dataclass(frozen=True)
class Aggregate:
    profile: str
    method: str
    buffer_size: int | None
    label: str
    seeds: int
    reached_seeds: int
    censored: bool
    mean_wall_clock_min: float
    std_wall_clock_min: float
    slowdown_vs_none: float


def _optional_int(value: str) -> int | None:
    return int(value) if value else None


def _optional_float(value: str) -> float | None:
    return float(value) if value else None


def _read_rows() -> list[dict[str, str]]:
    path = plot_output_path(SUMMARY_FILENAME)
    if not path.exists():
        raise FileNotFoundError(
            f"missing {path}; run plot/network_stressor_sweep.py before generating the profile bars"
        )
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _display_wall_clock_s(row: dict[str, str]) -> tuple[float, bool]:
    target_reached = row["target_reached"].lower() == "true"
    target_wall = _optional_float(row["target_wall_clock_s"])
    final_wall = _optional_float(row["final_wall_clock_s"])
    if target_reached and target_wall is not None:
        return target_wall, False
    if final_wall is not None:
        return final_wall, True
    raise ValueError(f"row has no usable wall-clock value: {row}")


def _aggregate(rows: list[dict[str, str]]) -> list[Aggregate]:
    grouped: dict[tuple[str, str, int | None], list[dict[str, str]]] = {}
    for row in rows:
        key = (row["profile"], row["method"], _optional_int(row["buffer_size"]))
        grouped.setdefault(key, []).append(row)

    none_baselines: dict[tuple[str, int | None], float] = {}
    raw_values: dict[tuple[str, str, int | None], list[tuple[float, bool]]] = {}
    for profile in PROFILE_ORDER:
        for method, buffer_size in VARIANT_ORDER:
            key = (profile, method, buffer_size)
            values = [_display_wall_clock_s(row) for row in grouped[key]]
            raw_values[key] = values
            if profile == "none":
                none_baselines[(method, buffer_size)] = statistics.fmean(value for value, _ in values)

    aggregates: list[Aggregate] = []
    for profile in PROFILE_ORDER:
        for method, buffer_size in VARIANT_ORDER:
            key = (profile, method, buffer_size)
            values = raw_values[key]
            wall_values = [value / 60.0 for value, _ in values]
            reached = sum(not censored for _, censored in values)
            mean = statistics.fmean(wall_values)
            std = statistics.stdev(wall_values) if len(wall_values) > 1 else 0.0
            baseline = none_baselines[(method, buffer_size)] / 60.0
            aggregates.append(
                Aggregate(
                    profile=profile,
                    method=method,
                    buffer_size=buffer_size,
                    label=METHOD_LABELS[(method, buffer_size)],
                    seeds=len(values),
                    reached_seeds=reached,
                    censored=reached != len(values),
                    mean_wall_clock_min=mean,
                    std_wall_clock_min=std,
                    slowdown_vs_none=mean / baseline if baseline else float("nan"),
                )
            )
    return aggregates


def _write_summary(aggregates: list[Aggregate]) -> None:
    write_csv_plot(
        "network_stressor_profile_bars_summary.csv",
        SUMMARY_FIELDS,
        (
            [
                row.profile,
                row.method,
                row.buffer_size if row.buffer_size is not None else "",
                row.label,
                row.seeds,
                row.reached_seeds,
                row.censored,
                f"{row.mean_wall_clock_min:.3f}",
                f"{row.std_wall_clock_min:.3f}",
                f"{row.slowdown_vs_none:.3f}",
            ]
            for row in aggregates
        ),
    )
    write_json_plot(
        "network_stressor_profile_bars_summary.json",
        {
            "profiles": list(PROFILE_ORDER),
            "variants": [
                {
                    "method": method,
                    "buffer_size": buffer_size,
                    "label": METHOD_LABELS[(method, buffer_size)],
                }
                for method, buffer_size in VARIANT_ORDER
            ],
            "censored_definition": (
                "Bars are hatched when at least one seed did not reach the 60% target; "
                "that seed contributes its final observed wall-clock time."
            ),
            "delta_label_definition": (
                "Bar labels on stressed profiles show percentage change in mean wall-clock time "
                "relative to the same method under the none profile."
            ),
        },
    )


def _delta_label(slowdown_vs_none: float) -> str:
    delta_pct = (slowdown_vs_none - 1.0) * 100.0
    rounded = int(round(delta_pct))
    if rounded == 0:
        return r"$0\%$"
    sign = "+" if rounded > 0 else ""
    return rf"${sign}{rounded}\%$"


def _plot(aggregates: list[Aggregate]) -> None:
    apply_publication_style()
    colors = default_cycle_colors(len(VARIANT_ORDER))
    fig, ax = plt.subplots(figsize=(PUBLICATION_FIGURE_WIDTH, 5.8))

    by_key = {(row.profile, row.method, row.buffer_size): row for row in aggregates}
    x_positions = list(range(len(PROFILE_ORDER)))
    width = 0.12
    offsets = [(idx - (len(VARIANT_ORDER) - 1) / 2) * width for idx in range(len(VARIANT_ORDER))]

    for idx, (method, buffer_size) in enumerate(VARIANT_ORDER):
        means: list[float] = []
        stds: list[float] = []
        censored: list[bool] = []
        for profile in PROFILE_ORDER:
            row = by_key[(profile, method, buffer_size)]
            means.append(row.mean_wall_clock_min)
            stds.append(row.std_wall_clock_min)
            censored.append(row.censored)
        bars = ax.bar(
            [x + offsets[idx] for x in x_positions],
            means,
            width=width,
            yerr=stds,
            capsize=2.5,
            color=colors[idx],
            edgecolor="black",
            linewidth=0.45,
            label=METHOD_LABELS[(method, buffer_size)],
        )
        for bar, is_censored in zip(bars, censored, strict=True):
            if is_censored:
                bar.set_hatch("///")
        for profile, bar, mean in zip(PROFILE_ORDER, bars, means, strict=True):
            if profile == "none":
                continue
            row = by_key[(profile, method, buffer_size)]
            y = min(mean + 1.5, 86.0)
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                y,
                _delta_label(row.slowdown_vs_none),
                ha="center",
                va="bottom",
                rotation=90,
                fontsize=10,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.65, "pad": 0.3},
            )

    ax.set_ylabel("Wall-clock to 60\\% target (min)")
    ax.set_xlabel("Network profile")
    ax.set_xticks(x_positions)
    ax.set_xticklabels([PROFILE_LABELS[profile] for profile in PROFILE_ORDER])
    ax.set_ylim(0, 90)
    ax.set_axisbelow(True)

    handles, labels = ax.get_legend_handles_labels()
    handles.append(Patch(facecolor="white", edgecolor="black", hatch="///", label="censored seed"))
    labels.append("censored seed")
    ax.legend(
        handles,
        labels,
        ncol=4,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.22),
        frameon=True,
        columnspacing=1.0,
        handlelength=1.5,
    )

    fig.tight_layout(pad=0.3)
    save_figure_plot_with_writeup_pdf(fig, "network_stressor_profile_bars")
    plt.close(fig)


def main() -> None:
    aggregates = _aggregate(_read_rows())
    _write_summary(aggregates)
    _plot(aggregates)
    print("Wrote network_stressor_profile_bars outputs")


if __name__ == "__main__":
    main()
