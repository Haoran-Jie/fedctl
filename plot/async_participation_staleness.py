#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import plistlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

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
    apply_publication_style_no_grid,
    cache_is_fresh,
    force_refresh_requested,
    plot_output_path,
    save_figure_plot_with_writeup_pdf,
    write_csv_plot,
    write_json_plot,
)

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
STEM = "network_async_participation_staleness"
TMPDIR = TMP_DIR / "wandb_network_async_participation_staleness"
MAX_STEPS = 60
DEVICE_SLOTS = {"rpi5": 10, "rpi4": 5}
STEP_TABLE_RE = re.compile(r"step_table_(\d+)_")


@dataclass(frozen=True)
class RunSpec:
    method: str
    buffer_size: int
    run_id: str
    source: str

    @property
    def title(self) -> str:
        method_title = "FedBuff" if self.method == "fedbuff" else "FedStaleWeight"
        return f"{method_title}, K={self.buffer_size}"


@dataclass(frozen=True)
class UpdateRow:
    run_id: str
    method: str
    buffer_size: int
    source: str
    server_step: int
    client_trips_total: int
    node_id: str
    device_type: str
    staleness: int


RUNS = (
    RunSpec("fedbuff", 5, "f8r1yqsh", "network_stressor_sweep"),
    RunSpec("fedbuff", 10, "j81afai0", "network_main"),
    RunSpec("fedstaleweight", 5, "qjnt77fk", "network_stressor_sweep"),
    RunSpec("fedstaleweight", 10, "wyc9rjxq", "network_main"),
)


def _table_sort_key(name: str) -> tuple[int, str]:
    match = STEP_TABLE_RE.search(name)
    return (int(match.group(1)) if match else 10**9, name)


def _column_index(columns: list[str]) -> dict[str, int]:
    return {str(name): idx for idx, name in enumerate(columns)}


