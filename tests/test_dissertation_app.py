from __future__ import annotations

import sys
import time
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
import tomllib
import yaml

import pytest

APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "fedctl_research"
    / "src"
)
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

torch = pytest.importorskip("torch")

from flwr.app import ArrayRecord, ConfigRecord, Message, MetricRecord, RecordDict  # noqa: E402
from flwr.app.metadata import Metadata  # noqa: E402

from fedctl_research.costs import build_model_catalog, get_model_costs  # noqa: E402
from fedctl_research.config import parse_device_type_allocations  # noqa: E402
from fedctl_research.methods.assignment import ModelRateAssigner  # noqa: E402
from fedctl_research.methods.fedavg.strategy import FedAvgBaseline  # noqa: E402
from fedctl_research.methods.fedavgm.strategy import FedAvgMStrategy  # noqa: E402
from fedctl_research.methods.fedbuff.async_loop import _apply_aggregated_delta, _staleness_weight  # noqa: E402
from fedctl_research.methods.fiarse.masking import (  # noqa: E402
    apply_hard_mask_in_place,
    build_threshold_map,
    maskable_parameter_names,
)
from fedctl_research.methods.fiarse.strategy import FiarseStrategy  # noqa: E402
from fedctl_research.methods.fiarse.slicing import build_importance_param_indices_for_rate  # noqa: E402
from fedctl_research.methods.fedrolex.strategy import FedRolex  # noqa: E402
from fedctl_research.methods.fedrolex.slicing import (  # noqa: E402
    _rolling_window_indices,
    build_rolling_param_indices_for_rate,
)
from fedctl_research.methods.heterofl.strategy import HeteroFLStrategy  # noqa: E402
from fedctl_research.methods.heterofl.slicing import (  # noqa: E402
    build_param_indices_for_rate,
    slice_state_dict,
)
from fedctl_research.methods.registry import resolve_method  # noqa: E402
from fedctl_research.methods.runtime import (  # noqa: E402
    build_partition_request,
    build_typed_partition_plan,
    central_evaluate_fn,
    run_submodel_evaluations,
)
from fedctl_research.metrics import normalize_metric_mapping  # noqa: E402
from fedctl_research.partitioning import (  # noqa: E402
    BalancedLabelSkewPartitioner,
    DeviceCorrelatedLabelSkewPartitioner,
    DirichletPartitioner,
    IidPartitioner,
    PartitionRequest,
    build_classification_partitioner,
    partitioners,
)
from fedctl_research.runtime.classification import (  # noqa: E402
    masked_cross_entropy_loss,
    should_use_masked_cross_entropy,
)
from fedctl_research.seeding import derive_seed  # noqa: E402
from fedctl_research.tasks.registry import resolve_task  # noqa: E402


class _Logger:
    def __init__(self) -> None:
        self.train_calls: list[tuple[int, dict[str, float | int]]] = []
        self.eval_calls: list[tuple[int, dict[str, float | int]]] = []
        self.server_eval_calls: list[tuple[int, dict[str, float | int]]] = []
        self.system_calls: list[tuple[int, dict[str, float | int]]] = []
        self.summary_calls: list[dict[str, float | int]] = []
        self.submodel_client_event_calls: list[tuple[int, list[dict[str, object]]]] = []

    def log_train_metrics(self, server_round: int, metrics) -> None:
        self.train_calls.append((server_round, dict(metrics or {})))

    def log_client_eval_metrics(self, server_round: int, metrics) -> None:
        self.eval_calls.append((server_round, dict(metrics or {})))

    def log_server_eval_metrics(self, server_round: int, metrics) -> None:
        self.server_eval_calls.append((server_round, dict(metrics or {})))

    def log_system_metrics(self, server_round: int, metrics) -> None:
        self.system_calls.append((server_round, dict(metrics or {})))

    def log_summary_metrics(self, metrics) -> None:
        self.summary_calls.append(dict(metrics or {}))

    def log_submodel_client_events(self, server_step: int, rows) -> None:
        self.submodel_client_event_calls.append((server_step, [dict(row) for row in rows]))


class _ArtifactLogger:
    def __init__(self) -> None:
        self.client_updates: list[dict[str, float | int | str]] = []
        self.client_evals: list[dict[str, float | int | str]] = []
        self.server_steps: list[dict[str, float | int | str]] = []
        self.evaluations: list[dict[str, float | int | str]] = []
        self.submodel_evaluations: list[dict[str, float | int | str]] = []

    def log_client_update_event(self, payload) -> None:
        self.client_updates.append(dict(payload))

    def log_client_eval_event(self, payload) -> None:
        self.client_evals.append(dict(payload))

    def log_server_step_event(self, payload) -> None:
        self.server_steps.append(dict(payload))

    def log_evaluation_event(self, payload) -> None:
        self.evaluations.append(dict(payload))

    def log_submodel_evaluation_event(self, payload) -> None:
        self.submodel_evaluations.append(dict(payload))


def _make_message(
    *,
    node_id: int,
    group_id: str,
    array_state: OrderedDict[str, torch.Tensor] | None = None,
    metrics: dict[str, float | int] | None = None,
    message_type: str = "train",
) -> Message:
    content = RecordDict({})
    if array_state is not None:
        content["arrays"] = ArrayRecord(array_state)
    if metrics is not None:
        content["metrics"] = MetricRecord(metrics)
    return Message(
        content=content,
        metadata=Metadata(
            run_id=1,
            message_id=f"msg-{node_id}",
            src_node_id=node_id,
            dst_node_id=0,
            reply_to_message_id="",
            group_id=group_id,
            created_at=0.0,
            ttl=10.0,
            message_type=message_type,
        ),
    )


def _partition_request(
    *,
    partitioning: str,
    partition_id: int = 0,
    num_partitions: int = 4,
    device_type: str = "unknown",
    partitioning_num_labels: int = 2,
    partitioning_dirichlet_alpha: float = 0.1,
    assignment_seed: int | None = 42,
    loader_seed: int | None = None,
    typed_partition_idx: int | None = None,
    typed_partition_count: int | None = None,
) -> PartitionRequest:
    return PartitionRequest(
        partition_id=partition_id,
        num_partitions=num_partitions,
        partitioning=partitioning,
        device_type=device_type,
        partitioning_num_labels=partitioning_num_labels,
        partitioning_dirichlet_alpha=partitioning_dirichlet_alpha,
        assignment_seed=assignment_seed,
        loader_seed=loader_seed,
        typed_partition_idx=typed_partition_idx,
        typed_partition_count=typed_partition_count,
    )


def test_task_registry_includes_fashion_mnist_cnn() -> None:
    task = resolve_task("fashion_mnist_cnn")
    model = task.build_model_for_rate(0.5, global_model_rate=1.0)
    output = model(torch.randn(4, 1, 28, 28))
    assert output.shape == (4, 10)


def test_task_registry_includes_cifar10_cnn() -> None:
    task = resolve_task("cifar10_cnn")
    model = task.build_model_for_rate(0.5, global_model_rate=1.0)
    output = model(torch.randn(4, 3, 32, 32))
    assert output.shape == (4, 10)


def test_task_registry_includes_cifar10_preresnet18() -> None:
    task = resolve_task("cifar10_preresnet18")
    model = task.build_model_for_rate(0.25, global_model_rate=1.0)
    output = model(torch.randn(2, 3, 32, 32))
    assert output.shape == (2, 10)


def test_preresnet18_slicing_matches_smaller_model_state() -> None:
    task = resolve_task("cifar10_preresnet18")
    global_model = task.build_model_for_rate(1.0, global_model_rate=1.0)
    local_model = task.build_model_for_rate(0.25, global_model_rate=1.0)
    global_state = OrderedDict(global_model.state_dict())
    param_idx = build_param_indices_for_rate(global_state, 0.25, global_model_rate=1.0)
    local_state = slice_state_dict(global_state, param_idx)
    local_model.load_state_dict(local_state, strict=True)


def test_method_registry_includes_fedavg_fedavgm_fedbuff_fedstaleweight_fedrolex_and_fiarse() -> None:
    assert hasattr(resolve_method("fedavg"), "run_server")
    assert hasattr(resolve_method("fedavgm"), "run_server")
    assert hasattr(resolve_method("fedbuff"), "run_server")
    assert hasattr(resolve_method("fedstaleweight"), "run_server")
    assert hasattr(resolve_method("fedrolex"), "run_server")
    assert hasattr(resolve_method("fiarse"), "run_server")


def test_network_heterogeneity_experiment_config_tree_contains_expected_families() -> None:
    config_root = Path(__file__).resolve().parents[1] / "apps" / "fedctl_research" / "experiment_configs"
    expected = [
        config_root / "smoke" / "network_heterogeneity" / "fashion_mnist_mlp" / "fedbuff_k10.toml",
        config_root / "network_heterogeneity" / "main" / "fashion_mnist_cnn" / "fedavg.toml",
        config_root / "network_heterogeneity" / "main" / "fashion_mnist_cnn" / "fedstaleweight.toml",
        config_root / "network_heterogeneity" / "main" / "cifar10_cnn" / "fedbuff.toml",
        config_root / "network_heterogeneity" / "main" / "cifar10_cnn" / "fedstaleweight.toml",
        config_root / "network_heterogeneity" / "ablations" / "scale_concurrency" / "scale_async" / "cifar10_cnn" / "fedbuff_c24_k10.toml",
        config_root / "network_heterogeneity" / "ablations" / "scale_concurrency" / "buffer_k" / "cifar10_cnn" / "fedbuff_k20.toml",
        config_root / "network_heterogeneity" / "ablations" / "stale_update_control" / "staleness_weighting" / "cifar10_cnn" / "fedbuff_polynomial.toml",
        config_root / "network_heterogeneity" / "ablations" / "stale_update_control" / "staleness_weighting" / "cifar10_cnn" / "fedbuff_alpha10.toml",
        config_root / "network_heterogeneity" / "ablations" / "stale_update_control" / "staleness_weighting" / "cifar10_cnn" / "fedstaleweight.toml",
        config_root / "network_heterogeneity" / "ablations" / "deployment_stressors" / "netem" / "cifar10_cnn" / "fedavgm.toml",
        config_root / "network_heterogeneity" / "ablations" / "deployment_stressors" / "device_correlated_non_iid" / "cifar10_cnn" / "fedstaleweight.toml",
        config_root / "network_heterogeneity" / "ablations" / "model_extension" / "cifar10_preresnet18" / "fedbuff.toml",
    ]
    for path in expected:
        assert path.exists(), path


