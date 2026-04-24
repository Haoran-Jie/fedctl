#!/usr/bin/env python3
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Iterable

import wandb

from common import cache_is_fresh, force_refresh_requested, plot_output_path, write_csv_plot

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"
TARGET_ACC = 0.60


@dataclass(frozen=True)
class RunSpec:
    profile: str
    method: str
    buffer_size: int | None
    run_id: str
    source: str

    @property
    def label(self) -> str:
        if self.method == "fedavg":
            return r"\texttt{FedAvg}"
        if self.method == "fedbuff":
            return rf"\texttt{{FedBuff}} \(K={self.buffer_size}\)"
        if self.method == "fedstaleweight":
            return rf"\texttt{{FedStaleWeight}} \(K={self.buffer_size}\)"
        raise ValueError(f"unknown method {self.method!r}")


@dataclass(frozen=True)
class SummaryRow:
    profile: str
    method: str
    buffer_size: int | None
    run_id: str
    source: str
    target_reached: bool
    target_client_trips: int | None
    target_wall_clock_s: float | None
    final_acc: float | None
    final_client_trips: int | None
    final_wall_clock_s: float | None
    rpi4_update_share: float | None
    rpi4_weight_share: float | None
    rpi4_staleness: float | None
    rpi5_staleness: float | None
    updates_per_second: float | None


PROFILE_ORDER = ("none", "mild", "med", "asym_up", "asym_down")
PROFILE_LABELS = {
    "none": r"\texttt{none}",
    "mild": r"\texttt{mild}",
    "med": r"\texttt{med}",
    "asym_up": r"\makecell[l]{\texttt{asym}\\\texttt{up}}",
    "asym_down": r"\makecell[l]{\texttt{asym}\\\texttt{down}}",
}
PROFILE_DESCRIPTION = {
    "none": "No added impairment",
    "mild": r"20 ms, 5 ms jitter, 100 Mbit/s",
    "med": r"60 ms, 15 ms jitter, 0.5\% loss, 50 Mbit/s",
    "asym_up": r"Egress only: 90 ms, 20 ms jitter, 0.5\% loss, 20 Mbit/s",
    "asym_down": r"Ingress only: 90 ms, 20 ms jitter, 0.5\% loss, 20 Mbit/s",
}
VARIANT_ORDER = (
    ("fedavg", None),
    ("fedbuff", 10),
    ("fedstaleweight", 10),
    ("fedbuff", 5),
    ("fedstaleweight", 5),
)

RUNS = (
    # No-impairment baselines from the main non-IID mixed seed-1337 matrix.
    RunSpec("none", "fedavg", None, "0ysztwpg", "network_main"),
    RunSpec("none", "fedbuff", 10, "j81afai0", "network_main"),
    RunSpec("none", "fedstaleweight", 10, "wyc9rjxq", "network_main"),
    # K=5 variants from the stressor sweep.
    RunSpec("none", "fedbuff", 5, "f8r1yqsh", "network_stressor_sweep"),
    RunSpec("none", "fedstaleweight", 5, "qjnt77fk", "network_stressor_sweep"),
    RunSpec("mild", "fedavg", None, "i6bntwqf", "network_stressor_sweep"),
    RunSpec("mild", "fedbuff", 10, "2p9z7l7w", "network_stressor_sweep"),
    RunSpec("mild", "fedstaleweight", 10, "drf94he0", "network_stressor_sweep"),
    RunSpec("mild", "fedbuff", 5, "job3dtrj", "network_stressor_sweep"),
    RunSpec("mild", "fedstaleweight", 5, "3463t0ch", "network_stressor_sweep"),
    RunSpec("med", "fedavg", None, "2hnjmyey", "network_stressor_sweep"),
    RunSpec("med", "fedbuff", 10, "semxze1r", "network_stressor_sweep"),
    RunSpec("med", "fedstaleweight", 10, "6f88023u", "network_stressor_sweep"),
    RunSpec("med", "fedbuff", 5, "57crpvxi", "network_stressor_sweep"),
    RunSpec("med", "fedstaleweight", 5, "navnxljy", "network_stressor_sweep"),
    RunSpec("asym_up", "fedavg", None, "7pgojwmx", "network_stressor_sweep"),
    RunSpec("asym_up", "fedbuff", 10, "37qs4r8b", "network_stressor_sweep"),
    RunSpec("asym_up", "fedstaleweight", 10, "jxdfszfk", "network_stressor_sweep"),
    RunSpec("asym_up", "fedbuff", 5, "6z31wp5b", "network_stressor_sweep"),
    RunSpec("asym_up", "fedstaleweight", 5, "e47c5qwj", "network_stressor_sweep"),
    RunSpec("asym_down", "fedavg", None, "gbw5a7sh", "network_stressor_sweep"),
    RunSpec("asym_down", "fedbuff", 10, "d4yqs2yc", "network_stressor_sweep"),
    RunSpec("asym_down", "fedstaleweight", 10, "624a37a2", "network_stressor_sweep"),
    RunSpec("asym_down", "fedbuff", 5, "dog9c4pg", "network_stressor_sweep"),
    RunSpec("asym_down", "fedstaleweight", 5, "r9kmeurg", "network_stressor_sweep"),
)

