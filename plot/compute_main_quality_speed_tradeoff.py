#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from common import (
    PUBLICATION_FIGURE_WIDTH,
    apply_publication_style,
    default_cycle_colors,
    plot_output_path,
    save_figure_plot_with_writeup_pdf,
    write_csv_plot,
    write_json_plot,
)

STEM = 'compute_main_quality_speed_tradeoff'


@dataclass(frozen=True)
class Metric:
    score: float
    score_std: float
    runtime: float
    runtime_std: float


@dataclass(frozen=True)
class TaskSpec:
    key: str
    title: str
    ylabel: str
    xlim: tuple[float, float]
    ylim: tuple[float, float]
    accuracy_delta_pp: bool


TASKS = (
    TaskSpec(
        key='california_housing',
        title='California Housing',
        ylabel=r'$\Delta$ Global $R^2$ vs \texttt{FedAvg}',
        xlim=(0.94, 1.03),
        ylim=(-0.13, 0.01),
        accuracy_delta_pp=False,
    ),
    TaskSpec(
        key='cifar10',
        title='CIFAR-10',
        ylabel=r'$\Delta$ Global accuracy vs \texttt{FedAvg} (pp)',
        xlim=(0.75, 2.50),
        ylim=(-12.5, 0.5),
        accuracy_delta_pp=True,
    ),
)

METHOD_COLOR_ORDER = ('fedavg', 'heterofl', 'fedrolex', 'fiarse')
HETEROGENEOUS_METHODS = ('heterofl', 'fedrolex', 'fiarse')
METHOD_LABELS = {
    'fedavg': r'\texttt{FedAvg}',
    'heterofl': r'\texttt{HeteroFL}',
    'fedrolex': r'\texttt{FedRolex}',
    'fiarse': r'\texttt{FIARSE}',
}
REGIMES = ('iid', 'noniid')
REGIME_LABELS = {'iid': 'IID', 'noniid': 'non-IID'}
REGIME_MARKERS = {'iid': 'o', 'noniid': 's'}

DATA: dict[str, dict[str, dict[str, Metric]]] = {
    'california_housing': {
        'iid': {
            'fedavg': Metric(0.724, 0.001, 25.5, 0.6),
            'heterofl': Metric(0.693, 0.006, 25.6, 1.8),
            'fedrolex': Metric(0.679, 0.003, 26.1, 1.5),
            'fiarse': Metric(0.710, 0.002, 26.2, 1.4),
        },
        'noniid': {
            'fedavg': Metric(0.711, 0.007, 37.0, 0.7),
            'heterofl': Metric(0.689, 0.005, 38.5, 3.0),
            'fedrolex': Metric(0.597, 0.017, 37.4, 2.1),
            'fiarse': Metric(0.614, 0.070, 37.9, 1.1),
        },
    },
    'cifar10': {
        'iid': {
            'fedavg': Metric(79.38, 0.25, 260.0, 55.6),
            'heterofl': Metric(74.95, 0.41, 111.1, 11.7),
            'fedrolex': Metric(74.24, 0.27, 120.4, 8.7),
            'fiarse': Metric(76.43, 2.08, 208.6, 81.5),
        },
        'noniid': {
            'fedavg': Metric(75.93, 0.67, 305.9, 24.7),
            'heterofl': Metric(64.86, 2.03, 148.6, 10.1),
            'fedrolex': Metric(65.72, 0.66, 135.0, 10.8),
            'fiarse': Metric(70.55, 1.75, 356.2, 30.3),
        },
    },
}


def _speedup_and_error(baseline: Metric, method: Metric) -> tuple[float, float]:
    speedup = baseline.runtime / method.runtime
    rel_var = 0.0
    if baseline.runtime > 0:
        rel_var += (baseline.runtime_std / baseline.runtime) ** 2
    if method.runtime > 0:
        rel_var += (method.runtime_std / method.runtime) ** 2
    return speedup, speedup * math.sqrt(rel_var)


