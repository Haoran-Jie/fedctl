#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import plistlib
import sys
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")

if sys.platform == "darwin":
    _plistlib_loads = plistlib.loads

    def _safe_plistlib_loads(data, *args, **kwargs):
        payload = _plistlib_loads(data, *args, **kwargs)
        if (
            isinstance(payload, list)
            and len(payload) == 1
            and isinstance(payload[0], dict)
            and "_items" not in payload[0]
        ):
            return [{"_items": []}]
        return payload

    plistlib.loads = _safe_plistlib_loads

import matplotlib.pyplot as plt
import numpy as np
import wandb

from common import (
    PUBLICATION_FIGURE_WIDTH,
    TMP_DIR,
    apply_publication_style,
    cache_is_fresh,
    default_cycle_colors,
    force_refresh_requested,
    plot_output_path,
    save_figure_dual,
    write_csv_dual,
    write_json_dual,
)

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
TASK = "cifar10_cnn"
SEED = 1340
TMPDIR = TMP_DIR / "wandb_cifar10_seed1340_local_submodel"

METHOD_ORDER = ("heterofl", "fedrolex", "fiarse")
METHOD_TITLES = {
    "heterofl": "HeteroFL",
    "fedrolex": "FedRolex",
    "fiarse": "FIARSE",
}
REGIME_ORDER = ("iid", "noniid")
REGIME_TITLES = {
    "iid": "IID",
    "noniid": "Non-IID",
}

RATE_ORDER = (1.0, 0.5, 0.25, 0.125)
RATE_STACK_ORDER = (0.125, 0.25, 0.5, 1.0)
RATE_LABELS = {
    1.0: "1",
    0.5: "1/2",
    0.25: "1/4",
    0.125: "1/8",
}

DISPLAY_X_LO = 0.35
DISPLAY_X_HI = 0.90
DISPLAY_BIN_COUNT = 20

RUNS = (
    ("iid", "heterofl", "skhigedl"),
    ("iid", "fedrolex", "i99r0zn3"),
    ("iid", "fiarse", "y51ex006"),
    ("noniid", "heterofl", "prg5qiyn"),
    ("noniid", "fedrolex", "bj8ua1of"),
    ("noniid", "fiarse", None),
)


@dataclass(frozen=True)
class RunSpec:
    regime: str
    method: str
    run_id: str | None


@dataclass(frozen=True)
class Row:
    run_id: str
    regime: str
    method: str
    seed: int
    model_rate: float
    eval_acc: float
    device_type: str
    client_model_rate: float
    node_id: int


def run_specs() -> list[RunSpec]:
    return [RunSpec(regime=regime, method=method, run_id=run_id) for regime, method, run_id in RUNS]


def fetch_table_rows(api: wandb.Api, spec: RunSpec) -> list[Row]:
    if spec.run_id is None:
        return []

    run = api.run(f"{ENTITY}/{PROJECT}/{spec.run_id}")
    outdir = TMPDIR / spec.run_id
    outdir.mkdir(parents=True, exist_ok=True)

    rows: list[Row] = []
    for remote in run.files():
        if "media/table/submodel/local_client_table" not in remote.name:
            continue

        remote.download(root=str(outdir), replace=True)
        path = outdir / remote.name
        payload = json.loads(path.read_text())

        columns = payload["columns"]
        idx = {name: columns.index(name) for name in columns}

        eval_key = "eval_acc" if "eval_acc" in idx else "eval_score"

        for raw in payload["data"]:
            rows.append(
                Row(
                    run_id=spec.run_id,
                    regime=spec.regime,
                    method=spec.method,
                    seed=SEED,
                    model_rate=float(raw[idx["model_rate"]]),
                    eval_acc=float(raw[idx[eval_key]]),
                    device_type=str(raw[idx["device_type"]]),
                    client_model_rate=float(raw[idx["client_model_rate"]]),
                    node_id=int(raw[idx["node_id"]]),
                )
            )
    return rows