def test_fedbuff_repo_config_tree_contains_expected_profiles() -> None:
    repo_root = Path(__file__).resolve().parents[1] / "apps" / "fedctl_research" / "repo_configs"
    expected = [
        repo_root / "smoke" / "compute_heterogeneity.yaml",
        repo_root / "smoke" / "network_heterogeneity.yaml",
        repo_root / "compute_heterogeneity" / "main" / "none.yaml",
        repo_root / "network_heterogeneity" / "main" / "none.yaml",
        repo_root / "network_heterogeneity" / "ablations" / "deployment_stressors" / "asym_down.yaml",
        repo_root / "network_heterogeneity" / "ablations" / "scale_concurrency" / "scale_async" / "med.yaml",
    ]
    for path in expected:
        assert path.exists(), path


def test_compute_heterogeneity_config_tree_contains_fiarse_families() -> None:
    config_root = Path(__file__).resolve().parents[1] / "apps" / "fedctl_research" / "experiment_configs"
    expected = [
        config_root / "smoke" / "compute_heterogeneity" / "fashion_mnist_mlp" / "fiarse.toml",
        config_root / "compute_heterogeneity" / "main" / "fashion_mnist_cnn" / "fiarse.toml",
        config_root / "compute_heterogeneity" / "main" / "cifar10_cnn" / "iid" / "fiarse.toml",
        config_root / "compute_heterogeneity" / "main" / "cifar10_cnn" / "noniid" / "fiarse.toml",
        config_root / "compute_heterogeneity" / "ablations" / "capacity_design" / "four_levels" / "fashion_mnist_cnn" / "fiarse.toml",
        config_root / "compute_heterogeneity" / "ablations" / "robustness_extension" / "preresnet18" / "cifar10_preresnet18" / "fiarse.toml",
        config_root / "compute_heterogeneity" / "ablations" / "method_mechanisms" / "fiarse_thresholds" / "cifar10_cnn" / "fiarse_global.toml",
        config_root / "compute_heterogeneity" / "ablations" / "method_mechanisms" / "fiarse_thresholds" / "cifar10_cnn" / "fiarse_layerwise.toml",
    ]
    for path in expected:
        assert path.exists(), path


def test_fedavg_aggregate_train_logs_summary_metrics() -> None:
    logger = _Logger()
    strategy = FedAvgBaseline(
        experiment_logger=logger,
        weighted_by_key="num-examples",
        min_available_nodes=1,
        min_train_nodes=1,
        min_evaluate_nodes=1,
        fraction_train=1.0,
        fraction_evaluate=1.0,
    )
    strategy._round_sampled_nodes = 2
    strategy._round_started_at = time.perf_counter()

    state1 = OrderedDict({"w": torch.tensor([1.0, 1.0])})
    state2 = OrderedDict({"w": torch.tensor([3.0, 3.0])})
    arrays, _ = strategy.aggregate_train(
        1,
        [
            _make_message(
                node_id=1,
                group_id="1",
                array_state=state1,
                metrics={"num-examples": 3, "train-loss": 1.0, "train-duration-s": 1.0},
            ),
            _make_message(
                node_id=2,
                group_id="1",
                array_state=state2,
                metrics={"num-examples": 1, "train-loss": 3.0, "train-duration-s": 2.0},
            ),
        ],
    )

    assert arrays is not None
    aggregated = arrays.to_torch_state_dict()
    assert torch.allclose(aggregated["w"], torch.tensor([1.5, 1.5]))
    assert logger.train_calls
    _, metrics = logger.train_calls[-1]
    assert metrics["round-model-rate-avg"] == 1.0
    assert logger.system_calls
    _, system_metrics = logger.system_calls[-1]
    assert system_metrics["round-sampled-nodes"] == 2
    assert system_metrics["round-successful-train-replies"] == 2
    assert "round_avg_params" in system_metrics


def test_normalize_metric_mapping_rounds_model_rate_noise() -> None:
    normalized = normalize_metric_mapping(
        {
            "model-rate": 1.0000000000000002,
            "round-model-rate-avg": 0.25000000000000006,
            "train-loss": 0.123456789,
        }
    )

    assert normalized["model-rate"] == 1.0
    assert normalized["round-model-rate-avg"] == 0.25
    assert normalized["train-loss"] == 0.123456789


def test_fedavg_aggregate_train_logs_duration_stats() -> None:
    logger = _Logger()
    strategy = FedAvgBaseline(
        experiment_logger=logger,
        weighted_by_key="num-examples",
        min_available_nodes=1,
        min_train_nodes=1,
        min_evaluate_nodes=1,
        fraction_train=1.0,
        fraction_evaluate=1.0,
    )
    strategy._round_sampled_nodes = 2
    strategy._round_started_at = time.perf_counter()

    arrays, _ = strategy.aggregate_train(
        1,
        [
            _make_message(
                node_id=1,
                group_id="1",
                array_state=OrderedDict({"w": torch.tensor([1.0])}),
                metrics={"num-examples": 1, "train-loss": 1.0, "train-duration-s": 1.0},
            ),
            _make_message(
                node_id=2,
                group_id="1",
                array_state=OrderedDict({"w": torch.tensor([3.0])}),
                metrics={"num-examples": 1, "train-loss": 3.0, "train-duration-s": 3.0},
            ),
        ],
    )

    assert arrays is not None
    _, system_metrics = logger.system_calls[-1]
    assert system_metrics["round-train-client-duration-mean-s"] == pytest.approx(2.0)
    assert system_metrics["round-train-client-duration-min-s"] == pytest.approx(1.0)
    assert system_metrics["round-train-client-duration-max-s"] == pytest.approx(3.0)
    assert system_metrics["round-train-straggler-gap-s"] == pytest.approx(2.0)


def test_fedavgm_applies_server_momentum() -> None:
    strategy = FedAvgMStrategy(
        server_momentum=0.5,
        weighted_by_key="num-examples",
        min_available_nodes=1,
        min_train_nodes=1,
        min_evaluate_nodes=1,
        fraction_train=1.0,
        fraction_evaluate=1.0,
    )
    strategy._round_sampled_nodes = 1
    strategy._round_started_at = time.perf_counter()
    strategy._global_state_before_round = OrderedDict({"w": torch.tensor([2.0])})
    strategy.current_arrays = ArrayRecord(OrderedDict({"w": torch.tensor([2.0])}))
    arrays, _ = strategy.aggregate_train(
        1,
        [
            _make_message(
                node_id=1,
                group_id="1",
                array_state=OrderedDict({"w": torch.tensor([1.0])}),
                metrics={"num-examples": 1, "train-loss": 1.0, "train-duration-s": 1.0},
            )
        ],
    )
    assert arrays is not None
    round1 = arrays.to_torch_state_dict()["w"]
    assert torch.allclose(round1, torch.tensor([1.0]))

    strategy._round_sampled_nodes = 1
    strategy._round_started_at = time.perf_counter()
    strategy._global_state_before_round = OrderedDict({"w": torch.tensor([1.0])})
    strategy.current_arrays = ArrayRecord(OrderedDict({"w": round1.clone()}))
    arrays, _ = strategy.aggregate_train(
        2,
        [
            _make_message(
                node_id=1,
                group_id="2",
                array_state=OrderedDict({"w": torch.tensor([0.5])}),
                metrics={"num-examples": 1, "train-loss": 1.0, "train-duration-s": 1.0},
            )
        ],
    )
    assert arrays is not None
    round2 = arrays.to_torch_state_dict()["w"]
    assert torch.allclose(round2, torch.tensor([0.0]))


def test_heterofl_aggregate_train_tracks_total_wall_clock_and_logs_client_updates() -> None:
    logger = _Logger()
    artifacts = _ArtifactLogger()
    progress: dict[str, float | int] = {}
    task = resolve_task("fashion_mnist_mlp")
    global_state = OrderedDict(task.build_model_for_rate(1.0, global_model_rate=1.0).state_dict())
    param_idx = build_param_indices_for_rate(global_state, 1.0, global_model_rate=1.0)
    local_state = slice_state_dict(global_state, param_idx)
    assigner = ModelRateAssigner(
        mode="fix",
        default_model_rate=1.0,
        explicit_rate_by_node_id={},
        explicit_rate_by_partition_id={},
        rate_by_device_type={"rpi4": 1.0},
        device_type_by_node_id={1: "rpi4"},
        partition_id_by_node_id={},
        dynamic_levels=(1.0,),
        dynamic_proportions=(1.0,),
    )
    strategy = HeteroFLStrategy(
        rate_assigner=assigner,
        experiment_logger=logger,
        artifact_logger=artifacts,
        progress_tracker=progress,
        weighted_by_key="num-examples",
        min_available_nodes=1,
        min_train_nodes=1,
        min_evaluate_nodes=1,
        fraction_train=1.0,
        fraction_evaluate=1.0,
    )
    strategy._global_state_for_round = global_state
    strategy._active_rate_by_node = {1: 1.0}
    strategy._active_param_idx_by_node = {1: param_idx}
    strategy._round_sampled_nodes = 1
    strategy._round_started_at = time.perf_counter() - 1.0
    strategy._server_started_at = time.perf_counter() - 5.0

    arrays, _ = strategy.aggregate_train(
        1,
        [
            _make_message(
                node_id=1,
                group_id="1",
                array_state=local_state,
                metrics={
                    "num-examples": 2,
                    "train-num-examples": 2,
                    "train-loss": 1.0,
                    "train-duration-s": 1.5,
                    "examples-per-second": 4.0,
                },
            )
        ],
    )

    assert arrays is not None
    assert progress["client_trips_total"] == 1
    assert progress["wall_clock_s_since_start"] >= 4.0
    assert artifacts.client_updates
    assert artifacts.client_updates[-1]["device_type"] == "rpi4"
    assert artifacts.client_updates[-1]["client_trips_total"] == 1
    assert artifacts.server_steps
    assert artifacts.server_steps[-1]["wall_clock_s_since_start"] >= 4.0


