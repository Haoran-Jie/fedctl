#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import wandb

ROOT = Path(__file__).resolve().parent.parent
PLOT_OUTPUT = ROOT / "plot" / "output"
TMPDIR = ROOT / "tmp" / "wandb_compute_main_runtime_decomposition"
ENTITY = "samueljie1-the-university-of-cambridge"
PROJECT = "fedctl"

METHOD_ORDER = ("fedavg", "heterofl", "fedrolex", "fiarse")
METHOD_TITLES = {
    "fedavg": r"\texttt{FedAvg}",
    "heterofl": r"\texttt{HeteroFL}",
    "fedrolex": r"\texttt{FedRolex}",
    "fiarse": r"\texttt{FIARSE}",
}
TASK_TITLES = {
    "california_housing_mlp": r"California Housing",
    "cifar10_cnn": r"CIFAR-10",
}
REGIME_TITLES = {
    "iid": "IID",
    "noniid": "non-IID",
}

RUNS = (
    # task, regime, method, seed, run_id
    ("california_housing_mlp", "iid", "fedavg", 1337, "fnwf3920"),
    ("california_housing_mlp", "iid", "fedavg", 1338, "k8snz3ji"),
    ("california_housing_mlp", "iid", "fedavg", 1339, "yss976jq"),
    ("california_housing_mlp", "iid", "heterofl", 1337, "jdjkltsl"),
    ("california_housing_mlp", "iid", "heterofl", 1338, "97z0ogzq"),
    ("california_housing_mlp", "iid", "heterofl", 1339, "cyti2mx5"),
    ("california_housing_mlp", "iid", "fedrolex", 1337, "qxlnfxpu"),
    ("california_housing_mlp", "iid", "fedrolex", 1338, "kp7fjsgl"),
    ("california_housing_mlp", "iid", "fedrolex", 1339, "nj7tsv5o"),
    ("california_housing_mlp", "iid", "fiarse", 1337, "dj71fc89"),
    ("california_housing_mlp", "iid", "fiarse", 1338, "3aa8qxje"),
    ("california_housing_mlp", "iid", "fiarse", 1339, "urgz971e"),
    ("california_housing_mlp", "noniid", "fedavg", 1337, "aud329ev"),
    ("california_housing_mlp", "noniid", "fedavg", 1338, "1n7h3zdf"),
    ("california_housing_mlp", "noniid", "fedavg", 1339, "r3j45xob"),
    ("california_housing_mlp", "noniid", "heterofl", 1337, "5trnnxj2"),
    ("california_housing_mlp", "noniid", "heterofl", 1338, "9uza2doa"),
    ("california_housing_mlp", "noniid", "heterofl", 1339, "9l37ywze"),
    ("california_housing_mlp", "noniid", "fedrolex", 1337, "tsh2vjv1"),
    ("california_housing_mlp", "noniid", "fedrolex", 1338, "jikxrtql"),
    ("california_housing_mlp", "noniid", "fedrolex", 1339, "ptevhxdo"),
    ("california_housing_mlp", "noniid", "fiarse", 1337, "2iu154j5"),
    ("california_housing_mlp", "noniid", "fiarse", 1338, "zf9dv3nf"),
    ("california_housing_mlp", "noniid", "fiarse", 1339, "09teh2jn"),
    ("cifar10_cnn", "iid", "fedavg", 1337, "1zkfor5s"),
    ("cifar10_cnn", "iid", "fedavg", 1338, "ft0s0pjm"),
    ("cifar10_cnn", "iid", "fedavg", 1339, "9h4hr570"),
    ("cifar10_cnn", "iid", "heterofl", 1337, "gucmw04b"),
    ("cifar10_cnn", "iid", "heterofl", 1338, "369blbfa"),
    ("cifar10_cnn", "iid", "heterofl", 1339, "p1b68rfp"),
    ("cifar10_cnn", "iid", "fedrolex", 1337, "qv9ns7bf"),
    ("cifar10_cnn", "iid", "fedrolex", 1338, "3moap2c9"),
    ("cifar10_cnn", "iid", "fedrolex", 1339, "ppd09xho"),
    ("cifar10_cnn", "iid", "fiarse", 1337, "8u3yzs3h"),
    ("cifar10_cnn", "iid", "fiarse", 1338, "epkcwli4"),
    ("cifar10_cnn", "iid", "fiarse", 1339, "fn79oxwl"),
    ("cifar10_cnn", "noniid", "fedavg", 1337, "hucmjiwu"),
    ("cifar10_cnn", "noniid", "fedavg", 1338, "3enb2mhp"),
    ("cifar10_cnn", "noniid", "fedavg", 1339, "oo34c156"),
    ("cifar10_cnn", "noniid", "heterofl", 1337, "dqpa3l1l"),
    ("cifar10_cnn", "noniid", "heterofl", 1338, "aw00uw2s"),
    ("cifar10_cnn", "noniid", "heterofl", 1339, "1wwq4bnu"),
    ("cifar10_cnn", "noniid", "fedrolex", 1337, "k5sau99r"),
    ("cifar10_cnn", "noniid", "fedrolex", 1338, "0o4e5trn"),
    ("cifar10_cnn", "noniid", "fedrolex", 1339, "mcx84zop"),
    ("cifar10_cnn", "noniid", "fiarse", 1337, "0fkj0quv"),
    ("cifar10_cnn", "noniid", "fiarse", 1338, "t1xizie2"),
    ("cifar10_cnn", "noniid", "fiarse", 1339, "6ibt9sv7"),
)

