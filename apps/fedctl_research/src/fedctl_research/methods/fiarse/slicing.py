"""Structured importance-aware slicing helpers for FIARSE."""

from __future__ import annotations

from collections import OrderedDict

import torch

from fedctl_research.methods.heterofl.slicing import (
    ParamIndex,
    _expand_flatten_indices,
    _final_classifier_keys,
    _infer_input_idx,
)


class _LayerPlan(dict):
    key: str
    raw_scores: torch.Tensor
    input_idx: torch.Tensor
    output_size: int
    local_output_size: int


def build_importance_param_indices_for_rate(
    global_state: OrderedDict[str, torch.Tensor],
    model_rate: float,
    *,
    global_model_rate: float = 1.0,
    threshold_mode: str = "global",
) -> ParamIndex:
    scale = float(model_rate) / float(global_model_rate)
    if scale <= 0:
        raise ValueError("model_rate must be positive")
    if threshold_mode not in {"global", "layerwise"}:
        raise ValueError(f"Unsupported FIARSE threshold mode: {threshold_mode}")

    final_classifier_weight, final_classifier_bias = _final_classifier_keys(global_state)
    layer_plans: list[dict[str, object]] = []
    prev_output_idx: torch.Tensor | None = None
    prev_full_output_size: int | None = None

    for key, value in global_state.items():
        if key in {final_classifier_weight, final_classifier_bias}:
            continue
        if not key.endswith("weight") or value.ndim <= 1:
            continue
        input_idx = _infer_input_idx(value, prev_output_idx, prev_full_output_size)
        output_size = int(value.size(0))
        local_output_size = max(1, int(torch.ceil(torch.tensor(output_size * scale)).item()))
        raw_scores = _output_importance_scores(value)
        layer_plans.append(
            {
                "key": key,
                "raw_scores": raw_scores,
                "input_idx": input_idx,
                "output_size": output_size,
                "local_output_size": local_output_size,
            }
        )
        prev_output_idx = torch.arange(output_size, device=value.device)
        prev_full_output_size = output_size

    selected_by_key = _resolve_output_indices(layer_plans, threshold_mode=threshold_mode)

    param_idx: ParamIndex = OrderedDict()
    prev_output_idx = None
    prev_full_output_size = None

    for key, value in global_state.items():
        if key == final_classifier_weight:
            assert prev_output_idx is not None
            assert prev_full_output_size is not None
            input_idx = _expand_flatten_indices(prev_output_idx, value.size(1), prev_full_output_size)
            output_idx = torch.arange(value.size(0), device=value.device)
            param_idx[key] = (output_idx, input_idx)
            prev_output_idx = output_idx
            prev_full_output_size = value.size(0)
            continue
        if key == final_classifier_bias:
            param_idx[key] = torch.arange(value.size(0), device=value.device)
            prev_output_idx = param_idx[key]
            prev_full_output_size = value.size(0)
            continue
        if key.endswith("weight"):
            if value.ndim > 1:
                input_idx = _infer_input_idx(value, prev_output_idx, prev_full_output_size)
                output_idx = selected_by_key.get(key)
                if output_idx is None:
                    output_idx = torch.arange(value.size(0), device=value.device)
                param_idx[key] = (output_idx, input_idx)
                prev_output_idx = output_idx
                prev_full_output_size = value.size(0)
            else:
                assert prev_output_idx is not None
                param_idx[key] = prev_output_idx
        elif key.endswith("bias"):
            assert prev_output_idx is not None
            param_idx[key] = prev_output_idx

    return param_idx


def _output_importance_scores(weight: torch.Tensor) -> torch.Tensor:
    if weight.ndim == 2:
        return weight.detach().abs().mean(dim=1)
    flattened = weight.detach().abs().reshape(weight.size(0), -1)
    return flattened.mean(dim=1)


def _resolve_output_indices(
    layer_plans: list[dict[str, object]],
    *,
    threshold_mode: str,
) -> dict[str, torch.Tensor]:
    if threshold_mode == "layerwise":
        return {
            str(plan["key"]): _topk_sorted_indices(
                plan["raw_scores"],
                int(plan["local_output_size"]),
            )
            for plan in layer_plans
        }

    total_keep = sum(int(plan["local_output_size"]) for plan in layer_plans)
    flattened_scores: list[torch.Tensor] = []
    owners: list[tuple[str, int]] = []
    for plan in layer_plans:
        # Paper-style global thresholding ranks channels by raw magnitude across layers.
        scores = plan["raw_scores"]
        flattened_scores.append(scores)
        owners.extend((str(plan["key"]), index) for index in range(int(scores.numel())))
    all_scores = torch.cat(flattened_scores, dim=0)
    top_positions = set(int(index.item()) for index in torch.topk(all_scores, k=min(total_keep, int(all_scores.numel()))).indices)

    selected: dict[str, list[int]] = {}
    for flat_position, (key, local_index) in enumerate(owners):
        if flat_position in top_positions:
            selected.setdefault(key, []).append(local_index)

    resolved: dict[str, torch.Tensor] = {}
    for plan in layer_plans:
        key = str(plan["key"])
        scores = plan["raw_scores"]
        local_keep = int(plan["local_output_size"])
        chosen = list(dict.fromkeys(selected.get(key, [])))
        if len(chosen) > local_keep:
            order = torch.argsort(scores[torch.tensor(chosen, device=scores.device)], descending=True)
            chosen = [chosen[int(idx.item())] for idx in order[:local_keep]]
        if len(chosen) < local_keep:
            local_rank = torch.argsort(scores, descending=True).tolist()
            for idx in local_rank:
                if idx not in chosen:
                    chosen.append(int(idx))
                if len(chosen) >= local_keep:
                    break
        resolved[key] = torch.tensor(sorted(chosen), dtype=torch.long, device=scores.device)
    return resolved


def _topk_sorted_indices(scores: torch.Tensor, k: int) -> torch.Tensor:
    if k >= int(scores.numel()):
        return torch.arange(int(scores.numel()), device=scores.device)
    indices = torch.topk(scores, k=k).indices
    return indices.sort().values
