#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
    save_figure_plot_with_writeup_pdf,
    write_csv_plot,
    write_json_plot,
)

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
STEM = "network_device_correlated"

RUN_SPECS = {
    ("fedavg", 1337): "x855vst0",
    ("fedbuff", 1337): "4pwdz3n5",
    ("fedstaleweight", 1337): "otboqbw9",
    ("fedavg", 1338): "wuufqbcy",
    ("fedbuff", 1338): "vi55i8zz",
    ("fedstaleweight", 1338): "ykl56p5a",
    ("fedavg", 1339): "1ey5gjrc",
    ("fedbuff", 1339): "p90mzxul",
    ("fedstaleweight", 1339): "wpinnavy",
}
METHOD_LABELS = {
    "fedavg": "FedAvg",
    "fedbuff": "FedBuff",
    "fedstaleweight": "FedStaleWeight",
}
METHOD_ORDER = ("fedavg", "fedbuff", "fedstaleweight")
ASYNC_METHODS = ("fedbuff", "fedstaleweight")
POPULATION_RPI4_SHARE = 5 / 15
ROLLING_WINDOW = 10


@dataclass(frozen=True)
class SummaryRow:
    method: str
    seed: int
    run_id: str
    client_trips: int
    wall_clock_s: float
    final_acc: float
    rpi4_group_acc: float | None
    rpi5_group_acc: float | None
    rpi4_update_share: float | None
    rpi4_weight_share: float | None
    rpi4_staleness: float | None
    rpi5_staleness: float | None
    updates_per_second: float


@dataclass(frozen=True)
class CurveRow:
    method: str
    seed: int
    wall_clock_s: float
    acc: float


@dataclass(frozen=True)
class ShareRow:
    method: str
    seed: int
    server_step: int
    update_share: float
    weight_share: float


def _summary_value(summary: dict[str, object], key: str) -> float | None:
    value = summary.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _summary_path() -> Path:
    return plot_output_path(f"{STEM}_summary.csv")


def _curve_path() -> Path:
    return plot_output_path(f"{STEM}_accuracy.csv")


def _share_path() -> Path:
    return plot_output_path(f"{STEM}_shares.csv")


def _load_cache() -> tuple[list[SummaryRow], list[CurveRow], list[ShareRow]]:
    paths = (_summary_path(), _curve_path(), _share_path())
    if force_refresh_requested() or any(not cache_is_fresh(path) for path in paths):
        return [], [], []

    summaries: list[SummaryRow] = []
    with _summary_path().open(newline="") as f:
        for row in csv.DictReader(f):
            summaries.append(
                SummaryRow(
                    method=row["method"],
                    seed=int(row["seed"]),
                    run_id=row["run_id"],
                    client_trips=int(row["client_trips"]),
                    wall_clock_s=float(row["wall_clock_s"]),
                    final_acc=float(row["final_acc"]),
                    rpi4_group_acc=float(row["rpi4_group_acc"]) if row["rpi4_group_acc"] else None,
                    rpi5_group_acc=float(row["rpi5_group_acc"]) if row["rpi5_group_acc"] else None,
                    rpi4_update_share=float(row["rpi4_update_share"]) if row["rpi4_update_share"] else None,
                    rpi4_weight_share=float(row["rpi4_weight_share"]) if row["rpi4_weight_share"] else None,
                    rpi4_staleness=float(row["rpi4_staleness"]) if row["rpi4_staleness"] else None,
                    rpi5_staleness=float(row["rpi5_staleness"]) if row["rpi5_staleness"] else None,
                    updates_per_second=float(row["updates_per_second"]),
                )
            )

    curves = [
        CurveRow(row["method"], int(row["seed"]), float(row["wall_clock_s"]), float(row["accuracy"]))
        for row in csv.DictReader(_curve_path().open())
    ]
    shares = [
        ShareRow(
            row["method"],
            int(row["seed"]),
            int(row["server_step"]),
            float(row["rpi4_update_share"]),
            float(row["rpi4_weight_share"]),
        )
        for row in csv.DictReader(_share_path().open())
    ]
    return summaries, curves, shares