def test_heterofl_configure_evaluate_slices_width_scaled_models() -> None:
    task = resolve_task("fashion_mnist_cnn")
    global_state = OrderedDict(task.build_model_for_rate(1.0, global_model_rate=1.0).state_dict())
    assigner = ModelRateAssigner(
        mode="fix",
        default_model_rate=1.0,
        explicit_rate_by_node_id={},
        explicit_rate_by_partition_id={},
        rate_by_device_type={"rpi4": 0.25, "rpi5": 1.0},
        device_type_by_node_id={1: "rpi4", 2: "rpi5"},
        partition_id_by_node_id={},
        dynamic_levels=(1.0,),
        dynamic_proportions=(1.0,),
    )
    strategy = HeteroFLStrategy(
        rate_assigner=assigner,
        weighted_by_key="num-examples",
        min_available_nodes=1,
        min_train_nodes=1,
        min_evaluate_nodes=1,
        fraction_train=1.0,
        fraction_evaluate=1.0,
    )
    grid = SimpleNamespace(get_node_ids=lambda: [1, 2])

    messages = list(strategy.configure_evaluate(1, ArrayRecord(global_state), ConfigRecord({}), grid))

    assert len(messages) == 2
    by_node = {message.metadata.dst_node_id: message for message in messages}
    assert by_node[1].content["config"]["model-rate"] == pytest.approx(0.25)
    assert by_node[2].content["config"]["model-rate"] == pytest.approx(1.0)

    small_state = by_node[1].content["arrays"].to_torch_state_dict()
    small_model = task.build_model_for_rate(0.25, global_model_rate=1.0)
    task.load_model_state(small_model, small_state)
    assert small_state["features.0.weight"].shape == small_model.state_dict()["features.0.weight"].shape
    assert small_state["features.0.weight"].shape != global_state["features.0.weight"].shape


def test_fedbuff_polynomial_staleness_weight_decays() -> None:
    assert _staleness_weight("none", 0.5, 5, buffer_size=10) == pytest.approx(1.0)
    assert _staleness_weight("polynomial", 0.5, 0, buffer_size=10) == pytest.approx(1.0)
    assert _staleness_weight("polynomial", 0.5, 3, buffer_size=10) < 1.0
    assert _staleness_weight("fair", 0.5, 3, buffer_size=10) > _staleness_weight("fair", 0.5, 1, buffer_size=10)


def test_fedbuff_applies_aggregated_parameter_delta_without_extra_lr_scaling() -> None:
    current_state = OrderedDict({"weight": torch.tensor([1.0])})
    aggregate_delta = OrderedDict({"weight": torch.tensor([0.2])})

    new_state = _apply_aggregated_delta(current_state, aggregate_delta)

    assert new_state["weight"].item() == pytest.approx(0.8)


def test_fedrolex_rolling_indices_change_across_rounds() -> None:
    state = OrderedDict(
        {
            "features.0.weight": torch.zeros(32, 1, 3, 3),
            "features.0.bias": torch.zeros(32),
            "features.4.weight": torch.zeros(64, 32, 3, 3),
            "features.4.bias": torch.zeros(64),
            "classifier.2.weight": torch.zeros(10, 64),
            "classifier.2.bias": torch.zeros(10),
        }
    )
    round1 = build_rolling_param_indices_for_rate(state, 0.25, server_round=1, global_model_rate=1.0)
    round2 = build_rolling_param_indices_for_rate(state, 0.25, server_round=2, global_model_rate=1.0)
    out1, _ = round1["features.0.weight"]
    out2, _ = round2["features.0.weight"]
    assert not torch.equal(out1, out2)


def test_fiarse_slicing_matches_smaller_model_state() -> None:
    task = resolve_task("cifar10_cnn")
    global_model = task.build_model_for_rate(1.0, global_model_rate=1.0)
    local_model = task.build_model_for_rate(0.25, global_model_rate=1.0)
    global_state = OrderedDict(global_model.state_dict())
    param_idx = build_importance_param_indices_for_rate(global_state, 0.25, global_model_rate=1.0, threshold_mode="global")
    local_state = slice_state_dict(global_state, param_idx)
    local_model.load_state_dict(local_state, strict=True)


def test_fiarse_threshold_modes_produce_distinct_thresholds_when_layers_have_different_scales() -> None:
    model = torch.nn.Sequential(
        OrderedDict(
            {
                "head": torch.nn.Linear(4, 4, bias=False),
                "tail": torch.nn.Linear(4, 4, bias=False),
            }
        )
    )
    with torch.no_grad():
        model.head.weight.copy_(
            torch.tensor(
                [
                    [100.0, 99.0, 98.0, 97.0],
                    [96.0, 95.0, 94.0, 93.0],
                    [92.0, 91.0, 90.0, 89.0],
                    [88.0, 87.0, 86.0, 85.0],
                ]
            )
        )
        model.tail.weight.copy_(
            torch.tensor(
                [
                    [4.0, 3.0, 2.0, 1.0],
                    [0.9, 0.8, 0.7, 0.6],
                    [0.5, 0.4, 0.3, 0.2],
                    [0.1, 0.05, 0.02, 0.01],
                ]
            )
        )

    global_thresholds = build_threshold_map(model, model_rate=0.25, threshold_mode="global")
    layerwise_thresholds = build_threshold_map(model, model_rate=0.25, threshold_mode="layerwise")

    assert float(global_thresholds["tail.weight"]) > float(layerwise_thresholds["tail.weight"])


def test_fiarse_global_threshold_prefers_largest_magnitudes_not_low_outliers() -> None:
    state = OrderedDict(
        {
            "features.0.weight": torch.tensor([100.0, 99.0, 98.0, 1.0], dtype=torch.float32).reshape(4, 1, 1, 1),
            "features.0.bias": torch.zeros(4),
            "classifier.1.weight": torch.ones(2, 4),
            "classifier.1.bias": torch.zeros(2),
        }
    )
    global_idx = build_importance_param_indices_for_rate(
        state,
        0.5,
        global_model_rate=1.0,
        threshold_mode="global",
    )
    global_out, _ = global_idx["features.0.weight"]
    assert torch.equal(global_out, torch.tensor([0, 1]))


def test_fiarse_masking_only_targets_maskable_layers() -> None:
    model = torch.nn.Sequential(
        OrderedDict(
            {
                "conv": torch.nn.Conv2d(1, 1, kernel_size=1, bias=True),
                "bn": torch.nn.BatchNorm2d(1),
                "head": torch.nn.Linear(1, 1),
            }
        )
    )

    assert maskable_parameter_names(model) == ("conv.weight", "conv.bias", "head.weight", "head.bias")


def test_fiarse_hard_mask_zeroes_low_magnitude_parameters_and_preserves_norm_affine() -> None:
    model = torch.nn.Sequential(
        OrderedDict(
            {
                "conv": torch.nn.Conv2d(1, 1, kernel_size=1, bias=True),
                "bn": torch.nn.BatchNorm2d(1),
                "head": torch.nn.Linear(1, 1),
            }
        )
    )
    with torch.no_grad():
        model.conv.weight.fill_(10.0)
        model.conv.bias.fill_(9.0)
        model.bn.weight.fill_(7.0)
        model.bn.bias.fill_(6.0)
        model.head.weight.fill_(0.01)
        model.head.bias.fill_(0.02)

    threshold_map = build_threshold_map(model, model_rate=0.5, threshold_mode="global")
    apply_hard_mask_in_place(model, threshold_map=threshold_map)

    assert torch.all(model.conv.weight != 0)
    assert torch.all(model.conv.bias != 0)
    assert torch.all(model.head.weight == 0)
    assert torch.all(model.head.bias == 0)
    assert torch.all(model.bn.weight == 7.0)
    assert torch.all(model.bn.bias == 6.0)


def test_fiarse_strategy_aggregates_sparse_deltas_with_global_lr() -> None:
    strategy = FiarseStrategy(
        rate_assigner=ModelRateAssigner(
            mode="fix",
            default_model_rate=0.5,
            explicit_rate_by_node_id={},
            explicit_rate_by_partition_id={},
            rate_by_device_type={"rpi4": 0.5},
            device_type_by_node_id={1: "rpi4", 2: "rpi4"},
            partition_id_by_node_id={},
            dynamic_levels=(1.0, 0.5),
            dynamic_proportions=(0.5, 0.5),
            device_type_allocations={},
        ),
        global_learning_rate=0.5,
        experiment_logger=_Logger(),
        min_available_nodes=1,
        min_train_nodes=1,
        min_evaluate_nodes=1,
        fraction_train=1.0,
        fraction_evaluate=1.0,
    )
    strategy._global_state_for_round = OrderedDict(
        {
            "layer.weight": torch.tensor([10.0, 10.0]),
            "bn.running_mean": torch.tensor([4.0]),
        }
    )
    strategy._active_rate_by_node = {1: 0.5, 2: 0.5}
    strategy._round_sampled_nodes = 2
    strategy._round_started_at = time.perf_counter()
    strategy._server_started_at = strategy._round_started_at

    replies = [
        _make_message(
            node_id=1,
            group_id="1",
            array_state=OrderedDict(
                {
                    "layer.weight": torch.tensor([8.0, 10.0]),
                    "bn.running_mean": torch.tensor([3.0]),
                }
            ),
            metrics={"train-duration-s": 1.0, "num-examples": 1, "train-num-examples": 1},
        ),
        _make_message(
            node_id=2,
            group_id="1",
            array_state=OrderedDict(
                {
                    "layer.weight": torch.tensor([10.0, 7.0]),
                    "bn.running_mean": torch.tensor([2.0]),
                }
            ),
            metrics={"train-duration-s": 1.0, "num-examples": 1, "train-num-examples": 1},
        ),
    ]

    arrays, _ = strategy.aggregate_train(server_round=1, replies=replies)
    assert arrays is not None
    aggregated = arrays.to_torch_state_dict()
    assert torch.allclose(aggregated["layer.weight"], torch.tensor([9.0, 8.5]))
    assert torch.allclose(aggregated["bn.running_mean"], torch.tensor([2.5]))


