"""Modern Flower HeteroFL strategy with shared rate assignment."""

from __future__ import annotations

import copy
import math
import time
from collections import OrderedDict
from collections.abc import Iterable
from logging import INFO

from flwr.app import ArrayRecord, ConfigRecord, Message, MessageType, RecordDict
from flwr.common import MetricRecord
from flwr.common.logger import log
from flwr.serverapp import Grid
from flwr.serverapp.strategy import FedAvg
from flwr.serverapp.strategy.fedavg import sample_nodes

from fedctl_research.costs import summarize_round_costs
from fedctl_research.metrics import normalize_metric_mapping
from fedctl_research.methods.assignment import ModelRateAssigner
from fedctl_research.netem_probe import netem_payload_from_metrics
from fedctl_research.result_artifacts import ResultArtifactLogger
from fedctl_research.wandb_logging import ExperimentLogger

from .slicing import (
    build_param_indices_for_rate,
    finalize_aggregation,
    init_aggregation_buffers,
    merge_local_state_into_global,
    slice_state_dict,
)


class HeteroFLStrategy(FedAvg):
    """Heterogeneous width-sliced strategy with masked parameter aggregation."""

    def __init__(
        self,
        *,
        rate_assigner: ModelRateAssigner,
        global_model_rate: float = 1.0,
        task_name: str = "fashion_mnist_mlp",
        experiment_logger: ExperimentLogger | None = None,
        artifact_logger: ResultArtifactLogger | None = None,
        client_eval_enabled: bool = True,
        progress_tracker: dict[str, int | float] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.rate_assigner = rate_assigner
        self.global_model_rate = global_model_rate
        self.task_name = task_name
        self.experiment_logger = experiment_logger or ExperimentLogger()
        self.artifact_logger = artifact_logger
        self.client_eval_enabled = client_eval_enabled
        self.progress_tracker = progress_tracker if progress_tracker is not None else {}
        self._active_rate_by_node: dict[int, float] = {}
        self._active_param_idx_by_node: dict[int, dict] = {}
        self.partition_plan_by_node_id: dict[int, dict[str, int | str]] = {}
        self._global_state_for_round: OrderedDict[str, object] | None = None
        self._round_started_at: float | None = None
        self._eval_started_at: float | None = None
        self._server_started_at: float | None = None
        self._round_sampled_nodes: int = 0
        self._eval_sampled_nodes: int = 0
        self._accepted_train_replies_total: int = 0

    def summary(self) -> None:
        log(INFO, "%s", self.__class__.__name__)
        log(INFO, "  global_model_rate: %s", self.global_model_rate)
        for key, value in self.rate_assigner.summary_dict().items():
            log(INFO, "  %s: %s", key, value)

    def set_node_capabilities(self, device_type_by_node_id: dict[int, str]) -> None:
        self.rate_assigner.set_node_capabilities(device_type_by_node_id)

    def set_node_partition_ids(self, partition_id_by_node_id: dict[int, int]) -> None:
        self.rate_assigner.set_node_partition_ids(partition_id_by_node_id)

    def set_node_partition_plan(self, partition_plan_by_node_id: dict[int, dict[str, int | str]]) -> None:
        self.partition_plan_by_node_id = {
            int(node_id): dict(plan_entry) for node_id, plan_entry in partition_plan_by_node_id.items()
        }
        self.rate_assigner.set_typed_partition_plan(self.partition_plan_by_node_id)

    def _inject_partition_plan_into_config(self, node_id: int, config: ConfigRecord) -> ConfigRecord:
        partition_plan = self.partition_plan_by_node_id.get(node_id)
        if partition_plan is None:
            return config
        updated_config = ConfigRecord(dict(config))
        updated_config.update(partition_plan)
        return updated_config

    def _inject_partition_plan_into_messages(self, messages: list[Message]) -> list[Message]:
        if not self.partition_plan_by_node_id:
            return messages
        for message in messages:
            config = message.content.get(self.configrecord_key)
            config_record = ConfigRecord(dict(config)) if isinstance(config, ConfigRecord) else ConfigRecord({})
            message.content[self.configrecord_key] = self._inject_partition_plan_into_config(
                message.metadata.dst_node_id,
                config_record,
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
        global_state = arrays.to_torch_state_dict()
        eval_rate_by_node = self.rate_assigner.assign_for_round(list(node_ids), server_round)

        messages: list[Message] = []
        for node_id in node_ids:
            model_rate = eval_rate_by_node[node_id]
            param_idx = self.build_param_indices(
                global_state,
                model_rate=model_rate,
                server_round=server_round,
            )
            local_state = slice_state_dict(global_state, param_idx)

            local_config = ConfigRecord(dict(base_config))
            local_config["model-rate"] = model_rate
            local_config["global-model-rate"] = self.global_model_rate
            local_config = self._inject_partition_plan_into_config(node_id, local_config)

            content = RecordDict(
                {
                    self.arrayrecord_key: ArrayRecord(local_state),
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

    def build_param_indices(self, global_state, *, model_rate: float, server_round: int):
        del server_round
        return build_param_indices_for_rate(
            global_state,
            model_rate,
            global_model_rate=self.global_model_rate,
        )

    def submodel_eval_rates(self) -> tuple[float, ...]:
        return self.rate_assigner.eval_rates(global_model_rate=self.global_model_rate)

    def weight_for_local_update(self, message: Message) -> float:
        metric_record = message.content.get("metrics")
        if metric_record is not None and self.weighted_by_key in metric_record:
            return float(metric_record[self.weighted_by_key])
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

        global_state = arrays.to_torch_state_dict()
        self._global_state_for_round = copy.deepcopy(global_state)
        self._active_rate_by_node = self.rate_assigner.assign_for_round(list(node_ids), server_round)
        self._active_param_idx_by_node.clear()
        now = time.perf_counter()
        self._round_started_at = now
        if self._server_started_at is None:
            self._server_started_at = now
        self._round_sampled_nodes = len(node_ids)

        messages: list[Message] = []
        for node_id in node_ids:
            model_rate = self._active_rate_by_node[node_id]
            param_idx = self.build_param_indices(
                global_state,
                model_rate=model_rate,
                server_round=server_round,
            )
            self._active_param_idx_by_node[node_id] = param_idx
            local_state = slice_state_dict(global_state, param_idx)

            local_config = ConfigRecord(dict(base_config))
            local_config["model-rate"] = model_rate
            local_config["global-model-rate"] = self.global_model_rate
            local_config = self._inject_partition_plan_into_config(node_id, local_config)

            content = RecordDict(
                {
                    self.arrayrecord_key: ArrayRecord(local_state),
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

    def _device_type_for_node(self, node_id: int) -> str:
        return self.rate_assigner.device_type_by_node_id.get(node_id, "unknown")

    def aggregate_train(
        self,
        server_round: int,
        replies: Iterable[Message],
    ) -> tuple[ArrayRecord | None, MetricRecord | None]:
        valid_replies, _ = self._check_and_log_replies(replies, is_train=True)
        if not valid_replies or self._global_state_for_round is None:
            return None, None

        sums, counts = init_aggregation_buffers(self._global_state_for_round)
        for message in valid_replies:
            node_id = message.metadata.src_node_id
            local_state = message.content[self.arrayrecord_key].to_torch_state_dict()
            merge_local_state_into_global(
                sums,
                counts,
                local_state,
                self._active_param_idx_by_node[node_id],
                weight=self.weight_for_local_update(message),
            )

        aggregated_state = finalize_aggregation(self._global_state_for_round, sums, counts)
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
                    "update_applied_weight": float(self.weight_for_local_update(message)),
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
                    "update_applied_weight": float(self.weight_for_local_update(message)),
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

    def aggregate_evaluate(
        self,
        server_round: int,
        replies: Iterable[Message],
    ) -> MetricRecord | None:
        reply_list = list(replies)
        metrics = super().aggregate_evaluate(server_round, reply_list)
        valid_replies, _ = self._check_and_log_replies(reply_list, is_train=False)
        if metrics is not None:
            metrics = MetricRecord(normalize_metric_mapping(dict(metrics)))
        eval_metrics = dict(metrics) if metrics is not None else {}
        valid_count = len(valid_replies)
        system_metrics = {
            "round-successful-eval-replies": valid_count,
            "round-failed-eval-replies": self._eval_sampled_nodes - valid_count,
            "round-client-eval-duration-s": (
                time.perf_counter() - self._eval_started_at if self._eval_started_at is not None else 0.0
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
        self.experiment_logger.log_client_eval_metrics(server_round, eval_metrics)
        self.experiment_logger.log_system_metrics(server_round, system_metrics)
        client_eval_rows: list[dict[str, float | int | str]] = []
        if self.artifact_logger is not None:
            for message in valid_replies:
                metrics_record = message.content.get("metrics")
                if metrics_record is None:
                    continue
                node_id = message.metadata.src_node_id
                payload = {
                    "server_round": server_round,
                    "server_step": server_round,
                    "node_id": node_id,
                    "device_type": self._device_type_for_node(node_id),
                    "model_rate": float(self._active_rate_by_node.get(node_id, self.global_model_rate)),
                    "eval_acc": float(metrics_record.get("eval-acc", 0.0)),
                    "eval_loss": float(metrics_record.get("eval-loss", 0.0)),
                    "eval_duration_s": float(metrics_record.get("eval-duration-s", 0.0)),
                    "num_examples": int(
                        metrics_record.get("eval-num-examples", metrics_record.get("num-examples", 0))
                    ),
                }
                client_eval_rows.append(payload)
                self.artifact_logger.log_client_eval_event(payload)
        else:
            for message in valid_replies:
                metrics_record = message.content.get("metrics")
                if metrics_record is None:
                    continue
                node_id = message.metadata.src_node_id
                client_eval_rows.append(
                    {
                        "server_round": server_round,
                        "server_step": server_round,
                        "node_id": node_id,
                        "device_type": self._device_type_for_node(node_id),
                        "model_rate": float(self._active_rate_by_node.get(node_id, self.global_model_rate)),
                        "eval_acc": float(metrics_record.get("eval-acc", 0.0)),
                        "eval_loss": float(metrics_record.get("eval-loss", 0.0)),
                        "eval_duration_s": float(metrics_record.get("eval-duration-s", 0.0)),
                        "num_examples": int(
                            metrics_record.get("eval-num-examples", metrics_record.get("num-examples", 0))
                        ),
                    }
                )
        if client_eval_rows:
            self.experiment_logger.log_client_eval_event_rows(server_round, client_eval_rows, axis_key="server_round")
        return metrics


FixedRateHeteroFL = HeteroFLStrategy
