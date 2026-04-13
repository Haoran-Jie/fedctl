from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "fedctl_research"
    / "src"
)
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from fedctl_research.wandb_logging import WandbExperimentLogger, create_experiment_logger  # noqa: E402


class _FakeWandbRun:
    def __init__(self, *, fail_finish: bool = False, fail_summary_after: int | None = None, **kwargs) -> None:
        self.init_kwargs = kwargs
        self.name = kwargs.get("name", "run")
        self.logged: list[tuple[dict[str, object], int | None]] = []
        self.summary: dict[str, object] = _FakeSummary(fail_after=fail_summary_after)
        self.finished = False
        self.fail_finish = fail_finish

    def log(self, payload: dict[str, object], step: int | None = None) -> None:
        self.logged.append((payload, step))

    def finish(self) -> None:
        if self.fail_finish:
            raise RuntimeError("wandb finish failed")
        self.finished = True


class _FakeWandbModule:
    def __init__(self, *, fail_finish: bool = False, fail_summary_after: int | None = None) -> None:
        self.runs: list[_FakeWandbRun] = []
        self.fail_finish = fail_finish
        self.fail_summary_after = fail_summary_after

    def init(self, **kwargs):
        run = _FakeWandbRun(
            fail_finish=self.fail_finish,
            fail_summary_after=self.fail_summary_after,
            **kwargs,
        )
        self.runs.append(run)
        return run


class _FakeSummary(dict[str, object]):
    def __init__(self, *, fail_after: int | None = None) -> None:
        super().__init__()
        self.fail_after = fail_after
        self.write_count = 0

    def __setitem__(self, key: str, value: object) -> None:
        if self.fail_after is not None and self.write_count >= self.fail_after:
            raise RuntimeError("wandb summary write failed")
        self.write_count += 1
        super().__setitem__(key, value)