FIELDS = [
    "profile",
    "method",
    "buffer_size",
    "run_id",
    "source",
    "target_reached",
    "target_client_trips",
    "target_wall_clock_s",
    "final_acc",
    "final_client_trips",
    "final_wall_clock_s",
    "rpi4_update_share",
    "rpi4_weight_share",
    "rpi4_staleness",
    "rpi5_staleness",
    "updates_per_second",
]


def _summary_number(summary: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = summary.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _history_number(row: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _fetch_summary(api: wandb.Api, spec: RunSpec) -> SummaryRow:
    run = api.run(f"{ENTITY}/{PROJECT}/{spec.run_id}")
    summary = dict(run.summary)
    weight_rpi4 = _summary_number(summary, ("fairness/run_weight_total_rpi4",))
    weight_rpi5 = _summary_number(summary, ("fairness/run_weight_total_rpi5",))
    rpi4_weight_share = None
    if weight_rpi4 is not None and weight_rpi5 is not None and weight_rpi4 + weight_rpi5 > 0:
        rpi4_weight_share = weight_rpi4 / (weight_rpi4 + weight_rpi5)

    final_client_trips = None
    final_wall_clock_s = None
    for row in run.scan_history(page_size=1000):
        score = _history_number(row, ("eval_server_trip/eval-acc", "eval_server_trip/eval-score"))
        if score is None:
            continue
        trip = row.get("client_trip")
        runtime = row.get("_runtime")
        if isinstance(trip, (int, float)):
            final_client_trips = int(trip)
        if isinstance(runtime, (int, float)):
            final_wall_clock_s = float(runtime)

    target_trips = _summary_number(summary, ("target/client_trips_to_target",))
    target_wall = _summary_number(summary, ("target/wall_clock_s_to_target",))
    final_acc = _summary_number(summary, ("final/eval_server/eval-acc", "final/eval_server/eval-score"))
    return SummaryRow(
        profile=spec.profile,
        method=spec.method,
        buffer_size=spec.buffer_size,
        run_id=spec.run_id,
        source=spec.source,
        target_reached=bool(summary.get("target/reached")),
        target_client_trips=int(target_trips) if target_trips is not None else None,
        target_wall_clock_s=float(target_wall) if target_wall is not None else None,
        final_acc=float(final_acc) if final_acc is not None else None,
        final_client_trips=final_client_trips,
        final_wall_clock_s=final_wall_clock_s,
        rpi4_update_share=_summary_number(summary, ("fairness/run_update_share_rpi4",)),
        rpi4_weight_share=rpi4_weight_share,
        rpi4_staleness=_summary_number(summary, ("fairness/run_avg_staleness_rpi4",)),
        rpi5_staleness=_summary_number(summary, ("fairness/run_avg_staleness_rpi5",)),
        updates_per_second=_summary_number(summary, ("progress/updates_per_second",)),
    )


def _write_cache(rows: list[SummaryRow]) -> None:
    write_csv_plot(
        "network_stressor_sweep_seed1337_summary.csv",
        FIELDS,
        (
            [
                row.profile,
                row.method,
                row.buffer_size if row.buffer_size is not None else "",
                row.run_id,
                row.source,
                row.target_reached,
                row.target_client_trips if row.target_client_trips is not None else "",
                row.target_wall_clock_s if row.target_wall_clock_s is not None else "",
                row.final_acc if row.final_acc is not None else "",
                row.final_client_trips if row.final_client_trips is not None else "",
                row.final_wall_clock_s if row.final_wall_clock_s is not None else "",
                row.rpi4_update_share if row.rpi4_update_share is not None else "",
                row.rpi4_weight_share if row.rpi4_weight_share is not None else "",
                row.rpi4_staleness if row.rpi4_staleness is not None else "",
                row.rpi5_staleness if row.rpi5_staleness is not None else "",
                row.updates_per_second if row.updates_per_second is not None else "",
            ]
            for row in rows
        ),
    )


def _load_cache() -> list[SummaryRow]:
    path = plot_output_path("network_stressor_sweep_seed1337_summary.csv")
    if force_refresh_requested() or not cache_is_fresh(path):
        return []
    rows: list[SummaryRow] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            return []
        for row in reader:
            rows.append(
                SummaryRow(
                    profile=row["profile"],
                    method=row["method"],
                    buffer_size=int(row["buffer_size"]) if row["buffer_size"] else None,
                    run_id=row["run_id"],
                    source=row["source"],
                    target_reached=row["target_reached"].lower() == "true",
                    target_client_trips=int(row["target_client_trips"]) if row["target_client_trips"] else None,
                    target_wall_clock_s=float(row["target_wall_clock_s"]) if row["target_wall_clock_s"] else None,
                    final_acc=float(row["final_acc"]) if row["final_acc"] else None,
                    final_client_trips=int(row["final_client_trips"]) if row["final_client_trips"] else None,
                    final_wall_clock_s=float(row["final_wall_clock_s"]) if row["final_wall_clock_s"] else None,
                    rpi4_update_share=float(row["rpi4_update_share"]) if row["rpi4_update_share"] else None,
                    rpi4_weight_share=float(row["rpi4_weight_share"]) if row["rpi4_weight_share"] else None,
                    rpi4_staleness=float(row["rpi4_staleness"]) if row["rpi4_staleness"] else None,
                    rpi5_staleness=float(row["rpi5_staleness"]) if row["rpi5_staleness"] else None,
                    updates_per_second=float(row["updates_per_second"]) if row["updates_per_second"] else None,
                )
            )
    expected = {(spec.profile, spec.method, spec.buffer_size, spec.run_id) for spec in RUNS}
    actual = {(row.profile, row.method, row.buffer_size, row.run_id) for row in rows}
    return rows if actual == expected else []


def fetch_or_load() -> list[SummaryRow]:
    cached = _load_cache()
    if cached:
        return cached
    api = wandb.Api()
    rows = [_fetch_summary(api, spec) for spec in RUNS]
    _write_cache(rows)
    return rows


def _fmt_int(value: int | None) -> str:
    return "--" if value is None else f"{value:d}"


def _fmt_seconds(value: float | None) -> str:
    return "--" if value is None else f"{value:.0f}"


def _fmt_acc(value: float | None) -> str:
    return "--" if value is None else f"{100.0 * value:.1f}"


def _fmt_pct(value: float | None) -> str:
    return "--" if value is None else f"{100.0 * value:.1f}"


def _fmt_float(value: float | None) -> str:
    return "--" if value is None else f"{value:.2f}"


def _target_trips(row: SummaryRow) -> str:
    if row.target_reached:
        return _fmt_int(row.target_client_trips)
    return rf"\(>{_fmt_int(row.final_client_trips)}\)"


def _target_wall(row: SummaryRow) -> str:
    if row.target_reached:
        return _fmt_seconds(row.target_wall_clock_s)
    return rf"\(>{_fmt_seconds(row.final_wall_clock_s)}\)"


def _row_sort_key(row: SummaryRow) -> tuple[int, int]:
    return PROFILE_ORDER.index(row.profile), VARIANT_ORDER.index((row.method, row.buffer_size))


def _latex_rows(rows: Iterable[SummaryRow]) -> str:
    by_profile = {profile: [] for profile in PROFILE_ORDER}
    for row in sorted(rows, key=_row_sort_key):
        by_profile[row.profile].append(row)

    lines: list[str] = []
    for profile in PROFILE_ORDER:
        group = by_profile[profile]
        for idx, row in enumerate(group):
            prefix = (
                rf"\multirow{{{len(group)}}}{{*}}{{{PROFILE_LABELS[profile]}}} "
                + rf"& \multirow{{{len(group)}}}{{=}}{{\raggedright {PROFILE_DESCRIPTION[profile]}}} "
                if idx == 0
                else " & "
            )
            spec = next(spec for spec in RUNS if spec.run_id == row.run_id)
            lines.append(
                prefix
                + f"& {spec.label} "
                + f"& {_target_trips(row)} "
                + f"& {_target_wall(row)} "
                + f"& {_fmt_acc(row.final_acc)} "
                + f"& {_fmt_pct(row.rpi4_update_share)} "
                + f"& {_fmt_pct(row.rpi4_weight_share)} "
                + f"& {_fmt_float(row.rpi4_staleness)} / {_fmt_float(row.rpi5_staleness)} "
                + f"& {_fmt_float(row.updates_per_second)} \\\\"
            )
        if profile != PROFILE_ORDER[-1]:
            lines.append(r"\midrule")
    return "\n".join(lines)


def main() -> None:
    rows = fetch_or_load()
    latex = _latex_rows(rows)
    latex_path = plot_output_path("network_stressor_sweep_seed1337_table_rows.tex")
    latex_path.write_text(latex + "\n")
    print(f"Wrote {plot_output_path('network_stressor_sweep_seed1337_summary.csv')}")
    print(f"Wrote {latex_path}")
    print(latex)


if __name__ == "__main__":
    main()
