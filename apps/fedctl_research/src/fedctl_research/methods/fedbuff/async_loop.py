"""Async FedBuff server loop."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import math
import time
from logging import INFO
from typing import Any

import torch
from flwr.app import ArrayRecord, ConfigRecord, Message, MessageType, MetricRecord, RecordDict
from flwr.common.logger import log
from flwr.serverapp import Grid

from fedctl_research.config import (
    get_client_eval_enabled,
    get_final_client_eval_enabled,
    get_fedbuff_buffer_size,
    get_fedbuff_evaluate_every_steps,
    get_fedbuff_num_server_steps,
    get_fedbuff_poll_interval_s,
    get_fedbuff_staleness_alpha,
    get_fedbuff_staleness_weighting,
    get_fedbuff_train_concurrency,
    get_float,
    get_int,
    get_optional_int,
    get_str,
)
from fedctl_research.costs import build_model_catalog, summarize_round_costs
from fedctl_research.methods.runtime import (
    TargetStopController,
    _async_client_trip_budget,
    build_typed_partition_plan,
    central_evaluate_fn,
    create_result_artifact_logger,
    discover_node_device_types,
    server_log,
)
from fedctl_research.seeding import derive_seed, set_global_seed
from fedctl_research.tasks.registry import resolve_task
from fedctl_research.wandb_logging import create_experiment_logger


@dataclass
class _InflightRequest:
    message_id: str
    node_id: int
    device_type: str
    server_model_version_sent: int
    wall_clock_dispatch_s: float


@dataclass
class _BufferedUpdate:
    trip_index: int
    node_id: int
    device_type: str
    staleness: int
    weight: float
    train_duration_s: float
    num_examples: int
    examples_per_second: float
    train_loss: float
    queue_latency_s: float
    delta: OrderedDict[str, torch.Tensor]


@dataclass
class _FedBuffResult:
    arrays: ArrayRecord
    train_metrics_clientapp: dict[int, MetricRecord] = field(default_factory=dict)
    evaluate_metrics_clientapp: dict[int, MetricRecord] = field(default_factory=dict)
    evaluate_metrics_serverapp: dict[int, MetricRecord] = field(default_factory=dict)


def _clone_state(state: OrderedDict[str, torch.Tensor]) -> OrderedDict[str, torch.Tensor]:
    return OrderedDict((key, value.detach().clone()) for key, value in state.items())


def _apply_aggregated_delta(
    current_state: OrderedDict[str, torch.Tensor],
    aggregate_delta: OrderedDict[str, torch.Tensor],
) -> OrderedDict[str, torch.Tensor]:
    return OrderedDict(
        (
            key,
            current_state[key].detach().clone() - aggregate_delta[key],
        )
        for key in current_state
    )


def _staleness_weight(mode: str, alpha: float, staleness: int, *, buffer_size: int = 1) -> float:
    if mode == "none":
        return 1.0
    if mode == "fair":
        return float(staleness) * float(buffer_size) + 1.0
    if mode == "polynomial":
        return 1.0 / math.pow(1.0 + float(staleness), float(alpha))
    raise ValueError(f"Unsupported FedBuff staleness-weighting: {mode}")


def _jain_index(values: list[float]) -> float:
    positive = [float(value) for value in values if value >= 0.0]
    if not positive:
        return 0.0
    denominator = len(positive) * sum(value * value for value in positive)
    if denominator <= 0.0:
        return 0.0
    numerator = sum(positive) ** 2
    return numerator / denominator


def _aggregate_eval_metrics(replies: list[Message]) -> MetricRecord | None:
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


def _dispatch_train_message(
    *,
    grid: Grid,
    node_id: int,
    current_state: OrderedDict[str, torch.Tensor],
    lr: float,
    global_model_rate: float,
    server_step: int,
    partition_plan_entry: dict[str, int | str] | None = None,
) -> str:
    config = {
        "lr": float(lr),
        "model-rate": float(global_model_rate),
        "global-model-rate": float(global_model_rate),
    }
    if partition_plan_entry is not None:
        config.update(partition_plan_entry)
    message = Message(
        content=RecordDict(
            {
                "arrays": ArrayRecord(_clone_state(current_state)),
                "config": ConfigRecord(config),
            }
        ),
        message_type=MessageType.TRAIN,
        dst_node_id=node_id,
        group_id=str(server_step),
    )
    return next(iter(grid.push_messages([message])))


def _dispatch_eval_messages(
    *,
    grid: Grid,
    node_ids: list[int],
    current_state: OrderedDict[str, torch.Tensor],
    global_model_rate: float,
    server_step: int,
    method_label: str,
    partition_plan_by_node_id: dict[int, dict[str, int | str]] | None = None,
) -> list[Message]:
    messages = [
        Message(
            content=RecordDict(
                {
                    "arrays": ArrayRecord(_clone_state(current_state)),
                    "config": ConfigRecord(
                        {
                            "model-rate": float(global_model_rate),
                            "global-model-rate": float(global_model_rate),
                            **dict((partition_plan_by_node_id or {}).get(node_id, {})),
                        }
                    ),
                }
            ),
            message_type=MessageType.EVALUATE,
            dst_node_id=node_id,
            group_id=f"{method_label}-final-eval-{server_step}",
        )
        for node_id in node_ids
    ]
    if not messages:
        return []
    message_ids = list(grid.push_messages(messages))
    return list(grid.pull_messages(message_ids))


def _async_method_title(method_label: str) -> str:
    if method_label == "fedstaleweight":
        return "FedStaleWeight"
    if method_label == "fedbuff":
        return "FedBuff"
    return method_label


def _log_async_loop_header(
    *,
    method_label: str,
    num_server_steps: int,
    concurrency: int,
    buffer_size: int,
    evaluate_every_steps: int,
    staleness_mode: str,
    staleness_alpha: float,
    client_trip_budget: int | None,
) -> None:
    log(INFO, "Starting %s async loop:", _async_method_title(method_label))
    log(INFO, " ├── Number of server steps: %s", num_server_steps)
    log(INFO, " ├── Train concurrency: %s", concurrency)
    log(INFO, " ├── Buffer size: %s", buffer_size)
    log(INFO, " ├── Evaluate every: %s step(s)", evaluate_every_steps)
    log(INFO, " ├── Staleness weighting: %s", staleness_mode)
    log(INFO, " ├── Staleness alpha: %s", staleness_alpha)
    if client_trip_budget is not None:
        log(INFO, " └── Client-trip budget: %s", client_trip_budget)
    else:
        log(INFO, " └── Client-trip budget: <unbounded>")


def run_fedbuff_server(
    grid: Grid,
    context,
    *,
    method_label: str = "fedbuff",
    staleness_mode_override: str | None = None,
) -> None:
    total_start = time.perf_counter()
    task = resolve_task(get_str(context.run_config, "task"))
    experiment_logger = create_experiment_logger(context)
    artifact_logger = create_result_artifact_logger(context)
    base_seed = get_optional_int(context.run_config, "seed")
    if base_seed is not None:
        set_global_seed(derive_seed(base_seed, method_label, "server-init", task.name))

    global_model_rate = get_float(context.run_config, "global-model-rate")
    configured_rates = [global_model_rate]
    experiment_logger.log_model_catalog(
        build_model_catalog(
            task.name,
            global_model_rate=global_model_rate,
            model_rates=configured_rates,
        )
    )
    initial_model = task.build_model_for_rate(global_model_rate, global_model_rate=global_model_rate)
    current_state = _clone_state(initial_model.state_dict())
    current_arrays = ArrayRecord(current_state)

    node_device_map = discover_node_device_types(grid, context)
    node_ids = sorted(node_device_map) if node_device_map else sorted(int(node_id) for node_id in grid.get_node_ids())
    if not node_ids:
        raise RuntimeError("FedBuff requires at least one available node")
    partition_plan_by_node_id = build_typed_partition_plan(
        node_ids=node_ids,
        device_type_by_node_id=node_device_map,
    )

    concurrency = get_fedbuff_train_concurrency(context.run_config) or get_int(context.run_config, "min-available-nodes")
    concurrency = max(1, min(concurrency, len(node_ids)))
    buffer_size = get_fedbuff_buffer_size(context.run_config)
    num_server_steps = get_fedbuff_num_server_steps(context.run_config)
    evaluate_every_steps = max(1, get_fedbuff_evaluate_every_steps(context.run_config))
    poll_interval_s = get_fedbuff_poll_interval_s(context.run_config)
    staleness_mode = staleness_mode_override or get_fedbuff_staleness_weighting(context.run_config)
    staleness_alpha = get_fedbuff_staleness_alpha(context.run_config)
    client_eval_enabled = get_client_eval_enabled(context.run_config)
    final_client_eval_enabled = get_final_client_eval_enabled(context.run_config)
    lr = get_float(context.run_config, "learning-rate")
    tracked_devices = ("rpi4", "rpi5")
    cumulative_update_counts = {device: 0 for device in tracked_devices}
    cumulative_weight_totals = {device: 0.0 for device in tracked_devices}
    cumulative_staleness_sums = {device: 0.0 for device in tracked_devices}

    inflight: dict[str, _InflightRequest] = {}
    busy_nodes: set[int] = set()
    node_cursor = 0
    model_history: dict[int, OrderedDict[str, torch.Tensor]] = {0: _clone_state(current_state)}
    buffered_updates: list[_BufferedUpdate] = []
    buffer_started_at: float | None = None
    server_step = 0
    client_trips_total = 0
    progress_state = {"wall_clock_s_since_start": 0.0, "client_trips_total": 0}
    result = _FedBuffResult(arrays=current_arrays)
    target_controller = TargetStopController.from_task(
        task,
        context.run_config,
        client_trip_budget=_async_client_trip_budget(context.run_config),
    )
    _log_async_loop_header(
        method_label=method_label,
        num_server_steps=num_server_steps,
        concurrency=concurrency,
        buffer_size=buffer_size,
        evaluate_every_steps=evaluate_every_steps,
        staleness_mode=staleness_mode,
        staleness_alpha=staleness_alpha,
        client_trip_budget=target_controller.client_trip_budget,
    )
    evaluate = central_evaluate_fn(
        context,
        method_label=method_label,
        experiment_logger=experiment_logger,
        artifact_logger=artifact_logger,
        progress_provider=lambda: dict(progress_state),
    )
    initial_eval = evaluate(0, current_arrays)
    if initial_eval is not None:
        result.evaluate_metrics_serverapp[0] = initial_eval
        if target_controller.observe(
            task=task,
            server_step=0,
            metrics=initial_eval,
            progress_state=progress_state,
        ):
            experiment_logger.log_summary_metrics(target_controller.summary_metrics())
            experiment_logger.log_run_summary(
                total_runtime_s=time.perf_counter() - total_start,
                result=result,
            )
            experiment_logger.finish()
            return

    def dispatch_until_full() -> None:
        nonlocal node_cursor
        while server_step < num_server_steps and len(inflight) < concurrency:
            selected = None
            for _ in range(len(node_ids)):
                node_id = node_ids[node_cursor % len(node_ids)]
                node_cursor += 1
                if node_id not in busy_nodes:
                    selected = node_id
                    break
            if selected is None:
                break
            message_id = _dispatch_train_message(
                grid=grid,
                node_id=selected,
                current_state=current_state,
                lr=lr,
                global_model_rate=global_model_rate,
                server_step=server_step,
                partition_plan_entry=partition_plan_by_node_id.get(selected),
            )
            inflight[message_id] = _InflightRequest(
                message_id=message_id,
                node_id=selected,
                device_type=node_device_map.get(selected, "unknown"),
                server_model_version_sent=server_step,
                wall_clock_dispatch_s=time.perf_counter(),
            )
            busy_nodes.add(selected)

    stop_requested = False
    dispatch_until_full()
    while server_step < num_server_steps and inflight and not stop_requested:
        replies = list(grid.pull_messages(list(inflight.keys())))
        if not replies:
            time.sleep(poll_interval_s)
            continue

        for reply in replies:
            request_id = reply.metadata.reply_to_message_id or reply.metadata.message_id
            request = inflight.pop(request_id, None)
            if request is None:
                continue
            busy_nodes.discard(request.node_id)
            if reply.has_error():
                dispatch_until_full()
                continue
            if "arrays" not in reply.content or "metrics" not in reply.content:
                dispatch_until_full()
                continue

            metrics = reply.content["metrics"]
            local_state = reply.content["arrays"].to_torch_state_dict()
            sent_state = model_history[request.server_model_version_sent]
            staleness = max(0, server_step - request.server_model_version_sent)
            weight = _staleness_weight(staleness_mode, staleness_alpha, staleness, buffer_size=buffer_size)
            queue_latency_s = time.perf_counter() - request.wall_clock_dispatch_s
            delta = OrderedDict(
                (
                    key,
                    sent_state[key].detach().clone() - local_state[key].detach().clone(),
                )
                for key in sent_state
            )
            trip_index = client_trips_total + 1
            update = _BufferedUpdate(
                trip_index=trip_index,
                node_id=request.node_id,
                device_type=request.device_type,
                staleness=staleness,
                weight=weight,
                train_duration_s=float(metrics.get("train-duration-s", 0.0)),
                num_examples=int(metrics.get("train-num-examples", metrics.get("num-examples", 0))),
                examples_per_second=float(metrics.get("examples-per-second", 0.0)),
                train_loss=float(metrics.get("train-loss", 0.0)),
                queue_latency_s=float(queue_latency_s),
                delta=delta,
            )
            if not buffered_updates:
                buffer_started_at = time.perf_counter()
            buffered_updates.append(update)
            client_trips_total = trip_index
            progress_state["client_trips_total"] = client_trips_total
            progress_state["wall_clock_s_since_start"] = time.perf_counter() - total_start
            experiment_logger.log_progress_metrics(
                client_trips_total,
                MetricRecord(
                    {
                        "wall_clock_s": float(progress_state["wall_clock_s_since_start"]),
                        "client_trips_total": client_trips_total,
                        "server_step": server_step,
                        "updates_per_second": (
                            client_trips_total / max(float(progress_state["wall_clock_s_since_start"]), 1e-6)
                        ),
                    }
                ),
            )

            if len(buffered_updates) >= buffer_size:
                aggregate = OrderedDict(
                    (key, torch.zeros_like(value))
                    for key, value in current_state.items()
                )
                train_loss = 0.0
                staleness_values = [entry.staleness for entry in buffered_updates]
                train_durations = [entry.train_duration_s for entry in buffered_updates]
                normalized_weights: list[float]
                if staleness_mode == "fair":
                    total_weight = sum(entry.weight for entry in buffered_updates)
                    normalized_weights = [
                        (entry.weight / total_weight) if total_weight > 0 else (1.0 / len(buffered_updates))
                        for entry in buffered_updates
                    ]
                else:
                    normalized_weights = [entry.weight / float(buffer_size) for entry in buffered_updates]
                by_device: dict[str, list[_BufferedUpdate]] = {}
                device_weight_totals = {device: 0.0 for device in tracked_devices}
                device_update_counts = {device: 0 for device in tracked_devices}
                device_staleness_sums = {device: 0.0 for device in tracked_devices}
                for entry, normalized_weight in zip(buffered_updates, normalized_weights, strict=True):
                    by_device.setdefault(entry.device_type, []).append(entry)
                    train_loss += entry.train_loss
                    if entry.device_type in tracked_devices:
                        device_weight_totals[entry.device_type] += normalized_weight
                        device_update_counts[entry.device_type] += 1
                        device_staleness_sums[entry.device_type] += float(entry.staleness)
                        cumulative_update_counts[entry.device_type] += 1
                        cumulative_weight_totals[entry.device_type] += normalized_weight
                        cumulative_staleness_sums[entry.device_type] += float(entry.staleness)
                    for key, tensor in entry.delta.items():
                        aggregate[key].add_(tensor, alpha=normalized_weight)
                # `aggregate` is already a weighted parameter delta reconstructed
                # from client-updated local states, so applying `lr` again would
                # incorrectly shrink the global step by another factor of the
                # client learning rate.
                new_state = _apply_aggregated_delta(current_state, aggregate)
                current_state = new_state
                server_step += 1
                model_history[server_step] = _clone_state(current_state)
                min_version_inflight = min(
                    (entry.server_model_version_sent for entry in inflight.values()),
                    default=server_step,
                )
                for version in list(model_history):
                    if version < min_version_inflight and version != server_step:
                        model_history.pop(version, None)
                current_arrays = ArrayRecord(_clone_state(current_state))
                result.arrays = current_arrays
                buffer_fill_duration_s = (
                    time.perf_counter() - buffer_started_at if buffer_started_at is not None else 0.0
                )
                mean_duration = sum(train_durations) / len(train_durations)
                variance = sum((duration - mean_duration) ** 2 for duration in train_durations) / len(train_durations)
                train_metrics = MetricRecord(
                    {
                        "train-loss": train_loss / len(buffered_updates),
                        "round-model-rate-avg": global_model_rate,
                        "round-model-rate-min": global_model_rate,
                        "round-model-rate-max": global_model_rate,
                        "round-successful-train-replies": len(buffered_updates),
                    }
                )
                result.train_metrics_clientapp[server_step] = train_metrics
                experiment_logger.log_train_metrics(server_step, train_metrics)
                for entry, normalized_weight in zip(buffered_updates, normalized_weights, strict=True):
                    artifact_logger.log_client_update_event(
                        {
                            "client_trips_total": entry.trip_index,
                            "server_step_applied": server_step,
                            "node_id": entry.node_id,
                            "device_type": entry.device_type,
                            "update_staleness_server_steps": entry.staleness,
                            "update_train_duration_s": entry.train_duration_s,
                            "update_num_examples": entry.num_examples,
                            "update_examples_per_second": entry.examples_per_second,
                            "update_queue_latency_s": entry.queue_latency_s,
                            "update_applied_weight": float(normalized_weight),
                        }
                    )
                fedbuff_metrics = MetricRecord(
                    {
                        "staleness_mean": sum(staleness_values) / len(staleness_values),
                        "staleness_max": max(staleness_values),
                        "staleness_min": min(staleness_values),
                        "buffer_fill_duration_s": float(buffer_fill_duration_s),
                        "inflight_clients": len(inflight),
                    }
                )
                experiment_logger.log_async_metrics(method_label, server_step, fedbuff_metrics)
                fairness_metrics = MetricRecord(
                    {
                        "weight_jain": _jain_index(list(device_weight_totals.values())),
                        "update_count_jain": _jain_index([float(value) for value in device_update_counts.values()]),
                        "device_weight_share_rpi4": device_weight_totals["rpi4"],
                        "device_weight_share_rpi5": device_weight_totals["rpi5"],
                        "device_update_share_rpi4": device_update_counts["rpi4"] / max(len(buffered_updates), 1),
                        "device_update_share_rpi5": device_update_counts["rpi5"] / max(len(buffered_updates), 1),
                        "device_mean_staleness_rpi4": (
                            device_staleness_sums["rpi4"] / device_update_counts["rpi4"]
                            if device_update_counts["rpi4"] > 0
                            else 0.0
                        ),
                        "device_mean_staleness_rpi5": (
                            device_staleness_sums["rpi5"] / device_update_counts["rpi5"]
                            if device_update_counts["rpi5"] > 0
                            else 0.0
                        ),
                    }
                )
                experiment_logger.log_summary_metrics(
                    {f"fairness/{key}": value for key, value in dict(fairness_metrics).items()}
                )
                system_metrics: dict[str, float | int] = {
                    "round-train-duration-s": float(buffer_fill_duration_s),
                    "round-successful-train-replies": len(buffered_updates),
                    "round-failed-train-replies": 0,
                    "round-train-client-duration-mean-s": mean_duration,
                    "round-train-client-duration-min-s": min(train_durations),
                    "round-train-client-duration-max-s": max(train_durations),
                    "round-train-client-duration-std-s": math.sqrt(variance),
                    "round-train-straggler-gap-s": max(train_durations) - min(train_durations),
                    "fairness_weight_jain": float(fairness_metrics["weight_jain"]),
                    "fairness_update_count_jain": float(fairness_metrics["update_count_jain"]),
                    "fairness_device_weight_share_rpi4": float(fairness_metrics["device_weight_share_rpi4"]),
                    "fairness_device_weight_share_rpi5": float(fairness_metrics["device_weight_share_rpi5"]),
                    "fairness_device_update_share_rpi4": float(fairness_metrics["device_update_share_rpi4"]),
                    "fairness_device_update_share_rpi5": float(fairness_metrics["device_update_share_rpi5"]),
                    "fairness_device_mean_staleness_rpi4": float(fairness_metrics["device_mean_staleness_rpi4"]),
                    "fairness_device_mean_staleness_rpi5": float(fairness_metrics["device_mean_staleness_rpi5"]),
                    "updates_per_second": len(buffered_updates) / max(float(buffer_fill_duration_s), 1e-6),
                }
                for device_type, entries in by_device.items():
                    system_metrics[f"{device_type}_train_duration_mean_s"] = sum(e.train_duration_s for e in entries) / len(entries)
                    system_metrics[f"{device_type}_examples_per_second_mean"] = sum(e.examples_per_second for e in entries) / len(entries)
                    system_metrics[f"{device_type}_updates_accepted"] = len(entries)
                system_metrics.update(
                    summarize_round_costs(
                        task.name,
                        [global_model_rate for _ in buffered_updates],
                        global_model_rate=global_model_rate,
                    )
                )
                experiment_logger.log_system_metrics(server_step, system_metrics)
                artifact_logger.log_server_step_event(
                    {
                        "server_step": server_step,
                        "wall_clock_s_since_start": float(time.perf_counter() - total_start),
                        "client_trips_total": client_trips_total,
                        "accepted_updates_this_step": len(buffered_updates),
                        "buffer_size": len(buffered_updates),
                        "buffer_fill_duration_s": float(buffer_fill_duration_s),
                        "staleness_mean": sum(staleness_values) / len(staleness_values),
                        "staleness_max": max(staleness_values),
                        "staleness_min": min(staleness_values),
                        "inflight_clients": len(inflight),
                        "updates_per_second": len(buffered_updates) / max(float(buffer_fill_duration_s), 1e-6),
                        **system_metrics,
                    }
                )
                log(INFO, "")
                log(INFO, "[STEP %s/%s]", server_step, num_server_steps)
                server_log(
                    method_label=method_label,
                    message=(
                        f"step_applied step={server_step}/{num_server_steps}"
                        f" accepted_updates={len(buffered_updates)}"
                        f" client_trips={client_trips_total}"
                        f" inflight={len(inflight)}"
                        f" staleness_mean={sum(staleness_values) / len(staleness_values):.2f}"
                    ),
                )
                if method_label == "fedstaleweight":
                    server_log(
                        method_label=method_label,
                        message=(
                            "fairness"
                            f" weight_share_rpi4={device_weight_totals['rpi4']:.2f}"
                            f" weight_share_rpi5={device_weight_totals['rpi5']:.2f}"
                            f" update_share_rpi4={device_update_counts['rpi4'] / max(len(buffered_updates), 1):.2f}"
                            f" update_share_rpi5={device_update_counts['rpi5'] / max(len(buffered_updates), 1):.2f}"
                        ),
                    )
                if server_step % evaluate_every_steps == 0:
                    eval_metrics = evaluate(server_step, current_arrays)
                    if eval_metrics is not None:
                        result.evaluate_metrics_serverapp[server_step] = eval_metrics
                        if target_controller.observe(
                            task=task,
                            server_step=server_step,
                            metrics=eval_metrics,
                            progress_state=progress_state,
                        ):
                            server_log(
                                method_label=method_label,
                                message=(
                                    f"target_reached step={server_step}"
                                    f" client_trips={target_controller.client_trips_to_target}"
                                    f" threshold={target_controller.threshold:.4f}"
                                ),
                            )
                            stop_requested = True
                buffered_updates.clear()
                buffer_started_at = None

                if stop_requested:
                    break
            dispatch_until_full()
            if server_step >= num_server_steps or stop_requested:
                break

    if not target_controller.reached and server_step >= num_server_steps:
        server_log(
            method_label=method_label,
            message=(
                f"budget_exhausted step={server_step}/{num_server_steps}"
                f" client_trips={client_trips_total}"
            ),
        )

    if final_client_eval_enabled:
        replies = _dispatch_eval_messages(
            grid=grid,
            node_ids=node_ids,
            current_state=current_state,
            global_model_rate=global_model_rate,
            server_step=server_step,
            method_label=method_label,
            partition_plan_by_node_id=partition_plan_by_node_id,
        )
        eval_metrics = _aggregate_eval_metrics(replies)
        if eval_metrics is not None:
            result.evaluate_metrics_clientapp[server_step] = eval_metrics
            experiment_logger.log_client_eval_metrics(server_step, eval_metrics)

    total_device_updates = sum(cumulative_update_counts.values())
    experiment_logger.log_summary_metrics(
        {
            "fairness/run_update_count_rpi4": cumulative_update_counts["rpi4"],
            "fairness/run_update_count_rpi5": cumulative_update_counts["rpi5"],
            "fairness/run_weight_total_rpi4": cumulative_weight_totals["rpi4"],
            "fairness/run_weight_total_rpi5": cumulative_weight_totals["rpi5"],
            "fairness/run_update_share_rpi4": cumulative_update_counts["rpi4"] / max(total_device_updates, 1),
            "fairness/run_update_share_rpi5": cumulative_update_counts["rpi5"] / max(total_device_updates, 1),
            "fairness/run_avg_staleness_rpi4": (
                cumulative_staleness_sums["rpi4"] / cumulative_update_counts["rpi4"]
                if cumulative_update_counts["rpi4"] > 0
                else 0.0
            ),
            "fairness/run_avg_staleness_rpi5": (
                cumulative_staleness_sums["rpi5"] / cumulative_update_counts["rpi5"]
                if cumulative_update_counts["rpi5"] > 0
                else 0.0
            ),
        }
    )
    target_summary_metrics = target_controller.summary_metrics()
    if target_summary_metrics:
        experiment_logger.log_summary_metrics(target_summary_metrics)
    experiment_logger.log_run_summary(
        total_runtime_s=time.perf_counter() - total_start,
        result=result,
    )
    experiment_logger.finish()