def test_fedrolex_paper_roll_mode_matches_round_modulo_rule() -> None:
    actual = _rolling_window_indices(
        key="features.0.weight",
        output_size=32,
        local_output_size=8,
        server_round=2,
        roll_mode="paper",
        overlap=None,
        device=torch.device("cpu"),
    )
    assert torch.equal(actual, torch.arange(1, 9))


def test_fedrolex_hashed_roll_mode_differs_from_paper_mode() -> None:
    paper = _rolling_window_indices(
        key="features.0.weight",
        output_size=32,
        local_output_size=8,
        server_round=1,
        roll_mode="paper",
        overlap=None,
        device=torch.device("cpu"),
    )
    hashed = _rolling_window_indices(
        key="features.0.weight",
        output_size=32,
        local_output_size=8,
        server_round=1,
        roll_mode="hashed",
        overlap=None,
        device=torch.device("cpu"),
    )
    assert torch.equal(paper, torch.arange(0, 8))
    assert not torch.equal(hashed, paper)


def test_fedrolex_overlap_step_uses_paper_formula() -> None:
    actual = _rolling_window_indices(
        key="features.0.weight",
        output_size=32,
        local_output_size=8,
        server_round=2,
        roll_mode="paper",
        overlap=0.5,
        device=torch.device("cpu"),
    )
    assert torch.equal(actual, torch.arange(5, 13))


def test_fedrolex_aggregate_train_is_unweighted_for_parameters() -> None:
    global_state = OrderedDict(
        {
            "features.0.weight": torch.zeros(4, 1),
            "features.0.bias": torch.zeros(4),
            "classifier.weight": torch.zeros(2, 4),
            "classifier.bias": torch.zeros(2),
        }
    )
    param_idx_round1 = build_rolling_param_indices_for_rate(
        global_state,
        0.5,
        server_round=1,
        global_model_rate=1.0,
        roll_mode="paper",
    )
    param_idx_round2 = build_rolling_param_indices_for_rate(
        global_state,
        0.5,
        server_round=2,
        global_model_rate=1.0,
        roll_mode="paper",
    )

    strategy = FedRolex(
        rate_assigner=ModelRateAssigner(
            mode="fix",
            default_model_rate=0.5,
            explicit_rate_by_node_id={},
            explicit_rate_by_partition_id={},
            rate_by_device_type={},
            device_type_by_node_id={},
            partition_id_by_node_id={},
            dynamic_levels=(1.0,),
            dynamic_proportions=(1.0,),
        ),
        weighted_by_key="num-examples",
        roll_mode="paper",
        min_available_nodes=1,
        min_train_nodes=1,
        min_evaluate_nodes=1,
        fraction_train=1.0,
        fraction_evaluate=1.0,
    )
    strategy._global_state_for_round = global_state
    strategy._active_param_idx_by_node = {1: param_idx_round1, 2: param_idx_round2}
    strategy._active_rate_by_node = {1: 0.5, 2: 0.5}
    strategy._round_sampled_nodes = 2
    strategy._round_started_at = time.perf_counter()

    arrays, _ = strategy.aggregate_train(
        1,
        [
            _make_message(
                node_id=1,
                group_id="1",
                array_state=OrderedDict((key, torch.full_like(tensor, 1.0)) for key, tensor in slice_state_dict(global_state, param_idx_round1).items()),
                metrics={"train-loss": 1.0, "num-examples": 100},
            ),
            _make_message(
                node_id=2,
                group_id="1",
                array_state=OrderedDict((key, torch.full_like(tensor, 3.0)) for key, tensor in slice_state_dict(global_state, param_idx_round2).items()),
                metrics={"train-loss": 3.0, "num-examples": 1},
            ),
        ],
    )

    assert arrays is not None
    aggregated = arrays.to_torch_state_dict()
    assert torch.allclose(aggregated["features.0.bias"], torch.tensor([1.0, 2.0, 3.0, 0.0]))


def test_dynamic_model_rate_assignment_is_deterministic() -> None:
    assigner = ModelRateAssigner(
        mode="dynamic",
        default_model_rate=0.25,
        explicit_rate_by_node_id={},
        explicit_rate_by_partition_id={},
        rate_by_device_type={},
        device_type_by_node_id={},
        partition_id_by_node_id={},
        dynamic_levels=(1.0, 0.5, 0.25),
        dynamic_proportions=(0.2, 0.3, 0.5),
        seed=1337,
    )
    first = assigner.assign_for_round([1, 2, 3], server_round=2)
    second = assigner.assign_for_round([1, 2, 3], server_round=2)
    sampled_rounds = {
        round_idx: assigner.assign_for_round([1, 2, 3], server_round=round_idx)
        for round_idx in range(2, 8)
    }
    assert first == second
    assert any(assignment != first for round_idx, assignment in sampled_rounds.items() if round_idx != 2)
    assert set(first.values()).issubset({1.0, 0.5, 0.25})


def test_parse_device_type_allocations_reads_exact_bucket_counts() -> None:
    parsed = parse_device_type_allocations("rpi4:0.125@5,0.25@5;rpi5:0.5@5,1.0@5")
    assert parsed == {
        "rpi4": ((0.125, 5), (0.25, 5)),
        "rpi5": ((0.5, 5), (1.0, 5)),
    }


def test_parse_device_type_allocations_rejects_malformed_entries() -> None:
    with pytest.raises(ValueError, match="heterofl-device-type-allocations"):
        parse_device_type_allocations("rpi4:0.25,0.125@5")


def test_fixed_model_rate_assignment_preserves_precedence() -> None:
    assigner = ModelRateAssigner(
        mode="fix",
        default_model_rate=0.25,
        explicit_rate_by_node_id={1: 0.125},
        explicit_rate_by_partition_id={},
        rate_by_device_type={"rpi4": 0.25, "rpi5": 1.0},
        device_type_by_node_id={1: "rpi5", 2: "rpi5", 3: "unknown"},
        partition_id_by_node_id={},
        dynamic_levels=(1.0,),
        dynamic_proportions=(1.0,),
        device_type_allocations={},
        seed=1337,
    )
    assigned = assigner.assign_for_round([1, 2, 3], server_round=1)
    assert assigned == {1: 0.125, 2: 1.0, 3: 0.25}


def test_fixed_model_rate_assignment_eval_rates_follow_actual_fixed_pool() -> None:
    assigner = ModelRateAssigner(
        mode="fix",
        default_model_rate=0.125,
        explicit_rate_by_node_id={},
        explicit_rate_by_partition_id={},
        rate_by_device_type={"rpi4": 0.25, "rpi5": 1.0},
        device_type_by_node_id={11: "rpi4", 12: "rpi4", 21: "rpi5", 22: "rpi5"},
        partition_id_by_node_id={},
        dynamic_levels=(1.0, 0.5, 0.25, 0.125, 0.0625),
        dynamic_proportions=(0.2, 0.2, 0.2, 0.2, 0.2),
        device_type_allocations={
            "rpi4": ((0.125, 5), (0.25, 5)),
            "rpi5": ((0.5, 5), (1.0, 5)),
        },
        seed=1337,
    )
    assigner.set_typed_partition_plan(
        {
            11: {"partition-device-type": "rpi4", "typed-partition-idx": 0, "typed-partition-count": 10},
            12: {"partition-device-type": "rpi4", "typed-partition-idx": 7, "typed-partition-count": 10},
            21: {"partition-device-type": "rpi5", "typed-partition-idx": 0, "typed-partition-count": 10},
            22: {"partition-device-type": "rpi5", "typed-partition-idx": 7, "typed-partition-count": 10},
        }
    )
    assert assigner.eval_rates(global_model_rate=1.0) == (0.125, 0.25, 0.5, 1.0)


def test_fixed_model_rate_assignment_applies_exact_typed_device_buckets() -> None:
    assigner = ModelRateAssigner(
        mode="fix",
        default_model_rate=0.125,
        explicit_rate_by_node_id={},
        explicit_rate_by_partition_id={},
        rate_by_device_type={"rpi4": 0.25, "rpi5": 1.0},
        device_type_by_node_id={
            **{node_id: "rpi4" for node_id in range(10)},
            **{node_id: "rpi5" for node_id in range(10, 20)},
        },
        partition_id_by_node_id={},
        dynamic_levels=(1.0, 0.5, 0.25, 0.125),
        dynamic_proportions=(0.25, 0.25, 0.25, 0.25),
        device_type_allocations={
            "rpi4": ((0.125, 5), (0.25, 5)),
            "rpi5": ((0.5, 5), (1.0, 5)),
        },
        seed=1337,
    )
    assigner.set_typed_partition_plan(
        {
            **{
                node_id: {
                    "partition-device-type": "rpi4",
                    "typed-partition-idx": node_id,
                    "typed-partition-count": 10,
                }
                for node_id in range(10)
            },
            **{
                node_id: {
                    "partition-device-type": "rpi5",
                    "typed-partition-idx": node_id - 10,
                    "typed-partition-count": 10,
                }
                for node_id in range(10, 20)
            },
        }
    )
    assigned = assigner.assign_for_round(list(range(20)), server_round=1)
    assert sum(rate == 0.125 for rate in assigned.values()) == 5
    assert sum(rate == 0.25 for rate in assigned.values()) == 5
    assert sum(rate == 0.5 for rate in assigned.values()) == 5
    assert sum(rate == 1.0 for rate in assigned.values()) == 5
    assert all(assigned[node_id] in {0.125, 0.25} for node_id in range(10))
    assert all(assigned[node_id] in {0.5, 1.0} for node_id in range(10, 20))


def test_fixed_model_rate_assignment_rejects_bucket_count_mismatches() -> None:
    assigner = ModelRateAssigner(
        mode="fix",
        default_model_rate=0.125,
        explicit_rate_by_node_id={},
        explicit_rate_by_partition_id={},
        rate_by_device_type={"rpi4": 0.25, "rpi5": 1.0},
        device_type_by_node_id={1: "rpi4"},
        partition_id_by_node_id={},
        dynamic_levels=(1.0, 0.5, 0.25, 0.125),
        dynamic_proportions=(0.25, 0.25, 0.25, 0.25),
        device_type_allocations={"rpi4": ((0.125, 5), (0.25, 5))},
        seed=1337,
    )
    assigner.set_typed_partition_plan(
        {
            1: {
                "partition-device-type": "rpi4",
                "typed-partition-idx": 0,
                "typed-partition-count": 8,
            }
        }
    )
    with pytest.raises(ValueError, match="expects 10 typed partitions"):
        assigner.assign_for_round([1], server_round=1)


