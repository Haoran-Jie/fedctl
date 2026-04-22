"""FIARSE strategy with full-model sparse masked local training."""

from __future__ import annotations

import copy
import math
import time
from collections import OrderedDict
from collections.abc import Iterable
from logging import INFO

import torch
from flwr.app import ArrayRecord, ConfigRecord, Message, MessageType, RecordDict
from flwr.common import MetricRecord
from flwr.common.logger import log
from flwr.serverapp import Grid
from flwr.serverapp.strategy.fedavg import sample_nodes

from fedctl_research.costs import summarize_round_costs
from fedctl_research.metrics import normalize_metric_mapping
from fedctl_research.methods.heterofl.strategy import HeteroFLStrategy
from fedctl_research.netem_probe import netem_payload_from_metrics


class FiarseStrategy(HeteroFLStrategy):
    """Reference-style FIARSE server using sparse full-model delta aggregation."""

    def __init__(
        self,
        *,
        threshold_mode: str = "global",
        global_learning_rate: float = 1.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.threshold_mode = threshold_mode
        self.global_learning_rate = float(global_learning_rate)

    def summary(self) -> None:
        super().summary()
        log(INFO, "  threshold_mode: %s", self.threshold_mode)
        log(INFO, "  fiarse_global_learning_rate: %s", self.global_learning_rate)

    def build_param_indices(self, global_state, *, model_rate: float, server_round: int):
        raise NotImplementedError("FIARSE uses full-model masked train/eval rather than width slicing.")

    def weight_for_local_update(self, message: Message) -> float:
        del message
        return 1.0

    def configure_train(
        self,
        server_round: int,
        arrays: ArrayRecord,
        config: ConfigRecord,
        grid: Grid,
    ) -> Iterable[Message]:
        if self.fraction_train == 0.0:
            return []

        num_nodes = int(len(list(grid.get_node_ids())) * self.fraction_train)
        sample_size = max(num_nodes, self.min_train_nodes)
        node_ids, num_total = sample_nodes(grid, self.min_available_nodes, sample_size)
        log(INFO, "configure_train: Sampled %s nodes (out of %s)", len(node_ids), len(num_total))

        base_config = ConfigRecord(dict(config))
        base_config["server-round"] = server_round
        base_config["fiarse-threshold-mode"] = self.threshold_mode

        global_state = arrays.to_torch_state_dict()
        self._global_state_for_round = copy.deepcopy(global_state)
        self._active_rate_by_node = self.rate_assigner.assign_for_round(list(node_ids), server_round)
        now = time.perf_counter()
        self._round_started_at = now
        if self._server_started_at is None:
            self._server_started_at = now
        self._round_sampled_nodes = len(node_ids)

        messages: list[Message] = []
        for node_id in node_ids:
            local_config = ConfigRecord(dict(base_config))
            local_config["model-rate"] = self._active_rate_by_node[node_id]
            local_config["global-model-rate"] = self.global_model_rate
            local_config = self._inject_partition_plan_into_config(node_id, local_config)
            content = RecordDict(
                {
                    self.arrayrecord_key: ArrayRecord(
                        OrderedDict((key, value.detach().clone()) for key, value in global_state.items())
                    ),
                    self.configrecord_key: local_config,
                }
            )
            messages.append(
                Message(
                    content=content,
                    message_type=MessageType.TRAIN,
                    dst_node_id=node_id,
                    group_id=str(server_round),
                )
            )
        return messages

    def configure_evaluate(
        self,
        server_round: int,
        arrays: ArrayRecord,
        config: ConfigRecord,
        grid: Grid,
    ) -> Iterable[Message]:
        if not self.client_eval_enabled:
            return []

        num_nodes = int(len(list(grid.get_node_ids())) * self.fraction_evaluate)
        sample_size = max(num_nodes, self.min_evaluate_nodes)
        node_ids, num_total = sample_nodes(grid, self.min_available_nodes, sample_size)
        log(INFO, "configure_evaluate: Sampled %s nodes (out of %s)", len(node_ids), len(num_total))
        self._eval_started_at = time.perf_counter()
        self._eval_sampled_nodes = len(node_ids)

        base_config = ConfigRecord(dict(config))
        base_config["server-round"] = server_round
        base_config["fiarse-threshold-mode"] = self.threshold_mode
        global_state = arrays.to_torch_state_dict()
        eval_rate_by_node = self.rate_assigner.assign_for_round(list(node_ids), server_round)

        messages: list[Message] = []
        for node_id in node_ids:
            local_config = ConfigRecord(dict(base_config))
            local_config["model-rate"] = eval_rate_by_node[node_id]
            local_config["global-model-rate"] = self.global_model_rate
            local_config = self._inject_partition_plan_into_config(node_id, local_config)
            content = RecordDict(
                {
                    self.arrayrecord_key: ArrayRecord(
                        OrderedDict((key, value.detach().clone()) for key, value in global_state.items())
                    ),
                    self.configrecord_key: local_config,
                }
            )
            messages.append(
                Message(
                    content=content,
                    message_type=MessageType.EVALUATE,
                    dst_node_id=node_id,
                    group_id=str(server_round),
                )
            )
        return messages

    def aggregate_train(
        self,
        server_round: int,
        replies: Iterable[Message],
    ) -> tuple[ArrayRecord | None, MetricRecord | None]:
        valid_replies, _ = self._check_and_log_replies(replies, is_train=True)
        if not valid_replies or self._global_state_for_round is None:
            return None, None

        delta_sums = {
            name: torch.zeros_like(value, dtype=torch.float32)
            for name, value in self._global_state_for_round.items()
        }
        delta_counts = {
            name: torch.zeros_like(value, dtype=torch.float32)
            for name, value in self._global_state_for_round.items()
        }

        for message in valid_replies:
            local_state = message.content[self.arrayrecord_key].to_torch_state_dict()
            for name, global_value in self._global_state_for_round.items():
                delta = global_value.detach().to(torch.float32) - local_state[name].detach().to(torch.float32)
                delta_sums[name] += delta
                delta_counts[name] += (delta != 0).to(torch.float32)

        aggregated_state: OrderedDict[str, torch.Tensor] = OrderedDict()
        for name, global_value in self._global_state_for_round.items():
            count = delta_counts[name]
            avg_delta = torch.where(
                count > 0,
                delta_sums[name] / count.clamp_min(1.0),
                torch.zeros_like(delta_sums[name]),
            )
            step = avg_delta if _is_tracking_stat_key(name) else self.global_learning_rate * avg_delta
            updated = global_value.detach().to(torch.float32) - step
            if global_value.dtype.is_floating_point:
                aggregated_state[name] = updated.to(dtype=global_value.dtype)
            else:
                aggregated_state[name] = updated.round().to(dtype=global_value.dtype)

        array_record = ArrayRecord(aggregated_state)
        metrics = self.train_metrics_aggr_fn([message.content for message in valid_replies], self.weighted_by_key)
        if metrics is not None:
            metrics = MetricRecord(normalize_metric_mapping(dict(metrics)))
        train_metrics = dict(metrics) if metrics is not None else {}
        valid_count = len(valid_replies)
        self._accepted_train_replies_total += valid_count
        reply_rates = [self._active_rate_by_node[msg.metadata.src_node_id] for msg in valid_replies]
        round_duration_s = time.perf_counter() - self._round_started_at if self._round_started_at is not None else 0.0
        total_wall_clock_s = (
            time.perf_counter() - self._server_started_at if self._server_started_at is not None else round_duration_s
        )
        system_metrics = {
            "round-sampled-nodes": self._round_sampled_nodes,
            "round-successful-train-replies": valid_count,
            "round-failed-train-replies": self._round_sampled_nodes - valid_count,
            "round-train-duration-s": round_duration_s,
        }
        train_durations = [
            float(message.content["metrics"]["train-duration-s"])
            for message in valid_replies
            if "metrics" in message.content and "train-duration-s" in message.content["metrics"]
        ]
        if train_durations:
            mean_duration = sum(train_durations) / len(train_durations)
            variance = sum((duration - mean_duration) ** 2 for duration in train_durations) / len(train_durations)
            system_metrics.update(
                {
                    "round-train-client-duration-mean-s": mean_duration,
                    "round-train-client-duration-min-s": min(train_durations),
                    "round-train-client-duration-max-s": max(train_durations),
                    "round-train-client-duration-std-s": math.sqrt(variance),
                    "round-train-straggler-gap-s": max(train_durations) - min(train_durations),
                }
            )
        if reply_rates:
            train_metrics["round-model-rate-avg"] = sum(reply_rates) / len(reply_rates)
            train_metrics["round-model-rate-min"] = min(reply_rates)
            train_metrics["round-model-rate-max"] = max(reply_rates)
            system_metrics.update(
                summarize_round_costs(
                    self.task_name,
                    reply_rates,
                    global_model_rate=self.global_model_rate,
                )
            )
        self.experiment_logger.log_train_metrics(server_round, train_metrics)
        self.experiment_logger.log_system_metrics(server_round, system_metrics)
        self.progress_tracker["wall_clock_s_since_start"] = float(total_wall_clock_s)
        self.progress_tracker["client_trips_total"] = int(self._accepted_train_replies_total)
        client_update_rows: list[dict[str, float | int | str]] = []
        if self.artifact_logger is not None:
            for offset, message in enumerate(valid_replies, start=1):
                metrics_record = message.content.get("metrics")
                if metrics_record is None:
                    continue
                node_id = message.metadata.src_node_id
                payload = {
                    "server_round": server_round,
                    "client_trips_total": self._accepted_train_replies_total - valid_count + offset,
                    "node_id": node_id,
                    "device_type": self._device_type_for_node(node_id),
                    "server_model_version_sent": max(server_round - 1, 0),
                    "server_step_applied": server_round,
                    "update_staleness_server_steps": 0,
                    "update_train_duration_s": float(metrics_record.get("train-duration-s", 0.0)),
                    "update_num_examples": int(metrics_record.get("train-num-examples", metrics_record.get("num-examples", 0))),
                    "update_examples_per_second": float(metrics_record.get("examples-per-second", 0.0)),
                    "update_queue_latency_s": 0.0,
                    "update_applied_weight": 1.0,
                    "model_rate": float(self._active_rate_by_node.get(node_id, self.global_model_rate)),
                }
                payload.update(netem_payload_from_metrics(metrics_record))
                client_update_rows.append(payload)
                self.artifact_logger.log_client_update_event(payload)
            self.artifact_logger.log_server_step_event(
                {
                    "server_step": server_round,
                    "wall_clock_s_since_start": float(total_wall_clock_s),
                    "client_trips_total": self._accepted_train_replies_total,
                    "accepted_updates_this_step": valid_count,
                    "buffer_size": valid_count,
                    "inflight_clients": 0,
                    **system_metrics,
                }
            )
        else:
            for offset, message in enumerate(valid_replies, start=1):
                metrics_record = message.content.get("metrics")
                if metrics_record is None:
                    continue
                node_id = message.metadata.src_node_id
                payload = {
                    "server_round": server_round,
                    "client_trips_total": self._accepted_train_replies_total - valid_count + offset,
                    "node_id": node_id,
                    "device_type": self._device_type_for_node(node_id),
                    "server_model_version_sent": max(server_round - 1, 0),
                    "server_step_applied": server_round,
                    "update_staleness_server_steps": 0,
                    "update_train_duration_s": float(metrics_record.get("train-duration-s", 0.0)),
                    "update_num_examples": int(metrics_record.get("train-num-examples", metrics_record.get("num-examples", 0))),
                    "update_examples_per_second": float(metrics_record.get("examples-per-second", 0.0)),
                    "update_queue_latency_s": 0.0,
                    "update_applied_weight": 1.0,
                    "model_rate": float(self._active_rate_by_node.get(node_id, self.global_model_rate)),
                }
                payload.update(netem_payload_from_metrics(metrics_record))
                client_update_rows.append(payload)
        if client_update_rows:
            self.experiment_logger.log_client_update_events(server_round, client_update_rows, axis_key="server_round")

        self._active_rate_by_node.clear()
        self._active_param_idx_by_node.clear()
        self._global_state_for_round = copy.deepcopy(aggregated_state)
        return array_record, metrics


def _is_tracking_stat_key(name: str) -> bool:
    return ("running_mean" in name) or ("running_var" in name) or ("num_batches_tracked" in name)
