"""FIARSE-lite method implementation using structured importance-aware slicing."""

from __future__ import annotations

from flwr.app import Context, Message
from flwr.serverapp import Grid

from fedctl_research.config import (
    device_rate_map,
    get_fiarse_selection_mode,
    get_fiarse_threshold_mode,
    get_float,
    get_model_rate_levels,
    get_model_rate_proportions,
    get_model_split_mode,
    parse_device_type_allocations,
    parse_partition_rate_map,
    parse_node_rate_map,
    resolve_device_type_for_context,
)
from fedctl_research.methods.assignment import ModelRateAssigner
from fedctl_research.methods.runtime import client_evaluate, client_train, query_capabilities, run_server_loop

from .strategy import FiarseStrategy


def _fallback_model_rate(msg: Message, context: Context) -> float:
    config = msg.content["config"]
    if "model-rate" in config:
        return float(config["model-rate"])
    device_type = resolve_device_type_for_context(context)
    return float(
        device_rate_map(context.run_config).get(
            device_type,
            get_float(context.run_config, "default-model-rate"),
        )
    )


def query_app(msg: Message, context: Context) -> Message:
    return query_capabilities(msg, context)


def train_app(msg: Message, context: Context) -> Message:
    return client_train(msg, context, method_label="fiarse", resolve_model_rate=_fallback_model_rate)


def evaluate_app(msg: Message, context: Context) -> Message:
    return client_evaluate(msg, context, method_label="fiarse", resolve_model_rate=_fallback_model_rate)


def run_server(grid: Grid, context: Context) -> None:
    run_server_loop(
        grid,
        context,
        method_label="fiarse",
        strategy_factory=FiarseStrategy,
        needs_capabilities=True,
        rate_assigner=ModelRateAssigner(
            mode=get_model_split_mode(context.run_config),
            default_model_rate=get_float(context.run_config, "default-model-rate"),
            explicit_rate_by_node_id=parse_node_rate_map(context.run_config.get("heterofl-node-rates", "")),
            explicit_rate_by_partition_id=parse_partition_rate_map(
                context.run_config.get("heterofl-partition-rates", "")
            ),
            rate_by_device_type=device_rate_map(context.run_config),
            device_type_by_node_id={},
            partition_id_by_node_id={},
            dynamic_levels=get_model_rate_levels(context.run_config),
            dynamic_proportions=get_model_rate_proportions(context.run_config),
            device_type_allocations=parse_device_type_allocations(
                context.run_config.get("heterofl-device-type-allocations", "")
            ),
            seed=context.run_config.get("seed"),
        ),
        global_model_rate=get_float(context.run_config, "global-model-rate"),
        selection_mode=get_fiarse_selection_mode(context.run_config),
        threshold_mode=get_fiarse_threshold_mode(context.run_config),
    )