def _node_sort_key(node: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", node)
    numeric = int(match.group(1)) if match else 10**9
    return (numeric, node)


def _parse_table_payload(payload_text: str, spec: RunSpec) -> list[UpdateRow]:
    payload = json.loads(payload_text)
    columns = payload["columns"]
    idx = _column_index(columns)
    required = {
        "server_step",
        "client_trips_total",
        "node_id",
        "device_type",
        "update_staleness_server_steps",
    }
    missing = sorted(required.difference(idx))
    if missing:
        raise RuntimeError(f"{spec.run_id}: missing client-update columns {missing}")

    rows: list[UpdateRow] = []
    for raw in payload["data"]:
        server_step = int(raw[idx["server_step"]])
        if server_step > MAX_STEPS:
            continue
        rows.append(
            UpdateRow(
                run_id=spec.run_id,
                method=spec.method,
                buffer_size=spec.buffer_size,
                source=spec.source,
                server_step=server_step,
                client_trips_total=int(raw[idx["client_trips_total"]]),
                node_id=str(raw[idx["node_id"]]),
                device_type=str(raw[idx["device_type"]]).lower(),
                staleness=int(raw[idx["update_staleness_server_steps"]]),
            )
        )
    return rows


def fetch_run_rows(api: wandb.Api, spec: RunSpec) -> list[UpdateRow]:
    run = api.run(f"{ENTITY}/{PROJECT}/{spec.run_id}")
    outdir = TMPDIR / spec.run_id
    outdir.mkdir(parents=True, exist_ok=True)

    rows: list[UpdateRow] = []
    seen: set[tuple[int, int, str]] = set()
    files = sorted(
        (remote for remote in run.files() if "media/table/client_update/step_table" in remote.name),
        key=lambda remote: _table_sort_key(remote.name),
    )
    if not files:
        raise RuntimeError(f"{spec.run_id}: no client_update/step_table files found")

    for remote in files:
        # The number in W&B's media filename is the run log step, not the
        # FedBuff server_step stored inside the table payload. Filter only
        # after parsing the table rows.
        local_path = outdir / remote.name
        if local_path.exists() and not force_refresh_requested():
            payload_text = local_path.read_text()
        else:
            local = remote.download(root=str(outdir), replace=True)
            payload_text = local.read()
        for row in _parse_table_payload(payload_text, spec):
            dedupe_key = (row.server_step, row.client_trips_total, row.node_id)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rows.append(row)
        covered_steps = {row.server_step for row in rows if 1 <= row.server_step <= MAX_STEPS}
        if len(covered_steps) >= MAX_STEPS:
            break
    return rows


def load_cached_rows() -> list[UpdateRow]:
    cache_path = plot_output_path(f"{STEM}_raw.csv")
    if force_refresh_requested() or not cache_is_fresh(cache_path):
        return []

    rows: list[UpdateRow] = []
    with cache_path.open(newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(
                UpdateRow(
                    run_id=raw["run_id"],
                    method=raw["method"],
                    buffer_size=int(raw["buffer_size"]),
                    source=raw["source"],
                    server_step=int(raw["server_step"]),
                    client_trips_total=int(raw["client_trips_total"]),
                    node_id=raw["node_id"],
                    device_type=raw["device_type"],
                    staleness=int(raw["staleness"]),
                )
            )
    run_ids = {spec.run_id for spec in RUNS}
    for run_id in run_ids:
        max_step = max((row.server_step for row in rows if row.run_id == run_id), default=0)
        if max_step < MAX_STEPS:
            return []
    return rows


def write_raw_rows(rows: list[UpdateRow]) -> Path:
    return write_csv_plot(
        f"{STEM}_raw.csv",
        [
            "run_id",
            "method",
            "buffer_size",
            "source",
            "server_step",
            "client_trips_total",
            "node_id",
            "device_type",
            "staleness",
        ],
        [
            [
                row.run_id,
                row.method,
                row.buffer_size,
                row.source,
                row.server_step,
                row.client_trips_total,
                row.node_id,
                row.device_type,
                row.staleness,
            ]
            for row in rows
        ],
    )


def load_rows() -> list[UpdateRow]:
    cached = load_cached_rows()
    if cached:
        return cached
    api = wandb.Api(timeout=60)
    rows: list[UpdateRow] = []
    for spec in RUNS:
        rows.extend(fetch_run_rows(api, spec))
    write_raw_rows(rows)
    return rows


def _run_node_positions(rows: list[UpdateRow], spec: RunSpec) -> tuple[dict[str, int], list[dict[str, object]]]:
    nodes_by_device: dict[str, set[str]] = {device: set() for device in DEVICE_SLOTS}
    for row in rows:
        if row.run_id == spec.run_id and row.device_type in nodes_by_device:
            nodes_by_device[row.device_type].add(row.node_id)

    positions: dict[str, int] = {}
    summary: list[dict[str, object]] = []
    offset = 0
    for device in ("rpi5", "rpi4"):
        nodes = sorted(nodes_by_device[device], key=_node_sort_key)
        for slot in range(DEVICE_SLOTS[device]):
            node = nodes[slot] if slot < len(nodes) else ""
            if node:
                positions[node] = offset + slot
            summary.append(
                {
                    "row": offset + slot,
                    "device_type": device,
                    "slot": slot,
                    "node_id": node,
                }
            )
        offset += DEVICE_SLOTS[device]
    return positions, summary


def _run_matrix(rows: list[UpdateRow], spec: RunSpec) -> tuple[np.ndarray, list[dict[str, object]]]:
    positions, node_summary = _run_node_positions(rows, spec)
    matrix = np.full((sum(DEVICE_SLOTS.values()), MAX_STEPS), np.nan)
    for row in rows:
        if row.run_id != spec.run_id or row.server_step < 1 or row.server_step > MAX_STEPS:
            continue
        if row.node_id not in positions:
            continue
        y = positions[row.node_id]
        x = row.server_step - 1
        previous = matrix[y, x]
        matrix[y, x] = row.staleness if np.isnan(previous) else max(previous, row.staleness)
    return matrix, node_summary


def plot_heatmaps(rows: list[UpdateRow]) -> dict[str, object]:
    apply_publication_style_no_grid()
    
    plt.rcParams.update(
        {
            'ytick.labelsize': 10,
            'xtick.labelsize': 12,
        }
    )

    max_staleness = max((row.staleness for row in rows if row.server_step <= MAX_STEPS), default=1)
    norm_cap = max(1, max_staleness)

    fig, axes = plt.subplots(2, 2, figsize=(PUBLICATION_FIGURE_WIDTH, 6), sharex=True, sharey=True)
    cmap = plt.colormaps["Reds"].copy()
    cmap.set_bad("white")
    spec_by_cell = (
        (RUNS[0], RUNS[1]),
        (RUNS[2], RUNS[3]),
    )

    client_summaries: dict[str, list[dict[str, object]]] = {}
    image = None
    for ax, spec in zip(axes.flat, [spec for row in spec_by_cell for spec in row], strict=True):
        matrix, node_summary = _run_matrix(rows, spec)
        client_summaries[spec.run_id] = node_summary
        image = ax.imshow(
            np.ma.masked_invalid(matrix),
            cmap=cmap,
            vmin=0,
            vmax=norm_cap,
            interpolation="none",
            aspect="auto",
            extent=(0.5, MAX_STEPS + 0.5, sum(DEVICE_SLOTS.values()) + 0.5, 0.5),
        )

        ax.set_title(spec.title, pad=6)
        ax.set_xlim(0.5, MAX_STEPS + 0.5)
        ax.set_ylim(sum(DEVICE_SLOTS.values()) + 0.5, 0.5)
        ax.set_xticks([1, 10, 20, 30, 40, 50, 60])
        ax.set_yticks(np.arange(1, sum(DEVICE_SLOTS.values()) + 1))
        ax.set_yticklabels([str(i) for i in range(1, sum(DEVICE_SLOTS.values()) + 1)])
        # ax.axhline(DEVICE_SLOTS["rpi5"], color="0.25", linewidth=0.9)
        ax.axhline(
            y=DEVICE_SLOTS["rpi5"] + 0.5,
            color="0.6",          # grey
            linewidth=0.6,        # thin
            linestyle="--",       # dashed
            zorder=3              # draw above heatmap
        )
        ax.tick_params(axis="both", which="both", length=0)
    axes[0, 0].set_ylabel("Client index")
    axes[1, 0].set_ylabel("Client index")
    fig.supxlabel("Server step", y=0.055, x= 0.47)
    fig.subplots_adjust(left=0.06, right=0.88, bottom=0.16, top=0.93, wspace=0.07, hspace=0.32)
    if image is not None:
        colorbar_ax = fig.add_axes((0.905, 0.18, 0.018, 0.68))
        colorbar = fig.colorbar(image, cax=colorbar_ax)
        colorbar.set_label("Staleness", labelpad=8)
    paths = save_figure_plot_with_writeup_pdf(fig, STEM)
    plt.close(fig)

    summary = {
        "runs": [
            {
                "method": spec.method,
                "buffer_size": spec.buffer_size,
                "run_id": spec.run_id,
                "source": spec.source,
                "updates_in_first_60_steps": sum(
                    1 for row in rows if row.run_id == spec.run_id and row.server_step <= MAX_STEPS
                ),
                "max_staleness_first_60_steps": max(
                    (row.staleness for row in rows if row.run_id == spec.run_id and row.server_step <= MAX_STEPS),
                    default=None,
                ),
            }
            for spec in RUNS
        ],
        "client_order_by_run": client_summaries,
        "max_steps": MAX_STEPS,
        "staleness_color_cap": norm_cap,
        "paths": {key: str(value) for key, value in paths.items()},
    }
    write_json_plot(f"{STEM}_summary.json", summary)
    return summary


def main() -> None:
    rows = load_rows()
    summary = plot_heatmaps(rows)
    print(f"Wrote {plot_output_path(STEM + '.pdf')}")
    print(f"Wrote {summary['paths']['pdf']}")


if __name__ == "__main__":
    main()