def _fetch() -> tuple[list[SummaryRow], list[CurveRow], list[ShareRow]]:
    api = wandb.Api(timeout=60)
    summaries: list[SummaryRow] = []
    curves: list[CurveRow] = []
    shares_by_key: dict[tuple[str, int, int], ShareRow] = {}

    for (method, seed), run_id in RUN_SPECS.items():
        run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        if run.state != "finished":
            raise RuntimeError(f"Expected finished run for {method} seed {seed}, got {run.state}: {run_id}")

        summary = dict(run.summary)
        weight_rpi4 = _summary_value(summary, "fairness/run_weight_total_rpi4")
        weight_rpi5 = _summary_value(summary, "fairness/run_weight_total_rpi5")
        rpi4_weight_share = None
        if weight_rpi4 is not None and weight_rpi5 is not None and weight_rpi4 + weight_rpi5 > 0:
            rpi4_weight_share = weight_rpi4 / (weight_rpi4 + weight_rpi5)

        client_trips = int(_summary_value(summary, "target/client_trip_budget") or 0)
        wall_clock_s = float(_summary_value(summary, "runtime/total_server_s") or _summary_value(summary, "_runtime") or 0.0)
        final_acc = float(_summary_value(summary, "final/eval_server/eval-acc") or 0.0)

        for row in run.scan_history(page_size=1000):
            wall_clock = row.get("_runtime")
            if not isinstance(wall_clock, (int, float)):
                continue

            trip_acc = row.get("eval_server_trip/eval-acc")
            trip = row.get("client_trip")
            if isinstance(trip_acc, (int, float)) and isinstance(trip, (int, float)):
                curves.append(CurveRow(method=method, seed=seed, wall_clock_s=float(wall_clock), acc=float(trip_acc)))

            server_acc = row.get("eval_server/eval-acc")
            if isinstance(server_acc, (int, float)):
                curves.append(CurveRow(method=method, seed=seed, wall_clock_s=float(wall_clock), acc=float(server_acc)))

        progress_updates_per_second = _summary_value(summary, "progress/updates_per_second")
        updates_per_second = (
            progress_updates_per_second
            if progress_updates_per_second is not None
            else (client_trips / wall_clock_s if wall_clock_s > 0 else 0.0)
        )

        summaries.append(
            SummaryRow(
                method=method,
                seed=seed,
                run_id=run_id,
                client_trips=client_trips,
                wall_clock_s=wall_clock_s,
                final_acc=final_acc,
                rpi4_group_acc=_summary_value(summary, "final/eval_server_group/rpi4-held/eval-acc"),
                rpi5_group_acc=_summary_value(summary, "final/eval_server_group/rpi5-held/eval-acc"),
                rpi4_update_share=_summary_value(summary, "fairness/run_update_share_rpi4"),
                rpi4_weight_share=rpi4_weight_share,
                rpi4_staleness=_summary_value(summary, "fairness/run_avg_staleness_rpi4"),
                rpi5_staleness=_summary_value(summary, "fairness/run_avg_staleness_rpi5"),
                updates_per_second=float(updates_per_second),
            )
        )

        if method in ASYNC_METHODS:
            share_keys = [
                "server_round",
                "round_device/fairness/device_update_share_rpi4",
                "round_device/fairness/device_weight_share_rpi4",
            ]
            for row in run.scan_history(keys=share_keys, page_size=1000):
                step = row.get("server_round")
                update_share = row.get("round_device/fairness/device_update_share_rpi4")
                weight_share = row.get("round_device/fairness/device_weight_share_rpi4")
                if (
                    isinstance(step, (int, float))
                    and isinstance(update_share, (int, float))
                    and isinstance(weight_share, (int, float))
                ):
                    server_step = int(step)
                    shares_by_key[(method, seed, server_step)] = ShareRow(
                        method=method,
                        seed=seed,
                        server_step=server_step,
                        update_share=float(update_share),
                        weight_share=float(weight_share),
                    )

    shares = sorted(shares_by_key.values(), key=lambda row: (row.method, row.seed, row.server_step))
    return summaries, curves, shares


