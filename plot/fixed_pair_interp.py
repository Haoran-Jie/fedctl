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
    default_cycle_colors,
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
TRAIN_TIME_KEY = 'round_client_stats/train_duration_mean_s'
LABELS = {
    'heterofl': 'HeteroFL',
    'fedrolex': 'FedRolex',
    'fiarse': 'FIARSE',
}
MARKERS = {
    'heterofl': 'o',
    'fedrolex': 's',
    'fiarse': '^',
}
LINESTYLES = {
    'heterofl': '-',
    'fedrolex': '--',
    'fiarse': '-.',
}


@dataclass(frozen=True)
class Point:
    pair: str
    method: str
    seed: int
    mix: str
    avg_params: float
    train_duration_s: float
    score: float
    run_id: str
    created_at: str = ''


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
        reader = csv.DictReader(f)
        if 'train_duration_s' not in (reader.fieldnames or ()):
            return []
        has_created_at = 'created_at' in (reader.fieldnames or ())
        for raw in reader:
            points.append(
                Point(
                    pair=raw['pair'],
                    method=raw['method'],
                    seed=int(raw['seed']),
                    mix=raw['mix'],
                    avg_params=float(raw['avg_params']),
                    train_duration_s=float(raw['train_duration_s']),
                    score=float(raw['score']),
                    run_id=raw['run_id'],
                    created_at=raw['created_at'] if has_created_at else '',
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
                train_duration_s = summary.get(TRAIN_TIME_KEY)
                y = _metric(summary, PREFERRED_Y_KEYS)
                mix = cfg.get('heterofl-partition-rates', '')
                seed = int(cfg.get('seed', 0))
                if not isinstance(x, (int, float)) or not isinstance(train_duration_s, (int, float)) or y is None:
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
                        train_duration_s=float(train_duration_s),
                        score=y,
                        run_id=run.id,
                        created_at=str(getattr(run, 'created_at', '') or ''),
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
                            train_duration_s=float(raw['train_duration_s']),
                            score=float(raw['score']),
                            run_id=raw['run_id'],
                            created_at=raw.get('created_at', ''),
                        )
                    )

    deduped: dict[tuple[str, str, int, str], Point] = {}
    for point in points:
        key = (point.pair, point.method, point.seed, point.mix)
        existing = deduped.get(key)
        if existing is None or point.created_at > existing.created_at:
            deduped[key] = point
    points = list(deduped.values())

    raw_rows = [
        [p.pair, p.method, p.seed, p.mix, p.avg_params, p.train_duration_s, p.score, p.run_id, p.created_at]
        for p in sorted(points, key=lambda p: (p.pair, p.method, p.avg_params, p.seed, p.mix))
    ]
    write_csv_plot(
        'fixed_pair_interpolation_triptych_raw.csv',
        ['pair', 'method', 'seed', 'mix', 'avg_params', 'train_duration_s', 'score', 'run_id', 'created_at'],
        raw_rows,
    )

    grouped: dict[str, dict[str, dict[float, list[Point]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for p in points:
        grouped[p.pair][p.method][p.avg_params].append(p)

    aggregated_rows: list[list[object]] = []
    apply_publication_style()
    method_colors = dict(zip(METHODS, default_cycle_colors(len(METHODS)), strict=True))
    legend_handles = []
    fig, axes = plt.subplots(
        2,
        3,
        figsize=(PUBLICATION_FIGURE_WIDTH, 7.2),
        sharex='col',
        sharey='row',
    )

    for col_idx, (pair_tag, pair_label) in enumerate(PAIR_ORDER):
        ax_params = axes[0, col_idx]
        ax_time = axes[1, col_idx]
        for method in METHODS:
            series = sorted(grouped[pair_tag][method].items())
            if not series:
                continue
            xs = np.array([x for x, _ in series], dtype=float)
            means = np.array([np.mean([p.score for p in vals]) for _, vals in series], dtype=float)
            stds = np.array([np.std([p.score for p in vals]) for _, vals in series], dtype=float)
            train_means = np.array([np.mean([p.train_duration_s for p in vals]) for _, vals in series], dtype=float)
            counts = np.array([len(vals) for _, vals in series], dtype=int)
            ax_params.plot(
                xs,
                means,
                marker=MARKERS[method],
                linestyle='-',
                linewidth=2.2,
                color=method_colors[method],
                label=LABELS[method],
            )
            time_line, = ax_time.plot(
                xs,
                train_means,
                marker=MARKERS[method],
                linestyle=LINESTYLES[method],
                linewidth=2.2,
                color=method_colors[method],
                label=LABELS[method],
            )
            if col_idx == 0:
                legend_handles.append(time_line)
            if np.any(counts > 1):
                ax_params.fill_between(xs, means - stds, means + stds, color=method_colors[method], alpha=0.16)
                train_stds = np.array([np.std([p.train_duration_s for p in vals]) for _, vals in series], dtype=float)
                ax_time.fill_between(xs, train_means - train_stds, train_means + train_stds, color=method_colors[method], alpha=0.16)
            for x, train_duration_mean, mean, std, count in zip(xs, train_means, means, stds, counts, strict=True):
                aggregated_rows.append([pair_tag, method, x, train_duration_mean, mean, std, count])

        ax_params.set_title(pair_label)
        x_scale = PAIR_X_SCALE[pair_tag]
        for ax in (ax_params, ax_time):
            ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _pos, scale=x_scale: f"{value / scale:g}"))
        ax_params.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.2f}"))
        ax_time.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.0f}"))
        ax_time.text(1.03, -0.05, f'1e{int(np.log10(x_scale))}', transform=ax_time.transAxes, ha='right', va='top')
        if col_idx == 0:
            ax_params.set_ylabel('Accuracy')
            ax_time.set_ylabel('Mean Client Train Time (s)')

    for ax in axes[1, :]:
        ax.set_xlabel('Average Model Parameters', labelpad=7)
    fig.legend(
        handles=legend_handles,
        labels=[LABELS[method] for method in METHODS],
        loc='upper center',
        ncol=len(METHODS),
        frameon=True,
        bbox_to_anchor=(0.5, 1.02),
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.subplots_adjust(bottom=0.12, hspace=0.30, wspace=0.20)

    write_csv_plot(
        'fixed_pair_interpolation_triptych_aggregated.csv',
        ['pair', 'method', 'avg_params', 'train_duration_mean_s', 'mean_score', 'std_score', 'n_runs'],
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
