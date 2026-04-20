#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import wandb

from common import TMP_DIR, save_figure_dual, write_csv_dual, write_json_dual

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
TASK = "california_housing_mlp"
TMPDIR = TMP_DIR / "wandb_california_local_submodel"

RUNS = (
    ("jdjkltsl", "HeteroFL", "iid", 1337),
    ("qxlnfxpu", "FedRolex", "iid", 1337),
    ("dj71fc89", "FIARSE", "iid", 1337),
    ("5trnnxj2", "HeteroFL", "noniid", 1337),
    ("tsh2vjv1", "FedRolex", "noniid", 1337),
    ("2iu154j5", "FIARSE", "noniid", 1337),
)

RATE_ORDER = (0.125, 0.25, 0.5, 1.0)
RATE_LABELS = {
    0.125: "1/8",
    0.25: "1/4",
    0.5: "1/2",
    1.0: "1",
}
RATE_COLORS = {
    0.125: "#d62728",
    0.25: "#2ca02c",
    0.5: "#ff7f0e",
    1.0: "#1f77b4",
}
METHOD_ORDER = ("HeteroFL", "FedRolex", "FIARSE")
REGIME_ORDER = ("iid", "noniid")
REGIME_TITLES = {
    "iid": "IID",
    "noniid": "Non-IID",
}
DISPLAY_Y_LO = -0.2
DISPLAY_Y_HI = 0.82


@dataclass(frozen=True)
class Row:
    run_id: str
    method: str
    regime: str
    seed: int
    node_id: int
    device_type: str
    model_rate: float
    client_model_rate: float
    eval_r2: float
    num_examples: int


def _download_rows(api: wandb.Api, run_id: str, method: str, regime: str, seed: int) -> list[Row]:
    run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
    outdir = TMPDIR / run_id
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[Row] = []
    for remote in run.files():
        if "media/table/submodel/local_client_table" not in remote.name:
            continue
        local = remote.download(root=str(outdir), replace=True)
        payload = json.loads(local.read())
        columns = payload["columns"]
        idx = {name: columns.index(name) for name in columns}
        for raw in payload["data"]:
            rows.append(
                Row(
                    run_id=run_id,
                    method=method,
                    regime=regime,
                    seed=seed,
                    node_id=int(raw[idx["node_id"]]),
                    device_type=str(raw[idx["device_type"]]),
                    model_rate=float(raw[idx["model_rate"]]),
                    client_model_rate=float(raw[idx["client_model_rate"]]),
                    eval_r2=float(raw[idx.get("eval_r2", idx.get("eval_score", idx["eval_acc"]))]),
                    num_examples=int(raw[idx.get("num_examples", -1)]) if "num_examples" in idx else 0,
                )
            )
    return rows


def _rate_token(rate: float) -> str:
    return RATE_LABELS[float(rate)]