METRICS = {
    "train_round_s": ("round_system/train_duration_s", "system/round-train-duration-s"),
    "client_train_mean_s": ("round_client_stats/train_duration_mean_s", "system/round-train-client-duration-mean-s", "train/train-duration-s"),
    "client_train_std_s": ("round_client_stats/train_duration_std_s", "system/round-train-client-duration-std-s"),
    "client_eval_round_s": ("round_system/client_eval_duration_s", "system/round-client-eval-duration-s"),
    "server_eval_s": ("round_system/server_eval_duration_s", "system/round-server-eval-duration-s"),
}
HISTORY_KEYS = sorted({key for keys in METRICS.values() for key in keys} | {"server_round"})

@dataclass(frozen=True)
class RunSpec:
    task: str
    regime: str
    method: str
    seed: int
    run_id: str

@dataclass(frozen=True)
class RunMetrics:
    task: str
    regime: str
    method: str
    seed: int
    run_id: str
    total_runtime_s: float
    train_round_s: float
    client_train_mean_s: float
    client_train_std_s: float
    client_eval_round_s: float
    server_eval_s: float


def _mean(values: Iterable[float | None]) -> float:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not clean:
        return float("nan")
    return statistics.fmean(clean)


def _std(values: list[float]) -> float:
    clean = [float(v) for v in values if math.isfinite(float(v))]
    if len(clean) < 2:
        return 0.0
    return statistics.stdev(clean)


