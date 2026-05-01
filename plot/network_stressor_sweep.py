#!/usr/bin/env python3
from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from typing import Iterable

import wandb

from common import cache_is_fresh, force_refresh_requested, plot_output_path, write_csv_plot

ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"


@dataclass(frozen=True)
class RunSpec:
    profile: str
    method: str
    buffer_size: int | None
    seed: int
    run_id: str
    source: str

    @property
    def label(self) -> str:
        if self.method == "fedavg":
            return r"\texttt{FedAvg}"
        if self.method == "fedbuff":
            return rf"\texttt{{FedBuff}}\(_{{{self.buffer_size}}}\)"
        if self.method == "fedstaleweight":
            return rf"\texttt{{FedSW}}\(_{{{self.buffer_size}}}\)"
        if self.method == "fedasync":
            return r"\texttt{FedAsync}"
        raise ValueError(f"unknown method {self.method!r}")


@dataclass(frozen=True)
class SummaryRow:
    profile: str
    method: str
    buffer_size: int | None
    seed: int
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
    "none": r"\centering \texttt{none}\\[0.25em]No added impairment",
    "mild": r"\centering \texttt{mild}\\[0.25em]20 ms, 5 ms jitter\\100 Mbit/s",
    "med": r"\centering \texttt{med}\\[0.25em]60 ms, 15 ms jitter\\0.5\% loss, 50 Mbit/s",
    "asym_up": r"\centering \makecell[c]{\texttt{asym up}}\\[0.25em]Egress only\\90 ms, 20 ms jitter\\0.5\% loss, 20 Mbit/s",
    "asym_down": r"\centering \makecell[c]{\texttt{asym down}}\\[0.25em]Ingress only\\90 ms, 20 ms jitter\\0.5\% loss, 20 Mbit/s",
}
VARIANT_ORDER = (
    ("fedavg", None),
    ("fedbuff", 10),
    ("fedstaleweight", 10),
    ("fedasync", 1),
    ("fedbuff", 5),
    ("fedstaleweight", 5),
)
SUMMARY_FILENAME = "network_stressor_sweep_summary.csv"
TABLE_FILENAME = "network_stressor_sweep_table_rows.tex"

