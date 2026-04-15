"""Shared method runtime helpers for client/server Flower app handlers."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
import os
import time
from logging import INFO, WARNING
from typing import Callable

import torch
from flwr.app import ArrayRecord, ConfigRecord, Context, Message, MessageType, MetricRecord, RecordDict
from flwr.common.logger import log
from flwr.serverapp import Grid

from fedctl_research.config import (
    get_client_eval_enabled,
    get_final_client_eval_enabled,
    get_float,
    get_int,
    get_masked_cross_entropy_mode,
    get_model_rate_levels,
    get_optional_bool,
    get_optional_float,
    get_optional_int,
    get_partitioning_dirichlet_alpha,
    get_partitioning_num_labels,
    get_str,
    get_submodel_eval_rates,
    get_submodel_local_eval_enabled,
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

    return PartitionRequest(
        partition_id=partition_id,
        num_partitions=int(context.node_config["num-partitions"]),
        partitioning=partitioning,
        device_type=partition_device_type,
        partitioning_num_labels=get_partitioning_num_labels(context.run_config),
        partitioning_dirichlet_alpha=get_partitioning_dirichlet_alpha(context.run_config),
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
        message=f"train:start model_rate={model_rate} lr={float(msg.content['config']['lr'])}",
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
    loss, accuracy = task.test(model, bundle.testloader, device)
    client_log(
        context,
        method_label=method_label,
        message=(
            f"eval:done loss={loss:.6f} acc={accuracy:.6f} "
            f"elapsed_s={time.perf_counter() - phase_start:.2f}"
        ),
    )
    eval_duration_s = time.perf_counter() - total_start

    reply = RecordDict(
        {
            "metrics": MetricRecord(
                {
                    "eval-loss": float(loss),
                    "eval-acc": float(accuracy),
                    "num-examples": bundle.num_test_examples,
                    "eval-num-examples": bundle.num_test_examples,
                    "eval-duration-s": float(eval_duration_s),
                }
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
        loss, accuracy = task.test(model, testloader, device="cpu")
        eval_duration_s = time.perf_counter() - eval_started_at
        metrics = MetricRecord(
            {
                "eval-loss": float(loss),
                "eval-acc": float(accuracy),
                "server-round": server_round,
            }
        )
        if experiment_logger is not None:
            experiment_logger.log_server_eval_metrics(server_round, metrics)
            experiment_logger.log_system_metrics(
                server_round,
                {"round-server-eval-duration-s": float(eval_duration_s)},
            )
        if artifact_logger is not None:
            payload: dict[str, int | float | str] = {
                "server_step": int(server_round),
                "eval_loss": float(loss),
                "eval_acc": float(accuracy),
                "round_server_eval_duration_s": float(eval_duration_s),
            }
            if progress_provider is not None:
                payload.update(progress_provider())
            artifact_logger.log_evaluation_event(payload)
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
    acc = 0.0
    for reply in valid:
        metrics = reply.content["metrics"]
        examples = int(metrics.get("num-examples", 0))
        loss += float(metrics.get("eval-loss", 0.0)) * examples
        acc += float(metrics.get("eval-acc", 0.0)) * examples
    return MetricRecord(
        {
            "eval-loss": loss / total_examples,
            "eval-acc": acc / total_examples,
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
                threshold_mode=str(context.run_config.get("fiarse-threshold-mode", "global")),
            )
            apply_hard_mask_in_place(global_model, threshold_map=threshold_map)
        else:
            param_idx = strategy.build_param_indices(final_state, model_rate=model_rate, server_round=server_step)
            local_state = slice_state_dict(final_state, param_idx)
            global_model = task.build_model_for_rate(model_rate, global_model_rate=global_model_rate)
            task.load_model_state(global_model, local_state)
        global_loss, global_acc = task.test(global_model, testloader, device="cpu")

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
        summary_metrics[f"submodel/global/rate_{rate_token}/eval-acc"] = float(global_acc)
        summary_metrics[f"submodel/global/rate_{rate_token}/eval-loss"] = float(global_loss)
        artifact_logger.log_submodel_evaluation_event(
            {
                "scope": "global",
                "server_step": int(server_step),
                "model_rate": float(model_rate),
                "eval_acc": float(global_acc),
                "eval_loss": float(global_loss),
            }
        )
        if local_metric is not None:
            summary_metrics[f"submodel/local/rate_{rate_token}/eval-acc"] = float(local_metric["eval-acc"])
            summary_metrics[f"submodel/local/rate_{rate_token}/eval-loss"] = float(local_metric["eval-loss"])
            artifact_logger.log_submodel_evaluation_event(
                {
                    "scope": "local",
                    "server_step": int(server_step),
                    "model_rate": float(model_rate),
                    "eval_acc": float(local_metric["eval-acc"]),
                    "eval_loss": float(local_metric["eval-loss"]),
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
                    "eval_acc": float(metrics["eval-acc"]),
                    "eval_loss": float(metrics["eval-loss"]),
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
    timeout_s = float(context.run_config.get("capability-discovery-timeout-s", 120.0))
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

    discovered.update(parse_node_device_type_map(context.run_config.get("heterofl-node-device-types", "")))
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
    train_config = ConfigRecord({"lr": get_float(context.run_config, "learning-rate"), "global-model-rate": global_model_rate})
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

    result = strategy.start(
        grid=grid,
        initial_arrays=initial_arrays,
        num_rounds=num_server_rounds,
        train_config=train_config,
        evaluate_config=evaluate_config if client_eval_enabled else ConfigRecord({}),
        evaluate_fn=central_evaluate_fn(
            context,
            grid=grid,
            strategy=strategy,
            method_label=method_label,
            experiment_logger=experiment_logger,
            artifact_logger=artifact_logger,
            progress_provider=lambda: dict(progress_state),
            num_server_rounds=num_server_rounds,
        ),
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
            server_step=num_server_rounds,
        )
        if final_metrics is not None:
            evaluate_history = getattr(result, "evaluate_metrics_clientapp", None)
            if isinstance(evaluate_history, Mapping):
                evaluate_history[num_server_rounds] = final_metrics
            experiment_logger.log_client_eval_metrics(
                num_server_rounds,
                final_metrics,
            )
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
    specific = context.run_config.get(f"{device_type}-max-{split}-examples")
    if specific is not None:
        parsed = int(specific)
        return parsed if parsed > 0 else None
    default = context.run_config.get(f"default-max-{split}-examples")
    if default is None:
        return None
    parsed = int(default)
    return parsed if parsed > 0 else None