def _first_present(row: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                return value
    return None


def _load_cached() -> list[RunMetrics]:
    path = PLOT_OUTPUT / "compute_main_runtime_decomposition_raw.csv"
    if not path.exists():
        return []
    rows = []
    with path.open(newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(RunMetrics(
                task=raw["task"], regime=raw["regime"], method=raw["method"], seed=int(raw["seed"]), run_id=raw["run_id"],
                total_runtime_s=float(raw["total_runtime_s"]), train_round_s=float(raw["train_round_s"]),
                client_train_mean_s=float(raw["client_train_mean_s"]), client_train_std_s=float(raw["client_train_std_s"]),
                client_eval_round_s=float(raw["client_eval_round_s"]), server_eval_s=float(raw["server_eval_s"]),
            ))
    return rows


def _fetch_run(api: wandb.Api, spec: RunSpec) -> RunMetrics:
    run = api.run(f"{ENTITY}/{PROJECT}/{spec.run_id}")
    summary = run.summary
    total_runtime_s = summary.get("runtime/total_server_s") or summary.get("run_system/total_server_s")
    if total_runtime_s is None:
        raise RuntimeError(f"missing total runtime for {spec.run_id}")

    values = {metric: [] for metric in METRICS}
    for row in run.scan_history(page_size=200):
        server_round = row.get("server_round")
        if server_round is not None:
            try:
                if int(server_round) <= 0:
                    continue
            except (TypeError, ValueError):
                pass
        for metric, keys in METRICS.items():
            values[metric].append(_first_present(row, keys))

    return RunMetrics(
        task=spec.task,
        regime=spec.regime,
        method=spec.method,
        seed=spec.seed,
        run_id=spec.run_id,
        total_runtime_s=float(total_runtime_s),
        train_round_s=_mean(values["train_round_s"]),
        client_train_mean_s=_mean(values["client_train_mean_s"]),
        client_train_std_s=_mean(values["client_train_std_s"]),
        client_eval_round_s=_mean(values["client_eval_round_s"]),
        server_eval_s=_mean(values["server_eval_s"]),
    )


def _fmt_mean_std(values: list[float], digits: int = 1) -> str:
    clean = [v for v in values if math.isfinite(v)]
    if not clean:
        return "--"
    return f"{statistics.fmean(clean):.{digits}f}$\\pm${_std(clean):.{digits}f}"


def _fmt_relative(value: float, baseline: float) -> str:
    if not math.isfinite(value) or not math.isfinite(baseline) or baseline <= 0:
        return "--"
    return f"{value / baseline:.2f}$\\times$"


def _latex_table(rows: list[RunMetrics]) -> str:
    lines = [
        r"\begin{table}[H]",
        r"\centering",
        r"\scriptsize",
        r"\renewcommand{\arraystretch}{1.08}",
        r"\setlength{\tabcolsep}{2.7pt}",
        r"\caption{\textbf{Compute-main runtime and bottleneck decomposition.} Entries report mean $\pm$ standard deviation over completed seeds \texttt{1337}, \texttt{1338}, and \texttt{1339}. Runtime is end-to-end server-observed training time from \texttt{runtime/total\_server\_s}. Train round is the wall-clock latency of the synchronous training phase in each round; client train mean/std summarise the client-reported local training durations within a round; client eval is the synchronous client-evaluation phase; server eval is centralized evaluation time. Lower is better for all timing columns.}",
        r"\label{tab:compute_main_runtime}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{@{}lllrrrrrrr@{}}",
        r"\toprule",
        r"Regime & Task & Method & \makecell[c]{Runtime\\(min)} & Rel. & \makecell[c]{Train\\round (s)} & \makecell[c]{Client train\\mean (s)} & \makecell[c]{Client train\\std (s)} & \makecell[c]{Client eval\\round (s)} & \makecell[c]{Server\\eval (s)} \\",
        r"\midrule",
    ]
    first_block = True
    for regime in ("iid", "noniid"):
        for task in ("california_housing_mlp", "cifar10_cnn"):
            block = [r for r in rows if r.regime == regime and r.task == task]
            if not block:
                continue
            if not first_block:
                lines.append(r"\midrule")
            first_block = False
            runtime_means = {
                method: statistics.fmean([r.total_runtime_s / 60.0 for r in block if r.method == method])
                for method in METHOD_ORDER
                if any(r.method == method for r in block)
            }
            best_runtime = min(runtime_means.values())
            first_method = True
            for method in METHOD_ORDER:
                method_rows = [r for r in block if r.method == method]
                if not method_rows:
                    continue
                runtime_values = [r.total_runtime_s / 60.0 for r in method_rows]
                runtime_mean = statistics.fmean(runtime_values)
                runtime_cell = _fmt_mean_std(runtime_values)
                if abs(runtime_mean - best_runtime) < 1e-9:
                    runtime_cell = rf"\textbf{{{runtime_cell}}}"
                regime_cell = REGIME_TITLES[regime] if first_method else ""
                task_cell = TASK_TITLES[task] if first_method else ""
                first_method = False
                lines.append(
                    " & ".join([
                        regime_cell,
                        task_cell,
                        METHOD_TITLES[method],
                        runtime_cell,
                        _fmt_relative(runtime_mean, best_runtime),
                        _fmt_mean_std([r.train_round_s for r in method_rows]),
                        _fmt_mean_std([r.client_train_mean_s for r in method_rows]),
                        _fmt_mean_std([r.client_train_std_s for r in method_rows]),
                        _fmt_mean_std([r.client_eval_round_s for r in method_rows]),
                        _fmt_mean_std([r.server_eval_s for r in method_rows]),
                    ]) + r" \\"
                )
    lines.extend([r"\bottomrule", r"\end{tabular}%", r"}", r"\end{table}", ""])
    return "\n".join(lines)


def main() -> None:
    PLOT_OUTPUT.mkdir(parents=True, exist_ok=True)
    TMPDIR.mkdir(parents=True, exist_ok=True)

    rows = _load_cached()
    metric_names = (
        "train_round_s",
        "client_train_mean_s",
        "client_train_std_s",
        "client_eval_round_s",
        "server_eval_s",
    )
    if rows and any(not math.isfinite(getattr(row, metric)) for row in rows for metric in metric_names):
        rows = []
    if not rows:
        api = wandb.Api(timeout=30)
        rows = [_fetch_run(api, RunSpec(*spec)) for spec in RUNS]

    raw_path = PLOT_OUTPUT / "compute_main_runtime_decomposition_raw.csv"
    with raw_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "task", "regime", "method", "seed", "run_id", "total_runtime_s", "train_round_s",
            "client_train_mean_s", "client_train_std_s", "client_eval_round_s", "server_eval_s",
        ])
        for r in rows:
            writer.writerow([
                r.task, r.regime, r.method, r.seed, r.run_id, r.total_runtime_s, r.train_round_s,
                r.client_train_mean_s, r.client_train_std_s, r.client_eval_round_s, r.server_eval_s,
            ])

    coverage = {
        "runs": len(rows),
        "expected_runs": len(RUNS),
        "missing_metric_counts": {
            metric: sum(not math.isfinite(getattr(r, metric)) for r in rows)
            for metric in ("train_round_s", "client_train_mean_s", "client_train_std_s", "client_eval_round_s", "server_eval_s")
        },
    }
    coverage_path = PLOT_OUTPUT / "compute_main_runtime_decomposition_coverage.json"
    coverage_path.write_text(json.dumps(coverage, indent=2))

    tex = _latex_table(rows)
    tex_path = PLOT_OUTPUT / "compute_main_runtime_decomposition.tex"
    tex_path.write_text(tex)
    print(json.dumps({"raw": str(raw_path), "coverage": str(coverage_path), "tex": str(tex_path), **coverage}, indent=2))

if __name__ == "__main__":
    main()
