"""FedAvg baseline strategy with shared logging hooks."""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Iterable

from flwr.app import ArrayRecord, ConfigRecord, Message
from flwr.common import MetricRecord
from flwr.serverapp import Grid
from flwr.serverapp.strategy import FedAvg

from fedctl_research.costs import summarize_round_costs
from fedctl_research.result_artifacts import ResultArtifactLogger
from fedctl_research.wandb_logging import ExperimentLogger


class SyncLoggingMixin:
    def __init__(
        self,
        *,
        experiment_logger: ExperimentLogger | None = None,
        artifact_logger: ResultArtifactLogger | None = None,
        task_name: str = "fashion_mnist_mlp",
        global_model_rate: float = 1.0,
        client_eval_enabled: bool = True,
        progress_tracker: dict[str, int | float] | None = None,
        device_type_by_node_id: dict[int, str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.experiment_logger = experiment_logger or ExperimentLogger()
        self.artifact_logger = artifact_logger
        self.task_name = task_name
        self.global_model_rate = global_model_rate
        self.client_eval_enabled = client_eval_enabled
        self.progress_tracker = progress_tracker if progress_tracker is not None else {}
        self.device_type_by_node_id = dict(device_type_by_node_id or {})
        self.partition_plan_by_node_id: dict[int, dict[str, int | str]] = {}
        self._round_started_at: float | None = None
        self._server_started_at: float | None = None
        self._round_sampled_nodes: int = 0
        self._accepted_train_replies_total: int = 0
        self._global_state_before_round: OrderedDict[str, object] | None = None

    def _inject_partition_plan(self, messages: list[Message]) -> list[Message]:
        if not self.partition_plan_by_node_id:
            return messages
        for message in messages:
            entry = self.partition_plan_by_node_id.get(message.metadata.dst_node_id)
            if entry is None:
                continue
            config = message.content.get(self.configrecord_key)
            config_record = ConfigRecord(dict(config)) if isinstance(config, ConfigRecord) else ConfigRecord({})
            config_record.update(entry)
            message.content[self.configrecord_key] = config_record
        return messages

    def configure_train(
        self,
        server_round: int,
        arrays: ArrayRecord,
        config: ConfigRecord,
        grid: Grid,
    ) -> Iterable[Message]:
        now = time.perf_counter()
        self._round_started_at = now
        if self._server_started_at is None:
            self._server_started_at = now
        self._global_state_before_round = arrays.to_torch_state_dict()
        messages = list(super().configure_train(server_round, arrays, config, grid))
        self._round_sampled_nodes = len(messages)
        return self._inject_partition_plan(messages)

    def configure_evaluate(
        self,
        server_round: int,
        arrays: ArrayRecord,
        config: ConfigRecord,
        grid: Grid,
    ) -> Iterable[Message]:
        if not self.client_eval_enabled:
            return []
        messages = list(super().configure_evaluate(server_round, arrays, config, grid))
        return self._inject_partition_plan(messages)

    def set_node_capabilities(self, device_type_by_node_id: dict[int, str]) -> None:
        self.device_type_by_node_id = dict(device_type_by_node_id)

    def set_node_partition_plan(self, partition_plan_by_node_id: dict[int, dict[str, int | str]]) -> None:
        self.partition_plan_by_node_id = {
            int(node_id): dict(plan_entry) for node_id, plan_entry in partition_plan_by_node_id.items()
        }

    def _update_progress_tracker(self, *, wall_clock_s: float, client_trips_total: int) -> None:
        self.progress_tracker["wall_clock_s_since_start"] = float(wall_clock_s)
        self.progress_tracker["client_trips_total"] = int(client_trips_total)

    def _log_server_step_event(
        self,
        *,
        server_round: int,
        wall_clock_s: float,
        valid_replies: list[Message],
        system_metrics: dict[str, float | int],
    ) -> None:
        if self.artifact_logger is None:
            return
        payload: dict[str, float | int | str] = {
            "server_step": server_round,
            "wall_clock_s_since_start": float(wall_clock_s),
            "client_trips_total": self._accepted_train_replies_total,
            "accepted_updates_this_step": len(valid_replies),
            "buffer_size": len(valid_replies),
            "inflight_clients": 0,
        }
        payload.update(system_metrics)
        self.artifact_logger.log_server_step_event(payload)

    def _log_client_update_events(
        self,
        *,
        server_round: int,
        valid_replies: list[Message],
    ) -> None:
        if self.artifact_logger is None:
            return
        for offset, message in enumerate(valid_replies, start=1):
            metrics_record = message.content.get("metrics")
            if metrics_record is None:
                continue
            self.artifact_logger.log_client_update_event(
                {
                    "client_trips_total": self._accepted_train_replies_total - len(valid_replies) + offset,
                    "node_id": message.metadata.src_node_id,
                    "device_type": self.device_type_by_node_id.get(message.metadata.src_node_id, "unknown"),
                    "server_model_version_sent": max(server_round - 1, 0),
                    "server_step_applied": server_round,
                    "update_staleness_server_steps": 0,
                    "update_train_duration_s": float(metrics_record.get("train-duration-s", 0.0)),
                    "update_num_examples": int(metrics_record.get("train-num-examples", metrics_record.get("num-examples", 0))),
                    "update_examples_per_second": float(metrics_record.get("examples-per-second", 0.0)),
                    "update_queue_latency_s": 0.0,
                }
            )

    def aggregate_train(
        self,
        server_round: int,
        replies: Iterable[Message],
    ) -> tuple[ArrayRecord | None, MetricRecord | None]:
        reply_list = list(replies)
        arrays, metrics = super().aggregate_train(server_round, reply_list)
        valid_replies, _ = self._check_and_log_replies(reply_list, is_train=True)
        self._accepted_train_replies_total += len(valid_replies)
        train_metrics = dict(metrics) if metrics is not None else {}
        train_durations = [
            float(message.content["metrics"]["train-duration-s"])
            for message in valid_replies
            if "metrics" in message.content and "train-duration-s" in message.content["metrics"]
        ]
        wall_clock_s = time.perf_counter() - self._round_started_at if self._round_started_at is not None else 0.0
        system_metrics = {
            "round-sampled-nodes": self._round_sampled_nodes,
            "round-successful-train-replies": len(valid_replies),
            "round-failed-train-replies": self._round_sampled_nodes - len(valid_replies),
            "round-train-duration-s": wall_clock_s,
        }
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
        by_device: dict[str, list[tuple[float, float]]] = {}
        for message in valid_replies:
            metrics_record = message.content.get("metrics")
            if metrics_record is None:
                continue
            device_type = self.device_type_by_node_id.get(message.metadata.src_node_id, "unknown")
            duration = float(metrics_record.get("train-duration-s", 0.0))
            eps = float(metrics_record.get("examples-per-second", 0.0))
            by_device.setdefault(device_type, []).append((duration, eps))
        for device_type, values in by_device.items():
            durations = [value[0] for value in values]
            eps_values = [value[1] for value in values]
            system_metrics[f"{device_type}_train_duration_mean_s"] = sum(durations) / len(durations)
            system_metrics[f"{device_type}_examples_per_second_mean"] = sum(eps_values) / len(eps_values)
            system_metrics[f"{device_type}_updates_accepted"] = len(values)
        system_metrics.update(
            summarize_round_costs(
                self.task_name,
                [self.global_model_rate for _ in valid_replies],
                global_model_rate=self.global_model_rate,
            )
        )
        train_metrics.update(
            {
                "round-model-rate-avg": self.global_model_rate if valid_replies else self.global_model_rate,
                "round-model-rate-min": self.global_model_rate if valid_replies else self.global_model_rate,
                "round-model-rate-max": self.global_model_rate if valid_replies else self.global_model_rate,
            }
        )
        self.experiment_logger.log_train_metrics(server_round, train_metrics)
        self.experiment_logger.log_system_metrics(server_round, system_metrics)
        total_wall_clock_s = (
            time.perf_counter() - self._server_started_at if self._server_started_at is not None else wall_clock_s
        )
        self._update_progress_tracker(
            wall_clock_s=total_wall_clock_s,
            client_trips_total=self._accepted_train_replies_total,
        )
        self._log_client_update_events(server_round=server_round, valid_replies=valid_replies)
        self._log_server_step_event(
            server_round=server_round,
            wall_clock_s=total_wall_clock_s,
            valid_replies=valid_replies,
            system_metrics=system_metrics,
        )
        return arrays, metrics

    def aggregate_evaluate(
        self,
        server_round: int,
        replies: Iterable[Message],
    ) -> MetricRecord | None:
        reply_list = list(replies)
        metrics = super().aggregate_evaluate(server_round, reply_list)
        valid_replies, _ = self._check_and_log_replies(reply_list, is_train=False)
        eval_metrics = dict(metrics) if metrics is not None else {}
        system_metrics = {
            "round-successful-eval-replies": len(valid_replies),
            "round-failed-eval-replies": self._round_sampled_nodes - len(valid_replies),
            "round-client-eval-duration-s": (
                time.perf_counter() - self._round_started_at if self._round_started_at is not None else 0.0
            ),
        }
        eval_durations = [
            float(message.content["metrics"]["eval-duration-s"])
            for message in valid_replies
            if "metrics" in message.content and "eval-duration-s" in message.content["metrics"]
        ]
        if eval_durations:
            mean_duration = sum(eval_durations) / len(eval_durations)
            variance = sum((duration - mean_duration) ** 2 for duration in eval_durations) / len(eval_durations)
            system_metrics.update(
                {
                    "round-eval-client-duration-mean-s": mean_duration,
                    "round-eval-client-duration-min-s": min(eval_durations),
                    "round-eval-client-duration-max-s": max(eval_durations),
                    "round-eval-client-duration-std-s": math.sqrt(variance),
                }
            )
        eval_metrics.update(
            {
                "round-model-rate-avg": self.global_model_rate if valid_replies else self.global_model_rate,
            }
        )
        self.experiment_logger.log_client_eval_metrics(server_round, eval_metrics)
        self.experiment_logger.log_system_metrics(server_round, system_metrics)
        return metrics


class FedAvgBaseline(SyncLoggingMixin, FedAvg):
    pass
