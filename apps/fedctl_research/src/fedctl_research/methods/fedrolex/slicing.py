"""Rolling submodel extraction helpers for FedRolex-style training."""

from __future__ import annotations

from collections import OrderedDict
import hashlib

import torch

from fedctl_research.methods.heterofl.slicing import (
    ParamIndex,
    _expand_flatten_indices,
    _final_classifier_keys,
    _infer_input_idx,
)


def build_rolling_param_indices_for_rate(
    global_state: OrderedDict[str, torch.Tensor],
    model_rate: float,
    *,
    server_round: int,
    global_model_rate: float = 1.0,
    roll_mode: str = "paper",
    overlap: float | None = None,
) -> ParamIndex:
    scale = float(model_rate) / float(global_model_rate)
    if scale <= 0:
        raise ValueError("model_rate must be positive")

    final_classifier_weight, final_classifier_bias = _final_classifier_keys(global_state)

    param_idx: ParamIndex = OrderedDict()
    prev_output_idx: torch.Tensor | None = None
    prev_full_output_size: int | None = None

    for key, value in global_state.items():
        if key == final_classifier_weight:
            assert prev_output_idx is not None
            assert prev_full_output_size is not None
            input_idx = _expand_flatten_indices(
                prev_output_idx,
                value.size(1),
                prev_full_output_size,
            )
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
                output_size = value.size(0)
                local_output_size = max(
                    1,
                    int(torch.ceil(torch.tensor(output_size * scale)).item()),
                )
                output_idx = _rolling_window_indices(
                    key=key,
                    output_size=output_size,
                    local_output_size=local_output_size,
                    server_round=server_round,
                    roll_mode=roll_mode,
                    overlap=overlap,
                    device=value.device,
                )
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
            continue

    return param_idx


def _rolling_window_indices(
    *,
    key: str,
    output_size: int,
    local_output_size: int,
    server_round: int,
    roll_mode: str,
    overlap: float | None,
    device: torch.device,
) -> torch.Tensor:
    if local_output_size >= output_size:
        return torch.arange(output_size, device=device)

    base = torch.arange(output_size, device=device)
    if overlap is None:
        step = 1
    else:
        overlap_clamped = min(max(overlap, 0.0), 1.0)
        step = 1 + int(torch.floor(torch.tensor(local_output_size * (1.0 - overlap_clamped))).item())

    round_offset = max(server_round - 1, 0) * step
    if roll_mode == "paper":
        offset = round_offset % output_size
    elif roll_mode == "hashed":
        layer_offset = _stable_layer_offset(key, output_size)
        offset = (layer_offset + round_offset) % output_size
    else:
        raise ValueError(f"Unsupported FedRolex roll mode: {roll_mode}")
    rolled = torch.roll(base, -offset, dims=0)
    return rolled[:local_output_size]


def _stable_layer_offset(key: str, output_size: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % max(output_size, 1)