RUNS = (
    RunSpec("none", "fedavg", None, 1337, "0ysztwpg", "network_main"),
    RunSpec("none", "fedavg", None, 1338, "kqc9pciy", "network_main"),
    RunSpec("none", "fedavg", None, 1339, "5cari6u0", "network_main"),
    RunSpec("none", "fedbuff", 10, 1337, "j81afai0", "network_main"),
    RunSpec("none", "fedbuff", 10, 1338, "kouohvbb", "network_main"),
    RunSpec("none", "fedbuff", 10, 1339, "o7i4mdii", "network_main"),
    RunSpec("none", "fedstaleweight", 10, 1337, "wyc9rjxq", "network_main"),
    RunSpec("none", "fedstaleweight", 10, 1338, "b0xxbbi7", "network_main"),
    RunSpec("none", "fedstaleweight", 10, 1339, "9qv2c0qb", "network_main"),
    RunSpec("none", "fedasync", 1, 1337, "u2awvlob", "network_main"),
    RunSpec("none", "fedasync", 1, 1338, "vnxrt39a", "network_main"),
    RunSpec("none", "fedasync", 1, 1339, "utho3iov", "network_main"),
    RunSpec("none", "fedbuff", 5, 1337, "f8r1yqsh", "network_stressor_sweep"),
    RunSpec("none", "fedbuff", 5, 1338, "3sduvg0n", "network_stressor_sweep"),
    RunSpec("none", "fedbuff", 5, 1339, "w54p73te", "network_stressor_sweep"),
    RunSpec("none", "fedstaleweight", 5, 1337, "qjnt77fk", "network_stressor_sweep"),
    RunSpec("none", "fedstaleweight", 5, 1338, "hmg55ujk", "network_stressor_sweep"),
    RunSpec("none", "fedstaleweight", 5, 1339, "yk3uqpnh", "network_stressor_sweep"),
    RunSpec("mild", "fedavg", None, 1337, "i6bntwqf", "network_stressor_sweep"),
    RunSpec("mild", "fedavg", None, 1338, "cwvfb928", "network_stressor_sweep"),
    RunSpec("mild", "fedavg", None, 1339, "it7x8vfb", "network_stressor_sweep"),
    RunSpec("mild", "fedbuff", 10, 1337, "2p9z7l7w", "network_stressor_sweep"),
    RunSpec("mild", "fedbuff", 10, 1338, "2rp6pb6m", "network_stressor_sweep"),
    RunSpec("mild", "fedbuff", 10, 1339, "jlylrg17", "network_stressor_sweep"),
    RunSpec("mild", "fedstaleweight", 10, 1337, "drf94he0", "network_stressor_sweep"),
    RunSpec("mild", "fedstaleweight", 10, 1338, "v0bgwzwy", "network_stressor_sweep"),
    RunSpec("mild", "fedstaleweight", 10, 1339, "vac832ee", "network_stressor_sweep"),
    RunSpec("mild", "fedasync", 1, 1337, "4i9ojhfv", "network_stressor_sweep"),
    RunSpec("mild", "fedasync", 1, 1338, "uav55bjs", "network_stressor_sweep"),
    RunSpec("mild", "fedasync", 1, 1339, "9xh5eogp", "network_stressor_sweep"),
    RunSpec("mild", "fedbuff", 5, 1337, "job3dtrj", "network_stressor_sweep"),
    RunSpec("mild", "fedbuff", 5, 1338, "2f3o3hry", "network_stressor_sweep"),
    RunSpec("mild", "fedbuff", 5, 1339, "amlbrdo2", "network_stressor_sweep"),
    RunSpec("mild", "fedstaleweight", 5, 1337, "3463t0ch", "network_stressor_sweep"),
    RunSpec("mild", "fedstaleweight", 5, 1338, "swto4jzv", "network_stressor_sweep"),
    RunSpec("mild", "fedstaleweight", 5, 1339, "mypog92u", "network_stressor_sweep"),
    RunSpec("med", "fedavg", None, 1337, "2hnjmyey", "network_stressor_sweep"),
    RunSpec("med", "fedavg", None, 1338, "uono0vnd", "network_stressor_sweep"),
    RunSpec("med", "fedavg", None, 1339, "9u438lpm", "network_stressor_sweep"),
    RunSpec("med", "fedbuff", 10, 1337, "semxze1r", "network_stressor_sweep"),
    RunSpec("med", "fedbuff", 10, 1338, "v2puht74", "network_stressor_sweep"),
    RunSpec("med", "fedbuff", 10, 1339, "9row2nir", "network_stressor_sweep"),
    RunSpec("med", "fedstaleweight", 10, 1337, "6f88023u", "network_stressor_sweep"),
    RunSpec("med", "fedstaleweight", 10, 1338, "kxsizy6s", "network_stressor_sweep"),
    RunSpec("med", "fedstaleweight", 10, 1339, "ad644r8t", "network_stressor_sweep"),
    RunSpec("med", "fedasync", 1, 1337, "mqwl7xe7", "network_stressor_sweep"),
    RunSpec("med", "fedasync", 1, 1338, "ze2sanxk", "network_stressor_sweep"),
    RunSpec("med", "fedasync", 1, 1339, "qnf7kd7u", "network_stressor_sweep"),
    RunSpec("med", "fedbuff", 5, 1337, "57crpvxi", "network_stressor_sweep"),
    RunSpec("med", "fedbuff", 5, 1338, "8wcprmti", "network_stressor_sweep"),
    RunSpec("med", "fedbuff", 5, 1339, "hyngttge", "network_stressor_sweep"),
    RunSpec("med", "fedstaleweight", 5, 1337, "navnxljy", "network_stressor_sweep"),
    RunSpec("med", "fedstaleweight", 5, 1338, "kaszfg39", "network_stressor_sweep"),
    RunSpec("med", "fedstaleweight", 5, 1339, "uq7g352u", "network_stressor_sweep"),
    RunSpec("asym_up", "fedavg", None, 1337, "7pgojwmx", "network_stressor_sweep"),
    RunSpec("asym_up", "fedavg", None, 1338, "h2maq496", "network_stressor_sweep"),
    RunSpec("asym_up", "fedavg", None, 1339, "gaf7v914", "network_stressor_sweep"),
    RunSpec("asym_up", "fedbuff", 10, 1337, "37qs4r8b", "network_stressor_sweep"),
    RunSpec("asym_up", "fedbuff", 10, 1338, "dbzckv0t", "network_stressor_sweep"),
    RunSpec("asym_up", "fedbuff", 10, 1339, "r5nbqadg", "network_stressor_sweep"),
    RunSpec("asym_up", "fedstaleweight", 10, 1337, "jxdfszfk", "network_stressor_sweep"),
    RunSpec("asym_up", "fedstaleweight", 10, 1338, "eoqfxo3e", "network_stressor_sweep"),
    RunSpec("asym_up", "fedstaleweight", 10, 1339, "x6o18ysg", "network_stressor_sweep"),
    RunSpec("asym_up", "fedasync", 1, 1337, "ovcslo9c", "network_stressor_sweep"),
    RunSpec("asym_up", "fedasync", 1, 1338, "pkqxtk2l", "network_stressor_sweep"),
    RunSpec("asym_up", "fedasync", 1, 1339, "ft3rf5tt", "network_stressor_sweep"),
    RunSpec("asym_up", "fedbuff", 5, 1337, "6z31wp5b", "network_stressor_sweep"),
    RunSpec("asym_up", "fedbuff", 5, 1338, "9oynevgp", "network_stressor_sweep"),
    RunSpec("asym_up", "fedbuff", 5, 1339, "cyjv02fg", "network_stressor_sweep"),
    RunSpec("asym_up", "fedstaleweight", 5, 1337, "e47c5qwj", "network_stressor_sweep"),
    RunSpec("asym_up", "fedstaleweight", 5, 1338, "4mw359io", "network_stressor_sweep"),
    RunSpec("asym_up", "fedstaleweight", 5, 1339, "lmmteiiu", "network_stressor_sweep"),
    RunSpec("asym_down", "fedavg", None, 1337, "gbw5a7sh", "network_stressor_sweep"),
    RunSpec("asym_down", "fedavg", None, 1338, "o8ag40uf", "network_stressor_sweep"),
    RunSpec("asym_down", "fedavg", None, 1339, "t3476rog", "network_stressor_sweep"),
    RunSpec("asym_down", "fedbuff", 10, 1337, "d4yqs2yc", "network_stressor_sweep"),
    RunSpec("asym_down", "fedbuff", 10, 1338, "g9425e0q", "network_stressor_sweep"),
    RunSpec("asym_down", "fedbuff", 10, 1339, "dtrmq5g2", "network_stressor_sweep"),
    RunSpec("asym_down", "fedstaleweight", 10, 1337, "624a37a2", "network_stressor_sweep"),
    RunSpec("asym_down", "fedstaleweight", 10, 1338, "dyf59phl", "network_stressor_sweep"),
    RunSpec("asym_down", "fedstaleweight", 10, 1339, "tqp9k6p8", "network_stressor_sweep"),
    RunSpec("asym_down", "fedasync", 1, 1337, "wvdkhrx3", "network_stressor_sweep"),
    RunSpec("asym_down", "fedasync", 1, 1338, "790dh1t2", "network_stressor_sweep"),
    RunSpec("asym_down", "fedasync", 1, 1339, "com619x6", "network_stressor_sweep"),
    RunSpec("asym_down", "fedbuff", 5, 1337, "dog9c4pg", "network_stressor_sweep"),
    RunSpec("asym_down", "fedbuff", 5, 1338, "8q2fjcf9", "network_stressor_sweep"),
    RunSpec("asym_down", "fedbuff", 5, 1339, "5cjtc1sn", "network_stressor_sweep"),
    RunSpec("asym_down", "fedstaleweight", 5, 1337, "r9kmeurg", "network_stressor_sweep"),
    RunSpec("asym_down", "fedstaleweight", 5, 1338, "f2p823gf", "network_stressor_sweep"),
    RunSpec("asym_down", "fedstaleweight", 5, 1339, "ozqrol1r", "network_stressor_sweep"),
)

