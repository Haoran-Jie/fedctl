"""FIARSE-specific client runtime helpers."""

from __future__ import annotations

import time
from collections import OrderedDict

import torch
import torch.nn as nn
from flwr.app import ArrayRecord, Context, Message, MetricRecord, RecordDict

from fedctl_research.config import (
    get_int,
    get_masked_cross_entropy_mode,
    get_optional_int,
    get_str,
    resolve_device_type_for_context,
)
from fedctl_research.methods.runtime import (
    build_partition_request,
    client_log,
    client_prefix,
    max_examples_for_device,
    resolve_batch_size,
)
from fedctl_research.runtime.classification import masked_cross_entropy_loss, should_use_masked_cross_entropy
from fedctl_research.seeding import derive_seed, set_global_seed
from fedctl_research.tasks.registry import resolve_task

from .masking import apply_hard_mask_in_place, build_masked_parameter_dict, build_threshold_map

try:  # pragma: no cover - compatibility shim
    from torch.func import functional_call
except ImportError:  # pragma: no cover
    from torch.nn.utils.stateless import functional_call


def client_train_fiarse(
    msg: Message,
    context: Context,
    *,
    method_label: str,
    resolve_model_rate,
    threshold_mode: str,
) -> Message:
    total_start = time.perf_counter()
    task = resolve_task(get_str(context.run_config, "task"))
    local_device_type = resolve_device_type_for_context(context)
    model_rate = float(resolve_model_rate(msg, context))
    partition_id = int(context.node_config["partition-id"])
    partitioning = get_str(context.run_config, "partitioning")
    base_seed = get_optional_int(context.run_config, "seed")
    if base_seed is not None:
        local_seed = derive_seed(base_seed, method_label, "client-train", task.name, partition_id)
        set_global_seed(local_seed)
    request = build_partition_request(
        context=context,
        msg=msg,
        task_name=task.name,
        method_label=method_label,
        split="train",
        local_device_type=local_device_type,
    )
    client_log(
        context,
        method_label=method_label,
        message=f"train:start model_rate={model_rate} lr={float(msg.content['config']['lr'])}",
    )

    global_model_rate = float(msg.content["config"].get("global-model-rate", 1.0))
    phase_start = time.perf_counter()
    model = task.build_model_for_rate(
        global_model_rate,
        global_model_rate=global_model_rate,
    )
    task.load_model_state(model, msg.content["arrays"].to_torch_state_dict())
    client_log(
        context,
        method_label=method_label,
        message=f"train:model_loaded elapsed_s={time.perf_counter() - phase_start:.2f}",
    )

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    batch_size = resolve_batch_size(context, local_device_type)
    bundle = task.load_data(
        request,
        batch_size,
        max_train_examples=max_examples_for_device(context, split="train", device_type=local_device_type),
        max_test_examples=max_examples_for_device(context, split="test", device_type=local_device_type),
    )
    client_log(
        context,
        method_label=method_label,
        message=(
            "train:data_ready "
            f"examples={bundle.num_train_examples} batches={len(bundle.trainloader)} "
            f"labels={bundle.label_set or 'all'}"
        ),
    )

    phase_start = time.perf_counter()
    loss = _train_sparse_masked_classifier(
        model,
        bundle.trainloader,
        get_int(context.run_config, "local-epochs"),
        float(msg.content["config"]["lr"]),
        device,
        model_rate=model_rate,
        threshold_mode=threshold_mode,
        label_mask=bundle.label_mask,
        use_masked_cross_entropy=should_use_masked_cross_entropy(
            get_masked_cross_entropy_mode(context.run_config),
            partitioning=partitioning,
        ),
        log_prefix=client_prefix(context, method_label=method_label),
    )
    client_log(
        context,
        method_label=method_label,
        message=f"train:fit_done loss={loss:.6f} elapsed_s={time.perf_counter() - phase_start:.2f}",
    )
    train_duration_s = time.perf_counter() - total_start
    examples_per_second = (
        float(bundle.num_train_examples) / train_duration_s if train_duration_s > 0 and bundle.num_train_examples > 0 else 0.0
    )

    reply = RecordDict(
        {
            "arrays": ArrayRecord(model.state_dict()),
            "metrics": MetricRecord(
                {
                    "train-loss": float(loss),
                    "num-examples": bundle.num_train_examples,
                    "train-num-examples": bundle.num_train_examples,
                    "train-duration-s": float(train_duration_s),
                    "examples-per-second": float(examples_per_second),
                    "model-rate": float(model_rate),
                }
            ),
        }
    )
    client_log(
        context,
        method_label=method_label,
        message=f"train:reply_ready total_elapsed_s={train_duration_s:.2f}",
    )
    return Message(content=reply, reply_to=msg)


