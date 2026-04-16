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

try:
    from tqdm.auto import tqdm
except ImportError as exc:  # pragma: no cover - user-facing dependency hint
    raise SystemExit(
        "tqdm is not installed in .venv. Run: ./.venv/bin/python -m pip install tqdm"
    ) from exc

from fedctl_research.runtime.classification import create_optimizer
from fedctl_research.runtime.regression import evaluate_regressor, regression_mse_loss
from fedctl_research.tasks.appliances_energy.data import CSV_PATH, DOWNLOAD_LOCK, datasets_pair
from fedctl_research.tasks.appliances_energy.mlp import build_model_for_rate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a single centralized Appliances MLP experiment with tqdm progress."
    )
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--optimizer", choices=["adam", "adamw", "sgd"], default="adam")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--train-batch-size", type=int, default=128)
    parser.add_argument("--test-batch-size", type=int, default=256)
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "tmp" / "appliances_single_run_tqdm.csv"),
        help="CSV path for per-epoch metrics.",
    )
    parser.add_argument(
        "--stale-lock-seconds",
        type=int,
        default=300,
        help="Remove the dataset lock if it is older than this and the CSV is still missing.",
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
        f"[single-run] removed stale dataset lock at {DOWNLOAD_LOCK} age_s={age_seconds:.1f}",
        flush=True,
    )


def write_epoch_rows(path: Path, rows: list[dict[str, float | int | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "epoch",
        "learning_rate",
        "optimizer",
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
    clear_stale_download_lock(args.stale_lock_seconds)
    if CSV_PATH.exists():
        print(f"[single-run] using cached dataset at {CSV_PATH}", flush=True)
    else:
        print(f"[single-run] dataset not cached yet; loader will download to {CSV_PATH}", flush=True)
    print("[single-run] loading and preprocessing dataset", flush=True)
    trainset, testset = datasets_pair()
    print(
        f"[single-run] dataset ready train_examples={len(trainset)} test_examples={len(testset)}",
        flush=True,
    )

    torch.manual_seed(args.seed)
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
    model = build_model_for_rate(1.0)
    optimizer = create_optimizer(args.optimizer, model.parameters(), lr=args.learning_rate)
    device = torch.device("cpu")
    model.to(device)

    epoch_rows: list[dict[str, float | int | str]] = []
    epoch_bar = tqdm(range(1, args.epochs + 1), desc="epochs", unit="epoch")
    for epoch in epoch_bar:
        model.train()
        running_loss = 0.0
        batch_count = 0
        batch_bar = tqdm(
            trainloader,
            desc=f"epoch {epoch:03d}",
            unit="batch",
            leave=False,
        )
        for features, labels in batch_bar:
            features = features.to(device)
            labels = labels.to(device)
            optimizer.zero_grad()
            predictions = model(features)
            loss = regression_mse_loss(predictions, labels)
            loss.backward()
            optimizer.step()

            loss_value = float(loss.item())
            running_loss += loss_value
            batch_count += 1
            batch_bar.set_postfix(batch_loss=f"{loss_value:.4f}", avg_loss=f"{running_loss / batch_count:.4f}")

        train_loss = running_loss / max(batch_count, 1)
        test_loss, r2 = evaluate_regressor(model, testloader, device)
        row: dict[str, float | int | str] = {
            "epoch": epoch,
            "learning_rate": args.learning_rate,
            "optimizer": args.optimizer,
            "train_loss": train_loss,
            "test_loss": test_loss,
            "r2": r2,
        }
        epoch_rows.append(row)
        epoch_bar.set_postfix(train_loss=f"{train_loss:.4f}", test_loss=f"{test_loss:.4f}", r2=f"{r2:.4f}")

    output_path = Path(args.output)
    write_epoch_rows(output_path, epoch_rows)
    best = max(epoch_rows, key=lambda row: float(row["r2"]))
    print(f"[single-run] wrote per-epoch metrics to {output_path}", flush=True)
    print(f"[single-run] best epoch {best['epoch']} r2={float(best['r2']):.6f} test_loss={float(best['test_loss']):.6f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
