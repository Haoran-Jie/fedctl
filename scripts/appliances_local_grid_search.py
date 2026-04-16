from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_SRC = REPO_ROOT / "apps" / "fedctl_research" / "src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from fedctl_research.runtime.regression import evaluate_regressor, train_regressor
from fedctl_research.tasks.appliances_energy.data import CSV_PATH, DOWNLOAD_LOCK, datasets_pair
from fedctl_research.tasks.appliances_energy.mlp import build_model_for_rate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a local centralized hyperparameter sweep for appliances_energy_mlp."
    )
    parser.add_argument(
        "--learning-rates",
        nargs="+",
        type=float,
        default=[1e-3, 3e-3, 1e-2],
        help="Learning rates to sweep.",
    )
    parser.add_argument(
        "--local-epochs",
        nargs="+",
        type=int,
        default=[1, 3, 5],
        help="Local epoch counts to sweep.",
    )
    parser.add_argument("--seed", type=int, default=1337, help="Torch random seed.")
    parser.add_argument(
        "--train-batch-size", type=int, default=128, help="Centralized train batch size."
    )
    parser.add_argument(
        "--test-batch-size", type=int, default=256, help="Centralized test batch size."
    )
    parser.add_argument(
        "--optimizer",
        default="adam",
        choices=["adam", "sgd", "adamw"],
        help="Optimizer to use.",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "tmp" / "appliances_local_grid_search.csv"),
        help="CSV path to write results to.",
    )
    parser.add_argument(
        "--stale-lock-seconds",
        type=int,
        default=300,
        help="Remove the dataset lock if it is older than this and the CSV is still missing.",
    )
    parser.add_argument(
        "--single-run",
        action="store_true",
        help="Run exactly one (lr, epochs) combination and still write the CSV output.",
    )
    return parser.parse_args()


def clear_stale_download_lock(max_age_seconds: int) -> None:
    if CSV_PATH.exists() or not DOWNLOAD_LOCK.exists():
        return
    age_seconds = time.time() - DOWNLOAD_LOCK.stat().st_mtime
    if age_seconds < max_age_seconds:
        return
    DOWNLOAD_LOCK.unlink(missing_ok=True)
    print(
        f"[grid] removed stale dataset lock at {DOWNLOAD_LOCK} age_s={age_seconds:.1f}",
        flush=True,
    )


def run_sweep(args: argparse.Namespace) -> list[dict[str, float | int | str]]:
    clear_stale_download_lock(args.stale_lock_seconds)
    if CSV_PATH.exists():
        print(f"[grid] using cached dataset at {CSV_PATH}", flush=True)
    else:
        print(f"[grid] dataset not cached yet; loader will download to {CSV_PATH}", flush=True)
    print("[grid] loading and preprocessing dataset", flush=True)
    trainset, testset = datasets_pair()
    print(
        f"[grid] dataset ready train_examples={len(trainset)} test_examples={len(testset)}",
        flush=True,
    )
    trainloader = DataLoader(
        trainset,
        batch_size=args.train_batch_size,
        shuffle=True,
        num_workers=0,
    )
    testloader = DataLoader(
        testset,
        batch_size=args.test_batch_size,
        shuffle=False,
        num_workers=0,
    )

    results: list[dict[str, float | int | str]] = []
    for local_epochs in args.local_epochs:
        for learning_rate in args.learning_rates:
            torch.manual_seed(args.seed)
            model = build_model_for_rate(1.0)
            print(
                f"[grid] start lr={learning_rate} local_epochs={local_epochs} seed={args.seed}",
                flush=True,
            )
            train_loss = train_regressor(
                model,
                trainloader,
                local_epochs,
                learning_rate,
                "cpu",
                optimizer=args.optimizer,
                log_prefix=f"[appliances grid lr={learning_rate} ep={local_epochs}]",
            )
            test_loss, r2 = evaluate_regressor(model, testloader, "cpu")
            row: dict[str, float | int | str] = {
                "optimizer": args.optimizer,
                "seed": args.seed,
                "learning_rate": learning_rate,
                "local_epochs": local_epochs,
                "train_loss": train_loss,
                "test_loss": test_loss,
                "r2": r2,
            }
            results.append(row)
            print(f"[grid] result {row}", flush=True)
            if args.single_run:
                return results
    return results


def write_results(path: Path, rows: list[dict[str, float | int | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "optimizer",
        "seed",
        "learning_rate",
        "local_epochs",
        "train_loss",
        "test_loss",
        "r2",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    rows = run_sweep(args)
    output_path = Path(args.output)
    write_results(output_path, rows)
    best = max(rows, key=lambda row: float(row["r2"]))
    print(f"[grid] wrote results to {output_path}", flush=True)
    print(f"[grid] best {best}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
