#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import plistlib
import re
import sys
from collections import defaultdict
from dataclasses import dataclass

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
    apply_publication_style,
    cache_is_fresh,
    default_cycle_colors,
    force_refresh_requested,
    plot_output_path,
    save_figure_plot_with_writeup_pdf,
    write_csv_plot,
    write_json_plot,
)

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
TASK = "cifar10_cnn"
SEED = 1340
STEM = "compute_main_cifar10_seed1340_client_train_time"
TMPDIR = TMP_DIR / "wandb_cifar10_seed1340_client_train_time"

METHOD_ORDER = ("heterofl", "fedrolex", "fiarse")
METHOD_TITLES = {
    "heterofl": "HeteroFL",
    "fedrolex": "FedRolex",
    "fiarse": "FIARSE",
}
REGIME_ORDER = ("iid", "noniid")
REGIME_TITLES = {
    "iid": "IID",
    "noniid": "Non-IID",
}

GROUP_ORDER = (
    ("rpi4", 0.125),
    ("rpi4", 0.25),
    ("rpi5", 0.5),
    ("rpi5", 1.0),
)
RATE_LABELS = {
    0.125: "1/8",
    0.25: "1/4",
    0.5: "1/2",
    1.0: "1",
}

RUNS = (
    ("iid", "heterofl", "skhigedl"),
    ("iid", "fedrolex", "i99r0zn3"),
    ("iid", "fiarse", "y51ex006"),
    ("noniid", "heterofl", "prg5qiyn"),
    ("noniid", "fedrolex", "bj8ua1of"),
    ("noniid", "fiarse", "b2jm399x"),
)

ROUND_TABLE_RE = re.compile(r"round_table_(\d+)_")


@dataclass(frozen=True)
class RunSpec:
    regime: str
    method: str
    run_id: str


@dataclass(frozen=True)
class ClientUpdateRow:
    run_id: str
    regime: str
    method: str
    seed: int
    server_round: int
    client_trips_total: int
    node_id: str
    device_type: str
    model_rate: float
    train_duration_s: float
    examples_per_second: float | None
    num_examples: int | None


@dataclass(frozen=True)
class AggregateRow:
    run_id: str
    regime: str
    method: str
    seed: int
    server_round: int
    device_type: str
    model_rate: float
    group_label: str
    mean_train_duration_s: float
    std_train_duration_s: float
    num_clients: int


def run_specs() -> list[RunSpec]:
    return [RunSpec(regime=regime, method=method, run_id=run_id) for regime, method, run_id in RUNS]


def _table_sort_key(name: str) -> tuple[int, str]:
    match = ROUND_TABLE_RE.search(name)
    return (int(match.group(1)) if match else 10**9, name)


def _column_index(columns: list[str]) -> dict[str, int]:
    return {name: idx for idx, name in enumerate(columns)}


def _optional_float(raw: list[object], idx: dict[str, int], key: str) -> float | None:
    if key not in idx:
        return None
    value = raw[idx[key]]
    return float(value) if isinstance(value, (int, float)) else None


def _optional_int(raw: list[object], idx: dict[str, int], key: str) -> int | None:
    if key not in idx:
        return None
    value = raw[idx[key]]
    return int(value) if isinstance(value, (int, float)) else None


def fetch_run_rows(api: wandb.Api, spec: RunSpec) -> list[ClientUpdateRow]:
    run = api.run(f"{ENTITY}/{PROJECT}/{spec.run_id}")
    outdir = TMPDIR / spec.run_id
    outdir.mkdir(parents=True, exist_ok=True)

    rows: list[ClientUpdateRow] = []
    seen: set[tuple[int, int, str]] = set()
    files = sorted(
        (remote for remote in run.files() if "media/table/client_update/round_table" in remote.name),
        key=lambda remote: _table_sort_key(remote.name),
    )

    for remote in files:
        local_path = outdir / remote.name
        if local_path.exists() and not force_refresh_requested():
            payload_text = local_path.read_text()
        else:
            local = remote.download(root=str(outdir), replace=True)
            payload_text = local.read()
        payload = json.loads(payload_text)
        columns = payload["columns"]
        idx = _column_index(columns)

        required = {
            "server_round",
            "client_trips_total",
            "node_id",
            "device_type",
            "model_rate",
            "update_train_duration_s",
        }
        missing = sorted(required.difference(idx))
        if missing:
            raise RuntimeError(f"{spec.run_id}: missing client-update columns {missing}")

        for raw in payload["data"]:
            server_round = int(raw[idx["server_round"]])
            client_trips_total = int(raw[idx["client_trips_total"]])
            node_id = str(raw[idx["node_id"]])
            dedupe_key = (server_round, client_trips_total, node_id)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rows.append(
                ClientUpdateRow(
                    run_id=spec.run_id,
                    regime=spec.regime,
                    method=spec.method,
                    seed=SEED,
                    server_round=server_round,
                    client_trips_total=client_trips_total,
                    node_id=node_id,
                    device_type=str(raw[idx["device_type"]]).lower(),
                    model_rate=float(raw[idx["model_rate"]]),
                    train_duration_s=float(raw[idx["update_train_duration_s"]]),
                    examples_per_second=_optional_float(raw, idx, "update_examples_per_second"),
                    num_examples=_optional_int(raw, idx, "update_num_examples"),
                )
            )
    return rows


