"""FIARSE-lite strategy with structured importance-aware extraction."""

from __future__ import annotations

from fedctl_research.methods.heterofl.strategy import HeteroFLStrategy

from .slicing import build_importance_param_indices_for_rate


class FiarseStrategy(HeteroFLStrategy):
    def __init__(
        self,
        *,
        selection_mode: str = "structured-magnitude",
        threshold_mode: str = "global",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.selection_mode = selection_mode
        self.threshold_mode = threshold_mode

    def build_param_indices(self, global_state, *, model_rate: float, server_round: int):
        del server_round
        if self.selection_mode != "structured-magnitude":
            raise ValueError(f"Unsupported FIARSE selection mode: {self.selection_mode}")
        return build_importance_param_indices_for_rate(
            global_state,
            model_rate,
            global_model_rate=self.global_model_rate,
            threshold_mode=self.threshold_mode,
        )