def _quality_delta_and_error(baseline: Metric, method: Metric) -> tuple[float, float]:
    delta = method.score - baseline.score
    err = math.sqrt(method.score_std**2 + baseline.score_std**2)
    return delta, err


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for task in TASKS:
        for regime in REGIMES:
            baseline = DATA[task.key][regime]['fedavg']
            for method_name in HETEROGENEOUS_METHODS:
                method = DATA[task.key][regime][method_name]
                speedup, speedup_err = _speedup_and_error(baseline, method)
                delta, delta_err = _quality_delta_and_error(baseline, method)
                rows.append(
                    {
                        'task': task.key,
                        'regime': regime,
                        'method': method_name,
                        'speedup_vs_fedavg': speedup,
                        'speedup_err': speedup_err,
                        'quality_delta': delta,
                        'quality_delta_err': delta_err,
                        'baseline_score': baseline.score,
                        'method_score': method.score,
                        'baseline_runtime_min': baseline.runtime,
                        'method_runtime_min': method.runtime,
                    }
                )
    return rows


def _write_outputs(rows: list[dict[str, object]]) -> None:
    fieldnames = (
        'task',
        'regime',
        'method',
        'speedup_vs_fedavg',
        'speedup_err',
        'quality_delta',
        'quality_delta_err',
        'baseline_score',
        'method_score',
        'baseline_runtime_min',
        'method_runtime_min',
    )
    write_csv_plot(f'{STEM}_points.csv', fieldnames, [[row[name] for name in fieldnames] for row in rows])
    write_json_plot(
        f'{STEM}_summary.json',
        {
            'description': 'Heterogeneous-method global quality delta and runtime speedup relative to matching FedAvg baselines; FedAvg is plotted as the shared (1x, 0) reference point in each task panel.',
            'rows': rows,
        },
    )


def main() -> None:
    rows = _rows()
    _write_outputs(rows)

    apply_publication_style()
    colors = dict(zip(METHOD_COLOR_ORDER, default_cycle_colors(len(METHOD_COLOR_ORDER)), strict=True))

    fig, axes = plt.subplots(1, 2, figsize=(PUBLICATION_FIGURE_WIDTH, 4.8), sharex=False, sharey=False)

    for ax, task in zip(axes, TASKS, strict=True):
        task_rows = [row for row in rows if row['task'] == task.key]
        ax.axvline(1.0, linestyle=':', linewidth=1.2, color='#444444', zorder=1)
        ax.axhline(0.0, linestyle=':', linewidth=1.2, color='#444444', zorder=1)
        ax.scatter(
            1.0,
            0.0,
            marker='D',
            color=colors['fedavg'],
            s=96,
            edgecolors='black',
            linewidths=0.7,
            alpha=0.98,
            zorder=4,
        )
        for row in task_rows:
            method = str(row['method'])
            regime = str(row['regime'])
            ax.scatter(
                float(row['speedup_vs_fedavg']),
                float(row['quality_delta']),
                marker=REGIME_MARKERS[regime],
                color=colors[method],
                s=78,
                edgecolors='black',
                linewidths=0.6,
                alpha=0.95,
                zorder=3,
            )
        ax.set_title(task.title)
        ax.set_xlim(*task.xlim)
        ax.set_ylim(*task.ylim)
        ax.set_xlabel(r'Speedup over \texttt{FedAvg} ($\times$)')
        ax.set_ylabel(task.ylabel)

    method_handles = [
        Line2D(
            [0],
            [0],
            marker='D' if method == 'fedavg' else 'o',
            linestyle='',
            markersize=8,
            markerfacecolor=colors[method],
            markeredgecolor='black',
            markeredgewidth=0.6,
            label=METHOD_LABELS[method],
        )
        for method in METHOD_COLOR_ORDER
    ]
    regime_handles = [
        Line2D(
            [0],
            [0],
            marker=REGIME_MARKERS[regime],
            linestyle='',
            markersize=8,
            markerfacecolor='white',
            markeredgecolor='black',
            markeredgewidth=0.9,
            label=REGIME_LABELS[regime],
        )
        for regime in REGIMES
    ]
    fig.legend(
        handles=method_handles + regime_handles,
        loc='upper center',
        ncol=6,
        bbox_to_anchor=(0.5, 1.05),
        frameon=True,
        columnspacing=0.75,
        handletextpad=0.30,
    )

    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.92), w_pad=2.0)
    outputs = save_figure_plot_with_writeup_pdf(fig, STEM)
    plt.close(fig)
    print(
        json.dumps(
            {
                'plot_output': {
                    'pdf': str(outputs['pdf'][0]),
                    'csv': str(plot_output_path(f'{STEM}_points.csv')),
                    'summary': str(plot_output_path(f'{STEM}_summary.json')),
                },
                'writeup_output': {'pdf': str(outputs['pdf'][1])},
            },
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
