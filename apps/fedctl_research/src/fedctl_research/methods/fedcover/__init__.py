"""FedCover: coverage-aware buffered async training for nested submodels."""

from __future__ import annotations

from flwr.app import Context, Message
from flwr.serverapp import Grid

from fedctl_research.config import (
    device_rate_map,
    get_fedcover_base_staleness_weighting,
    get_fedcover_buffer_size,
    get_fedcover_coverage_power,
    get_fedcover_evaluate_every_steps,
    get_fedcover_max_block_weight,
    get_fedcover_min_observed_mass,
    get_fedcover_num_server_steps,
    get_fedcover_poll_interval_s,
    get_fedcover_server_learning_rate,
    get_fedcover_slicer,
    get_fedcover_staleness_alpha,
    get_fedcover_train_concurrency,
    get_float,
    get_model_rate_levels,
    get_model_rate_proportions,
    get_model_split_mode,
    lookup_or_default,
    parse_device_type_allocations,
    parse_node_rate_map,
    parse_partition_rate_map,
    resolve_device_type_for_context,
)
from fedctl_research.methods.assignment import ModelRateAssigner
from fedctl_research.methods.fedbuff.async_loop import CoverageConfig, run_fedbuff_server
from fedctl_research.methods.runtime import client_evaluate, client_train, query_capabilities


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


def _rate_assigner(context: Context) -> ModelRateAssigner:
    return ModelRateAssigner(
        mode=get_model_split_mode(context.run_config),
        default_model_rate=get_float(context.run_config, "default-model-rate"),
        explicit_rate_by_node_id=parse_node_rate_map(
            lookup_or_default(context.run_config, "heterofl-node-rates", "")
        ),
        explicit_rate_by_partition_id=parse_partition_rate_map(
            lookup_or_default(context.run_config, "heterofl-partition-rates", "")
        ),
        rate_by_device_type=device_rate_map(context.run_config),
        device_type_by_node_id={},
        partition_id_by_node_id={},
        dynamic_levels=get_model_rate_levels(context.run_config),
        dynamic_proportions=get_model_rate_proportions(context.run_config),
        device_type_allocations=parse_device_type_allocations(
            lookup_or_default(context.run_config, "heterofl-device-type-allocations", "")
        ),
        seed=lookup_or_default(context.run_config, "seed", None),
    )


def query_app(msg: Message, context: Context) -> Message:
    return query_capabilities(msg, context)


def train_app(msg: Message, context: Context) -> Message:
    return client_train(msg, context, method_label="fedcover", resolve_model_rate=_fallback_model_rate)


def evaluate_app(msg: Message, context: Context) -> Message:
    return client_evaluate(msg, context, method_label="fedcover", resolve_model_rate=_fallback_model_rate)


def run_server(grid: Grid, context: Context) -> None:
    slicer = get_fedcover_slicer(context.run_config)
    if slicer != "heterofl":
        raise ValueError(
            f"FedCover MVP supports only fedcover-slicer='heterofl'; got {slicer!r}"
        )

    num_server_steps = get_fedcover_num_server_steps(context.run_config)
    buffer_size = get_fedcover_buffer_size(context.run_config)
    run_fedbuff_server(
        grid,
        context,
        method_label="fedcover",
        staleness_mode_override=get_fedcover_base_staleness_weighting(context.run_config),
        staleness_alpha_override=get_fedcover_staleness_alpha(context.run_config),
        buffer_size_override=buffer_size,
        train_concurrency_override=get_fedcover_train_concurrency(context.run_config),
        poll_interval_s_override=get_fedcover_poll_interval_s(context.run_config),
        num_server_steps_override=num_server_steps,
        evaluate_every_steps_override=get_fedcover_evaluate_every_steps(context.run_config),
        server_learning_rate_override=get_fedcover_server_learning_rate(context.run_config),
        client_trip_budget_override=num_server_steps * buffer_size,
        rate_assigner=_rate_assigner(context),
        coverage_config=CoverageConfig(
            coverage_power=get_fedcover_coverage_power(context.run_config),
            max_block_weight=get_fedcover_max_block_weight(context.run_config),
            min_observed_mass=get_fedcover_min_observed_mass(context.run_config),
        ),
    )
