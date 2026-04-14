"""Parameter slicing and masked aggregation helpers for fixed-rate HeteroFL."""

from __future__ import annotations

import copy
from collections import OrderedDict

import torch


ParamIndex = dict[str, torch.Tensor | tuple[torch.Tensor, torch.Tensor]]



def build_param_indices_for_rate(
    global_state: OrderedDict[str, torch.Tensor],
    model_rate: float,
    *,
    global_model_rate: float = 1.0,
) -> ParamIndex:
    scale = float(model_rate) / float(global_model_rate)
    if scale <= 0:
        raise ValueError("model_rate must be positive")

    final_classifier_weight, final_classifier_bias = _final_classifier_keys(global_state)

    param_idx: ParamIndex = OrderedDict()
    prev_output_idx: torch.Tensor | None = None
    prev_full_output_size: int | None = None
    residual_block_inputs: dict[str, tuple[torch.Tensor, int]] = {}

    for key, value in global_state.items():
        if key.endswith(".bn1.weight"):
            block_prefix = key[: -len(".bn1.weight")]
            if prev_output_idx is not None and prev_full_output_size is not None:
                residual_block_inputs[block_prefix] = (
                    prev_output_idx,
                    prev_full_output_size,
                )
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
                shortcut_marker = ".shortcut."
                if shortcut_marker in key:
                    block_prefix = key.split(shortcut_marker, 1)[0]
                    block_input = residual_block_inputs.get(block_prefix)
                    if block_input is not None:
                        shortcut_prev_output_idx, shortcut_prev_full_output_size = block_input
                        input_idx = _infer_input_idx(
                            value,
                            shortcut_prev_output_idx,
                            shortcut_prev_full_output_size,
                        )
                    else:
                        input_idx = _infer_input_idx(value, prev_output_idx, prev_full_output_size)
                else:
                    input_idx = _infer_input_idx(value, prev_output_idx, prev_full_output_size)
                output_size = value.size(0)
                local_output_size = max(1, int(torch.ceil(torch.tensor(output_size * scale)).item()))
                output_idx = torch.arange(output_size, device=value.device)[:local_output_size]
                param_idx[key] = (output_idx, input_idx)
                prev_output_idx = output_idx
                prev_full_output_size = output_size
            else:
                assert prev_output_idx is not None
                param_idx[key] = prev_output_idx
        elif key.endswith("bias"):
            assert prev_output_idx is not None
            param_idx[key] = prev_output_idx
        else:
            # No special slicing for buffers in the first scaffold.
            continue

    return param_idx



def slice_state_dict(
    global_state: OrderedDict[str, torch.Tensor], param_idx: ParamIndex
) -> OrderedDict[str, torch.Tensor]:
    local_state: OrderedDict[str, torch.Tensor] = OrderedDict()
    for key, value in global_state.items():
        if key not in param_idx:
            local_state[key] = copy.deepcopy(value)
            continue
        idx = param_idx[key]
        if isinstance(idx, tuple):
            out_idx, in_idx = idx
            mesh = torch.meshgrid(out_idx, in_idx, indexing="ij")
            local_state[key] = copy.deepcopy(value[mesh])
        else:
            local_state[key] = copy.deepcopy(value[idx])
    return local_state



def init_aggregation_buffers(
    global_state: OrderedDict[str, torch.Tensor],
) -> tuple[OrderedDict[str, torch.Tensor], OrderedDict[str, torch.Tensor]]:
    sums: OrderedDict[str, torch.Tensor] = OrderedDict()
    counts: OrderedDict[str, torch.Tensor] = OrderedDict()
    for key, value in global_state.items():
        sums[key] = torch.zeros_like(value, dtype=torch.float32)
        counts[key] = torch.zeros_like(value, dtype=torch.float32)
    return sums, counts



def merge_local_state_into_global(
    sums: OrderedDict[str, torch.Tensor],
    counts: OrderedDict[str, torch.Tensor],
    local_state: OrderedDict[str, torch.Tensor],
    param_idx: ParamIndex,
    *,
    weight: float,
) -> None:
    for key, value in local_state.items():
        tensor = value.detach().to(dtype=torch.float32)
        if key not in param_idx:
            sums[key] += tensor * weight
            counts[key] += weight
            continue
        idx = param_idx[key]
        if isinstance(idx, tuple):
            out_idx, in_idx = idx
            mesh = torch.meshgrid(out_idx, in_idx, indexing="ij")
            sums[key][mesh] += tensor * weight
            counts[key][mesh] += weight
        else:
            sums[key][idx] += tensor * weight
            counts[key][idx] += weight



def finalize_aggregation(
    global_state: OrderedDict[str, torch.Tensor],
    sums: OrderedDict[str, torch.Tensor],
    counts: OrderedDict[str, torch.Tensor],
) -> OrderedDict[str, torch.Tensor]:
    aggregated: OrderedDict[str, torch.Tensor] = OrderedDict()
    for key, original in global_state.items():
        merged = original.detach().clone().to(dtype=torch.float32)
        mask = counts[key] > 0
        if mask.any():
            merged[mask] = sums[key][mask] / counts[key][mask]
        aggregated[key] = merged.to(dtype=original.dtype)
    return aggregated



def _infer_input_idx(
    value: torch.Tensor,
    prev_output_idx: torch.Tensor | None,
    prev_full_output_size: int | None,
) -> torch.Tensor:
    input_size = value.size(1)
    if prev_output_idx is None:
        return torch.arange(input_size, device=value.device)
    if prev_full_output_size is None:
        return prev_output_idx
    if input_size == int(prev_output_idx.numel()):
        return prev_output_idx
    if input_size % prev_full_output_size == 0:
        return _expand_flatten_indices(prev_output_idx, input_size, prev_full_output_size)
    return prev_output_idx



def _expand_flatten_indices(
    channel_idx: torch.Tensor,
    flattened_input_size: int,
    full_channel_count: int,
) -> torch.Tensor:
    if flattened_input_size % full_channel_count != 0:
        raise ValueError(
            "Flattened input size is not divisible by the full channel count."
        )
    spatial_extent = flattened_input_size // full_channel_count
    expanded = [
        torch.arange(int(ch.item()) * spatial_extent, (int(ch.item()) + 1) * spatial_extent, device=channel_idx.device)
        for ch in channel_idx
    ]
    return torch.cat(expanded, dim=0) if expanded else torch.empty(0, dtype=torch.long, device=channel_idx.device)


def _final_classifier_keys(
    global_state: OrderedDict[str, torch.Tensor],
) -> tuple[str, str]:
    final_weight: str | None = None
    for key, value in global_state.items():
        if key.endswith("weight") and value.ndim > 1:
            final_weight = key
    if final_weight is None:
        raise ValueError("Could not identify final classifier weight in state_dict.")

    final_bias = final_weight[:-6] + "bias"
    if final_bias not in global_state:
        raise ValueError(f"Could not identify final classifier bias for {final_weight}.")
    return final_weight, final_bias
