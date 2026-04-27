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

from fedctl_research.wandb_logging import (  # noqa: E402
    WandbExperimentLogger,
    _wandb_safe_tag,
    create_experiment_logger,
)


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
        self.tables: list[_FakeTable] = []
        self.metric_definitions: list[tuple[str, dict[str, object]]] = []

    def init(self, **kwargs):
        run = _FakeWandbRun(
            fail_finish=self.fail_finish,
            fail_summary_after=self.fail_summary_after,
            **kwargs,
        )
        self.runs.append(run)
        return run

    def Table(self, *, columns, data):
        table = _FakeTable(columns=columns, data=data)
        self.tables.append(table)
        return table

    def define_metric(self, name: str, **kwargs) -> None:
        self.metric_definitions.append((name, kwargs))


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


class _FakeTable:
    def __init__(self, *, columns, data) -> None:
        self.columns = list(columns)
        self.data = list(data)


def test_create_experiment_logger_uses_run_config_and_env(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")
    monkeypatch.setenv(
        "FEDCTL_EXPERIMENT_CONFIG",
        "apps/fedctl_research/experiment_configs/compute_heterogeneity/main/cifar10_cnn/iid/fedrolex.toml",
    )
    monkeypatch.setenv("FEDCTL_REPO_CONFIG_LABEL", "none")
    monkeypatch.setenv("FEDCTL_SUBMISSION_ID", "sub-20260409-3017")
    monkeypatch.setenv("FEDCTL_ATTEMPT_STARTED_AT", "2026-04-09T10:00:00Z")

    context = SimpleNamespace(
        run_config={
            "method": "fedrolex",
            "task": "cifar10_cnn",
            "seed": 1337,
            "min-available-nodes": 20,
            "model-rate-levels": "1.0,0.5,0.25,0.125",
            "model-rate-proportions": "0.25,0.25,0.25,0.25",
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
    assert set(init_kwargs["tags"]) >= {
        "demo-exp",
        "fedrolex",
        "cifar10_cnn",
        "dissertation",
        "profile-none",
    }
    assert (
        init_kwargs["name"]
        == "demo-exp"
    )
    assert init_kwargs["config"]["fedctl_submission_id"] == "sub-20260409-3017"
    assert init_kwargs["config"]["fedctl_canonical_key"] == (
        "compute-main/cifar10_cnn/fedrolex/n20/split-1x25_0p5x25_0p25x25_0p125x25/seed1337/profile-none"
    )
    assert init_kwargs["config"]["fedctl_repo_config_label"] == "none"
    assert init_kwargs["config"]["fedctl_node_count_label"] == "n20"
    assert init_kwargs["config"]["fedctl_capacity_split_label"] == "split-1x25_0p5x25_0p25x25_0p125x25"
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
            "min-available-nodes": 12,
            "model-rate-levels": "1.0,0.5,0.25,0.125,0.0625",
            "model-rate-proportions": "0.2,0.2,0.2,0.2,0.2",
            "wandb-enabled": True,
            "wandb-project": "fedctl",
        }
    )

    logger = create_experiment_logger(context)
    logger.log_train_metrics(1, {"train-loss": 0.5, "num-examples": 32})
    logger.log_client_eval_metrics(1, {"eval-acc": 0.75})
    logger.log_server_eval_metrics(1, {"eval-acc": 0.8, "eval-loss": 0.4})
    logger.log_server_eval_trip_metrics(17, {"eval-acc": 0.8, "eval-loss": 0.4})
    logger.log_server_eval_group_metrics(1, "rpi4-held", {"eval-acc": 0.7, "eval-loss": 0.5})
    logger.log_server_eval_group_trip_metrics(17, "rpi4-held", {"eval-acc": 0.7, "eval-loss": 0.5})
    logger.log_system_metrics(
        1,
        {
            "round-train-duration-s": 3.2,
            "round_avg_flops": 1234,
            "rpi4_examples_per_second_mean": 12.5,
        },
    )
    logger.log_summary_metrics({"target/reached": True, "target/client_trips_to_target": 17})
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
    assert [step for _, step in run.logged] == [None, None, None, None, None, None, None]
    assert run.logged[0][0]["train/train-loss"] == 0.5
    assert run.logged[0][0]["server_round"] == 1
    assert run.logged[1][0]["eval_client/eval-acc"] == 0.75
    assert run.logged[2][0]["eval_server/eval-loss"] == 0.4
    assert run.logged[3][0]["eval_server_trip/eval-loss"] == 0.4
    assert run.logged[3][0]["client_trip"] == 17
    assert run.logged[4][0]["eval_server_group/rpi4-held/eval-acc"] == 0.7
    assert run.logged[4][0]["server_round"] == 1
    assert run.logged[5][0]["eval_server_group_trip/rpi4-held/eval-acc"] == 0.7
    assert run.logged[5][0]["client_trip"] == 17
    assert run.logged[6][0]["system/round-train-duration-s"] == 3.2
    assert run.logged[6][0]["round_system/train_duration_s"] == 3.2
    assert run.logged[6][0]["round_cost/avg_flops"] == 1234
    assert run.logged[6][0]["round_device/rpi4/examples_per_second_mean"] == 12.5
    assert run.logged[6][0]["server_round"] == 1
    assert run.summary["runtime/total_server_s"] == 12.5
    assert run.summary["run_system/total_server_s"] == 12.5
    assert run.summary["model/full/param_count"] == 100
    assert run.summary["model/rate_0.25/flops_estimate"] == 60
    assert run.summary["target/reached"] == 1
    assert run.summary["target/client_trips_to_target"] == 17
    assert run.summary["final/train/train-loss"] == 0.5
    assert run.summary["final/eval_client/eval-acc"] == 0.75
    assert run.summary["final/eval_server/eval-acc"] == 0.8
    assert run.summary["fedctl_submission_id"] == "sub-20260409-1462"
    assert run.summary["fedctl_canonical_key"] == (
        "compute-main/fashion_mnist_cnn/heterofl/n12/split-1x20_0p5x20_0p25x20_0p125x20_0p0625x20/seed1337/profile-none"
    )
    assert run.summary["fedctl_attempt_status"] == "completed"
    assert run.summary["fedctl_attempt_started_at"] == "2026-04-09T11:00:00Z"
    assert run.finished is True
    assert ("eval_server_trip/*", {"step_metric": "client_trip"}) in fake_wandb.metric_definitions
    assert ("eval_server_group/rpi4-held/*", {"step_metric": "server_round"}) in fake_wandb.metric_definitions
    assert ("eval_server_group/rpi5-held/*", {"step_metric": "server_round"}) in fake_wandb.metric_definitions
    assert ("eval_server_group_trip/rpi4-held/*", {"step_metric": "client_trip"}) in fake_wandb.metric_definitions
    assert ("eval_server_group_trip/rpi5-held/*", {"step_metric": "client_trip"}) in fake_wandb.metric_definitions
    assert ("train/*", {"step_metric": "server_round"}) in fake_wandb.metric_definitions
    assert ("fedbuff/*", {"step_metric": "server_step"}) in fake_wandb.metric_definitions


def test_wandb_finish_failure_is_non_fatal(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule(fail_finish=True)
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")

    context = SimpleNamespace(
        run_config={
            "method": "fedavg",
            "task": "fashion_mnist_mlp",
            "min-available-nodes": 12,
            "model-rate-levels": "1.0",
            "model-rate-proportions": "1.0",
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
            "min-available-nodes": 12,
            "model-rate-levels": "1.0",
            "model-rate-proportions": "1.0",
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


def test_wandb_retry_attempts_keep_same_canonical_key_and_name(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")
    monkeypatch.setenv(
        "FEDCTL_EXPERIMENT_CONFIG",
        "apps/fedctl_research/experiment_configs/network_heterogeneity/main/cifar10_cnn/noniid/mixed/fedbuff.toml",
    )
    monkeypatch.setenv("FEDCTL_REPO_CONFIG_LABEL", "none")
    monkeypatch.setenv("FEDCTL_ATTEMPT_STARTED_AT", "2026-04-09T12:00:00Z")

    context = SimpleNamespace(
        run_config={
            "method": "fedbuff",
            "task": "cifar10_cnn",
            "seed": 1337,
            "min-available-nodes": 8,
            "model-rate-levels": "1.0",
            "model-rate-proportions": "1.0",
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
        "network-main/cifar10_cnn/fedbuff/n8/split-1x100/seed1337/profile-none"
    )
    assert second_run.init_kwargs["config"]["fedctl_canonical_key"] == (
        "network-main/cifar10_cnn/fedbuff/n8/split-1x100/seed1337/profile-none"
    )
    assert first_run.init_kwargs["name"] == "demo-exp"
    assert second_run.init_kwargs["name"] == "demo-exp"
    assert first.canonical_key == second.canonical_key


def test_wandb_safe_tag_shortens_long_experiment_names() -> None:
    tag = "california_housing_mlp-fiarse-noniid-none-s1338-extra-long-suffix-to-force-shortening"

    safe = _wandb_safe_tag(tag)

    assert len(safe) <= 64
    assert safe.startswith("california_housing_mlp")
    assert safe != tag


def test_create_experiment_logger_sanitizes_long_experiment_tag(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv(
        "FEDCTL_EXPERIMENT",
        "california_housing_mlp-fiarse-noniid-none-s1338",
    )

    context = SimpleNamespace(
        run_config={
            "method": "fiarse",
            "task": "california_housing_mlp",
            "seed": 1338,
            "min-available-nodes": 20,
            "model-rate-levels": "1.0",
            "model-rate-proportions": "1.0",
            "wandb-enabled": True,
            "wandb-project": "fedctl",
        }
    )

    create_experiment_logger(context)

    tags = fake_wandb.runs[0].init_kwargs["tags"]
    long_tags = [tag for tag in tags if tag.startswith("california_housing_mlp-fiarse")]
    assert len(long_tags) == 1
    assert len(long_tags[0]) <= 64


def test_wandb_logger_logs_submodel_client_table(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")

    context = SimpleNamespace(
        run_config={
            "method": "heterofl",
            "task": "cifar10_cnn",
            "min-available-nodes": 20,
            "model-rate-levels": "1.0,0.5,0.25,0.125",
            "model-rate-proportions": "0.25,0.25,0.25,0.25",
            "wandb-enabled": True,
            "wandb-project": "fedctl",
        }
    )

    logger = create_experiment_logger(context)
    logger.log_submodel_client_events(
        20,
        [
            {
                "scope": "local_client",
                "server_step": 20,
                "node_id": 1,
                "device_type": "rpi4",
                "model_rate": 0.25,
                "client_model_rate": 0.25,
                "eval_acc": 0.8,
            },
            {
                "scope": "local_client",
                "server_step": 20,
                "node_id": 2,
                "device_type": "rpi5",
                "model_rate": 0.25,
                "client_model_rate": 1.0,
                "eval_acc": 0.6,
            },
        ],
    )

    run = fake_wandb.runs[0]
    assert len(run.logged) == 1
    payload, step = run.logged[0]
    assert step is None
    assert payload["server_step"] == 20
    table = payload["submodel/local_client_table"]
    assert isinstance(table, _FakeTable)
    assert "client_model_rate" in table.columns
    assert "model_rate" in table.columns
    assert len(table.data) == 2


def test_wandb_logger_logs_per_client_round_and_step_tables(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")

    context = SimpleNamespace(
        run_config={
            "method": "fedavg",
            "task": "cifar10_cnn",
            "min-available-nodes": 20,
            "model-rate-levels": "1.0",
            "model-rate-proportions": "1.0",
            "wandb-enabled": True,
            "wandb-project": "fedctl",
        }
    )

    logger = create_experiment_logger(context)
    logger.log_client_update_events(
        3,
        [
            {
                "server_round": 3,
                "node_id": 1,
                "device_type": "rpi4",
                "update_train_duration_s": 1.2,
            }
        ],
        axis_key="server_round",
    )
    logger.log_client_eval_event_rows(
        3,
        [
            {
                "server_round": 3,
                "node_id": 1,
                "device_type": "rpi4",
                "eval_duration_s": 0.2,
            }
        ],
        axis_key="server_round",
    )
    logger.log_client_update_events(
        7,
        [
            {
                "server_step": 7,
                "client_trips_total": 11,
                "node_id": 2,
                "device_type": "rpi5",
                "update_staleness_server_steps": 2,
            }
        ],
        axis_key="server_step",
    )

    run = fake_wandb.runs[0]
    assert len(run.logged) == 3
    round_train_payload, _ = run.logged[0]
    assert round_train_payload["server_round"] == 3
    round_train_table = round_train_payload["client_update/round_table"]
    assert isinstance(round_train_table, _FakeTable)
    assert "update_train_duration_s" in round_train_table.columns

    round_eval_payload, _ = run.logged[1]
    assert round_eval_payload["server_round"] == 3
    round_eval_table = round_eval_payload["client_eval/round_table"]
    assert isinstance(round_eval_table, _FakeTable)
    assert "eval_duration_s" in round_eval_table.columns

    step_train_payload, _ = run.logged[2]
    assert step_train_payload["server_step"] == 7
    step_train_table = step_train_payload["client_update/step_table"]
    assert isinstance(step_train_table, _FakeTable)
    assert "update_staleness_server_steps" in step_train_table.columns

    assert ("client_update/round_table", {"step_metric": "server_round"}) in fake_wandb.metric_definitions
    assert ("client_eval/round_table", {"step_metric": "server_round"}) in fake_wandb.metric_definitions
    assert ("client_update/step_table", {"step_metric": "server_step"}) in fake_wandb.metric_definitions


def test_create_experiment_logger_tolerates_flower_mapping_missing_optional_keys(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")
    monkeypatch.setenv(
        "FEDCTL_EXPERIMENT_CONFIG",
        "apps/fedctl_research/experiment_configs/network_heterogeneity/main/cifar10_cnn/iid/mixed/fedavg.toml",
    )
    monkeypatch.setenv("FEDCTL_REPO_CONFIG_LABEL", "none")

    class _WeirdRunConfig(dict):
        def get(self, key, default=None):
            if key in self:
                return super().get(key, default)
            raise KeyError(f"Key '{key}' is not present in the main dictionary")

        def __getitem__(self, key):
            if key in self:
                return super().__getitem__(key)
            raise KeyError(f"Key '{key}' is not present in the main dictionary")

    context = SimpleNamespace(
        run_config=_WeirdRunConfig(
            {
                "method": "fedavg",
                "task": "cifar10_cnn",
                "wandb-enabled": True,
                "wandb-project": "fedctl",
            }
        )
    )

    logger = create_experiment_logger(context)

    assert isinstance(logger, WandbExperimentLogger)
    assert len(fake_wandb.runs) == 1
    assert fake_wandb.runs[0].init_kwargs["name"] == "demo-exp"


def test_create_experiment_logger_tolerates_flower_mapping_get_without_default(monkeypatch) -> None:
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setenv("FEDCTL_EXPERIMENT", "demo-exp")
    monkeypatch.setenv(
        "FEDCTL_EXPERIMENT_CONFIG",
        "apps/fedctl_research/experiment_configs/network_heterogeneity/main/cifar10_cnn/iid/mixed/fedavg.toml",
    )
    monkeypatch.setenv("FEDCTL_REPO_CONFIG_LABEL", "none")

    class _WeirdRunConfig(dict):
        def get(self, key):
            if key in self:
                return super().get(key)
            raise KeyError(f"Key '{key}' is not present in the main dictionary")

        def __getitem__(self, key):
            if key in self:
                return super().__getitem__(key)
            raise KeyError(f"Key '{key}' is not present in the main dictionary")

    context = SimpleNamespace(
        run_config=_WeirdRunConfig(
            {
                "method": "fedavg",
                "task": "cifar10_cnn",
                "wandb-enabled": True,
                "wandb-project": "fedctl",
            }
        )
    )

    logger = create_experiment_logger(context)

    assert isinstance(logger, WandbExperimentLogger)
    assert len(fake_wandb.runs) == 1