def test_create_experiment_logger_uses_run_config_and_env(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")
    monkeypatch.setenv(
        "FEDCTL_EXPERIMENT_CONFIG",
        "apps/fedctl_research/experiment_configs/compute_heterogeneity/main/cifar10_cnn/fedrolex.toml",
    )
    monkeypatch.setenv("FEDCTL_REPO_CONFIG_LABEL", "none")
    monkeypatch.setenv("FEDCTL_SUBMISSION_ID", "sub-20260409-3017")
    monkeypatch.setenv("FEDCTL_ATTEMPT_STARTED_AT", "2026-04-09T10:00:00Z")

    context = SimpleNamespace(
        run_config={
            "method": "fedrolex",
            "task": "cifar10_cnn",
            "seed": 1337,
            "wandb-enabled": True,
            "wandb-project": "fedctl",
            "wandb-entity": "samueljie",
            "wandb-group": "mixed-cluster",
            "wandb-tags": "dissertation,cifar10",
        }
    )

    logger = create_experiment_logger(context)

    assert isinstance(logger, WandbExperimentLogger)
    assert len(fake_wandb.runs) == 1
    init_kwargs = fake_wandb.runs[0].init_kwargs
    assert init_kwargs["project"] == "fedctl"
    assert init_kwargs["entity"] == "samueljie"
    assert init_kwargs["group"] == "mixed-cluster"
    assert set(init_kwargs["tags"]) >= {"demo-exp", "fedrolex", "cifar10_cnn", "dissertation"}
    assert init_kwargs["name"] == "demo-exp-fedrolex-cifar10_cnn-sub3017"
    assert init_kwargs["config"]["fedctl_submission_id"] == "sub-20260409-3017"
    assert init_kwargs["config"]["fedctl_canonical_key"] == (
        "compute-main/cifar10_cnn/fedrolex/seed1337/profile-none"
    )
    assert init_kwargs["config"]["fedctl_attempt_status"] == "running"
    assert init_kwargs["config"]["fedctl_attempt_started_at"] == "2026-04-09T10:00:00Z"


def test_wandb_experiment_logger_logs_and_finishes(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")
    monkeypatch.setenv(
        "FEDCTL_EXPERIMENT_CONFIG",
        "apps/fedctl_research/experiment_configs/compute_heterogeneity/main/fashion_mnist_cnn/heterofl.toml",
    )
    monkeypatch.setenv("FEDCTL_REPO_CONFIG_LABEL", "none")
    monkeypatch.setenv("FEDCTL_SUBMISSION_ID", "sub-20260409-1462")
    monkeypatch.setenv("FEDCTL_ATTEMPT_STARTED_AT", "2026-04-09T11:00:00Z")

    context = SimpleNamespace(
        run_config={
            "method": "heterofl",
            "task": "fashion_mnist_cnn",
            "seed": 1337,
            "wandb-enabled": True,
            "wandb-project": "fedctl",
        }
    )

    logger = create_experiment_logger(context)
    logger.log_train_metrics(1, {"train-loss": 0.5, "num-examples": 32})
    logger.log_client_eval_metrics(1, {"eval-acc": 0.75})
    logger.log_server_eval_metrics(1, {"eval-acc": 0.8, "eval-loss": 0.4})
    logger.log_system_metrics(1, {"round-train-duration-s": 3.2, "round_avg_flops": 1234})
    logger.log_model_catalog(
        {
            "full": {"param_count": 100, "model_size_mb": 1.25, "flops_estimate": 200},
            "rate_0.25": {"param_count": 25, "model_size_mb": 0.4, "flops_estimate": 60},
        }
    )
    logger.log_run_summary(
        total_runtime_s=12.5,
        result=SimpleNamespace(
            train_metrics_clientapp={1: {"train-loss": 0.5, "round-successful-train-replies": 4}},
            evaluate_metrics_clientapp={1: {"eval-acc": 0.75}},
            evaluate_metrics_serverapp={1: {"eval-acc": 0.8, "eval-loss": 0.4}},
        ),
    )
    logger.finish()

    run = fake_wandb.runs[0]
    assert [step for _, step in run.logged] == [1, 1, 1, 1]
    assert run.logged[0][0]["train/train-loss"] == 0.5
    assert run.logged[1][0]["eval_client/eval-acc"] == 0.75
    assert run.logged[2][0]["eval_server/eval-loss"] == 0.4
    assert run.logged[3][0]["system/round-train-duration-s"] == 3.2
    assert run.summary["runtime/total_server_s"] == 12.5
    assert run.summary["model/full/param_count"] == 100
    assert run.summary["model/rate_0.25/flops_estimate"] == 60
    assert run.summary["final/train/train-loss"] == 0.5
    assert run.summary["final/eval_client/eval-acc"] == 0.75
    assert run.summary["final/eval_server/eval-acc"] == 0.8
    assert run.summary["fedctl_submission_id"] == "sub-20260409-1462"
    assert run.summary["fedctl_canonical_key"] == (
        "compute-main/fashion_mnist_cnn/heterofl/seed1337/profile-none"
    )
    assert run.summary["fedctl_attempt_status"] == "completed"
    assert run.summary["fedctl_attempt_started_at"] == "2026-04-09T11:00:00Z"
    assert run.finished is True


def test_wandb_finish_failure_is_non_fatal(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule(fail_finish=True)
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")

    context = SimpleNamespace(
        run_config={
            "method": "fedavg",
            "task": "fashion_mnist_mlp",
            "wandb-enabled": True,
            "wandb-project": "fedctl",
        }
    )

    logger = create_experiment_logger(context)
    logger.finish()

    run = fake_wandb.runs[0]
    assert run.finished is False
    assert logger.disabled is True


def test_wandb_summary_failure_disables_future_logging(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule(fail_summary_after=0)
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")

    context = SimpleNamespace(
        run_config={
            "method": "fedavg",
            "task": "fashion_mnist_mlp",
            "wandb-enabled": True,
            "wandb-project": "fedctl",
        }
    )

    logger = create_experiment_logger(context)
    logger.log_summary_metrics({"runtime/total_server_s": 1.5})
    logger.log_train_metrics(1, {"train-loss": 0.5})
    logger.finish()

    run = fake_wandb.runs[0]
    assert logger.disabled is True
    assert run.logged == []


def test_wandb_retry_attempts_keep_same_canonical_key_but_distinct_names(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")
    monkeypatch.setenv(
        "FEDCTL_EXPERIMENT_CONFIG",
        "apps/fedctl_research/experiment_configs/network_heterogeneity/main/cifar10_cnn/fedbuff.toml",
    )
    monkeypatch.setenv("FEDCTL_REPO_CONFIG_LABEL", "none")
    monkeypatch.setenv("FEDCTL_ATTEMPT_STARTED_AT", "2026-04-09T12:00:00Z")

    context = SimpleNamespace(
        run_config={
            "method": "fedbuff",
            "task": "cifar10_cnn",
            "seed": 1337,
            "wandb-enabled": True,
            "wandb-project": "fedctl",
        }
    )

    monkeypatch.setenv("FEDCTL_SUBMISSION_ID", "sub-20260409-1001")
    first = create_experiment_logger(context)
    monkeypatch.setenv("FEDCTL_SUBMISSION_ID", "sub-20260409-1002")
    second = create_experiment_logger(context)

    first_run = fake_wandb.runs[0]
    second_run = fake_wandb.runs[1]
    assert first_run.init_kwargs["config"]["fedctl_canonical_key"] == (
        "network-main/cifar10_cnn/fedbuff/seed1337/profile-none"
    )
    assert second_run.init_kwargs["config"]["fedctl_canonical_key"] == (
        "network-main/cifar10_cnn/fedbuff/seed1337/profile-none"
    )
    assert first_run.init_kwargs["name"] == "demo-exp-fedbuff-cifar10_cnn-sub1001"
    assert second_run.init_kwargs["name"] == "demo-exp-fedbuff-cifar10_cnn-sub1002"
    assert first.canonical_key == second.canonical_key