def test_heterofl_submodel_eval_rates_use_assigner_rates_in_fixed_mode() -> None:
    strategy = HeteroFLStrategy(
        rate_assigner=ModelRateAssigner(
            mode="fix",
            default_model_rate=0.125,
            explicit_rate_by_node_id={},
            explicit_rate_by_partition_id={},
            rate_by_device_type={"rpi4": 0.25, "rpi5": 1.0},
            device_type_by_node_id={11: "rpi4", 12: "rpi4", 21: "rpi5", 22: "rpi5"},
            partition_id_by_node_id={},
            dynamic_levels=(1.0, 0.5, 0.25, 0.125, 0.0625),
            dynamic_proportions=(0.2, 0.2, 0.2, 0.2, 0.2),
            device_type_allocations={
                "rpi4": ((0.125, 5), (0.25, 5)),
                "rpi5": ((0.5, 5), (1.0, 5)),
            },
        ),
        global_model_rate=1.0,
        min_available_nodes=1,
        min_train_nodes=1,
        min_evaluate_nodes=1,
        fraction_train=1.0,
        fraction_evaluate=1.0,
    )
    strategy.set_node_partition_plan(
        {
            11: {"partition-device-type": "rpi4", "typed-partition-idx": 0, "typed-partition-count": 10},
            12: {"partition-device-type": "rpi4", "typed-partition-idx": 7, "typed-partition-count": 10},
            21: {"partition-device-type": "rpi5", "typed-partition-idx": 0, "typed-partition-count": 10},
            22: {"partition-device-type": "rpi5", "typed-partition-idx": 7, "typed-partition-count": 10},
        }
    )
    assert strategy.submodel_eval_rates() == (0.125, 0.25, 0.5, 1.0)


def test_fixed_model_rate_assignment_can_follow_partition_ids() -> None:
    assigner = ModelRateAssigner(
        mode="fix",
        default_model_rate=0.25,
        explicit_rate_by_node_id={},
        explicit_rate_by_partition_id={0: 1.0, 1: 0.5, 2: 0.0625},
        rate_by_device_type={"rpi4": 0.25, "rpi5": 1.0},
        device_type_by_node_id={10: "rpi4", 11: "rpi5", 12: "rpi5", 13: "rpi4"},
        partition_id_by_node_id={10: 0, 11: 1, 12: 2},
        dynamic_levels=(1.0, 0.5, 0.25, 0.125, 0.0625),
        dynamic_proportions=(0.2, 0.2, 0.2, 0.2, 0.2),
        device_type_allocations={},
        seed=1337,
    )
    assigned = assigner.assign_for_round([10, 11, 12, 13], server_round=1)
    assert assigned == {10: 1.0, 11: 0.5, 12: 0.0625, 13: 0.25}


def test_cost_catalog_returns_stable_values() -> None:
    cost = get_model_costs("fashion_mnist_cnn", 0.25, global_model_rate=1.0)
    assert int(cost["param_count"]) > 0
    assert float(cost["model_size_mb"]) > 0
    assert int(cost["flops_estimate"]) > 0

    catalog = build_model_catalog(
        "cifar10_cnn",
        global_model_rate=1.0,
        model_rates=[1.0, 0.25],
    )
    assert "full" in catalog
    assert "rate_1.0" in catalog
    assert "rate_0.25" in catalog


def test_partitioning_iid_covers_all_examples() -> None:
    labels = tuple([i % 4 for i in range(40)])
    result = build_classification_partitioner(
        labels=labels,
        num_classes=4,
        request=_partition_request(
            partitioning="iid",
            num_partitions=4,
            assignment_seed=42,
        ),
    ).partition_result
    flattened = sorted(idx for part in result.indices_by_partition for idx in part)
    assert flattened == list(range(40))


def test_partitioning_label_skew_balanced_limits_labels_per_client() -> None:
    labels = tuple([i % 4 for i in range(80)])
    request = _partition_request(
        partitioning="label-skew-balanced",
        num_partitions=4,
        partitioning_num_labels=2,
        assignment_seed=42,
    )
    train = build_classification_partitioner(
        labels=labels,
        num_classes=4,
        request=request,
    ).partition_result
    test = build_classification_partitioner(
        labels=labels,
        num_classes=4,
        request=request,
        label_sets=train.label_sets_by_partition,
    ).partition_result
    for label_set in train.label_sets_by_partition:
        assert len(label_set) <= 2
    assert train.label_sets_by_partition == test.label_sets_by_partition


def test_build_classification_partitioner_returns_expected_types() -> None:
    labels = tuple([i % 10 for i in range(200)])
    assert set(partitioners()) == {
        "iid",
        "dirichlet",
        "label-skew-balanced",
        "device-correlated-label-skew",
    }
    assert isinstance(
        build_classification_partitioner(
            labels=labels,
            num_classes=10,
            request=_partition_request(
                partitioning="iid",
                num_partitions=4,
                assignment_seed=42,
            ),
        ),
        IidPartitioner,
    )
    assert isinstance(
        build_classification_partitioner(
            labels=labels,
            num_classes=10,
            request=_partition_request(
                partitioning="label-skew-balanced",
                num_partitions=4,
                partitioning_num_labels=2,
                assignment_seed=42,
            ),
        ),
        BalancedLabelSkewPartitioner,
    )
    assert isinstance(
        build_classification_partitioner(
            labels=labels,
            num_classes=10,
            request=_partition_request(
                partitioning="device-correlated-label-skew",
                num_partitions=4,
                partitioning_num_labels=2,
                assignment_seed=42,
            ),
        ),
        DeviceCorrelatedLabelSkewPartitioner,
    )
    assert isinstance(
        build_classification_partitioner(
            labels=labels,
            num_classes=10,
            request=_partition_request(
                partitioning="dirichlet",
                num_partitions=4,
                partitioning_dirichlet_alpha=0.3,
                assignment_seed=42,
            ),
        ),
        DirichletPartitioner,
    )


def test_iid_partitioner_load_partition_is_stable() -> None:
    labels = tuple([i % 5 for i in range(100)])
    partitioner = IidPartitioner(labels, num_classes=5, num_partitions=4, seed=99)
    first = partitioner.load_partition(0)
    second = partitioner.load_partition(0)
    assert first == second
    assert len(first) > 0


def test_partitioning_device_correlated_label_skew_splits_early_and_late_partitions() -> None:
    labels = tuple([i % 10 for i in range(200)])
    rpi4_train = build_classification_partitioner(
        labels=labels,
        num_classes=10,
        request=_partition_request(
            partitioning="device-correlated-label-skew",
            num_partitions=5,
            device_type="rpi4",
            partitioning_num_labels=2,
            assignment_seed=42,
        ),
    ).partition_result
    rpi5_train = build_classification_partitioner(
        labels=labels,
        num_classes=10,
        request=_partition_request(
            partitioning="device-correlated-label-skew",
            num_partitions=5,
            device_type="rpi5",
            partitioning_num_labels=2,
            assignment_seed=42,
        ),
    ).partition_result
    assert len(rpi4_train.label_sets_by_partition) == 5
    assert len(rpi5_train.label_sets_by_partition) == 5
    assert all(len(label_set) == 2 for label_set in rpi4_train.label_sets_by_partition)
    assert all(len(label_set) == 2 for label_set in rpi5_train.label_sets_by_partition)
    assert rpi4_train.label_sets_by_partition != rpi5_train.label_sets_by_partition


def test_build_typed_partition_plan_assigns_indices_within_device_groups() -> None:
    plan = build_typed_partition_plan(
        node_ids=[13, 11, 17, 12, 18, 16],
        device_type_by_node_id={
            11: "rpi4",
            12: "rpi4",
            13: "rpi5",
            16: "rpi5",
            17: "rpi4",
            18: "rpi5",
        },
    )
    assert plan[11] == {
        "partition-device-type": "rpi4",
        "typed-partition-idx": 0,
        "typed-partition-count": 3,
    }
    assert plan[12] == {
        "partition-device-type": "rpi4",
        "typed-partition-idx": 1,
        "typed-partition-count": 3,
    }
    assert plan[17] == {
        "partition-device-type": "rpi4",
        "typed-partition-idx": 2,
        "typed-partition-count": 3,
    }
    assert plan[13] == {
        "partition-device-type": "rpi5",
        "typed-partition-idx": 0,
        "typed-partition-count": 3,
    }
    assert plan[16] == {
        "partition-device-type": "rpi5",
        "typed-partition-idx": 1,
        "typed-partition-count": 3,
    }
    assert plan[18] == {
        "partition-device-type": "rpi5",
        "typed-partition-idx": 2,
        "typed-partition-count": 3,
    }


def test_partition_request_uses_typed_partition_metadata_when_present() -> None:
    request = PartitionRequest(
        partition_id=5,
        num_partitions=8,
        partitioning="device-correlated-label-skew",
        assignment_seed=123,
        loader_seed=456,
        typed_partition_idx=1,
        typed_partition_count=3,
    )
    assert request.effective_partition_id == 1
    assert request.effective_num_partitions == 3
    assert request.effective_assignment_seed == 123


def test_build_partition_request_reads_message_partition_overrides() -> None:
    context = SimpleNamespace(
        node_config={"partition-id": 4, "num-partitions": 6},
        run_config={
            "partitioning": "device-correlated-label-skew",
            "partitioning-num-labels": 2,
            "partitioning-dirichlet-alpha": 0.3,
            "seed": 1337,
        },
    )
    msg = Message(
        content=RecordDict(
            {
                "config": ConfigRecord(
                    {
                        "partition-device-type": "rpi5",
                        "typed-partition-idx": 1,
                        "typed-partition-count": 3,
                    }
                )
            }
        ),
        metadata=Metadata(
            run_id=1,
            message_id="cfg-msg",
            src_node_id=1,
            dst_node_id=0,
            reply_to_message_id="",
            group_id="g",
            created_at=0.0,
            ttl=10.0,
            message_type="train",
        ),
    )

    request = build_partition_request(
        context=context,
        msg=msg,
        task_name="cifar10_cnn",
        method_label="fedavg",
        split="train",
        local_device_type="rpi4",
    )

    assert request.partition_id == 4
    assert request.num_partitions == 6
    assert request.device_type == "rpi5"
    assert request.typed_partition_idx == 1
    assert request.typed_partition_count == 3
    assert request.partitioning_num_labels == 2
    assert request.partitioning_dirichlet_alpha == pytest.approx(0.3)
    assert request.assignment_seed == derive_seed(
        1337, "partition-assignment", "cifar10_cnn", "device-correlated-label-skew"
    )
    assert request.loader_seed == derive_seed(1337, "fedavg", "train-loader", "cifar10_cnn", 4)


