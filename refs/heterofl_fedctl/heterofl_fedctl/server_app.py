"""Flower ServerApp for fixed-rate HeteroFL."""

from __future__ import annotations

import time

from flwr.app import ArrayRecord, ConfigRecord, Context, Message, MessageType, MetricRecord, RecordDict
from flwr.serverapp import Grid, ServerApp

from .config import (
    device_rate_map,
    get_float,
    get_int,
    parse_node_device_type_map,
    parse_node_rate_map,
)
from .strategy import FixedRateHeteroFL
from .task import build_model_for_rate, load_centralized_test_dataset, load_model_state, test

app = ServerApp()



def _central_evaluate_fn(context: Context):
    testloader = load_centralized_test_dataset()

    def evaluate(server_round: int, arrays: ArrayRecord) -> MetricRecord | None:
        model = build_model_for_rate(get_float(context.run_config, "global-model-rate"))
        load_model_state(model, arrays.to_torch_state_dict())
        loss, accuracy = test(model, testloader, device="cpu")
        return MetricRecord(
            {
                "eval-loss": float(loss),
                "eval-acc": float(accuracy),
                "server-round": server_round,
            }
        )

    return evaluate


def _discover_node_device_types(grid: Grid, context: Context) -> dict[int, str]:
    min_available_nodes = get_int(context.run_config, "min-available-nodes")
    timeout_s = float(context.run_config.get("capability-discovery-timeout-s", 120.0))
    started = time.monotonic()

    all_node_ids: list[int] = []
    while len(all_node_ids) < min_available_nodes:
        all_node_ids = list(grid.get_node_ids())
        if len(all_node_ids) >= min_available_nodes:
            break
        if time.monotonic() - started >= timeout_s:
            raise RuntimeError(
                "Timed out waiting for enough nodes to perform capability discovery."
            )
        time.sleep(1.0)

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

    discovered: dict[int, str] = {}
    for reply in replies:
        if reply.has_error():
            continue
        capabilities = reply.content.get("capabilities")
        if not isinstance(capabilities, ConfigRecord):
            continue
        src_node_id = reply.metadata.src_node_id
        device_type = capabilities.get("device-type")
        if isinstance(device_type, str) and device_type:
            discovered[src_node_id] = device_type

    # Manual overrides remain available for debugging or incomplete discovery.
    discovered.update(
        parse_node_device_type_map(context.run_config.get("heterofl-node-device-types", ""))
    )
    return discovered


@app.main()
def main(grid: Grid, context: Context) -> None:
    global_model_rate = get_float(context.run_config, "global-model-rate")
    initial_model = build_model_for_rate(global_model_rate)
    initial_arrays = ArrayRecord(initial_model.state_dict())

    train_config = ConfigRecord(
        {
            "lr": get_float(context.run_config, "learning-rate"),
            "global-model-rate": global_model_rate,
        }
    )
    evaluate_config = ConfigRecord({"global-model-rate": global_model_rate})

    strategy = FixedRateHeteroFL(
        fraction_train=get_float(context.run_config, "fraction-train"),
        fraction_evaluate=get_float(context.run_config, "fraction-evaluate"),
        min_available_nodes=get_int(context.run_config, "min-available-nodes"),
        min_train_nodes=get_int(context.run_config, "min-train-nodes"),
        min_evaluate_nodes=get_int(context.run_config, "min-evaluate-nodes"),
        weighted_by_key="num-examples",
        rate_by_node_id=parse_node_rate_map(context.run_config.get("heterofl-node-rates", "")),
        rate_by_device_type=device_rate_map(context.run_config),
        global_model_rate=global_model_rate,
        default_model_rate=get_float(context.run_config, "default-model-rate"),
    )
    strategy.set_node_capabilities(_discover_node_device_types(grid, context))

    strategy.start(
        grid=grid,
        initial_arrays=initial_arrays,
        num_rounds=get_int(context.run_config, "num-server-rounds"),
        train_config=train_config,
        evaluate_config=evaluate_config,
        evaluate_fn=_central_evaluate_fn(context),
    )