def load_cached_rows() -> list[Row]:
    cache_path = plot_output_path("compute_main_cifar10_seed1340_local_submodel_grid_raw.csv")
    if not cache_is_fresh(cache_path) or force_refresh_requested():
        return []

    rows: list[Row] = []
    with cache_path.open(newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(
                Row(
                    run_id=raw["run_id"],
                    regime=raw["regime"],
                    method=raw["method"],
                    seed=int(raw["seed"]),
                    model_rate=float(raw["model_rate"]),
                    eval_acc=float(raw["eval_acc"]),
                    device_type=raw["device_type"],
                    client_model_rate=float(raw["client_model_rate"]),
                    node_id=int(raw["node_id"]),
                )
            )
    return rows


def panel_rows(rows: list[Row], *, regime: str, method: str) -> list[Row]:
    return [row for row in rows if row.regime == regime and row.method == method]


def main() -> None:
    all_rows = load_cached_rows()

    if not all_rows:
        try:
            api = wandb.Api(timeout=30)
            for spec in run_specs():
                if spec.run_id is not None:
                    all_rows.extend(fetch_table_rows(api, spec))
        except Exception:
            cache_path = plot_output_path("compute_main_cifar10_seed1340_local_submodel_grid_raw.csv")
            if not cache_path.exists():
                raise
            all_rows = load_cached_rows()

    coverage: list[dict[str, object]] = []
    for spec in run_specs():
        rows = [row for row in all_rows if spec.run_id is not None and row.run_id == spec.run_id]
        coverage.append(
            {
                "run_id": spec.run_id,
                "regime": spec.regime,
                "method": spec.method,
                "rows": len(rows),
                "rates": sorted({row.model_rate for row in rows}),
            }
        )

    write_csv_dual(
        "compute_main_cifar10_seed1340_local_submodel_grid_raw.csv",
        [
            "run_id",
            "regime",
            "method",
            "seed",
            "model_rate",
            "eval_acc",
            "device_type",
            "client_model_rate",
            "node_id",
        ],
        (
            [
                row.run_id,
                row.regime,
                row.method,
                row.seed,
                row.model_rate,
                row.eval_acc,
                row.device_type,
                row.client_model_rate,
                row.node_id,
            ]
            for row in all_rows
        ),
    )

    write_json_dual(
        "compute_main_cifar10_seed1340_local_submodel_grid_coverage.json",
        {
            "task": TASK,
            "seed": SEED,
            "runs": coverage,
            "rate_labels": {str(k): v for k, v in RATE_LABELS.items()},
        },
    )

    apply_publication_style()
    cycle_colors = default_cycle_colors(len(RATE_STACK_ORDER))
    rate_colors = {rate: color for rate, color in zip(RATE_STACK_ORDER, cycle_colors, strict=True)}

    fig, axes = plt.subplots(
        2,
        3,
        figsize=(PUBLICATION_FIGURE_WIDTH, 7.5),
        sharex=True,
        sharey=True,
    )
    bins = np.linspace(DISPLAY_X_LO, DISPLAY_X_HI, DISPLAY_BIN_COUNT)

    for row_idx, regime in enumerate(REGIME_ORDER):
        for col_idx, method in enumerate(METHOD_ORDER):
            ax = axes[row_idx, col_idx]
            subset = panel_rows(all_rows, regime=regime, method=method)

            stacked_vals = [
                [row.eval_acc for row in subset if abs(row.model_rate - rate) < 1e-9]
                for rate in RATE_STACK_ORDER
            ]

            ax.hist(
                stacked_vals,
                bins=bins,
                stacked=True,
                color=[rate_colors[rate] for rate in RATE_STACK_ORDER],
                label=[RATE_LABELS[rate] for rate in RATE_STACK_ORDER],
                edgecolor="white",
                linewidth=0.8,
                alpha=0.75,
            )

            if row_idx == 0:
                ax.set_title(METHOD_TITLES[method])
            ax.set_xlim(DISPLAY_X_LO, DISPLAY_X_HI)
            ax.set_ylim(bottom=0)
            ax.set_xticks([0.4, 0.5, 0.6, 0.7, 0.8, 0.9])

            fig.supxlabel("Local Test Accuracy", y=0.06)
            fig.supylabel("Number of Clients")

            ax.text(
                0.03,
                0.95,
                REGIME_TITLES[regime],
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

    handles = [
        plt.Line2D(
            [0],
            [0],
            marker="s",
            linestyle="",
            markerfacecolor=rate_colors[rate],
            markeredgecolor="none",
            markersize=10,
            alpha=0.9,
            label=f"rate={RATE_LABELS[rate]}",
        )
        for rate in RATE_ORDER
    ]
    labels = [f"rate={RATE_LABELS[rate]}" for rate in RATE_ORDER]

    fig.legend(handles, labels, loc="upper center", ncol=4, frameon=True, bbox_to_anchor=(0.5, 1))
    fig.tight_layout(rect=(0.0, 0.02, 1.0, 0.94))

    outputs = save_figure_dual(fig, "compute_main_cifar10_seed1340_local_submodel_grid")
    left_pdf, right_pdf = outputs["pdf"]
    print(
        json.dumps(
            {
                "rows": len(all_rows),
                "plot_output": {
                    "pdf": str(left_pdf),
                },
                "writeup_output": {
                    "pdf": str(right_pdf),
                },
                "coverage": coverage,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