def _write_cache(summaries: list[SummaryRow], curves: list[CurveRow], shares: list[ShareRow]) -> None:
    write_csv_plot(
        f"{STEM}_summary.csv",
        [
            "method",
            "seed",
            "run_id",
            "client_trips",
            "wall_clock_s",
            "final_acc",
            "rpi4_group_acc",
            "rpi5_group_acc",
            "rpi4_update_share",
            "rpi4_weight_share",
            "rpi4_staleness",
            "rpi5_staleness",
            "updates_per_second",
        ],
        (
            [
                row.method,
                row.seed,
                row.run_id,
                row.client_trips,
                row.wall_clock_s,
                row.final_acc,
                row.rpi4_group_acc if row.rpi4_group_acc is not None else "",
                row.rpi5_group_acc if row.rpi5_group_acc is not None else "",
                row.rpi4_update_share if row.rpi4_update_share is not None else "",
                row.rpi4_weight_share if row.rpi4_weight_share is not None else "",
                row.rpi4_staleness if row.rpi4_staleness is not None else "",
                row.rpi5_staleness if row.rpi5_staleness is not None else "",
                row.updates_per_second,
            ]
            for row in summaries
        ),
    )
    write_csv_plot(
        f"{STEM}_accuracy.csv",
        ["method", "seed", "wall_clock_s", "accuracy"],
        ([row.method, row.seed, row.wall_clock_s, row.acc] for row in curves),
    )
    write_csv_plot(
        f"{STEM}_shares.csv",
        ["method", "seed", "server_step", "rpi4_update_share", "rpi4_weight_share"],
        ([row.method, row.seed, row.server_step, row.update_share, row.weight_share] for row in shares),
    )


def _nonnull(values: list[float | None]) -> list[float]:
    return [float(value) for value in values if value is not None]


def _mean_std(values: list[float]) -> tuple[float, float, int]:
    if not values:
        return float("nan"), float("nan"), 0
    arr = np.array(values, dtype=float)
    std = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    return float(np.mean(arr)), std, int(arr.size)


def _fmt_mean_pm(values: list[float], *, decimals: int, scale: float = 1.0) -> str:
    mean, std, n = _mean_std([value * scale for value in values])
    if n == 0:
        return "--"
    if decimals == 0:
        return rf"{mean:.0f} $\pm$ {std:.0f}"
    return rf"{mean:.{decimals}f} $\pm$ {std:.{decimals}f}"


def _fmt_fixed_or_pm(values: list[float], *, decimals: int = 0) -> str:
    rounded = [round(value, decimals) for value in values]
    if len(set(rounded)) == 1:
        return f"{rounded[0]:.{decimals}f}" if decimals else f"{int(rounded[0])}"
    return _fmt_mean_pm(values, decimals=decimals)


def _rolling_mean(values: np.ndarray, *, window: int = ROLLING_WINDOW) -> np.ndarray:
    if values.size == 0:
        return values
    result = np.empty_like(values, dtype=float)
    for idx in range(values.size):
        start = max(0, idx - window + 1)
        result[idx] = float(np.mean(values[start : idx + 1]))
    return result


