"""Shared method runtime helpers for client/server Flower app handlers."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from collections.abc import Mapping
import os
import time
from logging import INFO, WARNING
from typing import Callable

import torch
from flwr.app import ArrayRecord, ConfigRecord, Context, Message, MessageType, MetricRecord, RecordDict
from flwr.common.logger import log
from flwr.serverapp import Grid
from flwr.serverapp.strategy import Result

from fedctl_research.config import (
    get_client_eval_enabled,
    get_final_client_eval_enabled,
    get_float,
    get_int,
    get_masked_cross_entropy_mode,
    get_model_rate_levels,
    get_optimizer_name,
    get_optional_bool,
    get_optional_float,
    get_optional_int,
    get_partitioning_continuous_column,
    get_partitioning_continuous_strictness,
    get_partitioning_dirichlet_alpha,
    get_partitioning_num_labels,
    get_partitioning_total_partitions,
    get_stop_on_target_score,
    get_str,
    get_submodel_eval_rates,
    get_submodel_local_eval_enabled,
    get_target_score,
    lookup_or_default,
    parse_node_device_type_map,
    resolve_device_type_for_context,
    resolve_instance_idx,
    resolve_nomad_node_id,
)
from fedctl_research.costs import build_model_catalog
from fedctl_research.partitioning.partition_request import PartitionRequest
from fedctl_research.result_artifacts import ResultArtifactLogger
from fedctl_research.seeding import derive_seed, set_global_seed
from fedctl_research.tasks.registry import resolve_task
from fedctl_research.wandb_logging import create_experiment_logger

ResolveModelRateFn = Callable[[Message, Context], float]
StrategyFactory = Callable[[Context, object], object]
TypedPartitionPlanEntry = dict[str, int | str]
TypedPartitionPlan = dict[int, TypedPartitionPlanEntry]


def _task_score_name(task: object) -> str:
    return str(getattr(task, "primary_score_name", "acc")).strip().lower() or "acc"


def _task_score_label(task: object) -> str:
    score_name = _task_score_name(task)
    return "score" if score_name != "acc" else "acc"


def _evaluation_metric_record(
    task: object,
    *,
    loss: float,
    score: float,
    num_examples: int | None = None,
    duration_s: float | None = None,
    server_round: int | None = None,
) -> MetricRecord:
    score_name = _task_score_name(task)
    metrics: dict[str, float | int] = {
        "eval-loss": float(loss),
        "eval-score": float(score),
        "eval-acc": float(score),
    }
    if score_name != "acc":
        metrics[f"eval-{score_name}"] = float(score)
    if num_examples is not None:
        metrics["num-examples"] = int(num_examples)
        metrics["eval-num-examples"] = int(num_examples)
    if duration_s is not None:
        metrics["eval-duration-s"] = float(duration_s)
    if server_round is not None:
        metrics["server-round"] = int(server_round)
    return MetricRecord(metrics)


def _artifact_eval_payload(
    task: object,
    *,
    loss: float,
    score: float,
) -> dict[str, float]:
    score_name = _task_score_name(task)
    payload = {
        "eval_loss": float(loss),
        "eval_score": float(score),
        "eval_acc": float(score),
    }
    if score_name != "acc":
        payload[f"eval_{score_name}"] = float(score)
    return payload


def _metric_score_value(task: object, metrics: Mapping[str, object]) -> float | None:
    score_name = _task_score_name(task)
    for key in (f"eval-{score_name}", "eval-score", "eval-acc"):
        value = metrics.get(key)
        if value is not None:
            return float(value)
    return None


def _score_meets_target(*, direction: str, value: float, threshold: float) -> bool:
    normalized_direction = str(direction).strip().lower() or "max"
    if normalized_direction == "min":
        return value <= threshold
    return value >= threshold


def _sync_client_trip_budget(run_config: Mapping[str, object]) -> int:
    return get_int(run_config, "num-server-rounds") * get_int(run_config, "min-train-nodes")


def _async_client_trip_budget(run_config: Mapping[str, object]) -> int:
    return get_int(run_config, "fedbuff-num-server-steps") * get_int(run_config, "fedbuff-buffer-size")


@dataclass
class TargetStopController:
    score_name: str
    score_direction: str
    threshold: float | None
    stop_on_target: bool
    client_trip_budget: int | None
    reached: bool = False
    client_trips_to_target: int | None = None
    server_step_to_target: int | None = None
    wall_clock_s_to_target: float | None = None

    @classmethod
    def from_task(
        cls,
        task: object,
        run_config: Mapping[str, object],
        *,
        client_trip_budget: int | None,
    ) -> "TargetStopController":
        return cls(
            score_name=_task_score_name(task),
            score_direction=str(getattr(task, "primary_score_direction", "max")).strip().lower() or "max",
            threshold=get_target_score(run_config),
            stop_on_target=get_stop_on_target_score(run_config),
            client_trip_budget=client_trip_budget,
        )

    @property
    def enabled(self) -> bool:
        return self.threshold is not None

    def observe(
        self,
        *,
        task: object,
        server_step: int,
        metrics: Mapping[str, object] | None,
        progress_state: Mapping[str, object],
    ) -> bool:
        if not self.enabled or self.reached or metrics is None:
            return False
        score_value = _metric_score_value(task, metrics)
        if score_value is None or self.threshold is None:
            return False
        if not _score_meets_target(direction=self.score_direction, value=score_value, threshold=self.threshold):
            return False
        self.reached = True
        self.client_trips_to_target = int(progress_state.get("client_trips_total", 0))
        self.server_step_to_target = int(server_step)
        self.wall_clock_s_to_target = float(progress_state.get("wall_clock_s_since_start", 0.0))
        return self.stop_on_target

    def summary_metrics(self) -> dict[str, int | float | bool | str]:
        if not self.enabled:
            return {}
        summary: dict[str, int | float | bool | str] = {
            "target/score_name": self.score_name,
            "target/score_threshold": float(self.threshold) if self.threshold is not None else 0.0,
            "target/reached": self.reached,
            "target/censored": not self.reached,
        }
        if self.client_trip_budget is not None:
            summary["target/client_trip_budget"] = int(self.client_trip_budget)
        if self.reached:
            if self.client_trips_to_target is not None:
                summary["target/client_trips_to_target"] = int(self.client_trips_to_target)
            if self.server_step_to_target is not None:
                summary["target/server_step_to_target"] = int(self.server_step_to_target)
            if self.wall_clock_s_to_target is not None:
                summary["target/wall_clock_s_to_target"] = float(self.wall_clock_s_to_target)
        return summary


def _experiment_name() -> str:
    return os.environ.get("FEDCTL_EXPERIMENT", "experiment")


def _capability_node_label(node_id: object) -> str:
    return f"{node_id:>20}"


def _capability_device_label(device_type: object) -> str:
    value = str(device_type) if device_type is not None else "-"
    return f"{value:<7}"


def create_result_artifact_logger(context: Context) -> ResultArtifactLogger:
    return ResultArtifactLogger(
        experiment=_experiment_name(),
        method=get_str(context.run_config, "method"),
        task=get_str(context.run_config, "task"),
    )


def client_prefix(context: Context, *, method_label: str) -> str:
    return (
        f"[{method_label}]"
        f" device_type={resolve_device_type_for_context(context)}"
        f" instance_idx={os.environ.get('FEDCTL_INSTANCE_IDX', '-')}"
        f" partition_id={context.node_config.get('partition-id', '-')}"
        f" nomad_node_id={resolve_nomad_node_id() or '-'}"
    )


def client_log(context: Context, *, method_label: str, message: str) -> None:
    print(f"{client_prefix(context, method_label=method_label)} {message}", flush=True)


def server_log(*, method_label: str, message: str) -> None:
    print(f"[{method_label}][server] {message}", flush=True)


def _metric_record_plain_dict(metrics: Mapping[str, object] | MetricRecord | None) -> dict[str, int | float]:
    if metrics is None:
        return {}
    plain: dict[str, int | float] = {}
    for key, value in dict(metrics).items():
        if isinstance(value, bool):
            plain[str(key)] = int(value)
        elif isinstance(value, (int, float)):
            plain[str(key)] = value
    return plain


def _log_sync_strategy_header(
    *,
    strategy: object,
    num_server_rounds: int,
    initial_arrays: ArrayRecord,
    train_config: ConfigRecord,
    evaluate_config: ConfigRecord,
    min_train_nodes: int,
    min_evaluate_nodes: int,
    min_available_nodes: int,
    fraction_train: float,
    fraction_evaluate: float,
) -> None:
    try:
        array_size_mb = sum(tensor.numel() * tensor.element_size() for tensor in initial_arrays.values()) / (1024 * 1024)
    except Exception:
        array_size_mb = 0.0
    log(INFO, "Starting %s strategy:", strategy.__class__.__name__)
    log(INFO, " ├── Number of rounds: %s", num_server_rounds)
    log(INFO, " ├── ArrayRecord (%.2f MB)", array_size_mb)
    log(INFO, " ├── ConfigRecord (train): %s", dict(train_config))
    log(INFO, " ├── ConfigRecord (evaluate): %s", dict(evaluate_config))
    log(INFO, " ├──> Sampling:")
    log(INFO, " │ ├──Fraction: train (%.2f) | evaluate (%5.2f)", fraction_train, fraction_evaluate)
    log(INFO, " │ ├──Minimum nodes: train (%s) | evaluate (%s)", min_train_nodes, min_evaluate_nodes)
    log(INFO, " │ └──Minimum available nodes: %s", min_available_nodes)
    log(INFO, " └──> Keys in records:")
    log(INFO, " ├── Weighted by: 'num-examples'")
    log(INFO, " ├── ArrayRecord key: 'arrays'")
    log(INFO, " └── ConfigRecord key: 'config'")
    log(INFO, "")


def _log_sync_metric_record(*, label: str, metrics: Mapping[str, object] | MetricRecord | None) -> None:
    if metrics is None:
        return
    log(INFO, " └──> %s: %s", label, _metric_record_plain_dict(metrics))


def query_capabilities(msg: Message, context: Context) -> Message:
    reply = RecordDict(
        {
            "capabilities": ConfigRecord(
                {
                    "device-type": resolve_device_type_for_context(context),
                    "instance-idx": resolve_instance_idx(),
                    "nomad-node-id": resolve_nomad_node_id(),
                    "partition-id": str(context.node_config.get("partition-id", "")),
                }
            )
        }
    )
    return Message(content=reply, reply_to=msg)


def _optional_config_int(config: Mapping[str, object], key: str) -> int | None:
    value = config.get(key)
    if value is None or value == "":
        return None
    return int(value)


def _message_partition_context(
    msg: Message,
    *,
    local_device_type: str,
) -> tuple[str, int | None, int | None]:
    config = msg.content.get("config")
    if not isinstance(config, Mapping):
        return local_device_type, None, None
    return (
        str(config.get("partition-device-type", local_device_type)),
        _optional_config_int(config, "typed-partition-idx"),
        _optional_config_int(config, "typed-partition-count"),
    )


def build_partition_request(
    *,
    context: Context,
    msg: Message,
    task_name: str,
    method_label: str,
    split: str,
    local_device_type: str,
) -> PartitionRequest:
    partition_id = int(context.node_config["partition-id"])
    partitioning = get_str(context.run_config, "partitioning")
    partition_device_type, typed_partition_idx, typed_partition_count = _message_partition_context(
        msg,
        local_device_type=local_device_type,
    )

    base_seed = get_optional_int(context.run_config, "seed")
    loader_seed = None
    assignment_seed = None
    if base_seed is not None:
        loader_seed = derive_seed(base_seed, method_label, f"{split}-loader", task_name, partition_id)
        assignment_seed = derive_seed(base_seed, "partition-assignment", task_name, partitioning)

    total_partitions = get_partitioning_total_partitions(context.run_config)
    num_partitions = total_partitions or int(context.node_config["num-partitions"])
    if partition_id >= num_partitions:
        raise ValueError(
            f"partition-id {partition_id} is outside the configured partition universe "
            f"of {num_partitions} partitions"
        )

    return PartitionRequest(
        partition_id=partition_id,
        num_partitions=num_partitions,
        partitioning=partitioning,
        device_type=partition_device_type,
        partitioning_num_labels=get_partitioning_num_labels(context.run_config),
        partitioning_dirichlet_alpha=get_partitioning_dirichlet_alpha(context.run_config),
        partitioning_continuous_column=get_partitioning_continuous_column(context.run_config),
        partitioning_continuous_strictness=get_partitioning_continuous_strictness(context.run_config),
        assignment_seed=assignment_seed,
        loader_seed=loader_seed,
        typed_partition_idx=typed_partition_idx,
        typed_partition_count=typed_partition_count,
    )


def build_typed_partition_plan(
    *,
    node_ids: list[int],
    device_type_by_node_id: Mapping[int, str],
) -> TypedPartitionPlan:
    grouped_node_ids: dict[str, list[int]] = {}
    for node_id in sorted(int(node_id) for node_id in node_ids):
        device_type = str(device_type_by_node_id.get(node_id, "unknown"))
        grouped_node_ids.setdefault(device_type, []).append(node_id)

    plan: TypedPartitionPlan = {}
    for device_type in sorted(grouped_node_ids):
        device_nodes = grouped_node_ids[device_type]
        for typed_partition_idx, node_id in enumerate(device_nodes):
            plan[node_id] = {
                "partition-device-type": device_type,
                "typed-partition-idx": int(typed_partition_idx),
                "typed-partition-count": int(len(device_nodes)),
            }
    return plan


def client_train(
    msg: Message,
    context: Context,
    *,
    method_label: str,
    resolve_model_rate: ResolveModelRateFn,
) -> Message:
    total_start = time.perf_counter()
    task = resolve_task(get_str(context.run_config, "task"))
    local_device_type = resolve_device_type_for_context(context)
    model_rate = resolve_model_rate(msg, context)
    partition_id = int(context.node_config["partition-id"])
    partitioning = get_str(context.run_config, "partitioning")
    base_seed = get_optional_int(context.run_config, "seed")
    if base_seed is not None:
        local_seed = derive_seed(base_seed, method_label, "client-train", task.name, partition_id)
        set_global_seed(local_seed)
    request = build_partition_request(
        context=context,
        msg=msg,
        task_name=task.name,
        method_label=method_label,
        split="train",
        local_device_type=local_device_type,
    )
    client_log(
        context,
        method_label=method_label,
        message=(
            f"train:start model_rate={model_rate} "
            f"lr={float(msg.content['config']['lr'])} optimizer={get_optimizer_name(context.run_config)}"
        ),
    )

    phase_start = time.perf_counter()
    model = task.build_model_for_rate(
        model_rate,
        global_model_rate=float(msg.content["config"].get("global-model-rate", 1.0)),
    )
    task.load_model_state(model, msg.content["arrays"].to_torch_state_dict())
    client_log(
        context,
        method_label=method_label,
        message=f"train:model_loaded elapsed_s={time.perf_counter() - phase_start:.2f}",
    )

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    batch_size = resolve_batch_size(context, local_device_type)
    bundle = task.load_data(
        request,
        batch_size,
        max_train_examples=max_examples_for_device(context, split="train", device_type=local_device_type),
        max_test_examples=max_examples_for_device(context, split="test", device_type=local_device_type),
    )
    client_log(
        context,
        method_label=method_label,
        message=(
            "train:data_ready "
            f"examples={bundle.num_train_examples} batches={len(bundle.trainloader)} "
            f"labels={bundle.label_set or 'all'}"
        ),
    )

    phase_start = time.perf_counter()
    loss = task.train(
        model,
        bundle.trainloader,
        get_int(context.run_config, "local-epochs"),
        float(msg.content["config"]["lr"]),
        device,
        optimizer=get_optimizer_name(context.run_config),
        label_mask=bundle.label_mask,
        masked_cross_entropy=get_masked_cross_entropy_mode(context.run_config),
        partitioning=partitioning,
        log_prefix=client_prefix(context, method_label=method_label),
    )
    client_log(
        context,
        method_label=method_label,
        message=f"train:fit_done loss={loss:.6f} elapsed_s={time.perf_counter() - phase_start:.2f}",
    )
    train_duration_s = time.perf_counter() - total_start
    examples_per_second = (
        float(bundle.num_train_examples) / train_duration_s if train_duration_s > 0 and bundle.num_train_examples > 0 else 0.0
    )

    reply = RecordDict(
        {
            "arrays": ArrayRecord(model.state_dict()),
            "metrics": MetricRecord(
                {
                    "train-loss": float(loss),
                    "num-examples": bundle.num_train_examples,
                    "train-num-examples": bundle.num_train_examples,
                    "train-duration-s": float(train_duration_s),
                    "examples-per-second": float(examples_per_second),
                    "model-rate": float(model_rate),
                }
            ),
        }
    )
    client_log(
        context,
        method_label=method_label,
        message=f"train:reply_ready total_elapsed_s={train_duration_s:.2f}",
    )
    return Message(content=reply, reply_to=msg)


def client_evaluate(
    msg: Message,
    context: Context,
    *,
    method_label: str,
    resolve_model_rate: ResolveModelRateFn,
) -> Message:
    total_start = time.perf_counter()
    task = resolve_task(get_str(context.run_config, "task"))
    local_device_type = resolve_device_type_for_context(context)
    partition_id = int(context.node_config["partition-id"])
    partitioning = get_str(context.run_config, "partitioning")
    base_seed = get_optional_int(context.run_config, "seed")
    if base_seed is not None:
        set_global_seed(derive_seed(base_seed, method_label, "client-eval", task.name, partition_id))
    request = build_partition_request(
        context=context,
        msg=msg,
        task_name=task.name,
        method_label=method_label,
        split="eval",
        local_device_type=local_device_type,
    )
    eval_rate = resolve_model_rate(msg, context)
    client_log(context, method_label=method_label, message=f"eval:start model_rate={eval_rate}")

    phase_start = time.perf_counter()
    model = task.build_model_for_rate(
        eval_rate,
        global_model_rate=float(msg.content["config"].get("global-model-rate", 1.0)),
    )
    task.load_model_state(model, msg.content["arrays"].to_torch_state_dict())
    client_log(
        context,
        method_label=method_label,
        message=f"eval:model_loaded elapsed_s={time.perf_counter() - phase_start:.2f}",
    )

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    batch_size = resolve_batch_size(context, local_device_type)
    bundle = task.load_data(
        request,
        batch_size,
        max_train_examples=max_examples_for_device(context, split="train", device_type=local_device_type),
        max_test_examples=max_examples_for_device(context, split="test", device_type=local_device_type),
    )
    client_log(
        context,
        method_label=method_label,
        message=(
            "eval:data_ready "
            f"examples={bundle.num_test_examples} batches={len(bundle.testloader)}"
        ),
    )

    phase_start = time.perf_counter()
    loss, score = task.test(model, bundle.testloader, device)
    client_log(
        context,
        method_label=method_label,
        message=(
            f"eval:done loss={loss:.6f} {_task_score_label(task)}={score:.6f} "
            f"elapsed_s={time.perf_counter() - phase_start:.2f}"
        ),
    )
    eval_duration_s = time.perf_counter() - total_start

    reply = RecordDict(
        {
            "metrics": _evaluation_metric_record(
                task,
                loss=float(loss),
                score=float(score),
                num_examples=bundle.num_test_examples,
                duration_s=float(eval_duration_s),
            )
        }
    )
    client_log(
        context,
        method_label=method_label,
        message=f"eval:reply_ready total_elapsed_s={eval_duration_s:.2f}",
    )
    return Message(content=reply, reply_to=msg)


def central_evaluate_fn(
    context: Context,
    *,
    grid: Grid | None = None,
    strategy: object | None = None,
    method_label: str,
    experiment_logger=None,
    artifact_logger: ResultArtifactLogger | None = None,
    progress_provider: Callable[[], Mapping[str, int | float | str]] | None = None,
    num_server_rounds: int | None = None,
    emit_server_log: bool = True,
):
    task = resolve_task(get_str(context.run_config, "task"))
    base_seed = get_optional_int(context.run_config, "seed")
    if base_seed is not None:
        set_global_seed(derive_seed(base_seed, method_label, "server-eval", task.name))
    testloader = task.load_centralized_test_dataset(
        seed=(
            derive_seed(base_seed, method_label, "server-eval-loader", task.name)
            if base_seed is not None
            else None
        )
    )

    def evaluate(server_round: int, arrays: ArrayRecord) -> MetricRecord | None:
        eval_started_at = time.perf_counter()
        global_model_rate = get_float(context.run_config, "global-model-rate")
        model = task.build_model_for_rate(
            global_model_rate,
            global_model_rate=global_model_rate,
        )
        task.load_model_state(model, arrays.to_torch_state_dict())
        loss, score = task.test(model, testloader, device="cpu")
        eval_duration_s = time.perf_counter() - eval_started_at
        metrics = _evaluation_metric_record(
            task,
            loss=float(loss),
            score=float(score),
            server_round=server_round,
        )
        progress_payload: Mapping[str, int | float | str] = {}
        if progress_provider is not None:
            progress_payload = dict(progress_provider())
        if experiment_logger is not None:
            experiment_logger.log_server_eval_metrics(server_round, metrics)
            client_trips_total = int(progress_payload.get("client_trips_total", 0))
            if client_trips_total > 0:
                experiment_logger.log_server_eval_trip_metrics(client_trips_total, metrics)
            experiment_logger.log_system_metrics(
                server_round,
                {"round-server-eval-duration-s": float(eval_duration_s)},
            )
        if artifact_logger is not None:
            payload: dict[str, int | float | str] = {
                "server_step": int(server_round),
                "round_server_eval_duration_s": float(eval_duration_s),
            }
            payload.update(_artifact_eval_payload(task, loss=float(loss), score=float(score)))
            payload.update(progress_payload)
            artifact_logger.log_evaluation_event(payload)
        client_trips_total = int(progress_payload.get("client_trips_total", 0))
        if emit_server_log:
            server_log(
                method_label=method_label,
                message=(
                    f"server_eval step={server_round}"
                    f" eval_{_task_score_label(task)}={float(score):.4f}"
                    f" eval_loss={float(loss):.4f}"
                    f" client_trips={client_trips_total}"
                    f" duration_s={float(eval_duration_s):.2f}"
                ),
            )
        if (
            grid is not None
            and strategy is not None
            and num_server_rounds is not None
            and server_round == num_server_rounds
            and method_label in {"heterofl", "fedrolex", "fiarse"}
        ):
            try:
                run_submodel_evaluations(
                    grid=grid,
                    context=context,
                    strategy=strategy,
                    arrays=arrays,
                    method_label=method_label,
                    experiment_logger=experiment_logger,
                    artifact_logger=artifact_logger,
                    server_step=server_round,
                )
            except Exception as exc:  # pragma: no cover - live defensive guard for auxiliary eval
                log(
                    WARNING,
                    "submodel evaluation failed for %s at round %s; continuing without submodel summary metrics: %s",
                    method_label,
                    server_round,
                    exc,
                )
        return metrics

    return evaluate


def _format_rate_token(rate: float) -> str:
    text = f"{float(rate):.4f}".rstrip("0")
    if text.endswith("."):
        text += "0"
    return text


def _aggregate_eval_replies(replies: list[Message]) -> MetricRecord | None:
    valid = [reply for reply in replies if not reply.has_error() and "metrics" in reply.content]
    if not valid:
        return None
    total_examples = sum(int(reply.content["metrics"].get("num-examples", 0)) for reply in valid)
    if total_examples <= 0:
        return None
    loss = 0.0
    score = 0.0
    for reply in valid:
        metrics = reply.content["metrics"]
        examples = int(metrics.get("num-examples", 0))
        loss += float(metrics.get("eval-loss", 0.0)) * examples
        score += float(metrics.get("eval-score", metrics.get("eval-acc", 0.0))) * examples
    return MetricRecord(
        {
            "eval-loss": loss / total_examples,
            "eval-score": score / total_examples,
            "eval-acc": score / total_examples,
            "num-examples": total_examples,
        }
    )


def run_submodel_evaluations(
    *,
    grid: Grid,
    context: Context,
    strategy: object,
    arrays: ArrayRecord,
    method_label: str,
    experiment_logger,
    artifact_logger: ResultArtifactLogger,
    server_step: int,
) -> None:
    if method_label != "fiarse" and not hasattr(strategy, "build_param_indices"):
        return

    if method_label != "fiarse":
        from fedctl_research.methods.heterofl.slicing import slice_state_dict
    else:
        from fedctl_research.methods.fiarse.masking import apply_hard_mask_in_place, build_threshold_map

    task = resolve_task(get_str(context.run_config, "task"))
    global_model_rate = get_float(context.run_config, "global-model-rate")
    base_seed = get_optional_int(context.run_config, "seed")
    final_state = arrays.to_torch_state_dict()
    testloader = task.load_centralized_test_dataset(
        seed=(
            derive_seed(base_seed, method_label, "submodel-eval", task.name)
            if base_seed is not None
            else None
        )
    )
    node_ids = sorted(int(node_id) for node_id in grid.get_node_ids())
    partition_plan_by_node_id = getattr(strategy, "partition_plan_by_node_id", {})
    device_type_by_node_id = getattr(getattr(strategy, "rate_assigner", None), "device_type_by_node_id", {})
    assigned_rate_by_node: dict[int, float] = {}
    if node_ids:
        rate_assigner = getattr(strategy, "rate_assigner", None)
        if rate_assigner is not None and hasattr(rate_assigner, "assign_for_round"):
            assigned_rate_by_node = {
                int(node_id): float(rate)
                for node_id, rate in rate_assigner.assign_for_round(list(node_ids), server_step).items()
            }
    local_eval_enabled = get_submodel_local_eval_enabled(context.run_config)
    summary_metrics: dict[str, float] = {}
    strategy_eval_rates = getattr(strategy, "submodel_eval_rates", None)
    eval_rates = (
        tuple(float(rate) for rate in strategy_eval_rates())
        if callable(strategy_eval_rates)
        else get_submodel_eval_rates(context.run_config)
    )

    for model_rate in eval_rates:
        if model_rate > global_model_rate:
            continue
        if method_label == "fiarse":
            local_state = OrderedDict((key, value.detach().clone()) for key, value in final_state.items())
            global_model = task.build_model_for_rate(global_model_rate, global_model_rate=global_model_rate)
            task.load_model_state(global_model, local_state)
            threshold_map = build_threshold_map(
                global_model,
                model_rate=model_rate,
                threshold_mode=str(lookup_or_default(context.run_config, "fiarse-threshold-mode", "global")),
            )
            apply_hard_mask_in_place(global_model, threshold_map=threshold_map)
        else:
            param_idx = strategy.build_param_indices(final_state, model_rate=model_rate, server_round=server_step)
            local_state = slice_state_dict(final_state, param_idx)
            global_model = task.build_model_for_rate(model_rate, global_model_rate=global_model_rate)
            task.load_model_state(global_model, local_state)
        global_loss, global_score = task.test(global_model, testloader, device="cpu")

        local_metric = None
        local_replies: list[Message] = []
        if local_eval_enabled and node_ids:
            messages = [
                Message(
                    content=RecordDict(
                        {
                            "arrays": ArrayRecord(OrderedDict((key, value.detach().clone()) for key, value in local_state.items())),
                            "config": ConfigRecord(
                                {
                                    "model-rate": float(model_rate),
                                    "global-model-rate": float(global_model_rate),
                                    **dict(partition_plan_by_node_id.get(node_id, {})),
                                }
                            ),
                        }
                    ),
                    message_type=MessageType.EVALUATE,
                    dst_node_id=node_id,
                    group_id=f"submodel-eval-{server_step}-{_format_rate_token(model_rate)}",
                )
                for node_id in node_ids
            ]
            local_replies = list(grid.send_and_receive(messages, timeout=3600.0))
            local_metric = _aggregate_eval_replies(local_replies)

        rate_token = _format_rate_token(model_rate)
        summary_metrics[f"submodel/global/rate_{rate_token}/eval-score"] = float(global_score)
        summary_metrics[f"submodel/global/rate_{rate_token}/eval-acc"] = float(global_score)
        summary_metrics[f"submodel/global/rate_{rate_token}/eval-loss"] = float(global_loss)
        score_name = _task_score_name(task)
        if score_name != "acc":
            summary_metrics[f"submodel/global/rate_{rate_token}/eval-{score_name}"] = float(global_score)
        artifact_logger.log_submodel_evaluation_event(
            {
                "scope": "global",
                "server_step": int(server_step),
                "model_rate": float(model_rate),
                **_artifact_eval_payload(task, loss=float(global_loss), score=float(global_score)),
            }
        )
        if local_metric is not None:
            local_score = float(local_metric.get("eval-score", local_metric["eval-acc"]))
            summary_metrics[f"submodel/local/rate_{rate_token}/eval-score"] = local_score
            summary_metrics[f"submodel/local/rate_{rate_token}/eval-acc"] = local_score
            summary_metrics[f"submodel/local/rate_{rate_token}/eval-loss"] = float(local_metric["eval-loss"])
            if score_name != "acc":
                summary_metrics[f"submodel/local/rate_{rate_token}/eval-{score_name}"] = local_score
            artifact_logger.log_submodel_evaluation_event(
                {
                    "scope": "local",
                    "server_step": int(server_step),
                    "model_rate": float(model_rate),
                    **_artifact_eval_payload(
                        task,
                        loss=float(local_metric["eval-loss"]),
                        score=local_score,
                    ),
                    "num_examples": int(local_metric["num-examples"]),
                }
            )
            wandb_rows: list[dict[str, object]] = []
            for reply in local_replies:
                if reply.has_error() or "metrics" not in reply.content:
                    continue
                metrics = reply.content["metrics"]
                node_id = int(reply.metadata.src_node_id)
                payload = {
                    "scope": "local_client",
                    "server_step": int(server_step),
                    "node_id": node_id,
                    "device_type": str(device_type_by_node_id.get(node_id, "unknown")),
                    "model_rate": float(model_rate),
                    "client_model_rate": float(assigned_rate_by_node.get(node_id, model_rate)),
                    **_artifact_eval_payload(
                        task,
                        loss=float(metrics["eval-loss"]),
                        score=float(metrics.get("eval-score", metrics["eval-acc"])),
                    ),
                    "num_examples": int(metrics["num-examples"]),
                }
                payload.update(
                    {
                        str(key).replace("-", "_"): value
                        for key, value in partition_plan_by_node_id.get(node_id, {}).items()
                    }
                )
                artifact_logger.log_submodel_evaluation_event(payload)
                wandb_rows.append(payload)
            if wandb_rows:
                experiment_logger.log_submodel_client_events(server_step, wandb_rows)

    experiment_logger.log_summary_metrics(summary_metrics)


def discover_node_capabilities(grid: Grid, context: Context) -> tuple[dict[int, str], dict[int, int]]:
    min_available_nodes = get_int(context.run_config, "min-available-nodes")
    timeout_s = float(lookup_or_default(context.run_config, "capability-discovery-timeout-s", 120.0))
    started = time.monotonic()

    all_node_ids: list[int] = []
    while len(all_node_ids) < min_available_nodes:
        all_node_ids = list(grid.get_node_ids())
        if len(all_node_ids) >= min_available_nodes:
            break
        if time.monotonic() - started >= timeout_s:
            raise RuntimeError("Timed out waiting for enough nodes to perform capability discovery.")
        time.sleep(1.0)

    discovered: dict[int, str] = {}
    partition_ids: dict[int, int] = {}
    messages = [
        Message(
            content=RecordDict({"capability-request": ConfigRecord({"request": "device-type"})}),
            message_type=MessageType.QUERY,
            dst_node_id=node_id,
            group_id="capability-discovery",
        )
        for node_id in all_node_ids
    ]
    replies = list(grid.send_and_receive(messages, timeout=timeout_s))
    log(INFO, "capability discovery: sent=%s replies=%s", len(messages), len(replies))

    for reply in replies:
        if reply.has_error():
            log(
                INFO,
                "capability discovery: node=%s error=%s",
                _capability_node_label(reply.metadata.src_node_id),
                reply.error,
            )
            continue
        capabilities = reply.content.get("capabilities")
        if not isinstance(capabilities, ConfigRecord):
            log(
                INFO,
                "capability discovery: node=%s missing capabilities record",
                _capability_node_label(reply.metadata.src_node_id),
            )
            continue
        src_node_id = reply.metadata.src_node_id
        device_type = capabilities.get("device-type")
        partition_id = capabilities.get("partition-id")
        log(
            INFO,
            "capability discovery: node=%s device_type=%s capabilities=%s",
            _capability_node_label(src_node_id),
            _capability_device_label(device_type),
            dict(capabilities),
        )
        if isinstance(device_type, str) and device_type:
            discovered[src_node_id] = device_type
        if partition_id is not None and str(partition_id).strip():
            partition_ids[src_node_id] = int(str(partition_id))

    discovered.update(
        parse_node_device_type_map(lookup_or_default(context.run_config, "heterofl-node-device-types", ""))
    )
    log(INFO, "capability discovery: final node->device map=%s", discovered)
    log(INFO, "capability discovery: final node->partition map=%s", partition_ids)
    return discovered, partition_ids


def discover_node_device_types(grid: Grid, context: Context) -> dict[int, str]:
    """Backward-compatible wrapper for older method code paths.

    Some async method modules still import the pre-refactor helper name and only
    need the node->device-type mapping.
    """

    device_types, _ = discover_node_capabilities(grid, context)
    return device_types


def create_server_strategy(
    *,
    grid: Grid,
    context: Context,
    method_label: str,
    strategy_factory: Callable[..., object],
    needs_capabilities: bool,
    **strategy_kwargs,
):
    strategy = strategy_factory(
        fraction_train=get_float(context.run_config, "fraction-train"),
        fraction_evaluate=get_float(context.run_config, "fraction-evaluate"),
        min_available_nodes=get_int(context.run_config, "min-available-nodes"),
        min_train_nodes=get_int(context.run_config, "min-train-nodes"),
        min_evaluate_nodes=get_int(context.run_config, "min-evaluate-nodes"),
        weighted_by_key="num-examples",
        **strategy_kwargs,
    )
    if needs_capabilities:
        node_device_map, node_partition_map = discover_node_capabilities(grid, context)
        if hasattr(strategy, "set_node_capabilities"):
            strategy.set_node_capabilities(node_device_map)
        if hasattr(strategy, "set_node_partition_ids"):
            strategy.set_node_partition_ids(node_partition_map)
        if hasattr(strategy, "set_node_partition_plan"):
            strategy.set_node_partition_plan(
                build_typed_partition_plan(
                    node_ids=[int(node_id) for node_id in grid.get_node_ids()],
                    device_type_by_node_id=node_device_map,
                )
            )
    return strategy


def run_final_client_evaluation(
    *,
    grid: Grid,
    strategy: object,
    arrays: ArrayRecord,
    evaluate_config: ConfigRecord,
    server_step: int,
) -> MetricRecord | None:
    if not hasattr(strategy, "configure_evaluate") or not hasattr(strategy, "aggregate_evaluate"):
        return None
    prior = getattr(strategy, "client_eval_enabled", None)
    if prior is not None:
        setattr(strategy, "client_eval_enabled", True)
    try:
        messages = list(strategy.configure_evaluate(server_step, arrays, evaluate_config, grid))
    finally:
        if prior is not None:
            setattr(strategy, "client_eval_enabled", prior)
    if not messages:
        return None
    replies = list(grid.send_and_receive(messages, timeout=3600.0))
    return strategy.aggregate_evaluate(server_step, replies)


def _run_sync_strategy_rounds(
    *,
    grid: Grid,
    method_label: str,
    strategy: object,
    initial_arrays: ArrayRecord,
    num_server_rounds: int,
    train_config: ConfigRecord,
    evaluate_config: ConfigRecord,
    evaluate_fn: Callable[[int, ArrayRecord], MetricRecord | None] | None,
    target_controller: TargetStopController,
    task: object,
    progress_state: Mapping[str, object],
    timeout: float = 3600.0,
) -> tuple[Result, int]:
    result = Result(arrays=initial_arrays)
    arrays = initial_arrays
    last_server_round = 0

    if evaluate_fn is not None:
        initial_eval = evaluate_fn(0, initial_arrays)
        if initial_eval is not None:
            result.evaluate_metrics_serverapp[0] = initial_eval
            log(INFO, "Initial global evaluation results: %s", _metric_record_plain_dict(initial_eval))
            if target_controller.observe(
                task=task,
                server_step=0,
                metrics=initial_eval,
                progress_state=progress_state,
            ):
                return result, 0

    for current_round in range(1, num_server_rounds + 1):
        log(INFO, "")
        log(INFO, "[ROUND %s/%s]", current_round, num_server_rounds)
        train_replies = grid.send_and_receive(
            messages=list(strategy.configure_train(current_round, arrays, train_config, grid)),
            timeout=timeout,
        )
        train_successes = sum(1 for reply in train_replies if not reply.has_error())
        train_failures = sum(1 for reply in train_replies if reply.has_error())
        agg_arrays, agg_train_metrics = strategy.aggregate_train(current_round, train_replies)
        if agg_arrays is not None:
            arrays = agg_arrays
            result.arrays = agg_arrays
        if agg_train_metrics is not None:
            result.train_metrics_clientapp[current_round] = agg_train_metrics
            _log_sync_metric_record(label="Aggregated MetricRecord", metrics=agg_train_metrics)
        else:
            server_log(
                method_label=method_label,
                message=(
                    f"round_train_done round={current_round}"
                    f" success={train_successes}"
                    f" fail={train_failures}"
                    f" client_trips={int(progress_state.get('client_trips_total', 0))}"
                ),
            )

        evaluate_replies = grid.send_and_receive(
            messages=list(strategy.configure_evaluate(current_round, arrays, evaluate_config, grid)),
            timeout=timeout,
        )
        eval_successes = sum(1 for reply in evaluate_replies if not reply.has_error())
        eval_failures = sum(1 for reply in evaluate_replies if reply.has_error())
        agg_evaluate_metrics = strategy.aggregate_evaluate(current_round, evaluate_replies)
        if agg_evaluate_metrics is not None:
            result.evaluate_metrics_clientapp[current_round] = agg_evaluate_metrics
            _log_sync_metric_record(label="Aggregated MetricRecord", metrics=agg_evaluate_metrics)

        if evaluate_fn is not None:
            server_eval_metrics = evaluate_fn(current_round, arrays)
            if server_eval_metrics is not None:
                result.evaluate_metrics_serverapp[current_round] = server_eval_metrics
                log(INFO, "Global evaluation")
                _log_sync_metric_record(label="MetricRecord", metrics=server_eval_metrics)
        last_server_round = current_round
        if evaluate_fn is not None and current_round in result.evaluate_metrics_serverapp:
            if target_controller.observe(
                task=task,
                server_step=current_round,
                metrics=result.evaluate_metrics_serverapp[current_round],
                progress_state=progress_state,
            ):
                server_log(
                    method_label=method_label,
                    message=(
                        f"target_reached step={current_round}"
                        f" client_trips={target_controller.client_trips_to_target}"
                        f" threshold={target_controller.threshold:.4f}"
                    ),
                )
                break

    if len(result.arrays) == 0:
        result.arrays = arrays
    return result, last_server_round


def run_server_loop(
    grid: Grid,
    context: Context,
    *,
    method_label: str,
    strategy_factory: Callable[..., object],
    needs_capabilities: bool,
    **strategy_kwargs,
) -> None:
    total_start = time.perf_counter()
    task = resolve_task(get_str(context.run_config, "task"))
    experiment_logger = create_experiment_logger(context)
    artifact_logger = create_result_artifact_logger(context)
    base_seed = get_optional_int(context.run_config, "seed")
    if base_seed is not None:
        set_global_seed(derive_seed(base_seed, method_label, "server-init", task.name))
    global_model_rate = get_float(context.run_config, "global-model-rate")
    strategy_kwargs.setdefault("global_model_rate", global_model_rate)
    configured_rates: list[float] = [global_model_rate]
    for key in ("default-model-rate", "rpi4-model-rate", "rpi5-model-rate"):
        value = get_optional_float(context.run_config, key)
        if value is not None:
            configured_rates.append(value)
    configured_rates.extend(get_model_rate_levels(context.run_config))
    experiment_logger.log_model_catalog(
        build_model_catalog(
            task.name,
            global_model_rate=global_model_rate,
            model_rates=configured_rates,
        )
    )
    initial_model = task.build_model_for_rate(
        global_model_rate,
        global_model_rate=global_model_rate,
    )
    initial_arrays = ArrayRecord(initial_model.state_dict())
    train_config = ConfigRecord(
        {
            "lr": get_float(context.run_config, "learning-rate"),
            "optimizer": get_optimizer_name(context.run_config),
            "global-model-rate": global_model_rate,
        }
    )
    evaluate_config = ConfigRecord({"global-model-rate": global_model_rate})
    client_eval_enabled = get_client_eval_enabled(context.run_config)
    final_client_eval_enabled = get_final_client_eval_enabled(context.run_config)
    progress_state = {
        "wall_clock_s_since_start": 0.0,
        "client_trips_total": 0,
    }

    strategy = create_server_strategy(
        grid=grid,
        context=context,
        method_label=method_label,
        strategy_factory=strategy_factory,
        needs_capabilities=needs_capabilities,
        task_name=task.name,
        experiment_logger=experiment_logger,
        artifact_logger=artifact_logger,
        client_eval_enabled=client_eval_enabled,
        progress_tracker=progress_state,
        **strategy_kwargs,
    )

    num_server_rounds = get_int(context.run_config, "num-server-rounds")
    _log_sync_strategy_header(
        strategy=strategy,
        num_server_rounds=num_server_rounds,
        initial_arrays=initial_arrays,
        train_config=train_config,
        evaluate_config=evaluate_config if client_eval_enabled else ConfigRecord({}),
        min_train_nodes=get_int(context.run_config, "min-train-nodes"),
        min_evaluate_nodes=get_int(context.run_config, "min-evaluate-nodes"),
        min_available_nodes=get_int(context.run_config, "min-available-nodes"),
        fraction_train=get_float(context.run_config, "fraction-train"),
        fraction_evaluate=get_float(context.run_config, "fraction-evaluate"),
    )
    target_controller = TargetStopController.from_task(
        task,
        context.run_config,
        client_trip_budget=_sync_client_trip_budget(context.run_config),
    )
    evaluate_fn = central_evaluate_fn(
        context,
        grid=grid,
        strategy=strategy,
        method_label=method_label,
        experiment_logger=experiment_logger,
        artifact_logger=artifact_logger,
        progress_provider=lambda: dict(progress_state),
        num_server_rounds=num_server_rounds,
        emit_server_log=False,
    )
    result, final_server_step = _run_sync_strategy_rounds(
        grid=grid,
        method_label=method_label,
        strategy=strategy,
        initial_arrays=initial_arrays,
        num_server_rounds=num_server_rounds,
        train_config=train_config,
        evaluate_config=evaluate_config if client_eval_enabled else ConfigRecord({}),
        evaluate_fn=evaluate_fn,
        target_controller=target_controller,
        task=task,
        progress_state=progress_state,
    )
    train_history = getattr(result, "train_metrics_clientapp", {})
    if isinstance(train_history, Mapping):
        derived_client_trips_total = 0
        for metrics in train_history.values():
            if isinstance(metrics, Mapping):
                derived_client_trips_total += int(metrics.get("round-successful-train-replies", 0))
        if int(progress_state.get("client_trips_total", 0)) <= 0:
            progress_state["client_trips_total"] = derived_client_trips_total
        progress_state["wall_clock_s_since_start"] = time.perf_counter() - total_start
    if not client_eval_enabled and final_client_eval_enabled:
        final_metrics = run_final_client_evaluation(
            grid=grid,
            strategy=strategy,
            arrays=result.arrays,
            evaluate_config=evaluate_config,
            server_step=final_server_step,
        )
        if final_metrics is not None:
            evaluate_history = getattr(result, "evaluate_metrics_clientapp", None)
            if isinstance(evaluate_history, Mapping):
                evaluate_history[final_server_step] = final_metrics
            experiment_logger.log_client_eval_metrics(
                final_server_step,
                final_metrics,
            )
    target_summary_metrics = target_controller.summary_metrics()
    if target_summary_metrics:
        experiment_logger.log_summary_metrics(target_summary_metrics)
    experiment_logger.log_run_summary(
        total_runtime_s=time.perf_counter() - total_start,
        result=result,
    )
    experiment_logger.finish()


def resolve_batch_size(context: Context, device_type: str) -> int:
    specific = get_optional_int(context.run_config, f"{device_type}-batch-size")
    if specific is not None and specific > 0:
        return specific
    return get_int(context.run_config, "batch-size")


def max_examples_for_device(
    context: Context,
    *,
    split: str,
    device_type: str,
) -> int | None:
    specific = lookup_or_default(context.run_config, f"{device_type}-max-{split}-examples", None)
    if specific is not None:
        parsed = int(specific)
        return parsed if parsed > 0 else None
    default = lookup_or_default(context.run_config, f"default-max-{split}-examples", None)
    if default is None:
        return None
    parsed = int(default)
    return parsed if parsed > 0 else None
