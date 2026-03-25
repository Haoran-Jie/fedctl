"""Flower ClientApp for fixed-rate HeteroFL."""

from __future__ import annotations

import os

import torch
from flwr.app import ArrayRecord, ConfigRecord, Context, Message, MetricRecord, RecordDict
from flwr.clientapp import ClientApp

from .config import (
    device_rate_map,
    get_float,
    get_int,
    get_str,
    resolve_device_type_for_context,
    resolve_instance_idx,
    resolve_nomad_node_id,
)
from .task import build_model_for_rate, load_data, load_model_state, test, train

app = ClientApp()



def _resolve_model_rate(msg: Message, context: Context) -> float:
    config = msg.content["config"]
    if "model-rate" in config:
        return float(config["model-rate"])
    device_type = resolve_device_type_for_context(context)
    return float(device_rate_map(context.run_config).get(device_type, get_float(context.run_config, "default-model-rate")))


@app.query()
def query_app(msg: Message, context: Context) -> Message:
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


@app.train()
def train_app(msg: Message, context: Context) -> Message:
    model_rate = _resolve_model_rate(msg, context)
    device_type = resolve_device_type_for_context(context)
    print(
        f"[heterofl] train device_type={device_type} model_rate={model_rate} "
        f"instance_idx={os.environ.get('FEDCTL_INSTANCE_IDX', '-') }"
    )

    model = build_model_for_rate(model_rate)
    load_model_state(model, msg.content["arrays"].to_torch_state_dict())

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    partition_id = int(context.node_config["partition-id"])
    num_partitions = int(context.node_config["num-partitions"])
    batch_size = get_int(context.run_config, "batch-size")
    partitioning = get_str(context.run_config, "partitioning")
    trainloader, _ = load_data(
        partition_id,
        num_partitions,
        batch_size,
        partitioning=partitioning,
    )
    loss = train(
        model,
        trainloader,
        get_int(context.run_config, "local-epochs"),
        float(msg.content["config"]["lr"]),
        device,
    )

    reply = RecordDict(
        {
            "arrays": ArrayRecord(model.state_dict()),
            "metrics": MetricRecord(
                {
                    "train-loss": float(loss),
                    "num-examples": len(trainloader.dataset),
                    "model-rate": float(model_rate),
                }
            ),
        }
    )
    return Message(content=reply, reply_to=msg)


@app.evaluate()
def evaluate_app(msg: Message, context: Context) -> Message:
    eval_rate = float(msg.content["config"].get("model-rate", get_float(context.run_config, "global-model-rate")))
    model = build_model_for_rate(eval_rate)
    load_model_state(model, msg.content["arrays"].to_torch_state_dict())

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    partition_id = int(context.node_config["partition-id"])
    num_partitions = int(context.node_config["num-partitions"])
    batch_size = get_int(context.run_config, "batch-size")
    partitioning = get_str(context.run_config, "partitioning")
    _, testloader = load_data(
        partition_id,
        num_partitions,
        batch_size,
        partitioning=partitioning,
    )
    loss, accuracy = test(model, testloader, device)

    reply = RecordDict(
        {
            "metrics": MetricRecord(
                {
                    "eval-loss": float(loss),
                    "eval-acc": float(accuracy),
                    "num-examples": len(testloader.dataset),
                }
            )
        }
    )
    return Message(content=reply, reply_to=msg)