def _write_table_rows(summaries: list[SummaryRow]) -> Path:
    by_method: dict[str, list[SummaryRow]] = defaultdict(list)
    for row in summaries:
        by_method[row.method].append(row)

    lines: list[str] = []
    summary_payload: dict[str, object] = {}
    for method in METHOD_ORDER:
        rows = sorted(by_method[method], key=lambda row: row.seed)
        row_payload = {
            "seeds": [row.seed for row in rows],
            "run_ids": [row.run_id for row in rows],
        }
        if method == "fedavg":
            update_share = r"33.3$^\dagger$"
            weight_share = r"33.3$^\dagger$"
            rpi4_stale = r"0$^\dagger$"
            rpi5_stale = r"0$^\dagger$"
        else:
            update_share = _fmt_mean_pm(_nonnull([row.rpi4_update_share for row in rows]), decimals=1, scale=100)
            weight_share = _fmt_mean_pm(_nonnull([row.rpi4_weight_share for row in rows]), decimals=1, scale=100)
            rpi4_stale = _fmt_mean_pm(_nonnull([row.rpi4_staleness for row in rows]), decimals=2)
            rpi5_stale = _fmt_mean_pm(_nonnull([row.rpi5_staleness for row in rows]), decimals=2)

        class_rpi4 = _fmt_mean_pm(_nonnull([row.rpi4_group_acc for row in rows]), decimals=1, scale=100)
        class_rpi5 = _fmt_mean_pm(_nonnull([row.rpi5_group_acc for row in rows]), decimals=1, scale=100)
        row_payload["class_group_seed_count"] = {
            "rpi4_held": len(_nonnull([row.rpi4_group_acc for row in rows])),
            "rpi5_held": len(_nonnull([row.rpi5_group_acc for row in rows])),
        }
        summary_payload[method] = row_payload

        lines.append(
            " & ".join(
                [
                    rf"\texttt{{{METHOD_LABELS[method]}}}",
                    _fmt_fixed_or_pm([float(row.client_trips) for row in rows]),
                    _fmt_mean_pm([row.wall_clock_s for row in rows], decimals=0),
                    _fmt_mean_pm([row.final_acc for row in rows], decimals=1, scale=100),
                    class_rpi4,
                    class_rpi5,
                    update_share,
                    weight_share,
                    rpi4_stale,
                    rpi5_stale,
                    _fmt_mean_pm([row.updates_per_second for row in rows], decimals=3),
                ]
            )
            + r" \\"
        )

    path = plot_output_path(f"{STEM}_table_rows.tex")
    path.write_text("\n".join(lines) + "\n")
    write_json_plot(f"{STEM}_summary.json", {"methods": summary_payload})
    return path


