#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import wandb

from common import (
    PUBLICATION_FIGURE_WIDTH,
    TMP_DIR,
    apply_publication_style,
    cache_is_fresh,
    force_refresh_requested,
    plot_output_path,
    save_figure_dual,
    write_csv_dual,
    write_json_dual,
)

ENTITY = 'samueljie1-the-university-of-cambridge'
PROJECT = 'fedctl'
TASK = 'cifar10_cnn'
TMPDIR = TMP_DIR / 'wandb_submodel_hist'
METHOD = 'fedrolex'
REGIME = 'iid'
RUNS = (
    ('3moap2c9', 1338),
    ('ppd09xho', 1339),
)
RATE_LABELS = {
    1.0: 'size=1',
    0.5: 'size=1/2',
    0.25: 'size=1/4',
    0.125: 'size=1/8',
}
RATE_ORDER = (1.0, 0.5, 0.25, 0.125)
RATE_STACK_ORDER = (0.125, 0.25, 0.5, 1.0)
RATE_COLORS = {
    1.0: '#1f77b4',
    0.5: '#ff7f0e',
    0.25: '#2ca02c',
    0.125: '#d62728',
}


@dataclass(frozen=True)
class Row:
    run_id: str
    seed: int
    model_rate: float
    eval_acc: float
    device_type: str
    client_model_rate: float
    node_id: int


def fetch_table_rows(api: wandb.Api, run_id: str, seed: int) -> list[Row]:
    run = api.run(f'{ENTITY}/{PROJECT}/{run_id}')
    outdir = TMPDIR / run_id
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[Row] = []
    for remote in run.files():
        if 'media/table/submodel/local_client_table' not in remote.name:
            continue
        remote.download(root=str(outdir), replace=True)
        path = outdir / remote.name
        payload = json.loads(path.read_text())
        columns = payload['columns']
        idx = {name: columns.index(name) for name in columns}
        for raw in payload['data']:
            rows.append(
                Row(
                    run_id=run_id,
                    seed=seed,
                    model_rate=float(raw[idx['model_rate']]),
                    eval_acc=float(raw[idx['eval_acc']]),
                    device_type=str(raw[idx['device_type']]),
                    client_model_rate=float(raw[idx['client_model_rate']]),
                    node_id=int(raw[idx['node_id']]),
                )
            )
    return rows


def load_cached_rows() -> list[Row]:
    cache_path = plot_output_path('compute_main_fedrolex_local_submodel_hist_raw.csv')
    if not cache_is_fresh(cache_path) or force_refresh_requested():
        return []
    rows: list[Row] = []
    with cache_path.open(newline='') as f:
        for raw in csv.DictReader(f):
            rows.append(
                Row(
                    run_id=raw['run_id'],
                    seed=int(raw['seed']),
                    model_rate=float(raw['model_rate']),
                    eval_acc=float(raw['eval_acc']),
                    device_type=raw['device_type'],
                    client_model_rate=float(raw['client_model_rate']),
                    node_id=int(raw['node_id']),
                )
            )
    return rows


def main() -> None:
    all_rows = load_cached_rows()
    if not all_rows:
        try:
            api = wandb.Api(timeout=30)
            for run_id, seed in RUNS:
                rows = fetch_table_rows(api, run_id, seed)
                all_rows.extend(rows)
        except Exception:
            cache_path = plot_output_path('compute_main_fedrolex_local_submodel_hist_raw.csv')
            if not cache_path.exists():
                raise
            with cache_path.open(newline='') as f:
                for raw in csv.DictReader(f):
                    all_rows.append(
                        Row(
                            run_id=raw['run_id'],
                            seed=int(raw['seed']),
                            model_rate=float(raw['model_rate']),
                            eval_acc=float(raw['eval_acc']),
                            device_type=raw['device_type'],
                            client_model_rate=float(raw['client_model_rate']),
                            node_id=int(raw['node_id']),
                        )
                    )

    coverage: list[dict[str, object]] = []
    for run_id, seed in RUNS:
        rows = [row for row in all_rows if row.run_id == run_id]
        coverage.append({'run_id': run_id, 'seed': seed, 'rows': len(rows), 'rates': sorted({row.model_rate for row in rows})})

    write_csv_dual(
        'compute_main_fedrolex_local_submodel_hist_raw.csv',
        ['run_id', 'seed', 'model_rate', 'eval_acc', 'device_type', 'client_model_rate', 'node_id'],
        ([r.run_id, r.seed, r.model_rate, r.eval_acc, r.device_type, r.client_model_rate, r.node_id] for r in all_rows),
    )
    write_json_dual(
        'compute_main_local_submodel_hist_coverage.json',
        {
            'task': TASK,
            'method': METHOD,
            'regime': REGIME,
            'runs': coverage,
            'rate_labels': {str(k): v for k, v in RATE_LABELS.items()},
        },
    )

    apply_publication_style()
    fig, axes = plt.subplots(1, len(RUNS), figsize=(PUBLICATION_FIGURE_WIDTH, 4.6), sharex=True, sharey=True)
    if len(RUNS) == 1:
        axes = [axes]

    bins = np.linspace(0.40, 0.85, 12)
    for ax, (run_id, seed) in zip(axes, RUNS, strict=True):
        run_rows = [row for row in all_rows if row.run_id == run_id]
        stacked_vals = [
            [row.eval_acc for row in run_rows if abs(row.model_rate - rate) < 1e-9]
            for rate in RATE_STACK_ORDER
        ]
        ax.hist(
            stacked_vals,
            bins=bins,
            stacked=True,
            color=[RATE_COLORS[rate] for rate in RATE_STACK_ORDER],
            label=[RATE_LABELS[rate] for rate in RATE_STACK_ORDER],
            edgecolor='white',
            linewidth=0.8,
            alpha=0.9,
        )
        ax.set_title(f'FedRolex IID (seed {seed})')
        ax.set_xlabel('Local Test Accuracy')
        ax.set_xlim(0.40, 0.85)
        ax.set_ylim(bottom=0)
    axes[0].set_ylabel('Number of Clients')

    handles, labels = axes[0].get_legend_handles_labels()
    order = [labels.index(RATE_LABELS[rate]) for rate in RATE_ORDER]
    handles = [handles[i] for i in order]
    labels = [labels[i] for i in order]
    fig.legend(handles, labels, loc='upper center', ncol=4, frameon=True, bbox_to_anchor=(0.5, 1.05))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    outputs = save_figure_dual(fig, 'compute_main_fedrolex_local_submodel_hist')

    left_pdf, right_pdf = outputs['pdf']
    left_png, right_png = outputs['png']
    print(json.dumps({
        'plot_output': {
            'pdf': str(left_pdf),
            'png': str(left_png),
        },
        'writeup_output': {
            'pdf': str(right_pdf),
            'png': str(right_png),
        },
        'rows': len(all_rows),
    }, indent=2))


if __name__ == '__main__':
    main()