FIELDS = [
    "profile",
    "method",
    "buffer_size",
    "seed",
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


def _mean_std(values: Iterable[float]) -> tuple[float, float]:
    items = [float(value) for value in values]
    if not items:
        raise ValueError("cannot aggregate an empty collection")
    mean = statistics.fmean(items)
    std = statistics.stdev(items) if len(items) > 1 else 0.0
    return mean, std


def _fetch_run_map(api: wandb.Api) -> dict[str, object]:
    expected_ids = {spec.run_id for spec in RUNS}
    run_map: dict[str, object] = {}
    for run_id in expected_ids:
        run_map[run_id] = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
    missing = sorted(expected_ids.difference(run_map))
    if missing:
        raise RuntimeError(f"missing W&B runs for ids: {missing}")
    return run_map


def _row_from_run(spec: RunSpec, run) -> SummaryRow:
    if run.state != "finished":
        raise RuntimeError(f"expected finished run for {spec.run_id}, got {run.state}")
    summary = dict(run.summary)
    target_trips = _summary_number(summary, ("target/client_trips_to_target",))
    target_wall = _summary_number(summary, ("target/wall_clock_s_to_target",))
    final_acc = _summary_number(summary, ("final/eval_server/eval-acc", "final/eval_server/eval-score"))
    final_client_trips = _summary_number(summary, ("progress/client_trips_total", "target/client_trip_budget"))
    final_wall_clock_s = _summary_number(summary, ("runtime/total_server_s", "progress/wall_clock_s", "_runtime"))
    updates_per_second = _summary_number(summary, ("progress/updates_per_second",))
    if updates_per_second is None and final_client_trips is not None and final_wall_clock_s not in (None, 0):
        updates_per_second = float(final_client_trips) / float(final_wall_clock_s)

    weight_rpi4 = _summary_number(summary, ("fairness/run_weight_total_rpi4",))
    weight_rpi5 = _summary_number(summary, ("fairness/run_weight_total_rpi5",))
    rpi4_weight_share = None
    if weight_rpi4 is not None and weight_rpi5 is not None and weight_rpi4 + weight_rpi5 > 0:
        rpi4_weight_share = weight_rpi4 / (weight_rpi4 + weight_rpi5)

    return SummaryRow(
        profile=spec.profile,
        method=spec.method,
        buffer_size=spec.buffer_size,
        seed=spec.seed,
        run_id=spec.run_id,
        source=spec.source,
        target_reached=bool(summary.get("target/reached")),
        target_client_trips=int(target_trips) if target_trips is not None else None,
        target_wall_clock_s=float(target_wall) if target_wall is not None else None,
        final_acc=float(final_acc) if final_acc is not None else None,
        final_client_trips=int(final_client_trips) if final_client_trips is not None else None,
        final_wall_clock_s=float(final_wall_clock_s) if final_wall_clock_s is not None else None,
        rpi4_update_share=_summary_number(summary, ("fairness/run_update_share_rpi4",)),
        rpi4_weight_share=rpi4_weight_share,
        rpi4_staleness=_summary_number(summary, ("fairness/run_avg_staleness_rpi4",)),
        rpi5_staleness=_summary_number(summary, ("fairness/run_avg_staleness_rpi5",)),
        updates_per_second=updates_per_second,
    )


def _write_cache(rows: list[SummaryRow]) -> None:
    write_csv_plot(
        SUMMARY_FILENAME,
        FIELDS,
        (
            [
                row.profile,
                row.method,
                row.buffer_size if row.buffer_size is not None else "",
                row.seed,
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
    path = plot_output_path(SUMMARY_FILENAME)
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
                    seed=int(row["seed"]),
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
    expected = {(spec.profile, spec.method, spec.buffer_size, spec.seed, spec.run_id) for spec in RUNS}
    actual = {(row.profile, row.method, row.buffer_size, row.seed, row.run_id) for row in rows}
    return rows if actual == expected else []


def fetch_or_load() -> list[SummaryRow]:
    cached = _load_cache()
    if cached:
        return cached
    api = wandb.Api(timeout=60)
    run_map = _fetch_run_map(api)
    rows = [_row_from_run(spec, run_map[spec.run_id]) for spec in RUNS]
    _write_cache(rows)
    return rows


def _fmt_mean_pm(
    values: Iterable[float],
    *,
    decimals: int,
    scale: float = 1.0,
    prefix: str = "",
    suffix: str = "",
) -> str:
    mean, std = _mean_std(value * scale for value in values)
    return rf"\({prefix}{mean:.{decimals}f} \pm {std:.{decimals}f}{suffix}\)"


def _fmt_mean(values: Iterable[float], *, decimals: int, scale: float = 1.0, suffix: str = "") -> str:
    mean, _ = _mean_std(value * scale for value in values)
    return rf"\({mean:.{decimals}f}{suffix}\)"


def _fmt_target(rows: list[SummaryRow], *, field: str, decimals: int) -> str:
    values: list[float] = []
    censored = False
    for row in rows:
        if field == "trips":
            if row.target_reached and row.target_client_trips is not None:
                values.append(float(row.target_client_trips))
            elif row.final_client_trips is not None:
                values.append(float(row.final_client_trips))
                censored = True
        elif field == "wall":
            if row.target_reached and row.target_wall_clock_s is not None:
                values.append(float(row.target_wall_clock_s))
            elif row.final_wall_clock_s is not None:
                values.append(float(row.final_wall_clock_s))
                censored = True
        else:
            raise ValueError(f"unknown target field {field!r}")
    formatted = _fmt_mean_pm(values, decimals=decimals)
    return rf"\cellcolor{{gray!12}}{formatted}" if censored else formatted


def _fmt_profile_cell(profile: str) -> str:
    return rf"\multirow{{{len(VARIANT_ORDER)}}}{{=}}{{{PROFILE_LABELS[profile]}}}"


def _latex_rows(rows: list[SummaryRow]) -> str:
    by_group: dict[tuple[str, str, int | None], list[SummaryRow]] = {}
    for spec in RUNS:
        key = (spec.profile, spec.method, spec.buffer_size)
        by_group.setdefault(key, [])
    for row in rows:
        by_group[(row.profile, row.method, row.buffer_size)].append(row)

    lines: list[str] = []
    for profile in PROFILE_ORDER:
        for idx, (method, buffer_size) in enumerate(VARIANT_ORDER):
            group = sorted(by_group[(profile, method, buffer_size)], key=lambda row: row.seed)
            spec = next(spec for spec in RUNS if (spec.profile, spec.method, spec.buffer_size) == (profile, method, buffer_size))
            prefix = _fmt_profile_cell(profile) + "\n & " if idx == 0 else " & "
            if method == "fedavg":
                diagnostics = ["--", "--", "-- / --", "--"]
            else:
                diagnostics = [
                    _fmt_mean_pm(
                        (row.rpi4_update_share for row in group if row.rpi4_update_share is not None),
                        decimals=1,
                        scale=100,
                    ),
                    _fmt_mean_pm(
                        (row.rpi4_weight_share for row in group if row.rpi4_weight_share is not None),
                        decimals=1,
                        scale=100,
                    ),
                    _fmt_mean((row.rpi4_staleness for row in group if row.rpi4_staleness is not None), decimals=2)
                    + " / "
                    + _fmt_mean((row.rpi5_staleness for row in group if row.rpi5_staleness is not None), decimals=2),
                    _fmt_mean((row.updates_per_second for row in group if row.updates_per_second is not None), decimals=3),
                ]
            line = (
                prefix
                + f"{spec.label} & "
                + _fmt_target(group, field="trips", decimals=0)
                + " & "
                + _fmt_target(group, field="wall", decimals=0)
                + " & "
                + _fmt_mean_pm((row.final_acc for row in group if row.final_acc is not None), decimals=1, scale=100)
                + " & "
                + " & ".join(diagnostics)
                + r" \\"
            )
            lines.append(line)
        if profile != PROFILE_ORDER[-1]:
            lines.append(r"\midrule")
    return "\n".join(lines)


def main() -> None:
    rows = fetch_or_load()
    latex = _latex_rows(rows)
    latex_path = plot_output_path(TABLE_FILENAME)
    latex_path.write_text(latex + "\n")
    print(f"Wrote {plot_output_path(SUMMARY_FILENAME)}")
    print(f"Wrote {latex_path}")
    print(latex)


if __name__ == "__main__":
    main()