def _aggregate_curves(method: str, curves: list[CurveRow]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    by_seed: dict[int, list[CurveRow]] = defaultdict(list)
    for row in curves:
        if row.method == method:
            by_seed[row.seed].append(row)

    cleaned: list[tuple[np.ndarray, np.ndarray]] = []
    for seed_rows in by_seed.values():
        ordered = sorted(seed_rows, key=lambda row: row.wall_clock_s)
        xs: list[float] = []
        ys: list[float] = []
        last_x: float | None = None
        for row in ordered:
            if last_x is not None and row.wall_clock_s <= last_x:
                continue
            xs.append(row.wall_clock_s / 60.0)
            ys.append(row.acc)
            last_x = row.wall_clock_s
        if len(xs) >= 2:
            cleaned.append((np.array(xs), np.array(ys)))

    if not cleaned:
        return np.array([]), np.array([]), np.array([])

    start = min(float(xs[0]) for xs, _ys in cleaned)
    end = max(float(xs[-1]) for xs, _ys in cleaned)
    grid = np.linspace(start, end, 240)
    interpolated = np.vstack([np.interp(grid, xs, ys, left=ys[0], right=ys[-1]) for xs, ys in cleaned])
    return grid, np.mean(interpolated, axis=0), np.std(interpolated, axis=0, ddof=1)


def _aggregate_shares(
    method: str,
    shares: list[ShareRow],
    selector: Callable[[ShareRow], float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[tuple[np.ndarray, np.ndarray]]]:
    by_seed: dict[int, list[ShareRow]] = defaultdict(list)
    for row in shares:
        if row.method == method:
            by_seed[row.seed].append(row)

    per_seed: list[tuple[np.ndarray, np.ndarray]] = []
    values_by_step: dict[int, list[float]] = defaultdict(list)
    for seed_rows in by_seed.values():
        ordered = sorted(seed_rows, key=lambda row: row.server_step)
        xs = np.array([row.server_step for row in ordered], dtype=int)
        ys = _rolling_mean(np.array([selector(row) for row in ordered], dtype=float))
        per_seed.append((xs, ys))
        for x, y in zip(xs, ys, strict=True):
            values_by_step[int(x)].append(float(y))

    steps = np.array(sorted(values_by_step), dtype=int)
    means = np.array([np.mean(values_by_step[int(step)]) for step in steps], dtype=float)
    stds = np.array(
        [
            np.std(values_by_step[int(step)], ddof=1) if len(values_by_step[int(step)]) > 1 else 0.0
            for step in steps
        ],
        dtype=float,
    )
    return steps, means, stds, per_seed


def main() -> None:
    summaries, curves, shares = _load_cache()
    if not summaries:
        summaries, curves, shares = _fetch()
        _write_cache(summaries, curves, shares)

    apply_publication_style()
    colors = dict(zip(METHOD_ORDER, default_cycle_colors(len(METHOD_ORDER)), strict=True))

    fig, axes = plt.subplots(1, 3, figsize=(PUBLICATION_FIGURE_WIDTH, 3.8))
    ax_acc, ax_weight, ax_update = axes
    legend_handles = []

    for method in METHOD_ORDER:
        grid, mean, std = _aggregate_curves(method, curves)
        if grid.size == 0:
            continue
        (line,) = ax_acc.plot(
            grid,
            mean,
            label=METHOD_LABELS[method],
            color=colors[method],
            linewidth=2.4,
        )
        ax_acc.fill_between(grid, mean - std, mean + std, color=colors[method], alpha=0.16, linewidth=0)
        legend_handles.append(line)

    for ax, selector, ylabel in (
        (ax_weight, lambda row: row.weight_share, r"\texttt{rpi4} weight share"),
        (ax_update, lambda row: row.update_share, r"\texttt{rpi4} update share"),
    ):
        ax.axhline(
            POPULATION_RPI4_SHARE,
            color=colors["fedavg"],
            linewidth=2.4,
            linestyle="-",
        )

        for method in ASYNC_METHODS:
            xs, means, stds, per_seed = _aggregate_shares(method, shares, selector)
            for seed_xs, seed_ys in per_seed:
                ax.plot(seed_xs, seed_ys, color=colors[method], linewidth=0.8, alpha=0.20)
            ax.plot(xs, means, color=colors[method], linewidth=2.5)
            ax.fill_between(xs, means - stds, means + stds, color=colors[method], alpha=0.16, linewidth=0)

        ax.set_xlabel("Server step")
        ax.set_ylabel(ylabel)
        ax.set_ylim(-0.02, 0.55)
        ax.yaxis.set_major_formatter(lambda value, _pos: f"{100 * value:.0f}\\%")

    ax_acc.set_xlabel("Wall clock time (min)")
    ax_acc.set_ylabel("Accuracy")
    ax_acc.set_ylim(0.08, 0.5)
    ax_acc.yaxis.set_major_formatter(lambda value, _pos: f"{value:.2f}")

    fig.legend(
        handles=legend_handles,
        labels=[METHOD_LABELS[method] for method in METHOD_ORDER],
        loc="upper center",
        ncol=3,
        frameon=True,
        bbox_to_anchor=(0.5, 1.05),
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))

    outputs = save_figure_plot_with_writeup_pdf(fig, STEM)
    table_path = _write_table_rows(summaries)
    print(
        json.dumps(
            {
                "plot_output": {"pdf": str(outputs["pdf"][0])},
                "writeup_output": {"pdf": str(outputs["pdf"][1])},
                "table_rows": str(table_path),
                "runs": {
                    f"{method}_s{seed}": run_id
                    for (method, seed), run_id in sorted(RUN_SPECS.items(), key=lambda item: (item[0][0], item[0][1]))
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()