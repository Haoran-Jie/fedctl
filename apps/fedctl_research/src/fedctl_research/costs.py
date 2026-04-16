"""Static model cost utilities for experiment logging."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import lru_cache

import torch
import torch.nn as nn

from fedctl_research.tasks.registry import resolve_task


_INPUT_SHAPES: dict[str, tuple[int, ...]] = {
    "appliances_energy_mlp": (1, 33),
    "california_housing_mlp": (1, 8),
    "fashion_mnist_mlp": (1, 1, 28, 28),
    "fashion_mnist_cnn": (1, 1, 28, 28),
    "cifar10_cnn": (1, 3, 32, 32),
    "cifar10_preresnet18": (1, 3, 32, 32),
}


def _format_rate_key(model_rate: float) -> str:
    text = f"{float(model_rate):.4f}".rstrip("0")
    if text.endswith("."):
        text += "0"
    return text


def _build_example_input(task_name: str) -> torch.Tensor:
    task = resolve_task(task_name)
    shape = getattr(task, "example_input_shape", None)
    if shape is None:
        try:
            shape = _INPUT_SHAPES[task_name]
        except KeyError as exc:
            known = ", ".join(sorted(_INPUT_SHAPES))
            raise ValueError(
                f"Unknown task '{task_name}' for cost estimation. Known tasks: {known}"
            ) from exc
    return torch.zeros(shape, dtype=torch.float32)


def _estimate_flops(model: nn.Module, example_input: torch.Tensor) -> int:
    total_flops = 0
    hooks: list[torch.utils.hooks.RemovableHandle] = []

    def conv_hook(module: nn.Conv2d, inputs, output) -> None:
        nonlocal total_flops
        if not isinstance(output, torch.Tensor):
            return
        batch_size = int(output.shape[0])
        out_channels = int(output.shape[1])
        out_h = int(output.shape[2])
        out_w = int(output.shape[3])
        kernel_mul_adds = 2 * (module.in_channels // module.groups) * module.kernel_size[0] * module.kernel_size[1]
        bias_ops = 1 if module.bias is not None else 0
        total_flops += batch_size * out_channels * out_h * out_w * (kernel_mul_adds + bias_ops)

    def linear_hook(module: nn.Linear, inputs, output) -> None:
        nonlocal total_flops
        if not isinstance(output, torch.Tensor):
            return
        batch_size = int(output.shape[0]) if output.ndim > 1 else 1
        kernel_mul_adds = 2 * module.in_features
        bias_ops = 1 if module.bias is not None else 0
        total_flops += batch_size * module.out_features * (kernel_mul_adds + bias_ops)

    for module in model.modules():
        if isinstance(module, nn.Conv2d):
            hooks.append(module.register_forward_hook(conv_hook))
        elif isinstance(module, nn.Linear):
            hooks.append(module.register_forward_hook(linear_hook))

    model.eval()
    with torch.no_grad():
        model(example_input)

    for hook in hooks:
        hook.remove()
    return int(total_flops)


@lru_cache(maxsize=None)
def get_model_costs(task_name: str, model_rate: float, global_model_rate: float = 1.0) -> dict[str, float | int]:
    task = resolve_task(task_name)
    model = task.build_model_for_rate(model_rate, global_model_rate=global_model_rate)
    param_count = sum(parameter.numel() for parameter in model.parameters())
    model_size_bytes = sum(tensor.numel() * tensor.element_size() for tensor in model.state_dict().values())
    flops_estimate = _estimate_flops(model, _build_example_input(task_name))
    return {
        "param_count": int(param_count),
        "model_size_mb": float(model_size_bytes) / (1024.0 * 1024.0),
        "flops_estimate": int(flops_estimate),
    }


def summarize_round_costs(
    task_name: str,
    model_rates: Iterable[float],
    *,
    global_model_rate: float,
) -> dict[str, float]:
    rates = [float(rate) for rate in model_rates]
    if not rates:
        return {}
    costs = [get_model_costs(task_name, rate, global_model_rate=global_model_rate) for rate in rates]
    avg_params = sum(float(cost["param_count"]) for cost in costs) / len(costs)
    avg_size_mb = sum(float(cost["model_size_mb"]) for cost in costs) / len(costs)
    avg_flops = sum(float(cost["flops_estimate"]) for cost in costs) / len(costs)
    return {
        "round_avg_params": avg_params,
        "round_avg_size_mb": avg_size_mb,
        "round_avg_flops": avg_flops,
        "round_total_client_flops": sum(float(cost["flops_estimate"]) for cost in costs),
        "round_avg_model_rate": sum(rates) / len(rates),
    }


def build_model_catalog(
    task_name: str,
    *,
    global_model_rate: float,
    model_rates: Iterable[float],
) -> dict[str, Mapping[str, float | int]]:
    rates = []
    seen: set[float] = set()
    for rate in [float(global_model_rate), *[float(rate) for rate in model_rates]]:
        if rate in seen:
            continue
        seen.add(rate)
        rates.append(rate)

    catalog: dict[str, Mapping[str, float | int]] = {
        "full": get_model_costs(task_name, global_model_rate, global_model_rate=global_model_rate),
    }
    for rate in sorted(rates, reverse=True):
        catalog[f"rate_{_format_rate_key(rate)}"] = get_model_costs(
            task_name,
            rate,
            global_model_rate=global_model_rate,
        )
    return catalog
