from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import matplotlib.pyplot as plt
import scienceplots  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
PLOT_DIR = ROOT / 'plot'
PLOT_OUTPUT_DIR = PLOT_DIR / 'output'
WRITEUP_GENERATED_DIR = ROOT / 'writeup' / 'figures' / 'generated'
TMP_DIR = ROOT / 'tmp'
PUBLICATION_FIGURE_WIDTH = 13.0
DEFAULT_PLOT_CACHE_HOURS = float(os.environ.get('FEDCTL_PLOT_CACHE_HOURS', '168'))

PUBLICATION_FONT_SIZES = {
    'font.size': 17,
    'axes.titlesize': 19,
    'axes.labelsize': 19,
    'xtick.labelsize': 15,
    'ytick.labelsize': 15,
    'legend.fontsize': 16,
    'figure.titlesize': 19,
}

PUBLICATION_FONT_FAMILY = {
    'text.usetex': True,
    'font.family': 'serif',
    'font.serif': ['Latin Modern Roman', 'Computer Modern Roman', 'CMU Serif', 'DejaVu Serif'],
    'mathtext.fontset': 'cm',
    'text.latex.preamble': r'\usepackage[T1]{fontenc}\usepackage{lmodern}',
}


def ensure_output_dirs() -> None:
    PLOT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WRITEUP_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)


def force_refresh_requested() -> bool:
    return os.environ.get('FEDCTL_PLOT_REFRESH', '').strip().lower() in {'1', 'true', 'yes'}


def cache_is_fresh(path: Path, *, max_age_hours: float | None = None) -> bool:
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    return age_hours <= (DEFAULT_PLOT_CACHE_HOURS if max_age_hours is None else max_age_hours)


def apply_publication_style() -> None:
    plt.style.use(['science', 'grid'])
    plt.rcParams.update(PUBLICATION_FONT_SIZES)
    plt.rcParams.update(PUBLICATION_FONT_FAMILY)


def dual_output_paths(filename: str) -> tuple[Path, Path]:
    ensure_output_dirs()
    return PLOT_OUTPUT_DIR / filename, WRITEUP_GENERATED_DIR / filename


def plot_output_path(filename: str) -> Path:
    ensure_output_dirs()
    return PLOT_OUTPUT_DIR / filename


def writeup_generated_path(filename: str) -> Path:
    ensure_output_dirs()
    return WRITEUP_GENERATED_DIR / filename


def write_json_dual(filename: str, payload: Mapping[str, object]) -> tuple[Path, Path]:
    left, right = dual_output_paths(filename)
    text = json.dumps(payload, indent=2)
    left.write_text(text)
    right.write_text(text)
    return left, right


def write_csv_dual(filename: str, fieldnames: Sequence[str], rows: Iterable[Sequence[object]]) -> tuple[Path, Path]:
    left, right = dual_output_paths(filename)
    for path in (left, right):
        with path.open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(fieldnames)
            for row in rows:
                writer.writerow(row)
    return left, right


def write_json_plot(filename: str, payload: Mapping[str, object]) -> Path:
    path = plot_output_path(filename)
    path.write_text(json.dumps(payload, indent=2))
    return path


def write_csv_plot(filename: str, fieldnames: Sequence[str], rows: Iterable[Sequence[object]]) -> Path:
    path = plot_output_path(filename)
    with path.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for row in rows:
            writer.writerow(row)
    return path


def save_figure_dual(fig, stem: str, *, dpi: int = 220, bbox_inches: str = 'tight') -> dict[str, tuple[Path, Path]]:
    pdf_left, pdf_right = dual_output_paths(f'{stem}.pdf')
    png_left, png_right = dual_output_paths(f'{stem}.png')
    for path in (pdf_left, pdf_right):
        fig.savefig(path, bbox_inches=bbox_inches)
    for path in (png_left, png_right):
        fig.savefig(path, dpi=dpi, bbox_inches=bbox_inches)
    return {'pdf': (pdf_left, pdf_right), 'png': (png_left, png_right)}


def save_figure_plot_with_writeup_pdf(
    fig,
    stem: str,
    *,
    dpi: int = 220,
    bbox_inches: str = 'tight',
) -> dict[str, Path | tuple[Path, Path]]:
    pdf_plot = plot_output_path(f'{stem}.pdf')
    pdf_writeup = writeup_generated_path(f'{stem}.pdf')
    png_plot = plot_output_path(f'{stem}.png')
    for path in (pdf_plot, pdf_writeup):
        fig.savefig(path, bbox_inches=bbox_inches)
    fig.savefig(png_plot, dpi=dpi, bbox_inches=bbox_inches)
    return {
        'pdf': (pdf_plot, pdf_writeup),
        'png': png_plot,
    }