def client_evaluate_fiarse(
    msg: Message,
    context: Context,
    *,
    method_label: str,
    resolve_model_rate,
    threshold_mode: str,
) -> Message:
    total_start = time.perf_counter()
    task = resolve_task(get_str(context.run_config, "task"))
    local_device_type = resolve_device_type_for_context(context)
    partition_id = int(context.node_config["partition-id"])
    base_seed = get_optional_int(context.run_config, "seed")
    if base_seed is not None:
        set_global_seed(derive_seed(base_seed, method_label, "client-eval", task.name, partition_id))
    request = build_partition_request(
        context=context,
        msg=msg,
        task_name=task.name,
        method_label=method_label,
        split="eval",
        local_device_type=local_device_type,
    )
    eval_rate = float(resolve_model_rate(msg, context))
    client_log(context, method_label=method_label, message=f"eval:start model_rate={eval_rate}")

    global_model_rate = float(msg.content["config"].get("global-model-rate", 1.0))
    phase_start = time.perf_counter()
    model = task.build_model_for_rate(
        global_model_rate,
        global_model_rate=global_model_rate,
    )
    task.load_model_state(model, msg.content["arrays"].to_torch_state_dict())
    threshold_map = build_threshold_map(model, model_rate=eval_rate, threshold_mode=threshold_mode)
    apply_hard_mask_in_place(model, threshold_map=threshold_map)
    client_log(
        context,
        method_label=method_label,
        message=f"eval:model_loaded elapsed_s={time.perf_counter() - phase_start:.2f}",
    )

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    batch_size = resolve_batch_size(context, local_device_type)
    bundle = task.load_data(
        request,
        batch_size,
        max_train_examples=max_examples_for_device(context, split="train", device_type=local_device_type),
        max_test_examples=max_examples_for_device(context, split="test", device_type=local_device_type),
    )
    client_log(
        context,
        method_label=method_label,
        message=(
            "eval:data_ready "
            f"examples={bundle.num_test_examples} batches={len(bundle.testloader)}"
        ),
    )

    phase_start = time.perf_counter()
    loss, accuracy = task.test(model, bundle.testloader, device)
    client_log(
        context,
        method_label=method_label,
        message=(
            f"eval:done loss={loss:.6f} acc={accuracy:.6f} "
            f"elapsed_s={time.perf_counter() - phase_start:.2f}"
        ),
    )
    eval_duration_s = time.perf_counter() - total_start

    reply = RecordDict(
        {
            "metrics": MetricRecord(
                {
                    "eval-loss": float(loss),
                    "eval-acc": float(accuracy),
                    "num-examples": bundle.num_test_examples,
                    "eval-num-examples": bundle.num_test_examples,
                    "eval-duration-s": float(eval_duration_s),
                }
            )
        }
    )
    client_log(
        context,
        method_label=method_label,
        message=f"eval:reply_ready total_elapsed_s={eval_duration_s:.2f}",
    )
    return Message(content=reply, reply_to=msg)


def _train_sparse_masked_classifier(
    model: nn.Module,
    trainloader,
    epochs: int,
    lr: float,
    device: torch.device | str,
    *,
    model_rate: float,
    threshold_mode: str,
    label_mask: torch.Tensor | None,
    use_masked_cross_entropy: bool,
    log_prefix: str,
) -> float:
    model.to(device)
    criterion = nn.CrossEntropyLoss().to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9)
    threshold_map = {
        name: value.to(device=device)
        for name, value in build_threshold_map(model, model_rate=model_rate, threshold_mode=threshold_mode).items()
    }
    model.train()

    print(
        f"{log_prefix} train:enter device={device} epochs={epochs} batches={len(trainloader)}",
        flush=True,
    )
    running_loss = 0.0
    steps = 0
    label_mask_device = label_mask.to(device) if label_mask is not None else None

    for epoch in range(epochs):
        epoch_start = time.perf_counter()
        epoch_loss = 0.0
        epoch_steps = 0
        for batch_idx, (images, labels) in enumerate(trainloader, start=1):
            batch_start = time.perf_counter()
            images = images.to(device)
            labels = labels.to(device)
            optimizer.zero_grad()

            masked_state = OrderedDict((name, tensor) for name, tensor in model.named_buffers())
            masked_state.update(
                build_masked_parameter_dict(
                    model,
                    threshold_map=threshold_map,
                    bern=True,
                )
            )
            logits = functional_call(model, masked_state, (images,))
            if use_masked_cross_entropy:
                loss = masked_cross_entropy_loss(logits, labels, label_mask=label_mask_device)
            else:
                loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()

            loss_value = float(loss.item())
            running_loss += loss_value
            steps += 1
            epoch_loss += loss_value
            epoch_steps += 1
            print(
                f"{log_prefix} train:batch_done "
                f"epoch={epoch + 1}/{epochs} batch={batch_idx}/{len(trainloader)} "
                f"loss={loss_value:.6f} elapsed_s={time.perf_counter() - batch_start:.2f}",
                flush=True,
            )
        print(
            f"{log_prefix} train:epoch_done "
            f"epoch={epoch + 1}/{epochs} avg_loss={epoch_loss / max(epoch_steps, 1):.6f} "
            f"steps={epoch_steps} elapsed_s={time.perf_counter() - epoch_start:.2f}",
            flush=True,
        )

    return running_loss / max(steps, 1)
