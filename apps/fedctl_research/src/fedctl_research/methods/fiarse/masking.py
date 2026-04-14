"""Element-wise sparse masking utilities for FIARSE."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable

import torch
import torch.nn as nn


_MASKABLE_MODULE_TYPES = (
    nn.Conv1d,
    nn.Conv2d,
    nn.Conv3d,
    nn.Linear,
    nn.Embedding,
)


class Bern(torch.autograd.Function):
    """Straight-through Bernoulli-style mask from the FIARSE reference code."""

    @staticmethod
    def forward(ctx, scores: torch.Tensor, threshold: torch.Tensor) -> torch.Tensor:
        ctx.save_for_backward(scores, threshold)
        return (scores >= threshold).to(dtype=scores.dtype)

    @staticmethod
    def backward(ctx, grad_output: torch.Tensor) -> tuple[torch.Tensor, None]:
        scores, threshold = ctx.saved_tensors
        grad = 2 * threshold / torch.pow(scores + threshold, 2)
        grad = torch.nan_to_num(grad, nan=0.0, posinf=0.0, neginf=0.0)
        mask = (scores >= threshold).to(dtype=grad_output.dtype)
        return grad_output * grad * mask, None


def maskable_parameter_names(model: nn.Module) -> tuple[str, ...]:
    names: list[str] = []
    for module_name, module in model.named_modules():
        if not isinstance(module, _MASKABLE_MODULE_TYPES):
            continue
        prefix = f"{module_name}." if module_name else ""
        for param_name, parameter in module.named_parameters(recurse=False):
            if parameter is None:
                continue
            if param_name not in {"weight", "bias"}:
                continue
            names.append(f"{prefix}{param_name}")
    return tuple(names)


def build_threshold_map(
    model: nn.Module,
    *,
    model_rate: float,
    threshold_mode: str,
) -> dict[str, torch.Tensor]:
    if not 0 < float(model_rate) <= 1.0:
        raise ValueError(f"FIARSE model_rate must be within (0, 1], got {model_rate!r}")
    normalized_mode = str(threshold_mode).strip().lower()
    if normalized_mode not in {"global", "layerwise"}:
        raise ValueError(f"Unsupported FIARSE threshold mode: {threshold_mode}")

    maskable_names = set(maskable_parameter_names(model))
    maskable = tuple((name, parameter.detach()) for name, parameter in model.named_parameters() if name in maskable_names)
    if not maskable:
        return {}

    if normalized_mode == "global":
        global_threshold = _topk_threshold(
            tensors=(parameter.abs().reshape(-1) for _, parameter in maskable),
            rate=float(model_rate),
        )
        return {
            name: torch.as_tensor(global_threshold, device=parameter.device, dtype=parameter.dtype)
            for name, parameter in maskable
        }

    thresholds: dict[str, torch.Tensor] = {}
    for name, parameter in maskable:
        thresholds[name] = torch.as_tensor(
            _topk_threshold((parameter.abs().reshape(-1),), rate=float(model_rate)),
            device=parameter.device,
            dtype=parameter.dtype,
        )
    return thresholds


def build_masked_parameter_dict(
    model: nn.Module,
    *,
    threshold_map: dict[str, torch.Tensor],
    bern: bool,
) -> OrderedDict[str, torch.Tensor]:
    masked = OrderedDict()
    for name, parameter in model.named_parameters():
        threshold = threshold_map.get(name)
        if threshold is None:
            masked[name] = parameter
            continue
        scores = parameter.abs()
        if bern:
            mask = Bern.apply(scores, threshold)
        else:
            mask = (scores >= threshold).to(dtype=parameter.dtype)
        masked[name] = parameter * mask
    return masked


def apply_hard_mask_in_place(
    model: nn.Module,
    *,
    threshold_map: dict[str, torch.Tensor],
) -> None:
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            threshold = threshold_map.get(name)
            if threshold is None:
                continue
            mask = (parameter.abs() >= threshold).to(dtype=parameter.dtype)
            parameter.mul_(mask)


def _topk_threshold(
    tensors: Iterable[torch.Tensor],
    *,
    rate: float,
) -> float:
    flattened = [tensor.reshape(-1) for tensor in tensors if tensor.numel() > 0]
    if not flattened:
        return 0.0
    values = torch.cat(flattened, dim=0)
    if rate >= 1.0:
        return 0.0
    keep = max(1, int(values.numel() * rate))
    topk = torch.topk(values, k=keep)
    return float(topk.values[-1].item())