def load_cached_rows() -> list[ClientUpdateRow]:
    cache_path = plot_output_path(f"{STEM}_raw.csv")
    if force_refresh_requested() or not cache_is_fresh(cache_path):
        return []

    rows: list[ClientUpdateRow] = []
    with cache_path.open(newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(
                ClientUpdateRow(
                    run_id=raw["run_id"],
                    regime=raw["regime"],
                    method=raw["method"],
                    seed=int(raw["seed"]),
                    server_round=int(raw["server_round"]),
                    client_trips_total=int(raw["client_trips_total"]),
                    node_id=raw["node_id"],
                    device_type=raw["device_type"],
                    model_rate=float(raw["model_rate"]),
                    train_duration_s=float(raw["train_duration_s"]),
                    examples_per_second=float(raw["examples_per_second"]) if raw["examples_per_second"] else None,
                    num_examples=int(raw["num_examples"]) if raw["num_examples"] else None,
                )
            )
    return rows


def write_raw_cache(rows: list[ClientUpdateRow]) -> None:
    write_csv_plot(
        f"{STEM}_raw.csv",
        [
            "run_id",
            "regime",
            "method",
            "seed",
            "server_round",
            "client_trips_total",
            "node_id",
            "device_type",
            "model_rate",
            "train_duration_s",
            "examples_per_second",
            "num_examples",
        ],
        (
            [
                row.run_id,
                row.regime,
                row.method,
                row.seed,
                row.server_round,
                row.client_trips_total,
                row.node_id,
                row.device_type,
                row.model_rate,
                row.train_duration_s,
                row.examples_per_second if row.examples_per_second is not None else "",
                row.num_examples if row.num_examples is not None else "",
            ]
            for row in rows
        ),
    )


def _group_label(device_type: str, model_rate: float) -> str:
    return f"{device_type} {RATE_LABELS[model_rate]}"


def aggregate_rows(rows: list[ClientUpdateRow]) -> list[AggregateRow]:
    groups: dict[tuple[str, str, str, int, str, float], list[float]] = defaultdict(list)
    for row in rows:
        key = (
            row.run_id,
            row.regime,
            row.method,
            row.server_round,
            row.device_type,
            row.model_rate,
        )
        groups[key].append(row.train_duration_s)

    aggregates: list[AggregateRow] = []
    for (run_id, regime, method, server_round, device_type, model_rate), values in sorted(groups.items()):
        arr = np.asarray(values, dtype=float)
        std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
        aggregates.append(
            AggregateRow(
                run_id=run_id,
                regime=regime,
                method=method,
                seed=SEED,
                server_round=server_round,
                device_type=device_type,
                model_rate=model_rate,
                group_label=_group_label(device_type, model_rate),
                mean_train_duration_s=float(arr.mean()),
                std_train_duration_s=std,
                num_clients=len(arr),
            )
        )
    return aggregates


def write_aggregate_cache(rows: list[AggregateRow]) -> None:
    write_csv_plot(
        f"{STEM}_summary.csv",
        [
            "run_id",
            "regime",
            "method",
            "seed",
            "server_round",
            "device_type",
            "model_rate",
            "group_label",
            "mean_train_duration_s",
            "std_train_duration_s",
            "num_clients",
        ],
        (
            [
                row.run_id,
                row.regime,
                row.method,
                row.seed,
                row.server_round,
                row.device_type,
                row.model_rate,
                row.group_label,
                row.mean_train_duration_s,
                row.std_train_duration_s,
                row.num_clients,
            ]
            for row in rows
        ),
    )


def _load_or_fetch_rows() -> list[ClientUpdateRow]:
    rows = load_cached_rows()
    if rows:
        return rows

    api = wandb.Api(timeout=30)
    fetched: list[ClientUpdateRow] = []
    for spec in run_specs():
        fetched.extend(fetch_run_rows(api, spec))
    write_raw_cache(fetched)
    return fetched


def _coverage(rows: list[ClientUpdateRow], aggregates: list[AggregateRow]) -> dict[str, object]:
    coverage_runs: list[dict[str, object]] = []
    for spec in run_specs():
        run_rows = [row for row in rows if row.run_id == spec.run_id]
        coverage_runs.append(
            {
                "run_id": spec.run_id,
                "regime": spec.regime,
                "method": spec.method,
                "raw_rows": len(run_rows),
                "rounds": sorted({row.server_round for row in run_rows}),
                "groups": sorted(
                    {
                        f"{row.device_type}:{RATE_LABELS.get(row.model_rate, row.model_rate)}"
                        for row in run_rows
                    }
                ),
            }
        )

    expected_groups = {f"{device}:{RATE_LABELS[rate]}" for device, rate in GROUP_ORDER}
    observed_groups = {
        f"{row.device_type}:{RATE_LABELS.get(row.model_rate, row.model_rate)}"
        for row in rows
    }
    return {
        "task": TASK,
        "seed": SEED,
        "metric": "update_train_duration_s",
        "expected_groups": sorted(expected_groups),
        "observed_groups": sorted(observed_groups),
        "aggregate_rows": len(aggregates),
        "runs": coverage_runs,
    }


def _panel_rows(rows: list[AggregateRow], *, regime: str, method: str, device_type: str, model_rate: float) -> list[AggregateRow]:
    return sorted(
        (
            row
            for row in rows
            if row.regime == regime
            and row.method == method
            and row.device_type == device_type
            and abs(row.model_rate - model_rate) < 1e-9
        ),
        key=lambda row: row.server_round,
    )


def main() -> None:
    raw_rows = _load_or_fetch_rows()
    aggregate = aggregate_rows(raw_rows)
    write_aggregate_cache(aggregate)
    write_json_plot(f"{STEM}_coverage.json", _coverage(raw_rows, aggregate))

    apply_publication_style()
    colors = default_cycle_colors(len(GROUP_ORDER))
    group_colors = {group: color for group, color in zip(GROUP_ORDER, colors, strict=True)}

    fig, axes = plt.subplots(
        2,
        3,
        figsize=(PUBLICATION_FIGURE_WIDTH, 7.6),
        sharex=False,
        sharey=True,
    )

    legend_handles = []
    legend_labels = []
    for row_idx, regime in enumerate(REGIME_ORDER):
        for col_idx, method in enumerate(METHOD_ORDER):
            ax = axes[row_idx, col_idx]
            panel_all_rows = [
                row
                for row in aggregate
                if row.regime == regime and row.method == method
            ]
            if row_idx == 0:
                ax.set_title(METHOD_TITLES[method])
            ax.text(
                0.03,
                0.92,
                REGIME_TITLES[regime],
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=13,
                bbox={"boxstyle": "round,pad=0.22", "facecolor": "white", "edgecolor": "#555555", "alpha": 0.92},
            )

            for group in GROUP_ORDER:
                device_type, model_rate = group
                rows = _panel_rows(aggregate, regime=regime, method=method, device_type=device_type, model_rate=model_rate)
                if not rows:
                    continue
                x = np.asarray([row.server_round for row in rows], dtype=float)
                y = np.asarray([row.mean_train_duration_s for row in rows], dtype=float)
                std = np.asarray([row.std_train_duration_s for row in rows], dtype=float)
                label = f"{device_type}, rate={RATE_LABELS[model_rate]}"
                color = group_colors[group]
                (line,) = ax.plot(x, y, marker="o", markersize=3.0, linewidth=1.7, color=color, label=label)
                ax.fill_between(x, np.maximum(0.0, y - std), y + std, color=color, alpha=0.16, linewidth=0)
                if row_idx == 0 and col_idx == 0:
                    legend_handles.append(line)
                    legend_labels.append(label)

            panel_max_round = max((row.server_round for row in panel_all_rows), default=20)
            ax.set_xlim(0, panel_max_round + 1)
            if panel_max_round <= 20:
                ax.set_xticks([0, 5, 10, 15, 20])
            else:
                ax.set_xticks([0, 10, 20, 30, 40])
            ax.margins(x=0.02)

    fig.supxlabel("Server round", y=0.17, x =0.55)
    fig.supylabel("Client train time (s)", x=0.08, y = 0.6)

    fig.legend(
        legend_handles,
        legend_labels,
        loc="upper center",
        ncol=4,
        frameon=True,
        bbox_to_anchor=(0.55, 1.02),
    )
    fig.tight_layout(rect=(0.055, 0.145, 1.0, 0.94), w_pad=1.0, h_pad=0.75)

    outputs = save_figure_plot_with_writeup_pdf(fig, STEM)
    plt.close(fig)
    print(f"Wrote {outputs['pdf'][0]}")
    print(f"Wrote {outputs['pdf'][1]}")


if __name__ == "__main__":
    main()
