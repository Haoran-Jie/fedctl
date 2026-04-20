from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
PLOT_DIR = ROOT / 'plot'
PLOT_OUTPUT_DIR = PLOT_DIR / 'output'
WRITEUP_GENERATED_DIR = ROOT / 'writeup' / 'figures' / 'generated'
TMP_DIR = ROOT / 'tmp'


def ensure_output_dirs() -> None:
    PLOT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WRITEUP_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)


def dual_output_paths(filename: str) -> tuple[Path, Path]:
    ensure_output_dirs()
    return PLOT_OUTPUT_DIR / filename, WRITEUP_GENERATED_DIR / filename


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


def save_figure_dual(fig, stem: str, *, dpi: int = 220, bbox_inches: str = 'tight') -> dict[str, tuple[Path, Path]]:
    pdf_left, pdf_right = dual_output_paths(f'{stem}.pdf')
    png_left, png_right = dual_output_paths(f'{stem}.png')
    for path in (pdf_left, pdf_right):
        fig.savefig(path, bbox_inches=bbox_inches)
    for path in (png_left, png_right):
        fig.savefig(path, dpi=dpi, bbox_inches=bbox_inches)
    return {'pdf': (pdf_left, pdf_right), 'png': (png_left, png_right)}
