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

from common import (
    PUBLICATION_FIGURE_WIDTH,
    apply_publication_style,
    cache_is_fresh,
    force_refresh_requested,
    plot_output_path,
    save_figure_plot_with_writeup_pdf,
    write_csv_plot,
    write_json_plot,
)

ENTITY = 'samueljie1-the-university-of-cambridge'
PROJECT = 'fedctl'
PAIR_ORDER = (
    ('pair_a_c', 'a-c'),
    ('pair_a_e', 'a-e'),
    ('pair_c_e', 'c-e'),
)
PAIR_X_SCALE = {
    'pair_a_c': 1e5,
    'pair_a_e': 1e5,
    'pair_c_e': 1e4,
}
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
    pair: str
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


def _pair_tag(tags: object) -> str | None:
    if not isinstance(tags, list):
        return None
    for pair_tag, _label in PAIR_ORDER:
        if pair_tag in tags:
            return pair_tag
    return None


def _load_cached_points() -> list[Point]:
    cache_path = plot_output_path('fixed_pair_interpolation_triptych_raw.csv')
    if not cache_is_fresh(cache_path) or force_refresh_requested():
        return []
    points: list[Point] = []
    with cache_path.open(newline='') as f:
        for raw in csv.DictReader(f):
            points.append(
                Point(
                    pair=raw['pair'],
                    method=raw['method'],
                    seed=int(raw['seed']),
                    mix=raw['mix'],
                    avg_params=float(raw['avg_params']),
                    score=float(raw['score']),
                    run_id=raw['run_id'],
                )
            )
    return points


def main() -> None:
    points = _load_cached_points()
    missing: list[dict[str, object]] = []
    if not points:
        try:
            api = wandb.Api(timeout=30)
            runs = api.runs(
                f'{ENTITY}/{PROJECT}',
                filters={
                    '$and': [
                        {'state': 'finished'},
                        {'tags': {'$in': ['fixed_pair_interpolation']}},
                        {'tags': {'$in': [pair_tag for pair_tag, _ in PAIR_ORDER]}},
                    ]
                },
            )

            for run in runs:
                cfg = run.config
                method = cfg.get('method')
                if method not in METHODS:
                    continue
                pair = _pair_tag(run.tags)
                if pair is None:
                    continue
                summary = dict(run.summary)
                x = summary.get(X_KEY)
                y = _metric(summary, PREFERRED_Y_KEYS)
                mix = cfg.get('heterofl-partition-rates', '')
                seed = int(cfg.get('seed', 0))
                if not isinstance(x, (int, float)) or y is None:
                    missing.append(
                        {
                            'pair': pair,
                            'run_id': run.id,
                            'method': method,
                            'seed': seed,
                            'mix': mix,
                        }
                    )
                    continue
                points.append(
                    Point(
                        pair=pair,
                        method=method,
                        seed=seed,
                        mix=str(mix),
                        avg_params=float(x),
                        score=y,
                        run_id=run.id,
                    )
                )
        except Exception:
            cache_path = plot_output_path('fixed_pair_interpolation_triptych_raw.csv')
            if not cache_path.exists():
                raise
            with cache_path.open(newline='') as f:
                for raw in csv.DictReader(f):
                    points.append(
                        Point(
                            pair=raw['pair'],
                            method=raw['method'],
                            seed=int(raw['seed']),
                            mix=raw['mix'],
                            avg_params=float(raw['avg_params']),
                            score=float(raw['score']),
                            run_id=raw['run_id'],
                        )
                    )

    raw_rows = [
        [p.pair, p.method, p.seed, p.mix, p.avg_params, p.score, p.run_id]
        for p in sorted(points, key=lambda p: (p.pair, p.method, p.avg_params, p.seed, p.mix))
    ]
    write_csv_plot(
        'fixed_pair_interpolation_triptych_raw.csv',
        ['pair', 'method', 'seed', 'mix', 'avg_params', 'score', 'run_id'],
        raw_rows,
    )

    grouped: dict[str, dict[str, dict[float, list[float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for p in points:
        grouped[p.pair][p.method][p.avg_params].append(p.score)

    aggregated_rows: list[list[object]] = []
    apply_publication_style()
    fig, axes = plt.subplots(1, 3, figsize=(PUBLICATION_FIGURE_WIDTH, 4.3), sharey=True)

    for ax, (pair_tag, pair_label) in zip(axes, PAIR_ORDER, strict=True):
        for method in METHODS:
            series = sorted(grouped[pair_tag][method].items())
            if not series:
                continue
            xs = np.array([x for x, _ in series], dtype=float)
            means = np.array([np.mean(vals) for _, vals in series], dtype=float)
            stds = np.array([np.std(vals) for _, vals in series], dtype=float)
            counts = np.array([len(vals) for _, vals in series], dtype=int)
            ax.plot(
                xs,
                means,
                marker='o',
                linewidth=2.2,
                color=COLORS[method],
                label=LABELS[method],
            )
            if np.any(counts > 1):
                ax.fill_between(xs, means - stds, means + stds, color=COLORS[method], alpha=0.16)
            for x, mean, std, count in zip(xs, means, stds, counts, strict=True):
                aggregated_rows.append([pair_tag, method, x, mean, std, count])

        ax.set_title(pair_label)
        x_scale = PAIR_X_SCALE[pair_tag]
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _pos, scale=x_scale: f"{value / scale:g}"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.2f}"))
        ax.text(1.0, -0.03, f'1e{int(np.log10(x_scale))}', transform=ax.transAxes, ha='right', va='top')
        if ax is axes[0]:
            ax.legend(frameon=True, loc='lower right')

    fig.supxlabel('Average Model Parameters')
    fig.supylabel('Accuracy')
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.18, wspace=0.20)

    write_csv_plot(
        'fixed_pair_interpolation_triptych_aggregated.csv',
        ['pair', 'method', 'avg_params', 'mean_score', 'std_score', 'n_runs'],
        aggregated_rows,
    )
    coverage = {
        'points': len(points),
        'points_by_pair': {
            pair_tag: sum(1 for p in points if p.pair == pair_tag)
            for pair_tag, _label in PAIR_ORDER
        },
        'missing': missing,
    }
    write_json_plot('fixed_pair_interpolation_triptych_coverage.json', coverage)
    outputs = save_figure_plot_with_writeup_pdf(fig, 'fixed_pair_interpolation_triptych_methods')

    print(
        json.dumps(
            {
                'plot_output': {
                    'pdf': str(outputs['pdf'][0]),
                    'png': str(outputs['png']),
                },
                'writeup_output': {
                    'pdf': str(outputs['pdf'][1]),
                },
                **coverage,
            },
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
