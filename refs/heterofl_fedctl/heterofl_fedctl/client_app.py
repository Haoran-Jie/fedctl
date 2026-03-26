"""Flower ClientApp for fixed-rate HeteroFL."""

from __future__ import annotations

import os
import time

import torch
from flwr.app import ArrayRecord, ConfigRecord, Context, Message, MetricRecord, RecordDict
from flwr.clientapp import ClientApp

from .config import (
    device_rate_map,
    get_float,
    get_int,
    get_optional_int,
    get_str,
    resolve_device_type_for_context,
    resolve_instance_idx,
    resolve_nomad_node_id,
)
from .task import build_model_for_rate, load_data, load_model_state, test, train

app = ClientApp()


def _client_prefix(context: Context) -> str:
    return (
        "[heterofl]"
        f" device_type={resolve_device_type_for_context(context)}"
        f" instance_idx={os.environ.get('FEDCTL_INSTANCE_IDX', '-')}"
        f" partition_id={context.node_config.get('partition-id', '-')}"
        f" nomad_node_id={resolve_nomad_node_id() or '-'}"
    )


def _log(context: Context, message: str) -> None:
    print(f"{_client_prefix(context)} {message}", flush=True)


def _optional_positive_int(value: object | None) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _max_examples_for_device(
    context: Context,
    *,
    split: str,
    device_type: str,
) -> int | None:
    run_config = context.run_config
    specific = run_config.get(f"{device_type}-max-{split}-examples")
    if specific is not None:
        return _optional_positive_int(specific)
    default = run_config.get(f"default-max-{split}-examples")
    return _optional_positive_int(default)


def _resolve_model_rate(msg: Message, context: Context) -> float:
    config = msg.content["config"]
    if "model-rate" in config:
        return float(config["model-rate"])
    device_type = resolve_device_type_for_context(context)
    return float(device_rate_map(context.run_config).get(device_type, get_float(context.run_config, "default-model-rate")))


def _resolve_batch_size(context: Context, device_type: str) -> int:
    specific = get_optional_int(context.run_config, f"{device_type}-batch-size")
    if specific is not None and specific > 0:
        return specific
    return get_int(context.run_config, "batch-size")


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
    total_start = time.perf_counter()
    device_type = resolve_device_type_for_context(context)
    model_rate = _resolve_model_rate(msg, context)
    _log(context, f"train:start model_rate={model_rate} lr={float(msg.content['config']['lr'])}")

    phase_start = time.perf_counter()
    model = build_model_for_rate(model_rate)
    load_model_state(model, msg.content["arrays"].to_torch_state_dict())
    _log(context, f"train:model_loaded elapsed_s={time.perf_counter() - phase_start:.2f}")

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    partition_id = int(context.node_config["partition-id"])
    num_partitions = int(context.node_config["num-partitions"])
    batch_size = _resolve_batch_size(context, device_type)
    partitioning = get_str(context.run_config, "partitioning")
    max_train_examples = _max_examples_for_device(
        context,
        split="train",
        device_type=device_type,
    )
    max_test_examples = _max_examples_for_device(
        context,
        split="test",
        device_type=device_type,
    )
    trainloader, _ = load_data(
        partition_id,
        num_partitions,
        batch_size,
        partitioning=partitioning,
        max_train_examples=max_train_examples,
        max_test_examples=max_test_examples,
    )
    _log(
        context,
        "train:data_ready "
        f"examples={len(trainloader.dataset)} batches={len(trainloader)} "
        f"max_train_examples={max_train_examples or 'all'}",
    )
    phase_start = time.perf_counter()
    loss = train(
        model,
        trainloader,
        get_int(context.run_config, "local-epochs"),
        float(msg.content["config"]["lr"]),
        device,
        log_prefix=_client_prefix(context),
    )
    _log(context, f"train:fit_done loss={loss:.6f} elapsed_s={time.perf_counter() - phase_start:.2f}")

    phase_start = time.perf_counter()
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
    _log(
        context,
        f"train:reply_ready elapsed_s={time.perf_counter() - phase_start:.2f} "
        f"total_elapsed_s={time.perf_counter() - total_start:.2f}",
    )
    return Message(content=reply, reply_to=msg)


@app.evaluate()
def evaluate_app(msg: Message, context: Context) -> Message:
    total_start = time.perf_counter()
    device_type = resolve_device_type_for_context(context)
    eval_rate = float(msg.content["config"].get("model-rate", get_float(context.run_config, "global-model-rate")))
    _log(context, f"eval:start model_rate={eval_rate}")
    phase_start = time.perf_counter()
    model = build_model_for_rate(eval_rate)
    load_model_state(model, msg.content["arrays"].to_torch_state_dict())
    _log(context, f"eval:model_loaded elapsed_s={time.perf_counter() - phase_start:.2f}")

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    partition_id = int(context.node_config["partition-id"])
    num_partitions = int(context.node_config["num-partitions"])
    batch_size = _resolve_batch_size(context, device_type)
    partitioning = get_str(context.run_config, "partitioning")
    max_train_examples = _max_examples_for_device(
        context,
        split="train",
        device_type=device_type,
    )
    max_test_examples = _max_examples_for_device(
        context,
        split="test",
        device_type=device_type,
    )
    _, testloader = load_data(
        partition_id,
        num_partitions,
        batch_size,
        partitioning=partitioning,
        max_train_examples=max_train_examples,
        max_test_examples=max_test_examples,
    )
    _log(
        context,
        "eval:data_ready "
        f"examples={len(testloader.dataset)} batches={len(testloader)} "
        f"max_test_examples={max_test_examples or 'all'}",
    )
    phase_start = time.perf_counter()
    loss, accuracy = test(model, testloader, device)
    _log(
        context,
        f"eval:done loss={loss:.6f} acc={accuracy:.6f} elapsed_s={time.perf_counter() - phase_start:.2f}",
    )

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
    _log(context, f"eval:reply_ready total_elapsed_s={time.perf_counter() - total_start:.2f}")
    return Message(content=reply, reply_to=msg)
