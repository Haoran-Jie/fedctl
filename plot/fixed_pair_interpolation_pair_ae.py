#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np
import wandb

from common import save_figure_dual, write_csv_dual

ENTITY = 'samueljie1-the-university-of-cambridge'
PROJECT = 'fedctl'
PAIR_TAG = 'pair_a_e'
METHODS = ('heterofl', 'fedrolex', 'fiarse')
PREFERRED_Y_KEYS = (
    'submodel/global/rate_1.0/eval-acc',
    'submodel/global/rate_1.0/eval-score',
    'final/eval_server/eval-acc',
    'final/eval_server/eval-score',
)
X_KEY = 'round_cost/avg_params'
COLORS = {
    'heterofl': '#1f77b4',
    'fedrolex': '#ff7f0e',
    'fiarse': '#2ca02c',
}
LABELS = {
    'heterofl': 'HeteroFL',
    'fedrolex': 'FedRolex',
    'fiarse': 'FIARSE',
}


@dataclass(frozen=True)
class Point:
    method: str
    seed: int
    mix: str
    avg_params: float
    score: float
    run_id: str


def _metric(summary: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = summary.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def main() -> None:
    api = wandb.Api(timeout=30)
    runs = api.runs(
        f'{ENTITY}/{PROJECT}',
        filters={
            '$and': [
                {'state': 'finished'},
                {'tags': {'$in': ['fixed_pair_interpolation']}},
                {'tags': {'$in': [PAIR_TAG]}},
            ]
        },
    )

    points: list[Point] = []
    missing: list[dict[str, object]] = []
    for run in runs:
        cfg = run.config
        method = cfg.get('method')
        if method not in METHODS:
            continue
        summary = dict(run.summary)
        x = summary.get(X_KEY)
        y = _metric(summary, PREFERRED_Y_KEYS)
        mix = cfg.get('heterofl-partition-rates', '')
        seed = int(cfg.get('seed', 0))
        if not isinstance(x, (int, float)) or y is None:
            missing.append({'run_id': run.id, 'method': method, 'seed': seed, 'mix': mix})
            continue
        points.append(Point(method=method, seed=seed, mix=str(mix), avg_params=float(x), score=y, run_id=run.id))

    raw_rows = [
        [p.method, p.seed, p.mix, p.avg_params, p.score, p.run_id]
        for p in sorted(points, key=lambda p: (p.method, p.avg_params, p.seed, p.mix))
    ]
    write_csv_dual(
        'fixed_pair_interpolation_pair_a_e_raw.csv',
        ['method', 'seed', 'mix', 'avg_params', 'score', 'run_id'],
        raw_rows,
    )

    grouped: dict[str, dict[float, list[float]]] = defaultdict(lambda: defaultdict(list))
    for p in points:
        grouped[p.method][p.avg_params].append(p.score)

    aggregated_rows: list[list[object]] = []
    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    for method in METHODS:
        series = sorted(grouped[method].items())
        if not series:
            continue
        xs = np.array([x for x, _ in series], dtype=float)
        means = np.array([np.mean(vals) for _, vals in series], dtype=float)
        stds = np.array([np.std(vals) for _, vals in series], dtype=float)
        ax.plot(xs, means, marker='o', linewidth=2.2, color=COLORS[method], label=LABELS[method])
        ax.fill_between(xs, means - stds, means + stds, color=COLORS[method], alpha=0.16)
        for x, vals, mean, std in zip(xs, (vals for _, vals in series), means, stds, strict=True):
            aggregated_rows.append([method, x, mean, std, len(vals)])

    write_csv_dual(
        'fixed_pair_interpolation_pair_a_e_aggregated.csv',
        ['method', 'avg_params', 'mean_score', 'std_score', 'n_runs'],
        aggregated_rows,
    )

    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value / 1e5:g}"))
    ax.text(1.0, -0.095, '1e5', transform=ax.transAxes, ha='right', va='top')

    ax.set_xlabel('Average Client-Side Model Parameters')
    ax.set_ylabel('Final Global Test Accuracy')
    ax.legend(frameon=True)
    ax.set_title('Fixed-Pair Interpolation (pair a-e)')
    fig.tight_layout()
    outputs = save_figure_dual(fig, 'fixed_pair_interpolation_pair_a_e_methods')

    print(json.dumps({
        'plot_output': {
            'pdf': str(outputs['pdf'][0]),
            'png': str(outputs['png'][0]),
        },
        'writeup_output': {
            'pdf': str(outputs['pdf'][1]),
            'png': str(outputs['png'][1]),
        },
        'points': len(points),
        'missing': missing,
    }, indent=2))


if __name__ == '__main__':
    main()
