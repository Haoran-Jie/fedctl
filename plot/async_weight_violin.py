#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np

from async_violin_data import MAX_STEPS, UpdateRow, expected_seed_coverage, load_or_fetch_rows
from common import (
    PUBLICATION_FIGURE_WIDTH,
    apply_publication_style_no_grid,
    default_cycle_colors,
    save_figure_plot_with_writeup_pdf,
    write_json_plot,
    darken_color_hls,
)

STEM = 'network_async_weight_violin'


@dataclass(frozen=True)
class PanelSpec:
    method: str
    buffer_size: int
    title: str


PANELS = (
    PanelSpec('fedbuff', 5, r'FedBuff ($K=5$)'),
    PanelSpec('fedbuff', 10, r'FedBuff ($K=10$)'),
    PanelSpec('fedstaleweight', 5, r'FedStaleWeight ($K=5$)'),
    PanelSpec('fedstaleweight', 10, r'FedStaleWeight ($K=10$)'),
)
DEVICE_ORDER = ('rpi4', 'rpi5')
DEVICE_TITLES = {'rpi4': 'rpi4 updates', 'rpi5': 'rpi5 updates'}
CATEGORY_POSITIONS = tuple(reversed(range(len(PANELS))))


def _style_violin(parts: dict[str, object], *, facecolor: str) -> None:
    for body in parts['bodies']:
        facecolor = darken_color_hls(facecolor, factor=0.9)
        body.set_facecolor(facecolor)
        body.set_edgecolor('#303030')
        body.set_alpha(0.85)
        body.set_linewidth(1.2)


def _draw_inner_summary(ax, values: list[float], y: float) -> None:
    q1, median, q3 = np.percentile(values, [25, 50, 75])
    ax.plot([q1, q3], [y, y], color='#333333', linewidth=2.8, solid_capstyle='round', zorder=4)
    ax.plot([median], [y], marker='o', markersize=3.2, color='white', markeredgecolor='#333333', markeredgewidth=0.6, zorder=5)


def _panel_rows(rows: list[UpdateRow], *, device: str, spec: PanelSpec) -> list[UpdateRow]:
    return [
        row
        for row in rows
        if row.device_type == device and row.method == spec.method and row.buffer_size == spec.buffer_size
    ]


def _legend_handles(category_colors: list[str]) -> list[Patch]:
    return [
        Patch(facecolor=darken_color_hls(color, factor=0.9), edgecolor='#303030', linewidth=1.0, label=spec.title)
        for color, spec in zip(category_colors, PANELS, strict=True)
    ]


def main() -> None:
    rows = load_or_fetch_rows()
    apply_publication_style_no_grid()
    category_colors = default_cycle_colors(len(PANELS))

    fig, axes = plt.subplots(1, 2, figsize=(PUBLICATION_FIGURE_WIDTH, 5), sharex=True, sharey=True)
    summary: dict[str, dict[str, object]] = {}

    for ax, device in zip(axes, DEVICE_ORDER, strict=True):
        summary[device] = {}
        for position, color, spec in zip(CATEGORY_POSITIONS, category_colors, PANELS, strict=True):
            panel_rows = _panel_rows(rows, device=device, spec=spec)
            values = [row.applied_weight for row in panel_rows]
            if not values:
                continue
            parts = ax.violinplot(
                [values],
                positions=[position],
                vert=False,
                widths=0.62,
                showmeans=False,
                showmedians=False,
                showextrema=False,
                bw_method=0.35,
            )
            _style_violin(parts, facecolor=color)
            _draw_inner_summary(ax, values, position)
            summary_key = f'{spec.method}_k{spec.buffer_size}'
            summary[device][summary_key] = {
                'n': len(values),
                'seeds': sorted({row.seed for row in panel_rows}),
                'run_ids': sorted({row.run_id for row in panel_rows}),
                'mean': float(np.mean(values)),
                'median': float(np.median(values)),
                'q1': float(np.percentile(values, 25)),
                'q3': float(np.percentile(values, 75)),
                'min': float(np.min(values)),
                'max': float(np.max(values)),
            }

        ax.set_title(DEVICE_TITLES[device])
        ax.set_yticks(list(CATEGORY_POSITIONS))
        ax.set_yticklabels([])
        ax.tick_params(axis='y', length=0)
        ax.set_xlim(-0.005, 0.40)
        ax.set_xticks([0, 0.1, 0.2, 0.3, 0.4])
        ax.xaxis.set_major_formatter(lambda value, _pos: f'{100 * value:.0f}\\%')
        ax.grid(axis='x', color='#d0d0d0', linewidth=0.8)
        ax.grid(axis='y', visible=False)

    fig.legend(
        handles=_legend_handles(category_colors),
        loc='upper center',
        ncol=4,
        bbox_to_anchor=(0.5, 1.0),
        frameon=True,
        columnspacing=1.5,
        handlelength=1.3,
    )
    fig.supxlabel('Aggregate weight', y=0.2)
    fig.tight_layout(rect=(0.02, 0.13, 1.0, 0.88), w_pad=1.8)
    outputs = save_figure_plot_with_writeup_pdf(fig, STEM)
    summary_path = write_json_plot(
        f'{STEM}_summary.json',
        {
            'max_steps': MAX_STEPS,
            'expected_seed_coverage': expected_seed_coverage(),
            'panels': summary,
        },
    )
    print(
        json.dumps(
            {
                'plot_output': {'pdf': str(outputs['pdf'][0]), 'summary': str(summary_path)},
                'writeup_output': {'pdf': str(outputs['pdf'][1])},
            },
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