def main() -> None:
    api = wandb.Api(timeout=30)
    all_rows: list[Row] = []
    per_run_coverage: list[dict[str, object]] = []

    for run_id, method, regime, seed in RUNS:
        rows = _download_rows(api, run_id, method, regime, seed)
        all_rows.extend(rows)
        per_run_coverage.append(
            {
                "run_id": run_id,
                "method": method,
                "regime": regime,
                "seed": seed,
                "rows": len(rows),
                "model_rates": sorted({row.model_rate for row in rows}),
                "client_model_rates": sorted({row.client_model_rate for row in rows}),
            }
        )

    write_csv_dual(
        "compute_main_california_local_submodel_distributions_raw.csv",
        [
            "run_id",
            "method",
            "regime",
            "seed",
            "node_id",
            "device_type",
            "model_rate",
            "client_model_rate",
            "eval_r2",
            "num_examples",
        ],
        (
            [
                row.run_id,
                row.method,
                row.regime,
                row.seed,
                row.node_id,
                row.device_type,
                row.model_rate,
                row.client_model_rate,
                row.eval_r2,
                row.num_examples,
            ]
            for row in all_rows
        ),
    )

    write_json_dual(
        "compute_main_california_local_submodel_distributions_coverage.json",
        {
            "task": TASK,
            "coverage_fraction_overall": {
                "with_table_runs": len(per_run_coverage),
                "total_completed_heterogeneous_runs": 18,
            },
            "coverage_note": "Usable local-client tables exist for exactly one seed (1337) in each method x regime branch.",
            "runs": per_run_coverage,
        },
    )

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 3, figsize=(13.0, 7.4), sharex=True, sharey=True)

    for row_idx, regime in enumerate(REGIME_ORDER):
        for col_idx, method in enumerate(METHOD_ORDER):
            ax = axes[row_idx, col_idx]
            subset = [row for row in all_rows if row.regime == regime and row.method == method]
            grouped = [[row.eval_r2 for row in subset if abs(row.model_rate - rate) < 1e-9] for rate in RATE_ORDER]
            positions = np.arange(1, len(RATE_ORDER) + 1)
            bp = ax.boxplot(
                grouped,
                positions=positions,
                widths=0.56,
                patch_artist=True,
                showfliers=False,
                medianprops={"color": "#222222", "linewidth": 1.4},
                whiskerprops={"color": "#444444", "linewidth": 1.0},
                capprops={"color": "#444444", "linewidth": 1.0},
                boxprops={"linewidth": 1.0, "edgecolor": "#444444"},
            )
            for patch, rate in zip(bp["boxes"], RATE_ORDER, strict=True):
                patch.set_facecolor(RATE_COLORS[rate])
                patch.set_alpha(0.35)

            for pos, rate in zip(positions, RATE_ORDER, strict=True):
                vals = [row.eval_r2 for row in subset if abs(row.model_rate - rate) < 1e-9]
                node_ids = [row.node_id for row in subset if abs(row.model_rate - rate) < 1e-9]
                if not vals:
                    continue
                rng = np.random.default_rng(1000 + row_idx * 100 + col_idx * 10 + int(rate * 1000))
                jitter = rng.uniform(-0.12, 0.12, size=len(vals))
                ax.scatter(
                    np.full(len(vals), pos) + jitter,
                    vals,
                    s=24,
                    c=RATE_COLORS[rate],
                    alpha=0.8,
                    edgecolors="white",
                    linewidths=0.4,
                    zorder=3,
                )
                assert len(node_ids) == len(vals)

                clipped = [value for value in vals if value < DISPLAY_Y_LO]
                if clipped:
                    min_clipped = min(clipped)
                    ax.scatter(
                        [pos],
                        [DISPLAY_Y_LO],
                        marker="v",
                        s=42,
                        c=RATE_COLORS[rate],
                        edgecolors="black",
                        linewidths=0.5,
                        zorder=4,
                        clip_on=False,
                    )
                    ax.annotate(
                        f"min={min_clipped:.2f}\n$n$={len(clipped)}",
                        xy=(pos, DISPLAY_Y_LO),
                        xytext=(4, 6),
                        textcoords="offset points",
                        ha="left",
                        va="bottom",
                        fontsize=8,
                        color="#333333",
                        clip_on=False,
                    )

            if row_idx == 0:
                ax.set_title(method, fontsize=14)
            if col_idx == 0:
                ax.set_ylabel(f"{REGIME_TITLES[regime]}\nLocal $R^2$", fontsize=12)
            ax.set_xticks(positions)
            ax.set_xticklabels([RATE_LABELS[rate] for rate in RATE_ORDER], fontsize=11)
            ax.set_ylim(DISPLAY_Y_LO, DISPLAY_Y_HI)
            ax.axhline(0.0, color="#888888", linewidth=0.9, linestyle="--", alpha=0.8)

    for ax in axes[-1, :]:
        ax.set_xlabel("Extracted submodel rate", fontsize=12)

    handles = [
        plt.Line2D(
            [0],
            [0],
            marker="s",
            linestyle="",
            markerfacecolor=RATE_COLORS[rate],
            markeredgecolor="none",
            markersize=10,
            alpha=0.7,
            label=f"rate={RATE_LABELS[rate]}",
        )
        for rate in (1.0, 0.5, 0.25, 0.125)
    ]
    fig.legend(handles=handles, loc="upper center", ncol=4, frameon=True, bbox_to_anchor=(0.5, 1.02), fontsize=12)
    fig.tight_layout(rect=(0.02, 0.06, 1, 0.94))
    outputs = save_figure_dual(fig, "compute_main_california_local_submodel_distributions")

    left_pdf, right_pdf = outputs["pdf"]
    left_png, right_png = outputs["png"]
    print(
        json.dumps(
            {
                "rows": len(all_rows),
                "plot_output": {"pdf": str(left_pdf), "png": str(left_png)},
                "writeup_output": {"pdf": str(right_pdf), "png": str(right_png)},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