def test_partitioning_device_correlated_label_skew_uses_explicit_partition_device_types() -> None:
    labels = tuple([i % 10 for i in range(200)])
    train = build_classification_partitioner(
        labels=labels,
        num_classes=10,
        request=_partition_request(
            partitioning="device-correlated-label-skew",
            num_partitions=5,
            device_type="unknown",
            partitioning_num_labels=2,
            assignment_seed=42,
        ),
        partition_device_types=("rpi4", "rpi4", "rpi5", "rpi5", "rpi5"),
    ).partition_result
    assert set(train.label_sets_by_partition[0]).issubset(set(range(5)))
    assert set(train.label_sets_by_partition[-1]).issubset(set(range(5, 10)))


def test_partitioning_loader_seed_does_not_change_membership() -> None:
    labels = tuple([i % 5 for i in range(100)])
    request_a = _partition_request(
        partitioning="dirichlet",
        num_partitions=4,
        partitioning_dirichlet_alpha=0.3,
        assignment_seed=99,
        loader_seed=1,
    )
    request_b = _partition_request(
        partitioning="dirichlet",
        num_partitions=4,
        partitioning_dirichlet_alpha=0.3,
        assignment_seed=99,
        loader_seed=2,
    )
    result_a = build_classification_partitioner(
        labels=labels,
        num_classes=5,
        request=request_a,
    ).partition_result
    result_b = build_classification_partitioner(
        labels=labels,
        num_classes=5,
        request=request_b,
    ).partition_result
    assert result_a.indices_by_partition == result_b.indices_by_partition
    assert result_a.class_probabilities == result_b.class_probabilities


def test_typed_device_correlated_requests_partition_within_device_group() -> None:
    labels = tuple([i % 10 for i in range(300)])
    rpi4_request = _partition_request(
        partitioning="device-correlated-label-skew",
        partition_id=5,
        num_partitions=10,
        device_type="rpi4",
        partitioning_num_labels=2,
        assignment_seed=42,
        typed_partition_idx=1,
        typed_partition_count=5,
    )
    rpi5_request = _partition_request(
        partitioning="device-correlated-label-skew",
        partition_id=2,
        num_partitions=10,
        device_type="rpi5",
        partitioning_num_labels=2,
        assignment_seed=42,
        typed_partition_idx=1,
        typed_partition_count=5,
    )
    rpi4_result = build_classification_partitioner(
        labels=labels,
        num_classes=10,
        request=rpi4_request,
    ).partition_result
    rpi5_result = build_classification_partitioner(
        labels=labels,
        num_classes=10,
        request=rpi5_request,
    ).partition_result

    assert len(rpi4_result.indices_by_partition) == 5
    assert len(rpi5_result.indices_by_partition) == 5
    assert all(len(label_set) == 2 for label_set in rpi4_result.label_sets_by_partition)
    assert all(len(label_set) == 2 for label_set in rpi5_result.label_sets_by_partition)
    assert rpi4_result.label_sets_by_partition != rpi5_result.label_sets_by_partition


def test_partitioning_dirichlet_is_deterministic() -> None:
    labels = tuple([i % 5 for i in range(100)])
    request = _partition_request(
        partitioning="dirichlet",
        num_partitions=4,
        partitioning_dirichlet_alpha=0.3,
        assignment_seed=99,
    )
    train_a = build_classification_partitioner(
        labels=labels,
        num_classes=5,
        request=request,
    ).partition_result
    train_b = build_classification_partitioner(
        labels=labels,
        num_classes=5,
        request=request,
    ).partition_result
    assert train_a.indices_by_partition == train_b.indices_by_partition
    assert train_a.class_probabilities == train_b.class_probabilities


def test_masked_cross_entropy_matches_masked_logits() -> None:
    logits = torch.tensor([[1.0, 5.0, -2.0]], dtype=torch.float32)
    labels = torch.tensor([0])
    label_mask = torch.tensor([True, False, True])
    expected = torch.nn.functional.cross_entropy(
        logits.masked_fill(~label_mask.unsqueeze(0), 0.0),
        labels,
        reduction="mean",
    )
    actual = masked_cross_entropy_loss(logits, labels, label_mask=label_mask)
    assert torch.allclose(actual, expected)


def test_masked_cross_entropy_auto_only_enables_for_balanced_label_skew() -> None:
    assert should_use_masked_cross_entropy("auto", partitioning="label-skew-balanced") is True
    assert should_use_masked_cross_entropy("auto", partitioning="iid") is False
    assert should_use_masked_cross_entropy("auto", partitioning="dirichlet") is False


def test_central_evaluate_logs_server_eval_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeTask:
        name = "fake_task"

        def build_model_for_rate(self, model_rate: float, *, global_model_rate: float = 1.0):
            return object()

        def load_model_state(self, model, state_dict) -> None:
            return None

        def load_centralized_test_dataset(self, batch_size: int = 256, *, seed: int | None = None):
            return ["fake_loader"]

        def test(self, model, testloader, device: str):
            return 0.25, 0.75

    monkeypatch.setattr("fedctl_research.methods.runtime.resolve_task", lambda _name: _FakeTask())
    logger = _Logger()
    artifact_logger = _ArtifactLogger()
    context = SimpleNamespace(run_config={"task": "fake_task", "global-model-rate": 1.0}, node_config={})
    arrays = ArrayRecord(OrderedDict({"w": torch.tensor([1.0])}))
    evaluate = central_evaluate_fn(
        context,
        method_label="fedavg",
        experiment_logger=logger,
        artifact_logger=artifact_logger,
        progress_provider=lambda: {"client_trips_total": 5},
        num_server_rounds=1,
    )

    result = evaluate(1, arrays)

    assert result is not None
    assert logger.system_calls
    _, system_metrics = logger.system_calls[-1]
    assert "round-server-eval-duration-s" in system_metrics
    assert system_metrics["round-server-eval-duration-s"] >= 0.0
    assert artifact_logger.evaluations
    assert "round_server_eval_duration_s" in artifact_logger.evaluations[-1]


def test_sync_strategy_logs_per_client_eval_events() -> None:
    strategy = FedAvgBaseline(
        fraction_train=1.0,
        fraction_evaluate=1.0,
        min_train_nodes=2,
        min_evaluate_nodes=2,
        min_available_nodes=2,
        experiment_logger=_Logger(),
        artifact_logger=_ArtifactLogger(),
        task_name="fashion_mnist_cnn",
        global_model_rate=1.0,
    )
    strategy.set_node_capabilities({1: "rpi5", 2: "rpi4"})
    strategy._round_sampled_nodes = 2
    strategy._round_started_at = time.perf_counter()
    replies = [
        _make_message(
            node_id=1,
            group_id="eval",
            metrics={
                "eval-acc": 0.8,
                "eval-loss": 0.5,
                "eval-duration-s": 1.2,
                "eval-num-examples": 100,
                "num-examples": 100,
            },
            message_type="evaluate",
        ),
        _make_message(
            node_id=2,
            group_id="eval",
            metrics={
                "eval-acc": 0.6,
                "eval-loss": 0.7,
                "eval-duration-s": 1.5,
                "eval-num-examples": 120,
                "num-examples": 120,
            },
            message_type="evaluate",
        ),
    ]

    strategy.aggregate_evaluate(server_round=1, replies=replies)

    assert len(strategy.artifact_logger.client_evals) == 2
    first = strategy.artifact_logger.client_evals[0]
    assert first["server_step"] == 1
    assert first["node_id"] == 1
    assert first["device_type"] == "rpi5"
    assert first["eval_acc"] == pytest.approx(0.8)


