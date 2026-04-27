"""Shared neural-network layers for research tasks."""

from __future__ import annotations

import torch
import torch.nn as nn


class Scaler(nn.Module):
    def __init__(self, rate: float):
        super().__init__()
        self.rate = float(rate)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        if not self.training or self.rate == 0:
            return inputs
        return inputs / self.rate


class StaticBatchNorm2d(nn.BatchNorm2d):
    def __init__(self, num_features: int):
        super().__init__(num_features, momentum=None, track_running_stats=False)
