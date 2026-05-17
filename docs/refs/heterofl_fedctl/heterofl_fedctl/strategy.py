"""Modern Flower fixed-rate HeteroFL strategy."""

from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Iterable
from logging import INFO

from flwr.app import ArrayRecord, ConfigRecord, Message, MessageType, RecordDict
from flwr.common import MetricRecord
from flwr.common.logger import log
from flwr.serverapp import Grid
from flwr.serverapp.strategy import FedAvg
from flwr.serverapp.strategy.fedavg import sample_nodes

from .slicing import (
    build_param_indices_for_rate,
    finalize_aggregation,
    init_aggregation_buffers,
    merge_local_state_into_global,
    slice_state_dict,
)


class FixedRateHeteroFL(FedAvg):
    """A first fixed-rate HeteroFL strategy for the modern Flower API."""

    def __init__(
        self,
        *,
        rate_by_node_id: dict[int, float] | None = None,
        rate_by_device_type: dict[str, float] | None = None,
        device_type_by_node_id: dict[int, str] | None = None,
        global_model_rate: float = 1.0,
        default_model_rate: float = 1.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.rate_by_node_id = rate_by_node_id or {}
        self.rate_by_device_type = rate_by_device_type or {}
        self.device_type_by_node_id = device_type_by_node_id or {}
        self.global_model_rate = global_model_rate
        self.default_model_rate = default_model_rate
        self._active_rate_by_node: dict[int, float] = {}
        self._active_param_idx_by_node: dict[int, dict] = {}
        self._global_state_for_round: OrderedDict[str, object] | None = None

    def summary(self) -> None:
        log(INFO, "FixedRateHeteroFL")
        log(INFO, "  global_model_rate: %s", self.global_model_rate)
        log(INFO, "  default_model_rate: %s", self.default_model_rate)
        if self.rate_by_node_id:
            log(INFO, "  explicit node-rate map: %s", self.rate_by_node_id)
        if self.rate_by_device_type:
            log(INFO, "  device-rate map: %s", self.rate_by_device_type)
        if self.device_type_by_node_id:
            log(INFO, "  discovered node device types: %s", self.device_type_by_node_id)

    def set_node_capabilities(self, device_type_by_node_id: dict[int, str]) -> None:
        self.device_type_by_node_id = dict(device_type_by_node_id)

    def _resolve_model_rate(self, node_id: int) -> float:
        explicit_rate = self.rate_by_node_id.get(node_id)
        if explicit_rate is not None:
            log(INFO, "model-rate: node=%s source=explicit-node-map rate=%s", node_id, explicit_rate)
            return float(explicit_rate)
        device_type = self.device_type_by_node_id.get(node_id)
        if device_type is not None:
            device_rate = self.rate_by_device_type.get(device_type)
            if device_rate is not None:
                log(
                    INFO,
                    "model-rate: node=%s source=device-map device_type=%s rate=%s",
                    node_id,
                    device_type,
                    device_rate,
                )
                return float(device_rate)
            log(
                INFO,
                "model-rate: node=%s device_type=%s missing in rate map, falling back=%s",
                node_id,
                device_type,
                self.default_model_rate,
            )
        else:
            log(
                INFO,
                "model-rate: node=%s source=fallback no device type discovered rate=%s",
                node_id,
                self.default_model_rate,
            )
        return self.default_model_rate

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
        log(
            INFO,
            "configure_train: Sampled %s nodes (out of %s)",
            len(node_ids),
            len(num_total),
        )

        base_config = ConfigRecord(dict(config))
        base_config["server-round"] = server_round

        global_state = arrays.to_torch_state_dict()
        self._global_state_for_round = copy.deepcopy(global_state)
        self._active_rate_by_node.clear()
        self._active_param_idx_by_node.clear()

        messages: list[Message] = []
        for node_id in node_ids:
            model_rate = self._resolve_model_rate(node_id)
            self._active_rate_by_node[node_id] = model_rate
            param_idx = build_param_indices_for_rate(
                global_state,
                model_rate,
                global_model_rate=self.global_model_rate,
            )
            self._active_param_idx_by_node[node_id] = param_idx
            local_state = slice_state_dict(global_state, param_idx)

            local_config = ConfigRecord(dict(base_config))
            local_config["model-rate"] = model_rate
            local_config["global-model-rate"] = self.global_model_rate

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
            content = message.content
            local_state = content[self.arrayrecord_key].to_torch_state_dict()
            metric_record = content.get("metrics")
            weight = 1.0
            if metric_record is not None and self.weighted_by_key in metric_record:
                weight = float(metric_record[self.weighted_by_key])
            param_idx = self._active_param_idx_by_node[node_id]
            merge_local_state_into_global(
                sums,
                counts,
                local_state,
                param_idx,
                weight=weight,
            )

        aggregated_state = finalize_aggregation(self._global_state_for_round, sums, counts)
        array_record = ArrayRecord(aggregated_state)
        metrics = self.train_metrics_aggr_fn(
            [message.content for message in valid_replies],
            self.weighted_by_key,
        )
        self._active_rate_by_node.clear()
        self._active_param_idx_by_node.clear()
        self._global_state_for_round = copy.deepcopy(aggregated_state)
        return array_record, metrics