def test_run_submodel_evaluations_logs_per_client_local_events(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeTask:
        name = "fake_task"

        def build_model_for_rate(self, model_rate: float, *, global_model_rate: float = 1.0):
            return {"model_rate": model_rate, "global_model_rate": global_model_rate}

        def load_model_state(self, model, state_dict) -> None:
            model["state_dict"] = state_dict

        def load_centralized_test_dataset(self, batch_size: int = 256, *, seed: int | None = None):
            return ["fake_loader", seed]

        def test(self, model, testloader, device: str):
            return 0.2, 0.9

    monkeypatch.setattr("fedctl_research.methods.runtime.resolve_task", lambda _name: _FakeTask())
    monkeypatch.setattr(
        "fedctl_research.methods.heterofl.slicing.slice_state_dict",
        lambda state_dict, param_idx: OrderedDict(state_dict),
    )

    class _Grid:
        def get_node_ids(self):
            return [1, 2]

        def send_and_receive(self, messages, timeout: float):
            del timeout
            replies = []
            metrics_by_node = {
                1: {"eval-acc": 0.8, "eval-loss": 0.4, "num-examples": 100},
                2: {"eval-acc": 0.6, "eval-loss": 0.7, "num-examples": 120},
            }
            for message in messages:
                node_id = int(message.metadata.dst_node_id)
                replies.append(
                    _make_message(
                        node_id=node_id,
                        group_id=message.metadata.group_id,
                        metrics=metrics_by_node[node_id],
                        message_type="evaluate",
                    )
                )
            return replies

    rate_assigner = ModelRateAssigner(
            mode="fix",
            default_model_rate=0.25,
            explicit_rate_by_node_id={},
            explicit_rate_by_partition_id={},
            rate_by_device_type={"rpi4": 0.25, "rpi5": 1.0},
            device_type_by_node_id={1: "rpi4", 2: "rpi5"},
            partition_id_by_node_id={},
            dynamic_levels=(1.0, 0.5, 0.25, 0.125),
            dynamic_proportions=(0.25, 0.25, 0.25, 0.25),
            device_type_allocations={},
            seed=1337,
    )
    partition_plan = {
        1: {"partition-device-type": "rpi4", "typed-partition-idx": 0, "typed-partition-count": 1},
        2: {"partition-device-type": "rpi5", "typed-partition-idx": 0, "typed-partition-count": 1},
    }
    rate_assigner.set_typed_partition_plan(partition_plan)

    strategy = SimpleNamespace(
        rate_assigner=rate_assigner,
        partition_plan_by_node_id=partition_plan,
        build_param_indices=lambda global_state, *, model_rate, server_round: {},
    )
    logger = _Logger()
    artifact_logger = _ArtifactLogger()

    context = SimpleNamespace(
        run_config={
            "task": "fake_task",
            "global-model-rate": 1.0,
            "submodel-local-eval-enabled": True,
            "model-rate-levels": "1.0,0.5,0.25,0.125",
        },
        node_config={},
    )

    run_submodel_evaluations(
        grid=_Grid(),
        context=context,
        strategy=strategy,
        arrays=ArrayRecord(OrderedDict({"w": torch.tensor([1.0])})),
        method_label="heterofl",
        experiment_logger=logger,
        artifact_logger=artifact_logger,
        server_step=7,
    )

    local_client_events = [
        event
        for event in artifact_logger.submodel_evaluations
        if event["scope"] == "local_client" and event["model_rate"] == pytest.approx(0.25)
    ]
    assert len(local_client_events) == 2
    by_node = {int(event["node_id"]): event for event in local_client_events}
    assert by_node[1]["device_type"] == "rpi4"
    assert by_node[1]["client_model_rate"] == pytest.approx(0.25)
    assert by_node[1]["typed_partition_idx"] == 0
    assert by_node[2]["device_type"] == "rpi5"
    assert by_node[2]["client_model_rate"] == pytest.approx(1.0)
    assert by_node[2]["eval_acc"] == pytest.approx(0.6)
    assert logger.submodel_client_event_calls


def test_derive_seed_is_stable_and_partition_specific() -> None:
    seed_a = derive_seed(1337, "client-train", "fashion_mnist_mlp", 0)
    seed_b = derive_seed(1337, "client-train", "fashion_mnist_mlp", 0)
    seed_c = derive_seed(1337, "client-train", "fashion_mnist_mlp", 1)
    assert seed_a == seed_b
    assert seed_a != seed_c


def test_large_server_config_exists() -> None:
    config_path = (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "fedctl_research"
        / "experiment_configs"
        / "compute_heterogeneity"
        / "ablations"
        / "method_mechanisms"
        / "large_server"
        / "cifar10_cnn"
        / "gamma_2"
        / "fedrolex.toml"
    )
    data = tomllib.loads(config_path.read_text())
    assert data["model"]["global-model-rate"] == 2.0
    assert data["devices"]["rpi5"]["model-rate"] == 1.0
    assert data["devices"]["rpi4"]["model-rate"] == 0.25


def test_all_active_experiment_configs_set_required_keys() -> None:
    config_root = Path(__file__).resolve().parents[1] / "apps" / "fedctl_research" / "experiment_configs"
    config_paths = sorted(config_root.rglob("*.toml"))
    assert config_paths
    for path in config_paths:
        if path.name == "README.md":
            continue
        data = tomllib.loads(path.read_text())
        assert "experiment" in data, str(path)
        assert "server" in data, str(path)
        assert "client" in data, str(path)
        assert "data" in data, str(path)
        assert "model" in data, str(path)
        if "compute_heterogeneity" in path.parts:
            assert "capacity" in data, str(path)
        assert "wandb" in data, str(path)
        assert "rpi4" in data["devices"], str(path)
        assert "rpi5" in data["devices"], str(path)
        if "smoke" not in path.parts:
            assert data["experiment"]["seeds"] == [1337, 1338, 1339], str(path)
        assert data["wandb"]["enabled"] is True, str(path)
        if "capacity" in data:
            assert "model-split-mode" in data["capacity"], str(path)
        assert "partitioning-num-labels" in data["data"], str(path)
        assert "partitioning-dirichlet-alpha" in data["data"], str(path)
        assert "masked-cross-entropy" in data["data"], str(path)
    dynamic_paths = [path for path in config_paths if "four_levels" in path.parts]
    assert dynamic_paths
    for path in dynamic_paths:
        data = tomllib.loads(path.read_text())
        assert data["capacity"]["model-split-mode"] == "dynamic", str(path)
        assert data["capacity"]["model-rate-levels"] == [1.0, 0.5, 0.25, 0.125], str(path)
        assert data["capacity"]["model-rate-proportions"] == [0.25, 0.25, 0.25, 0.25], str(path)
    non_iid_paths = [
        path
        for path in config_paths
        if "compute_heterogeneity" in path.parts and "non_iid" in path.parts
    ]
    assert non_iid_paths
    for path in non_iid_paths:
        data = tomllib.loads(path.read_text())
        assert data["data"]["partitioning"] == "label-skew-balanced", str(path)
    main_noniid_paths = [
        path
        for path in config_paths
        if "compute_heterogeneity" in path.parts and "noniid" in path.parts
    ]
    assert main_noniid_paths
    for path in main_noniid_paths:
        data = tomllib.loads(path.read_text())
        assert data["data"]["partitioning"] == "dirichlet", str(path)
        assert data["data"]["partitioning-dirichlet-alpha"] == 0.3, str(path)
        assert data["server"]["fraction-train"] == 0.5, str(path)
        assert data["server"]["min-train-nodes"] == 10, str(path)


def test_experiment_config_tree_matches_study_matrix() -> None:
    config_root = Path(__file__).resolve().parents[1] / "apps" / "fedctl_research" / "experiment_configs"
    expected_subset = {
        "smoke/compute_heterogeneity/fashion_mnist_mlp/fedavg.toml",
        "smoke/compute_heterogeneity/fashion_mnist_mlp/heterofl.toml",
        "smoke/compute_heterogeneity/fashion_mnist_mlp/fedrolex.toml",
        "compute_heterogeneity/main/fashion_mnist_cnn/fedavg.toml",
        "compute_heterogeneity/main/fashion_mnist_cnn/heterofl.toml",
        "compute_heterogeneity/main/fashion_mnist_cnn/fedrolex.toml",
        "compute_heterogeneity/main/cifar10_cnn/iid/fedavg.toml",
        "compute_heterogeneity/main/cifar10_cnn/iid/heterofl.toml",
        "compute_heterogeneity/main/cifar10_cnn/iid/fedrolex.toml",
        "compute_heterogeneity/main/cifar10_cnn/iid/fiarse.toml",
        "compute_heterogeneity/main/cifar10_cnn/noniid/fedavg.toml",
        "compute_heterogeneity/main/cifar10_cnn/noniid/heterofl.toml",
        "compute_heterogeneity/main/cifar10_cnn/noniid/fedrolex.toml",
        "compute_heterogeneity/main/cifar10_cnn/noniid/fiarse.toml",
        "compute_heterogeneity/ablations/capacity_design/four_levels/fashion_mnist_cnn/heterofl.toml",
        "compute_heterogeneity/ablations/capacity_design/four_levels/fashion_mnist_cnn/fedrolex.toml",
        "compute_heterogeneity/ablations/capacity_design/fixed_pair_interpolation/cifar10_cnn/a/heterofl.toml",
        "compute_heterogeneity/ablations/capacity_design/fixed_pair_interpolation/cifar10_cnn/a_e/p001/heterofl.toml",
        "compute_heterogeneity/ablations/capacity_design/fixed_pair_interpolation/cifar10_cnn/d_e/p009/heterofl.toml",
        "compute_heterogeneity/ablations/robustness_extension/non_iid/fashion_mnist_cnn/heterofl.toml",
        "compute_heterogeneity/ablations/robustness_extension/non_iid/fashion_mnist_cnn/fedrolex.toml",
        "compute_heterogeneity/ablations/method_mechanisms/large_server/cifar10_cnn/gamma_2/fedrolex.toml",
        "compute_heterogeneity/ablations/robustness_extension/preresnet18/cifar10_preresnet18/fedavg.toml",
        "compute_heterogeneity/ablations/robustness_extension/preresnet18/cifar10_preresnet18/heterofl.toml",
        "compute_heterogeneity/ablations/robustness_extension/preresnet18/cifar10_preresnet18/fedrolex.toml",
        "compute_heterogeneity/ablations/capacity_design/uniform_five_levels/cifar10_cnn/heterofl.toml",
        "compute_heterogeneity/ablations/capacity_design/uniform_five_levels/cifar10_cnn/fedrolex.toml",
        "compute_heterogeneity/ablations/robustness_extension/non_iid/cifar10_cnn/high/fedavg.toml",
        "compute_heterogeneity/ablations/robustness_extension/non_iid/cifar10_cnn/high/heterofl.toml",
        "compute_heterogeneity/ablations/robustness_extension/non_iid/cifar10_cnn/high/fedrolex.toml",
        "compute_heterogeneity/ablations/robustness_extension/non_iid/cifar10_cnn/low/fedavg.toml",
        "compute_heterogeneity/ablations/robustness_extension/non_iid/cifar10_cnn/low/heterofl.toml",
        "compute_heterogeneity/ablations/robustness_extension/non_iid/cifar10_cnn/low/fedrolex.toml",
        "compute_heterogeneity/ablations/participation_coverage/participation_rate/cifar10_cnn/25pct/heterofl.toml",
        "compute_heterogeneity/ablations/participation_coverage/participation_rate/cifar10_cnn/25pct/fedrolex.toml",
        "compute_heterogeneity/ablations/participation_coverage/participation_rate/cifar10_cnn/50pct/heterofl.toml",
        "compute_heterogeneity/ablations/participation_coverage/participation_rate/cifar10_cnn/50pct/fedrolex.toml",
        "compute_heterogeneity/ablations/participation_coverage/participation_rate/cifar10_cnn/100pct/heterofl.toml",
        "compute_heterogeneity/ablations/participation_coverage/participation_rate/cifar10_cnn/100pct/fedrolex.toml",
        "compute_heterogeneity/ablations/participation_coverage/inclusiveness/cifar10_cnn/high/fedrolex.toml",
        "compute_heterogeneity/ablations/participation_coverage/inclusiveness/cifar10_cnn/low/fedrolex.toml",
    }
    actual = {
        str(path.relative_to(config_root))
        for path in config_root.rglob("*.toml")
    }
    assert expected_subset.issubset(actual)
    capacity_sweep = sorted(
        path
        for path in actual
        if path.startswith("compute_heterogeneity/ablations/capacity_design/capacity_distribution/cifar10_cnn/")
    )
    assert len(capacity_sweep) == 11
    fixed_pair_sweep = sorted(
        path
        for path in actual
        if path.startswith("compute_heterogeneity/ablations/capacity_design/fixed_pair_interpolation/cifar10_cnn/")
    )
    assert len(fixed_pair_sweep) == 96
    gamma_sweep = sorted(
        path
        for path in actual
        if path.startswith("compute_heterogeneity/ablations/method_mechanisms/large_server/cifar10_cnn/gamma_")
    )
    assert gamma_sweep == [
        "compute_heterogeneity/ablations/method_mechanisms/large_server/cifar10_cnn/gamma_16/fedrolex.toml",
        "compute_heterogeneity/ablations/method_mechanisms/large_server/cifar10_cnn/gamma_2/fedrolex.toml",
        "compute_heterogeneity/ablations/method_mechanisms/large_server/cifar10_cnn/gamma_4/fedrolex.toml",
        "compute_heterogeneity/ablations/method_mechanisms/large_server/cifar10_cnn/gamma_8/fedrolex.toml",
    ]


def test_new_paper_inspired_configs_encode_expected_values() -> None:
    config_root = Path(__file__).resolve().parents[1] / "apps" / "fedctl_research" / "experiment_configs"

    inclusiveness = tomllib.loads(
        (
            config_root
            / "compute_heterogeneity"
            / "ablations"
            / "participation_coverage"
            / "inclusiveness"
            / "cifar10_cnn"
            / "high"
            / "fedrolex.toml"
        ).read_text()
    )
    assert inclusiveness["capacity"]["model-rate-levels"] == [1.0, 0.5, 0.25, 0.125, 0.0625]
    assert inclusiveness["capacity"]["model-rate-proportions"] == [0.06, 0.1, 0.11, 0.18, 0.55]

    low_heterogeneity = tomllib.loads(
        (
            config_root
            / "compute_heterogeneity"
            / "ablations"
            / "robustness_extension"
            / "non_iid"
            / "cifar10_cnn"
            / "low"
            / "fedrolex.toml"
        ).read_text()
    )
    assert low_heterogeneity["data"]["partitioning"] == "label-skew-balanced"
    assert low_heterogeneity["data"]["partitioning-num-labels"] == 5

    main_noniid = tomllib.loads(
        (
            config_root
            / "compute_heterogeneity"
            / "main"
            / "cifar10_cnn"
            / "noniid"
            / "fedrolex.toml"
        ).read_text()
    )
    assert main_noniid["server"]["num-server-rounds"] == 40
    assert main_noniid["server"]["fraction-train"] == 0.5
    assert main_noniid["server"]["min-train-nodes"] == 10
    assert main_noniid["data"]["partitioning"] == "dirichlet"
    assert main_noniid["data"]["partitioning-dirichlet-alpha"] == 0.3

    participation = tomllib.loads(
        (
            config_root
            / "compute_heterogeneity"
            / "ablations"
            / "participation_coverage"
            / "participation_rate"
            / "cifar10_cnn"
            / "50pct"
            / "fedrolex.toml"
        ).read_text()
    )
    assert participation["server"]["fraction-train"] == 0.5
    assert participation["server"]["min-train-nodes"] == 2

    rho_mid = tomllib.loads(
        (
            config_root
            / "compute_heterogeneity"
            / "ablations"
            / "capacity_design"
            / "capacity_distribution"
            / "cifar10_cnn"
            / "rho_050"
            / "fedrolex.toml"
        ).read_text()
    )
    assert rho_mid["capacity"]["model-rate-levels"] == [1.0, 0.0625]
    assert rho_mid["capacity"]["model-rate-proportions"] == [0.5, 0.5]

    fixed_singleton = tomllib.loads(
        (
            config_root
            / "compute_heterogeneity"
            / "ablations"
            / "capacity_design"
            / "fixed_pair_interpolation"
            / "cifar10_cnn"
            / "a"
            / "heterofl.toml"
        ).read_text()
    )
    assert fixed_singleton["server"]["min-available-nodes"] == 10
    assert fixed_singleton["model"]["global-model-rate"] == 1.0
    assert fixed_singleton["capacity"]["model-split-mode"] == "fix"
    assert fixed_singleton["capacity"]["heterofl-partition-rates"].count(",") == 9

    fixed_pair = tomllib.loads(
        (
            config_root
            / "compute_heterogeneity"
            / "ablations"
            / "capacity_design"
            / "fixed_pair_interpolation"
            / "cifar10_cnn"
            / "a_e"
            / "p005"
            / "heterofl.toml"
        ).read_text()
    )
    assert fixed_pair["capacity"]["model-rate-levels"] == [1.0, 0.0625]
    assert fixed_pair["capacity"]["model-rate-proportions"] == [0.5, 0.5]
    assert fixed_pair["capacity"]["heterofl-partition-rates"].startswith("0:1")


def test_main_study_configs_match_balanced_twelve_node_plan() -> None:
    app_root = Path(__file__).resolve().parents[1] / "apps" / "fedctl_research"

    compute_paths = sorted((app_root / "experiment_configs" / "compute_heterogeneity" / "main").rglob("*.toml"))
    network_paths = sorted((app_root / "experiment_configs" / "network_heterogeneity" / "main").rglob("*.toml"))

    assert compute_paths
    assert network_paths

    for path in compute_paths:
        data = tomllib.loads(path.read_text())
        is_cifar10 = "cifar10_cnn" in path.parts
        is_main_cifar10_noniid = (
            "compute_heterogeneity" in path.parts
            and "main" in path.parts
            and "cifar10_cnn" in path.parts
            and "noniid" in path.parts
        )
        expected_rounds = 40 if is_main_cifar10_noniid else (20 if is_cifar10 else 15)
        expected_train_examples = 2500 if is_cifar10 else 5000
        expected_test_examples = 500 if is_cifar10 else 834
        assert data["server"]["num-server-rounds"] == expected_rounds, str(path)
        expected_nodes = 20 if is_cifar10 else 12
        expected_min_nodes = 10 if is_main_cifar10_noniid else expected_nodes
        expected_fraction = 0.5 if is_main_cifar10_noniid else 1.0
        assert data["server"]["min-available-nodes"] == expected_nodes, str(path)
        assert data["server"]["min-train-nodes"] == expected_min_nodes, str(path)
        assert data["server"]["min-evaluate-nodes"] == expected_min_nodes, str(path)
        assert data["server"]["fraction-train"] == expected_fraction, str(path)
        assert data["server"]["fraction-evaluate"] == expected_fraction, str(path)
        assert data["client"]["local-epochs"] == (3 if is_cifar10 else 1), str(path)
        assert data["client"]["learning-rate"] == (0.05 if is_cifar10 else 0.01), str(path)
        assert data["devices"]["rpi4"]["batch-size"] == 8, str(path)
        assert data["devices"]["rpi4"]["max-train-examples"] == expected_train_examples, str(path)
        assert data["devices"]["rpi4"]["max-test-examples"] == expected_test_examples, str(path)
        assert data["devices"]["rpi5"]["batch-size"] == 32, str(path)
        assert data["devices"]["rpi5"]["max-train-examples"] == expected_train_examples, str(path)
        assert data["devices"]["rpi5"]["max-test-examples"] == expected_test_examples, str(path)

    for path in network_paths:
        data = tomllib.loads(path.read_text())
        expected_rounds = 15 if "fashion_mnist_cnn" in str(path) else 20
        expected_train_examples = 5000 if "fashion_mnist_cnn" in str(path) else 4167
        expected_test_examples = 834
        if data["experiment"]["method"] in {"fedbuff", "fedstaleweight"}:
            assert data["fedbuff"]["num-server-steps"] == expected_rounds, str(path)
            assert data["fedbuff"]["train-concurrency"] == 8, str(path)
            assert data["fedbuff"]["buffer-size"] == 10, str(path)
            assert data["fedbuff"]["staleness-alpha"] == 0.5, str(path)
            if data["experiment"]["method"] == "fedbuff":
                assert data["fedbuff"]["staleness-weighting"] == "polynomial", str(path)
        else:
            assert data["server"]["num-server-rounds"] == expected_rounds, str(path)
        assert data["server"]["min-available-nodes"] == 12, str(path)
        assert data["server"]["min-train-nodes"] == 12, str(path)
        assert data["server"]["min-evaluate-nodes"] == 12, str(path)
        assert data["server"]["fraction-train"] == 1.0, str(path)
        assert data["server"]["fraction-evaluate"] == 1.0, str(path)
        assert data["client"]["local-epochs"] == 1, str(path)
        assert data["client"]["learning-rate"] == 0.01, str(path)
        assert data["devices"]["rpi4"]["batch-size"] == 8, str(path)
        assert data["devices"]["rpi4"]["max-train-examples"] == expected_train_examples, str(path)
        assert data["devices"]["rpi4"]["max-test-examples"] == expected_test_examples, str(path)
        assert data["devices"]["rpi5"]["batch-size"] == 32, str(path)
        assert data["devices"]["rpi5"]["max-train-examples"] == expected_train_examples, str(path)
        assert data["devices"]["rpi5"]["max-test-examples"] == expected_test_examples, str(path)

    compute_repo = yaml.safe_load(
        (app_root / "repo_configs" / "compute_heterogeneity" / "main" / "none.yaml").read_text()
    )
    network_repo = yaml.safe_load(
        (app_root / "repo_configs" / "network_heterogeneity" / "main" / "none.yaml").read_text()
    )
    assert compute_repo["deploy"]["supernodes"] == {"rpi4": 10, "rpi5": 10}
    assert network_repo["deploy"]["supernodes"] == {"rpi4": 6, "rpi5": 6}
